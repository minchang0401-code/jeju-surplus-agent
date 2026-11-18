"""제주 잉여전력 도우미 에이전트.

- LLM 키가 있으면: LLM이 질문을 이해하고 tools.py 의 도구를 골라 부른 뒤, 결과로만 답합니다.
- LLM 키가 없거나 연결이 안 되면: 질문의 낱말로 도구를 고르고 정해진 문장으로 답합니다(비상 모드).

.env 설정
  LLM_PROVIDER=gemini | openai | upstage | anthropic | none
  LLM_API_KEY=...
  LLM_MODEL=(선택, 비우면 config.DEFAULT_LLM 의 기본값)

    python agent.py "이번 주말에 빨래 언제 돌리면 좋아?"
"""
from __future__ import annotations

import json
import re
import sys
from datetime import date, datetime, timedelta

import requests

from config import DEFAULT_LLM, MAX_HORIZON_DAYS, get_key
from facts import FACTS, SAFETY_RULES
from tools import TOOL_SPECS, TOOLS

def _system_prompt() -> str:
    """질문할 때마다 오늘 날짜·이번 주/다음 주 범위를 새로 넣음 (서버가 며칠씩 켜져 있어도 날짜가 맞도록)."""
    now = datetime.now()
    today = now.date()
    mon = today - timedelta(days=today.weekday())
    wd = "월화수목금토일"
    last = today + timedelta(days=MAX_HORIZON_DAYS)
    return f"""너는 '제주 잉여전력 도우미'다. 제주 도민이 재생에너지가 남는 시간에 전기를 쓰도록 돕는다.
지금: {today:%Y-%m-%d}({wd[today.weekday()]}) {now:%H}시
- 이번 주 = {mon:%Y-%m-%d}(월) ~ {mon + timedelta(days=6):%Y-%m-%d}(일)
- 다음 주 = {mon + timedelta(days=7):%Y-%m-%d}(월) ~ {mon + timedelta(days=13):%Y-%m-%d}(일)
- 예보 가능 범위 = {today:%Y-%m-%d} ~ {last:%Y-%m-%d}. 이 밖의 날짜는 예보할 수 없다.
규칙:
- 반드시 도구를 불러 그 결과에 있는 숫자·날짜·장소만 말한다. 도구 결과에 없는 것은 모른다고 말한다.
- 사용자가 말한 기간(오늘·내일·이번 주·다음 주·특정 날짜·요일)을 위 날짜로 바꿔서, 그 기간에 맞게 forecast_surplus 의
  start·days 를 정해 부른다. 묻지 않은 날짜를 그 기간인 것처럼 말하지 않는다.
- 물은 기간의 일부만 예보 범위 안이면, 예보할 수 있는 날과 없는 날을 나눠서 말한다.
- 도구 결과의 not_forecast 날짜는 "예보할 수 없다"고 먼저 말한다. past_surplus_day_rate_same_month 는
  '과거 같은 달 기록(참고)'이라고 밝힐 때만 쓰고, 그 날짜의 예보처럼 말하지 않는다.
- basis 가 '날씨 미반영'인 날은 '날씨 예보가 아직 없어 과거 패턴으로 본 참고치'라고 밝힌다.
- "지금까지 대화 정리해줘", "방금 말한 거 다시 설명해줘"처럼 앞 대화에 대한 요청은 도구 없이 앞 대화 내용으로 답한다.
- 질문이 도구로 답할 수 없는 내용(잉여전력·전기 사용 시간·충전소와 관계없는 질문)이면 도구를 억지로 부르지 말고,
  "제가 가진 데이터로는 답할 수 없어요"라고 말한 뒤 답할 수 있는 질문 예시 2~3개를 알려 준다.
- 도민은 kWh·kW를 모른다. 세탁기·빨래·건조기·식기세척기·전기차(차 배터리)·히트펌프·온수기·보일러·음식물처리기·
  의류관리기·밥솥·에어컨·히터·전기장판 등을 언제 쓸지 물으면 plan_appliance_use 를 먼저 부르고, 사용자에게 전력량을 묻지 않는다.
  도구가 계산한 걸리는 시간·전력량을 '대략'과 '제품·코스마다 달라요'를 붙여 말한다.
- 때를 나타내는 말은 시각으로 바꿔 start_hour·end_hour 에 넣는다: 새벽 0~6, 아침 6~10, 오전 6~12, 낮·점심 10~15,
  오후 12~18, 저녁 18~22, 밤 20~24, 'N시' = 그 시각부터. 날은 day 에 넣는다(오늘·내일은 날짜로, 요일은 한 글자).
- 원하는 시간대에 남는 전기가 거의 없으면(level 낮음 또는 requested_window_best 없음) 솔직히 그렇다고 먼저 말하고,
  best_windows·alternatives 의 더 나은 시간대와 예약 기능을 권한다. evening_note 가 있으면 함께 전한다.
- 전기차는 배터리가 몇 % 남았는지만 물을 수 있다(ask_user). 보일러는 ask_user 질문을 그대로 묻고,
  기름·가스 보일러라고 하면 fuel 을 넣어 다시 불러 support_program 을 안내한다.
- shift 가 '불가'·'낮음'인 기기는 억지로 시간을 옮기라고 하지 않고 도구의 how 를 전한다.
- 질문에 딱 맞는 도구만 부른다. 묻지 않은 예보·충전 습관을 덧붙이지 않는다.
- 어르신도 알아듣게 짧고 쉬운 말로, 3~6문장으로 답한다. 시간은 '낮 12시~오후 2시'처럼 말한다.
- 도구를 썼다면 답 끝에 실제로 쓴 데이터 출처를 한 줄로 적는다 (예: 출처: 제주데이터허브 862, EPSIS). 도구를 안 썼으면 적지 않는다.
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


def llm_status() -> dict:
    """화면에 보여 줄 AI 연결 상태 (키 값은 절대 넣지 않음)."""
    provider = (get_key("LLM_PROVIDER") or "none").lower()
    if provider == "none":
        return {"on": False, "text": "AI(LLM) 꺼짐 — 규칙 기반으로 답해요 (LLM_PROVIDER 미설정)"}
    if provider not in DEFAULT_LLM:
        return {"on": False, "text": f"AI(LLM) 꺼짐 — 지원하지 않는 LLM_PROVIDER: {provider}"}
    if not get_key("LLM_API_KEY"):
        return {"on": False, "text": "AI(LLM) 꺼짐 — LLM_API_KEY 가 없어요"}
    cfg = _llm_config()
    return {"on": True, "text": f"AI(LLM) 연결: {provider} · {cfg['model']}"}


def _run_tool(name: str, args: dict) -> dict:
    fn = TOOLS.get(name)
    if fn is None:
        return {"error": f"없는 도구: {name}"}
    try:
        return fn(**(args or {}))
    except Exception as e:  # 도구 오류도 LLM에게 그대로 알려 설명하게 함
        return {"error": f"{type(e).__name__}: {e}"}


def _history_msgs(history: list | None) -> list[dict]:
    """앞 대화(질문·답변)를 LLM 메시지로. 하루 한도를 아끼려고 최근 3번만, 답변은 1,200자까지."""
    msgs = []
    for q, a in (history or [])[-3:]:
        msgs.append({"role": "user", "content": q})
        if a:
            msgs.append({"role": "assistant", "content": a[:1200]})
    return msgs


def _chat_openai(cfg: dict, question: str, trace: list, history: list | None = None) -> str:
    tools = [{"type": "function", "function": t} for t in TOOL_SPECS]
    msgs = ([{"role": "system", "content": _system_prompt()}] + _history_msgs(history)
            + [{"role": "user", "content": question}])
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


def _chat_anthropic(cfg: dict, question: str, trace: list, history: list | None = None) -> str:
    tools = [{"name": t["name"], "description": t["description"], "input_schema": t["parameters"]}
             for t in TOOL_SPECS]
    msgs = _history_msgs(history) + [{"role": "user", "content": question}]
    headers = {"x-api-key": cfg["key"], "anthropic-version": "2023-06-01"}
    for _ in range(6):
        r = requests.post(f"{cfg['base_url']}/messages", headers=headers, timeout=90,
                          json={"model": cfg["model"], "max_tokens": 1200, "system": _system_prompt(),
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
APPLIANCE_WORDS = ("빨래", "세탁", "식기", "설거지", "건조기", "가전", "에어컨", "보일러", "청소기", "다리미", "밥솥", "충전기",
                   "히트펌프", "온수기", "음식물", "스타일러", "에어드레서", "의류관리기", "히터", "온풍기", "난로",
                   "전기장판", "온수매트", "냉장고", "킥보드", "배터리")
# 이 기기들은 기기 사전(plan_appliance_use)으로 시간·전력량을 계산해 답함 ('가전'처럼 뭉뚱그린 말은 제외)
PLAN_WORDS = tuple(w for w in APPLIANCE_WORDS if w not in ("가전", "청소기", "다리미", "충전기"))
_FUEL_WORDS = ("기름", "가스", "석유", "등유", "lpg")


def _guess_time(question: str) -> tuple[int | None, int | None]:
    """'오늘 저녁', '밤에', '오후 3시' → (시작 시각, 끝 시각). 없으면 (None, None)."""
    q = question.replace(" ", "")
    m = re.search(r"(오전|오후|저녁|밤|낮|아침|새벽)?(\d{1,2})시", q)
    if m:
        h = int(m.group(2))
        if m.group(1) in ("오후", "저녁", "밤") and h < 12:
            h += 12
        return min(h, 23), None
    for words, rng in ((("새벽",), (0, 6)), (("아침",), (6, 10)), (("저녁", "퇴근후", "퇴근하고"), (18, 22)),
                       (("밤", "자기전", "자기 전", "잘때"), (20, 24)), (("오전",), (6, 12)),
                       (("점심", "낮"), (10, 15)), (("오후",), (12, 18))):
        if any(w.replace(" ", "") in q for w in words):
            return rng
    return None, None


def _guess_battery(question: str) -> float | None:
    """'반 남았어'=50, '30%'·'30퍼' → 30, '거의 없어'=10, '조금 남'=20"""
    q = question.replace(" ", "").lower()
    for name in ("아이오닉5", "아이오닉6", "ev3", "ev6", "ev9"):   # 차 이름 속 숫자를 %로 읽지 않도록
        q = q.replace(name, " ")
    m = re.search(r"(\d{1,3})(%|퍼센트|퍼)", q)
    if m:
        return float(m.group(1))
    if "반" in q and ("남" in q or "정도" in q or "쯤" in q):
        return 50.0
    if "거의없" in q or "바닥" in q:
        return 10.0
    if "조금남" in q or "얼마안남" in q:
        return 20.0
    return None


def _guess_car(question: str) -> str:
    from appliances import EV_MODELS
    q = question.replace(" ", "").lower()
    for name in sorted(EV_MODELS, key=len, reverse=True):
        if name.replace(" ", "") in q:
            return name
    return ""


def _guess_day(question: str) -> str:
    q = question.replace(" ", "")
    for w in "월화수목금토일":
        if f"{w}요일" in q:
            return w
    today = date.today()
    for word, plus in (("모레", 2), ("내일", 1), ("오늘", 0)):
        if word in q:
            return (today + timedelta(days=plus)).strftime("%Y-%m-%d")
    m = re.search(r"(\d{1,2})월(\d{1,2})일", q)
    special = (12, 25) if "크리스마스" in q or "성탄" in q else ((int(m.group(1)), int(m.group(2))) if m else None)
    if special:
        try:
            d = date(today.year, *special)
            if d < today:
                d = date(today.year + 1, *special)
            return d.strftime("%Y-%m-%d")
        except ValueError:
            pass
    if "주말" in q:  # 이번 주 토요일 (토·일 중 더 좋은 날은 추천 목록에서 함께 보임)
        return ""
    return ""


# 동네 이름 뒤에 붙는 조사 (예: '하귀리에서' → '하귀리')
_PARTICLES = ("에서", "으로", "근처", "주변", "쪽", "에", "로", "의", "은", "는", "이", "가", "을", "를")
# '동'·'리'로 끝나지만 동네 이름이 아닌 흔한 낱말
_NOT_PLACES = {"자동", "이동", "활동", "행동", "작동", "변동", "가동", "운동", "재가동",
               "우리", "거리", "자리", "소리", "빨리", "멀리", "요리", "정리", "처리", "관리", "무리", "배터리"}


def _guess_area(question: str) -> str:
    """질문에서 동네 이름을 찾음. 목록에 없는 곳은 '○○동/○○리'(3글자 이상)만 동네로 봄.
    '면'·'읍'으로 끝나는 낱말은 보지 않음 → '충전을 하면'의 '하면'을 동네로 착각하지 않도록.
    (제주의 읍·면 이름은 모두 JEJU_PLACES 에 들어 있음)"""
    q = question.replace(" ", "")
    for place in sorted(JEJU_PLACES, key=len, reverse=True):
        if place in q:
            return place
    for w in re.split(r"[\s?!.,~]+", question):
        for p in _PARTICLES:
            if w.endswith(p) and len(w) > len(p) + 1:
                w = w[: -len(p)]
                break
        if len(w) >= 3 and w[-1] in "동리" and w not in _NOT_PLACES:
            return w
    return ""


def _route(question: str) -> list[tuple[str, dict]]:
    """비상 모드: 낱말로 도구를 고름. 어느 것에도 해당하지 않으면 빈 목록 → '답할 수 없는 질문'으로 안내."""
    q = question.replace(" ", "").lower()
    day = _guess_day(question)
    has = lambda *ks: any(k in q for k in ks)
    if has("맞았", "맞혔", "틀렸", "검증", "적중", "정확했", "정확해", "지난예보", "지난주예보", "저번주예보", "지난달예보"):
        return [("check_past_forecast", {})]
    if has("어떻게해", "어떻게하", "방법", "뭘해야", "뭐부터", "어떡해") and not has("출력제어", "smp", "생겨", "생기", "만들어"):
        target = "전기차" if has("전기차", "충전", "ev") else "가전"
        steps = [("recommend_actions", {"target": target, "day": day}), ("how_to_act", {"target": target})]
        area = _guess_area(question) if target == "전기차" else ""
        if area:
            steps.append(("find_chargers", {"area": area, "quick_only": "급속" in q}))
        return steps
    when = has("언제", "몇시", "이번주", "다음주", "내일", "모레", "오늘", "주말", "요일", "며칠")
    # '언제 써야 싸게 쓸까?'처럼 시간을 묻는 질문은 이득 설명이 아니라 시간 추천으로 보냄
    if has("이득", "혜택", "좋은점", "장점", "왜써", "도움이돼", "뭐가좋", "뭐가이득", "어떤게좋", "어떤점이좋",
           "왜좋", "무슨이득", "뭐가달라") or (
            has("돈이", "절약", "아낄", "아껴", "요금이줄", "싸져", "싸게", "싸지") and not when):
        steps = [("explain_benefits", {})]
        if when and has("전기차", "충전", "ev"):   # '이번 주에 충전하면 뭐가 좋아?' → 이번 주 좋은 시간 + 이득
            steps.insert(0, ("recommend_actions", {"target": "전기차", "day": day}))
        return steps
    if has("왜", "이유", "원인", "출력제어", "smp", "무슨뜻", "어떻게생", "왜생", "생기는이유") or (has("뭐야", "뭔가요", "뭐예요") and has("잉여", "전기", "smp", "출력")):
        return [("explain_surplus", {})]
    if has("습관", "보통충전", "보통몇시", "다들", "도민들은", "다른사람", "많이충전"):
        return [("ev_charging_habits", {})]
    small = has("휴대폰", "핸드폰", "폰", "노트북", "킥보드", "보조배터리", "전기자전거", "로봇청소기")
    if small:
        return [("plan_appliance_use", {"appliance": question, "day": day})]
    if not small and has("전기차", "충전", "ev", "배터리") and (
            _guess_battery(question) is not None or _guess_car(question) or has("배터리")):
        sh, eh = _guess_time(question)
        args = {"appliance": "전기차", "day": day, "battery_percent": _guess_battery(question), "car": _guess_car(question)}
        if sh is not None:
            args["start_hour"] = sh
        if eh is not None:
            args["end_hour"] = eh
        steps = [("plan_appliance_use", args)]
        area = _guess_area(question)
        if area:
            steps.append(("find_chargers", {"area": area, "quick_only": "급속" in q}))
        return steps
    if has("전기차", "충전", "ev"):
        area = _guess_area(question)
        if area or has("충전소", "충전기", "어디", "근처", "가까운"):
            steps = [("find_chargers", {"area": area, "quick_only": "급속" in q})]
            if day or has("하려", "할건데", "하려는데", "언제", "몇시"):   # '토요일에 노형동에서 충전하려는데' → 시간 + 장소
                steps.insert(0, ("recommend_actions", {"target": "전기차", "day": day}))
            return steps
        return [("recommend_actions", {"target": "전기차", "day": day})]
    if has("데이터", "상태", "연결", "출처"):
        return [("data_status", {})]
    if has(*PLAN_WORDS):
        from appliances import find_all
        sh, eh = _guess_time(question)
        steps = []
        for key in (find_all(question) or [question])[:3]:   # '빨래랑 식기세척기' → 기기마다 하나씩
            args = {"appliance": key if key != question else question, "day": day, "question": question}
            if sh is not None:
                args["start_hour"] = sh
            if eh is not None:
                args["end_hour"] = eh
            steps.append(("plan_appliance_use", args))
        return steps
    if has(*APPLIANCE_WORDS) or has("돌려", "돌릴", "켜도", "써도", "쓰면좋", "언제쓰", "써야", "싸게", "싸지"):
        return [("recommend_actions", {"target": "가전", "day": day})]
    if has("예보", "며칠", "이번주", "다음주", "언제", "내일", "모레", "주말", "남아", "남는", "잉여"):
        return [("forecast_surplus", {})]
    return []


UNKNOWN_ANSWER = (
    "죄송해요, 이 질문은 제가 가진 데이터로는 답할 수 없어요. 제가 도와드릴 수 있는 건 아래와 같아요.\n"
    "- 언제 전기가 남는지 예보 (예: '이번 주 언제 전기가 남아?')\n"
    "- 빨래·식기세척기·건조기·전기차 충전 좋은 시간과 걸리는 시간·전기량 (예: '오늘 저녁에 세탁기 돌리려고', '차 배터리 반 남았어')\n"
    "- 동네 근처 충전소 (예: '노형동 근처 급속 충전소')\n"
    "- 잉여전력이 생기는 이유, 도민이 얻는 이득, 지난 예보가 맞았는지\n"
    "질문을 이 중 하나로 바꿔 주시면 데이터를 찾아 답해 드릴게요."
)


def _day_text(d: str, wd: str) -> str:
    return f"{int(d[5:7])}월 {int(d[8:10])}일({wd})"


def _range_text(lo: float, hi: float, unit: str) -> str:
    f = lambda x: f"{x:g}"
    return f"{f(lo)}{unit}" if lo == hi else f"{f(lo)}~{f(hi)}{unit}"


def _hours_word(h: float) -> str:
    """1.7 → '1시간 40분', 0.5 → '30분', 2.0 → '2시간'"""
    total = int(round(h * 6)) * 10           # 10분 단위
    hh, mm = divmod(total, 60)
    if hh == 0:
        return f"{max(mm, 10)}분"
    return f"{hh}시간" + (f" {mm}분" if mm else "")


def _plan_text(r: dict) -> str:
    """plan_appliance_use 결과 → 쉬운 말"""
    name, lines = r["appliance"], []
    if "ev" in r:
        ev = r["ev"]
        lines.append(f"- 전기차: {ev['battery_note']}으로 {int(ev['now_percent'])}% → {int(ev['target_percent'])}% 채우려면 "
                     f"전기 약 {ev['kwh']:g}kWh, 완속 충전기(7kW)로 약 {_hours_word(ev['hours'])} 걸려요.")
        if ev["hours"] >= 4:
            lines.append(f"- 완속은 오래 걸려 낮 시간에 다 못 맞출 수 있어요. 급속 충전기(50kW)를 쓰면 약 "
                         f"{_hours_word(ev['quick_hours'])}이라 남는 전기 시간에 맞추기 쉬워요.")
    elif r.get("kwh_range") or r.get("hours_range") or r.get("kwh_per_hour_range"):
        bits = []
        if r.get("hours_range"):
            lo, hi = r["hours_range"]
            bits.append(f"한 번에 약 {_hours_word(lo)}~{_hours_word(hi)}")
        if r.get("kwh_range"):
            bits.append(f"전기 약 {_range_text(*r['kwh_range'], 'kWh')}")
        if r.get("kwh_per_hour_range"):
            bits.append(f"1시간에 전기 약 {_range_text(*r['kwh_per_hour_range'], 'kWh')}")
        lines.append(f"- {name}: " + ", ".join(bits) + " 써요 (제품·코스마다 달라요).")
    if r["mode"] in ("ask", "none") or r["shift"] == "불가":
        lines.append(f"- {r['how']}")
        if r.get("ask_user"):
            lines.append(f"- {r['ask_user']}")
        if r.get("support_program"):
            lines.append(f"- {r['support_program']}")
        return "\n".join(lines)
    if r.get("not_forecast"):
        lines.append(f"- {r['not_forecast']}")
        lines.append(f"- {r['how']}")
        return "\n".join(lines)
    if r["shift"] == "낮음":
        lines.append(f"- {r['how']}")
        wins = r.get("alternatives") or r.get("best_windows") or []
        if wins:
            w = wins[0]
            lines.append(f"- 그래도 낮에 쓸 수 있다면 {_day_text(w['date'], w['weekday'])} {w['time_text']}가 가장 나아요"
                         f"(가능성 {w['level']}).")
        return "\n".join(lines)
    req = r.get("requested_window_best", "없음")
    if req != "없음":
        if not req or req["level"] == "낮음":
            lines.append("- 원하신 때에는 제주에 남는 전기가 거의 없을 것 같아요.")
        else:
            lines.append(f"- 원하신 때 중에는 {_day_text(req['date'], req['weekday'])} {req['time_text']}가 가장 나아요"
                         f"(가능성 {req['level']}).")
    if r.get("evening_note"):
        lines.append(f"- {r['evening_note']}")
    wins = r.get("alternatives") or r.get("best_windows") or []
    if wins:
        if all(w["level"] == "낮음" for w in wins):
            lines.append("- 예보 기간에는 남는 전기 가능성이 모두 낮아요. 그래도 그중 나은 때는:")
        else:
            verb = "충전하기" if name == "전기차" else ("틀기" if name in ("에어컨", "전기히터") else "돌리기")
            lines.append(f"- {name} {verb} 좋은 때 ({r['length_hours']}시간 연속):")
        for w in wins:
            ref = " · 날씨 미반영 참고치" if w["basis"].startswith("날씨 미반영") else ""
            lines.append(f"  · {_day_text(w['date'], w['weekday'])} {w['time_text']} (가능성 {w['level']}{ref})")
    lines.append(f"- {r['how']}")
    if r.get("ask_user"):
        lines.append(f"- {r['ask_user']}")
    return "\n".join(lines)


def _template(name: str, r: dict) -> str:
    if "error" in r:
        return f"- {r['error']}"
    if name == "recommend_actions":
        return "\n".join(f"- {t}" for t in r["tips"]) + f"\n- 참고: {FACTS['jeju_new_tariff_plan']['text']}"
    if name == "forecast_surplus":
        lines = [f"- {d['date']}({d['weekday']}): {d['level']} · {d['likely_time_text']}"
                 + (" (날씨 미반영 참고치)" if d.get("basis", "").startswith("날씨 미반영") else "")
                 for d in r["forecast"]]
        nf = r.get("not_forecast")
        if nf:
            rates = ", ".join(f"{m} {v:.0%}" for m, v in nf["past_surplus_day_rate_same_month"].items())
            lines.append(f"- {nf['dates']}: 예보할 수 있는 기간({r['forecast_range'].split(' (')[0]}) 밖이라 예보할 수 없어요. "
                         f"참고로 과거 같은 달에 전기가 남은 날의 비율은 {rates}였어요(예보 아님).")
        return "\n".join(lines)
    if name == "explain_benefits":
        lines = ["- 지금 바로: " + r["now_if_tou"],
                 "- 솔직히 말하면: " + r["not_for_standard"]]
        if "ev_evening_share" in r:
            lines.append(f"- 전기차: 제주 공용 충전의 {r['ev_evening_share']:.0%}가 가장 비싼 저녁 4~10시에 시작돼요"
                         f"({r['ev_period']}). 이 중 일부를 낮 잉여 시간으로 옮기는 게 이 도우미의 목표예요.")
        lines.append("- 모두에게: " + r["public"])
        lines.append("- 앞으로: " + r["future"])
        return "\n".join(lines)
    if name == "plan_appliance_use":
        return _plan_text(r)
    if name == "how_to_act":
        return "- 이렇게 해 보세요:\n" + "\n".join(f"  {i}. {t}" for i, t in enumerate(r["steps"], 1))
    if name == "find_chargers":
        if r.get("error"):
            return f"- {r['error']}"
        if r.get("search") == "전체":
            return (f"- 어느 동네인지 알려 주시면 그 근처 충전소를 찾아 드릴게요. 제주에는 공용 충전소가 {r['count']:,}곳 있어요.\n"
                    "  예: '노형동 근처 충전소', '애월 급속 충전기', '서귀포시청 근처 충전소'")
        if not r.get("count"):
            return (f"- {r['search']}에서는 충전소를 찾지 못했어요. "
                    "동네 이름을 넣어 다시 물어봐 주세요. (예: '노형동 근처 충전소', '애월 급속 충전기')")
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


# 앞 질문을 가리키는 말 ('그렇게 하려면 어떻게 해?', '그럼 언제?')
_FOLLOWUP = ("그렇게", "그럼", "그러면", "그거", "그건", "그걸", "그것", "그때", "거기", "이거", "이렇게", "그래서")
_TOPIC = ("전기차", "충전", "ev") + APPLIANCE_WORDS
_ASK_WORDS = ("어떻게", "방법", "언제", "몇시", "어디", "근처", "가까운", "급속", "왜", "좋아", "좋을", "이득",
              "요일", "내일", "모레", "오늘", "주말", "이번주", "다음주", "뭘해", "어떡")


def _with_context(question: str, history: list[str] | None) -> tuple[str, str]:
    """앞 질문에 기대는 짧은 질문이면 앞 질문의 주제(충전·빨래 등)를 붙여서 이해함.
    반환: (도구 고르기에 쓸 질문, 이어 받은 앞 질문 — 없으면 '')"""
    if not history:
        return question, ""
    q = question.replace(" ", "").lower()
    if any(t in q for t in _TOPIC):
        return question, ""
    # '기름이야'(보일러 종류 답), '30% 남았어'(배터리 답) 처럼 앞 질문에 대한 대답
    for prev in reversed(history[-2:]):
        p = prev.replace(" ", "").lower()
        if "보일러" in p and any(w in q for w in _FUEL_WORDS + ("전기",)):
            return f"{question} 보일러", prev
        if any(w in p for w in ("전기차", "충전", "ev", "배터리")) and _guess_battery(question) is not None:
            return f"전기차 배터리 {question} {prev}", prev
    if not (any(w in q for w in _FOLLOWUP) or (not _route(question) and len(q) <= 15)):
        return question, ""
    # '그럼 맛집은?'처럼 앞 주제와 관계없는 질문까지 끌어오지 않도록, 묻는 말(언제·어디·어떻게 …)이 있을 때만 이어 받음
    if not any(w in q for w in _ASK_WORDS):
        return question, ""
    for prev in reversed(history):
        p = prev.replace(" ", "").lower()
        hit = [t for t in _TOPIC if t in p]
        if hit:
            topic = "전기차 충전" if hit[0] in ("전기차", "충전", "ev") else hit[0]
            area = _guess_area(prev)
            return f"{area} {topic} {question}".strip(), prev
    return question, ""


def _fallback(question: str, trace: list, history: list[str] | None = None) -> str:
    routed, prev = _with_context(question, history)
    steps = _route(routed)
    if prev and steps:
        trace.append({"tool": "context", "args": {"앞 질문": prev}, "result": {"note": f"앞 질문에 이어서 이해: {routed}"}})
    if not steps:
        trace.append({"tool": "none", "args": {}, "result": {"note": "지원하지 않는 질문"}})
        return UNKNOWN_ANSWER
    parts = []
    for name, args in steps:
        result = _run_tool(name, args)
        trace.append({"tool": name, "args": args, "result": result})
        parts.append(_template(name, result))
    # 여러 도구의 답에 같은 문장이 겹치면 한 번만 보여 줌 (예: 제주형 요금제 안내)
    seen, lines = set(), []
    for line in "\n".join(parts).split("\n"):
        key = line.split(": ", 1)[-1].strip()
        if key and key in seen and not line.startswith("  ·"):   # 시간대 목록은 기기마다 보여 줌
            continue
        seen.add(key)
        lines.append(line)
    parts = ["\n".join(lines)]
    if prev:
        parts.insert(0, f"(앞 질문 '{prev}'에 이어서 답할게요)")
    sources = sorted({s for t in trace for s in t["result"].get("sources", []) if isinstance(s, str)})
    return "\n".join(parts) + (f"\n\n출처: {', '.join(sources)}" if sources else "")


# ---------------------------------------------------------------- 공개 함수
def ask(question: str, history: list | None = None) -> dict:
    """history: 같은 대화의 앞 질문들(오래된 것부터). 각 항목은 질문 문자열 또는 (질문, 답변).
    LLM 에는 앞 질문·답변을 대화로 넘기고, 비상 모드는 앞 질문의 주제만 이어 받음.
    반환: {'answer': 답변, 'trace': 부른 도구와 결과, 'mode': 'llm' 또는 'fallback'}"""
    trace: list = []
    pairs = [(h, None) if isinstance(h, str) else (h[0], h[1]) for h in (history or [])]
    cfg = _llm_config()
    if cfg:
        try:
            fn = _chat_anthropic if cfg["provider"] == "anthropic" else _chat_openai
            return {"answer": fn(cfg, question, trace, pairs), "trace": trace, "mode": "llm"}
        except Exception as e:
            trace.append({"tool": "llm_error", "args": {}, "result": {"error": str(e)}})
    return {"answer": _fallback(question, trace, [q for q, _ in pairs]), "trace": trace, "mode": "fallback"}


if __name__ == "__main__":
    q = " ".join(sys.argv[1:]) or "이번 주에 빨래 언제 돌리면 좋아?"
    res = ask(q)
    print(f"[{res['mode']}] {res['answer']}")
    print("사용한 도구:", [t["tool"] for t in res["trace"]])
