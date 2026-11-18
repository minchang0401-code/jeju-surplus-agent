"""제주 잉여전력 도우미 에이전트.

- LLM 키가 있으면: LLM이 질문을 이해하고 tools.py 의 도구를 골라 부른 뒤, 결과로만 답합니다.
- LLM 키가 없거나 연결이 안 되면: 질문의 낱말로 도구를 고르고 정해진 문장으로 답합니다(비상 모드).

.env 설정
  LLM_PROVIDER=openai | upstage | anthropic | none
  LLM_API_KEY=...
  LLM_MODEL=(선택, 비우면 config.DEFAULT_LLM 의 기본값)

    python agent.py "이번 주말에 빨래 언제 돌리면 좋아?"
"""
from __future__ import annotations

import json
import sys
from datetime import date, timedelta

import requests

from config import DEFAULT_LLM, get_key
from facts import FACTS, SAFETY_RULES
from tools import TOOL_SPECS, TOOLS

SYSTEM_PROMPT = f"""너는 '제주 잉여전력 도우미'다. 제주 도민이 재생에너지가 남는 시간에 전기를 쓰도록 돕는다.
오늘 날짜: {date.today():%Y-%m-%d}
규칙:
- 반드시 도구를 불러 그 결과에 있는 숫자·날짜·장소만 말한다. 도구 결과에 없는 것은 모른다고 말한다.
- 질문이 도구로 답할 수 없는 내용(잉여전력·전기 사용 시간·충전소와 관계없는 질문)이면 도구를 억지로 부르지 말고,
  "제가 가진 데이터로는 답할 수 없어요"라고 말한 뒤 답할 수 있는 질문 예시 2~3개를 알려 준다.
- 질문에 딱 맞는 도구만 부른다. 묻지 않은 예보·충전 습관을 덧붙이지 않는다.
- 어르신도 알아듣게 짧고 쉬운 말로, 3~6문장으로 답한다. 시간은 '낮 12시~오후 2시'처럼 말한다.
- 답 끝에 쓴 데이터 출처를 한 줄로 적는다 (예: 출처: 제주데이터허브 862, EPSIS).
- 지켜야 할 사실:
{chr(10).join('  - ' + f['text'] for f in FACTS.values())}
- 주의:
{chr(10).join('  - ' + r for r in SAFETY_RULES)}
"""


# ---------------------------------------------------------------- LLM 연결
def _llm_config() -> dict | None:
    provider = (get_key("LLM_PROVIDER") or "none").lower()
    key = get_key("LLM_API_KEY")
    if provider == "none" or not key or provider not in DEFAULT_LLM:
        return None
    cfg = dict(DEFAULT_LLM[provider])
    cfg["provider"], cfg["key"] = provider, key
    cfg["model"] = get_key("LLM_MODEL") or cfg["model"]
    return cfg


def _run_tool(name: str, args: dict) -> dict:
    fn = TOOLS.get(name)
    if fn is None:
        return {"error": f"없는 도구: {name}"}
    try:
        return fn(**(args or {}))
    except Exception as e:  # 도구 오류도 LLM에게 그대로 알려 설명하게 함
        return {"error": f"{type(e).__name__}: {e}"}


def _chat_openai(cfg: dict, question: str, trace: list) -> str:
    tools = [{"type": "function", "function": t} for t in TOOL_SPECS]
    msgs = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": question}]
    for _ in range(6):
        r = requests.post(f"{cfg['base_url']}/chat/completions", timeout=90,
                          headers={"Authorization": f"Bearer {cfg['key']}"},
                          json={"model": cfg["model"], "messages": msgs, "tools": tools, "temperature": 0.2})
        r.raise_for_status()
        msg = r.json()["choices"][0]["message"]
        calls = msg.get("tool_calls") or []
        if not calls:
            return msg.get("content") or ""
        msgs.append({"role": "assistant", "content": msg.get("content") or "", "tool_calls": calls})
        for c in calls:
            args = json.loads(c["function"].get("arguments") or "{}")
            result = _run_tool(c["function"]["name"], args)
            trace.append({"tool": c["function"]["name"], "args": args, "result": result})
            msgs.append({"role": "tool", "tool_call_id": c["id"],
                         "content": json.dumps(result, ensure_ascii=False, default=str)[:12000]})
    return "질문을 처리하는 데 단계가 너무 많이 필요했어요. 조금 더 짧게 물어봐 주세요."


def _chat_anthropic(cfg: dict, question: str, trace: list) -> str:
    tools = [{"name": t["name"], "description": t["description"], "input_schema": t["parameters"]}
             for t in TOOL_SPECS]
    msgs = [{"role": "user", "content": question}]
    headers = {"x-api-key": cfg["key"], "anthropic-version": "2023-06-01"}
    for _ in range(6):
        r = requests.post(f"{cfg['base_url']}/messages", headers=headers, timeout=90,
                          json={"model": cfg["model"], "max_tokens": 1200, "system": SYSTEM_PROMPT,
                                "tools": tools, "messages": msgs})
        r.raise_for_status()
        body = r.json()
        uses = [b for b in body["content"] if b["type"] == "tool_use"]
        if not uses:
            return "".join(b.get("text", "") for b in body["content"] if b["type"] == "text")
        msgs.append({"role": "assistant", "content": body["content"]})
        results = []
        for u in uses:
            result = _run_tool(u["name"], u.get("input") or {})
            trace.append({"tool": u["name"], "args": u.get("input"), "result": result})
            results.append({"type": "tool_result", "tool_use_id": u["id"],
                            "content": json.dumps(result, ensure_ascii=False, default=str)[:12000]})
        msgs.append({"role": "user", "content": results})
    return "질문을 처리하는 데 단계가 너무 많이 필요했어요. 조금 더 짧게 물어봐 주세요."


# ---------------------------------------------------------------- 비상 모드 (LLM 없음)
# 제주 동네·장소 이름 (충전소 검색어로 씀). 필요하면 더 추가하세요.
JEJU_PLACES = [
    # 제주시 동
    "일도", "이도", "삼도", "용담", "건입", "화북", "삼양", "봉개", "아라", "오라", "연동", "노형",
    "외도", "이호", "도두", "신제주", "구제주",
    # 읍면
    "애월", "한림", "한경", "조천", "구좌", "우도", "추자", "대정", "안덕", "남원", "성산", "표선",
    # 서귀포시 동
    "송산", "정방", "중앙", "천지", "효돈", "영천", "동홍", "서홍", "대륜", "대천", "중문", "예래",
    # 자주 쓰는 장소
    "제주공항", "공항", "도청", "제주시청", "서귀포시청", "시청", "터미널", "함덕", "협재", "월정",
]
APPLIANCE_WORDS = ("빨래", "세탁", "식기", "건조기", "가전", "에어컨", "보일러", "청소기", "다리미", "밥솥", "충전기")


def _guess_day(question: str) -> str:
    q = question.replace(" ", "")
    for w in "월화수목금토일":
        if f"{w}요일" in q:
            return w
    today = date.today()
    for word, plus in (("모레", 2), ("내일", 1), ("오늘", 0)):
        if word in q:
            return (today + timedelta(days=plus)).strftime("%Y-%m-%d")
    if "주말" in q:  # 이번 주 토요일 (토·일 중 더 좋은 날은 추천 목록에서 함께 보임)
        return ""
    return ""


def _guess_area(question: str) -> str:
    q = question.replace(" ", "")
    for place in sorted(JEJU_PLACES, key=len, reverse=True):
        if place in q:
            return place
    for w in question.replace("?", " ").split():
        for suf in ("동", "읍", "면", "리"):
            if w.endswith(suf) and 2 <= len(w) <= 5:
                return w
    return ""


def _route(question: str) -> list[tuple[str, dict]]:
    """비상 모드: 낱말로 도구를 고름. 어느 것에도 해당하지 않으면 빈 목록 → '답할 수 없는 질문'으로 안내."""
    q = question.replace(" ", "").lower()
    day = _guess_day(question)
    has = lambda *ks: any(k in q for k in ks)
    if has("맞았", "맞혔", "틀렸", "검증", "적중", "정확했", "정확해", "지난예보", "지난주예보", "저번주예보", "지난달예보"):
        return [("check_past_forecast", {})]
    when = has("언제", "몇시", "이번주", "다음주", "내일", "모레", "오늘", "주말", "요일", "며칠")
    # '언제 써야 싸게 쓸까?'처럼 시간을 묻는 질문은 이득 설명이 아니라 시간 추천으로 보냄
    if has("이득", "혜택", "좋은점", "장점", "왜써", "도움이돼") or (
            has("돈이", "절약", "아낄", "아껴", "요금이줄", "싸져", "싸게", "싸지") and not when):
        return [("explain_benefits", {})]
    if has("왜", "이유", "원인", "출력제어", "smp", "무슨뜻") or (has("뭐야", "뭔가요", "뭐예요") and has("잉여", "전기", "smp", "출력")):
        return [("explain_surplus", {})]
    if has("습관", "몇시에충전", "보통충전", "도민들은", "다른사람", "많이충전"):
        return [("ev_charging_habits", {})]
    if has("전기차", "충전", "ev"):
        area = _guess_area(question)
        if area or has("충전소", "충전기", "어디", "근처", "가까운"):
            steps = [("find_chargers", {"area": area, "quick_only": "급속" in q})]
            if day or has("하려", "할건데", "하려는데", "언제"):   # '토요일에 노형동에서 충전하려는데' → 시간 + 장소
                steps.insert(0, ("recommend_actions", {"target": "전기차", "day": day}))
            return steps
        return [("recommend_actions", {"target": "전기차", "day": day})]
    if has("데이터", "상태", "연결", "출처"):
        return [("data_status", {})]
    if has(*APPLIANCE_WORDS) or has("돌려", "돌릴", "켜도", "써도", "쓰면좋", "언제쓰", "써야", "싸게", "싸지"):
        return [("recommend_actions", {"target": "가전", "day": day})]
    if has("예보", "며칠", "이번주", "다음주", "언제", "내일", "모레", "주말", "남아", "남는", "잉여"):
        return [("forecast_surplus", {})]
    return []


UNKNOWN_ANSWER = (
    "죄송해요, 이 질문은 제가 가진 데이터로는 답할 수 없어요. 제가 도와드릴 수 있는 건 아래와 같아요.\n"
    "- 언제 전기가 남는지 예보 (예: '이번 주 언제 전기가 남아?')\n"
    "- 빨래·식기세척기·전기차 충전 좋은 시간 (예: '내일 빨래 언제 돌려?')\n"
    "- 동네 근처 충전소 (예: '노형동 근처 급속 충전소')\n"
    "- 잉여전력이 생기는 이유, 도민이 얻는 이득, 지난 예보가 맞았는지\n"
    "질문을 이 중 하나로 바꿔 주시면 데이터를 찾아 답해 드릴게요."
)


def _template(name: str, r: dict) -> str:
    if "error" in r:
        return f"- {r['error']}"
    if name == "recommend_actions":
        return "\n".join(f"- {t}" for t in r["tips"]) + f"\n- 참고: {FACTS['jeju_new_tariff_plan']['text']}"
    if name == "forecast_surplus":
        return "\n".join(f"- {d['date']}({d['weekday']}): {d['level']} · {d['likely_time_text']}" for d in r["forecast"])
    if name == "explain_benefits":
        lines = ["- 지금 바로: " + r["now_if_tou"],
                 "- 솔직히 말하면: " + r["not_for_standard"]]
        if "ev_evening_share" in r:
            lines.append(f"- 전기차: 제주 공용 충전의 {r['ev_evening_share']:.0%}가 가장 비싼 저녁 4~10시에 시작돼요"
                         f"({r['ev_period']}). 이 중 일부를 낮 잉여 시간으로 옮기는 게 이 도우미의 목표예요.")
        lines.append("- 모두에게: " + r["public"])
        lines.append("- 앞으로: " + r["future"])
        return "\n".join(lines)
    if name == "find_chargers":
        if r.get("error"):
            return f"- {r['error']}"
        lines = [f"- {r['search']}에서 충전소 {r['count']}곳을 찾았어요. 가까운 곳(급속 먼저):"]
        for c in r["chargers"]:
            quick = f"급속 {c['quick_count']}대" if c["has_quick"] else "완속만"
            if c["slow_count"]:
                quick += f"·완속 {c['slow_count']}대"
            dist = f"{c['distance_km']:.1f}km · " if "distance_km" in c else ""
            fee = ""  # parkingFeeFlag 의 뜻(유료/무료)이 문서로 확인되지 않아 표시하지 않음
            extra = ""
            cr = c.get("crowding_2022") or {}
            if "wait_rate" in cr:
                extra = f" · 2022년 조사: 대기 발생 {cr['wait_rate']:.0%}, 관광객 {cr.get('tourist_share', 0):.0%}"
            lines.append(f"  · {c['name']} ({dist}{quick}{fee}{extra})")
        return "\n".join(lines)
    if name == "ev_charging_habits":
        if "peak_charging_start_hour" not in r:
            return "- 충전 이력 데이터가 아직 없어 비교할 수 없어요."
        return (f"- 제주 공용 충전기에서는 {r['peak_charging_start_hour']}시에 충전을 가장 많이 시작했어요"
                f"({r['period']}).\n- 잉여가 잘 생기는 {r['surplus_window_text']}에 시작한 충전은 전체의 "
                f"{r['share_of_charging_in_surplus_window']:.0%}예요."
                + (f"\n- 반대로 저녁 4~10시(계시별 요금의 최대부하 시간)에 시작한 충전이 {r['evening_peak_share']:.0%}나 돼요. "
                   "이 중 일부만 낮으로 옮겨도 남는 전기를 더 쓸 수 있고, 계시별 요금을 쓰는 집 충전이라면 요금도 줄일 수 있어요." if "evening_peak_share" in r else ""))
    if name == "explain_surplus":
        top = sorted(r["surplus_day_rate_by_month"].items(), key=lambda x: -x[1])[:3]
        months = ", ".join(f"{m}월({v:.0%})" for m, v in top)
        text = (f"- {r['period']} 동안 {r['days']}일 중 {r['surplus_days']}일, 모두 {r['surplus_hours']}시간에 "
                f"제주 전기 가격이 0원 이하로 떨어졌어요.\n- 잉여가 잦은 달: {months}\n"
                f"- 주로 맑은 날 한낮에 태양광 발전이 몰리고, 냉난방을 덜 쓰는 봄·가을 주말에 많이 생겨요.")
        if "climate_by_month_2000_2021" in r:
            c = r["climate_by_month_2000_2021"]
            sol = {int(k): v for k, v in c["solar_hourly_mean_MJ_gosan"].items()}
            sunh = {int(k): v for k, v in c["sunshine_hours"].items()}
            text += (f"\n- 2000~2021년 제주 기후를 보면 4~5월 햇빛(일사)이 1월의 약 {sol[4] / sol[1]:.1f}배로 강하고, "
                     f"하루 해 비치는 시간도 4월 {sunh[4]}시간으로 장마철 6월({sunh[6]}시간)보다 길어요. "
                     f"여기에 봄은 냉난방을 덜 써서 전기가 남기 쉬워요.")
        elif "solar_by_month_MJ" in r:
            sun = sorted(r["solar_by_month_MJ"].items(), key=lambda x: -x[1])[:3]
            text += "\n- 제주 햇빛(일사량)이 강한 달: " + ", ".join(f"{m}월" for m, _ in sun)
        if "solar_business" in r:
            sb = r["solar_business"]
            cum = {int(k): v for k, v in sb["cumulative_mw_by_year"].items()}
            y0 = 2018 if 2018 in cum else min(cum)
            text += (f"\n- 도에 등록된 태양광 발전 사업체는 {sb['count']:,}곳, 모두 {sb['total_mw']:.0f}MW예요. "
                     f"{y0}년 {cum[y0]:.0f}MW에서 지금 {sb['total_mw']:.0f}MW로 늘어 한낮에 남는 전기가 많아졌어요.")
        if "wind_power" in r:
            wp = r["wind_power"]
            text += f"\n- 풍력발전소도 {wp['count']}곳, {wp['total_mw']:.0f}MW가 있어 바람 센 날엔 전기가 더 남기 쉬워요."
        return text
    if name == "check_past_forecast":
        actual_days = sum(d["actual_surplus"] for d in r["days"])
        head = f"- {r['period']} 실제 잉여일 {actual_days}일."
        if r["said_possible"]:
            head += (f" '가능성 있음'으로 알린 {r['said_possible']}일 중 {r['correct_when_said']}일이 맞았고, "
                     f"놓친 날은 {r['missed_surplus_days']}일이에요.")
        else:
            head += f" 이 기간에는 '가능성 있음' 예보를 내지 않아 {r['missed_surplus_days']}일을 놓쳤어요."
        return head + f"\n- 기준: {r['basis']}"
    if name == "data_status":
        return f"- 모드: {r['mode']} / 준비된 허브 데이터 {r['hub_datasets_ready']}종"
    return json.dumps(r, ensure_ascii=False, default=str)[:800]


def _fallback(question: str, trace: list) -> str:
    steps = _route(question)
    if not steps:
        trace.append({"tool": "none", "args": {}, "result": {"note": "지원하지 않는 질문"}})
        return UNKNOWN_ANSWER
    parts = []
    for name, args in steps:
        result = _run_tool(name, args)
        trace.append({"tool": name, "args": args, "result": result})
        parts.append(_template(name, result))
    sources = sorted({s for t in trace for s in t["result"].get("sources", []) if isinstance(s, str)})
    return "\n".join(parts) + (f"\n\n출처: {', '.join(sources)}" if sources else "")


# ---------------------------------------------------------------- 공개 함수
def ask(question: str) -> dict:
    """반환: {'answer': 답변, 'trace': 부른 도구와 결과, 'mode': 'llm' 또는 'fallback'}"""
    trace: list = []
    cfg = _llm_config()
    if cfg:
        try:
            fn = _chat_anthropic if cfg["provider"] == "anthropic" else _chat_openai
            return {"answer": fn(cfg, question, trace), "trace": trace, "mode": "llm"}
        except Exception as e:
            trace.append({"tool": "llm_error", "args": {}, "result": {"error": str(e)}})
    return {"answer": _fallback(question, trace), "trace": trace, "mode": "fallback"}


if __name__ == "__main__":
    q = " ".join(sys.argv[1:]) or "이번 주에 빨래 언제 돌리면 좋아?"
    res = ask(q)
    print(f"[{res['mode']}] {res['answer']}")
    print("사용한 도구:", [t["tool"] for t in res["trace"]])
