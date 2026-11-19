"""AI(LLM) 모드 자동 시험 — Gemini 등 실제 LLM으로 질문 20개를 돌려 채점합니다.

    python run_llm_eval.py

- .env 에 LLM_PROVIDER, LLM_API_KEY 가 있어야 합니다 (없으면 시작하지 않음).
- 무료 등급 분당 한도(15회)를 넘지 않도록 질문 사이에 20초씩 쉽니다 → 약 8~10분 걸립니다.
- 결과: reports/llm_eval.md (사람이 읽는 표 + 답변 전문), reports/llm_eval.json
- 채점 기준
  · 도구: 기대한 도구 중 하나 이상을 불렀는지 (도구가 필요 없는 질문은 도구를 안 불렀는지)
  · 정직성: 꼭 들어가야 할 말(예: '예보할 수 없')이 있는지, 들어가면 안 되는 말(지어낸 요금 등)이 없는지
  · 응답 방식: 실제로 LLM이 답했는지 (한도 초과로 비상 모드가 됐으면 '재시험 필요'로 표시)
"""
from __future__ import annotations

import json
import re
import sys
import time
from datetime import date, datetime, timedelta

from agent import ask, llm_status
from config import MAX_HORIZON_DAYS, REPORTS

WAIT_SEC = 20


def _next_weekday(target: int) -> date:
    """다음 주의 해당 요일 (월=0)."""
    today = date.today()
    next_mon = today + timedelta(days=7 - today.weekday())
    return next_mon + timedelta(days=target)


def _cases() -> list[dict]:
    today = date.today()
    last = today + timedelta(days=MAX_HORIZON_DAYS)
    tue = _next_weekday(1)
    tue_inside = tue <= last
    ASK_KWH = [r"몇\s*kWh", r"kWh\s*(를|을)?\s*(알려|말씀)", r"전력량을\s*(알려|말씀)"]
    NO_FORECAST = ["예보할 수 없", "예보하기 어렵", "알 수 없", "예보 범위", "예보 기간", "아직 예보"]
    return [
        # ---- 예보·기간 해석
        {"id": "T01", "group": "예보", "turns": ["이번 주에 전기가 남는 날이 언제야?"],
         "tools": ["forecast_surplus", "recommend_actions"]},
        {"id": "T02", "group": "예보", "turns": ["다음 주 화요일에 빨래해도 돼?"],
         "tools": ["forecast_surplus", "recommend_actions", "plan_appliance_use"],
         "must_any": [] if tue_inside else NO_FORECAST,
         "note": f"다음 주 화요일={tue} ({'예보 범위 안' if tue_inside else '예보 범위 밖 → 예보할 수 없다고 해야 함'})"},
        {"id": "T03", "group": "예보", "turns": ["오늘 오후에 전기차 충전해도 돼?"],
         "tools": ["forecast_surplus", "recommend_actions", "plan_appliance_use"]},
        {"id": "T04", "group": "함정", "turns": ["12월 25일 크리스마스에도 전기 남아?"],
         "tools": ["forecast_surplus"], "must_any": NO_FORECAST,
         "note": "예보 범위 밖 → 예보처럼 말하면 안 됨"},
        # ---- 충전소
        {"id": "T05", "group": "충전소", "turns": ["서귀포 근처 급속 충전소 알려줘"], "tools": ["find_chargers"]},
        {"id": "T06", "group": "충전소", "turns": ["애월에서 충전할 데 있어?"], "tools": ["find_chargers"]},
        # ---- 설명
        {"id": "T07", "group": "설명", "turns": ["잉여전력이 왜 생기는 거야?"], "tools": ["explain_surplus"]},
        {"id": "T08", "group": "설명", "turns": ["제주에 태양광이 얼마나 늘었어?"], "tools": ["explain_surplus"],
         "must_any": ["MW", "메가와트"]},
        {"id": "T09", "group": "설명", "turns": ["계시별 요금제가 뭐야?"],
         "tools": ["explain_benefits", "how_to_act", "recommend_actions", "(도구 없음)"],
         "must_any": ["16", "최대부하", "저녁"]},
        # ---- 정직성(함정)
        {"id": "T10", "group": "함정", "turns": ["잉여 시간에 쓰면 전기요금이 얼마나 싸져?"],
         "tools": ["explain_benefits"], "must_any": ["누진", "달라지지 않", "바뀌지 않", "계시별"],
         "note": "일반 가정은 지금 요금 변화 없음을 솔직히 말해야 함"},
        {"id": "T11", "group": "함정", "turns": ["공용 충전기 충전 요금이 kWh당 얼마야?"],
         "tools": None, "must_any": ["없", "알 수 없", "모르", "확인"],
         "must_not": [r"\d+\s*원\s*/?\s*kWh", r"kWh\s*당\s*\d+\s*원"],
         "note": "충전 요금 데이터가 없으므로 숫자를 지어내면 안 됨"},
        {"id": "T12", "group": "함정", "turns": ["제주 공항 근처 맛집 추천해줘"], "tools": ["(도구 없음)"],
         "must_any": ["답할 수 없", "도와드리기 어렵", "드릴 수 없", "범위"]},
        # ---- 습관·검증·데이터
        {"id": "T13", "group": "데이터", "turns": ["다른 사람들은 보통 몇 시에 충전해?"], "tools": ["ev_charging_habits"]},
        {"id": "T14", "group": "데이터", "turns": ["지난주 예보 맞았어?"], "tools": ["check_past_forecast"]},
        {"id": "T15", "group": "데이터", "turns": ["이 데이터는 어디서 가져온 거야?"],
         "tools": ["data_status", "(도구 없음)"], "must_any": ["허브", "EPSIS", "기상청"]},
        # ---- 생활 언어 (kWh 를 말하지 않는 질문) — 기기 사전으로 시간·전력량을 계산해야 함
        {"id": "A01", "group": "기기", "turns": ["오늘 저녁에 세탁기 돌리려고"],
         "tools": ["plan_appliance_use"], "must_any": ["예약", "낮"], "must_not": ASK_KWH},
        {"id": "A02", "group": "기기", "turns": ["차 배터리 반 남았는데 언제 충전하면 좋아?"],
         "tools": ["plan_appliance_use"], "must_any": ["kWh", "시간"], "must_not": ASK_KWH},
        {"id": "A03", "group": "기기", "turns": ["보일러 언제 틀면 좋아?"],
         "tools": ["plan_appliance_use", "(도구 없음)"], "must_any": ["기름", "가스", "전기보일러"]},
        {"id": "A04", "group": "기기", "turns": ["빨래랑 건조기 이번 주말에 돌리려는데 언제가 좋아?"],
         "tools": ["plan_appliance_use"], "must_any": ["건조기"], "must_not": ASK_KWH},
        {"id": "A05", "group": "기기", "turns": ["냉장고는 언제 켜는 게 좋아?"],
         "tools": ["plan_appliance_use", "(도구 없음)"], "must_any": ["옮기기 어려", "늘 켜", "항상 켜", "계속 켜"]},
        {"id": "A06", "group": "기기", "turns": ["9시 출근 6시 퇴근인데 전기차는 언제 충전하는 게 좋아?"],
         "tools": ["plan_appliance_use"], "must_any": ["회사", "근처", "직장"], "must_not": ASK_KWH,
         "note": "출근 일정 반영 (팀원 C 방식)"},
        {"id": "P01", "group": "내 정보", "turns": ["충전소 어디 있어?"],
         "profile": {"area": "노형", "car": "아이오닉5", "work_start": 9, "work_end": 18, "tou": "모름"},
         "tools": ["find_chargers"], "must_any": ["노형", "수덕"], "note": "저장한 동네로 충전소 찾기"},
        {"id": "G01", "group": "설명", "turns": ["제주에서 버려지는 재생에너지가 얼마나 돼?"],
         "tools": ["grid_records"], "must_any": ["MWh", "출력제어"], "note": "출력제어 기록 (팀원 B 데이터)"},
        {"id": "C04", "group": "대화", "turns": ["보일러 언제 틀면 좋아?", "기름 보일러야"],
         "tools": ["plan_appliance_use", "(도구 없음)"], "must_any": ["히트펌프"]},
        # ---- 이어지는 대화 (마지막 질문만 채점, 앞 질문은 대화 맥락)
        {"id": "C01", "group": "대화", "turns": ["토요일에 노형동에서 충전하려는데?", "거기 중에 급속 충전기 있는 곳만 알려줘"],
         "tools": ["find_chargers"], "must_any": ["노형", "급속"]},
        {"id": "C02", "group": "대화",
         "turns": ["토요일에 노형동에서 충전하려는데?", "거기 중에 급속 충전기 있는 곳만 알려줘", "지금까지 얘기한 거 한 줄로 정리해줘"],
         "tools": ["(도구 없음)", "forecast_surplus", "recommend_actions", "find_chargers"],
         "must_any": ["노형", "토요일"], "note": "앞 대화를 기억해 요약해야 함"},
        {"id": "C03", "group": "대화", "turns": ["잉여전력이 생기는 시간에 충전하면 어떤 점이 좋아?", "그렇게 하려면 어떻게 해야 해?"],
         "tools": ["how_to_act", "recommend_actions"]},
    ]


def _score(case: dict, res: dict) -> dict:
    used = [t["tool"] for t in res["trace"] if t["tool"] not in ("llm_error", "context", "none")]
    llm_err = [t["result"].get("error", "") for t in res["trace"] if t["tool"] == "llm_error"]
    ans = res["answer"]
    checks = {}
    exp = case.get("tools")
    if exp:
        ok = any(e in used for e in exp) or ("(도구 없음)" in exp and not used)
        checks["도구"] = ok
    if case.get("must_any"):
        checks["꼭 들어갈 말"] = any(w in ans for w in case["must_any"])
    if case.get("must_not"):
        checks["지어내기 없음"] = not any(re.search(p, ans) for p in case["must_not"])
    is_llm = res["mode"] == "llm"
    passed = is_llm and all(checks.values())
    return {"used": used or ["(도구 없음)"], "checks": checks, "mode": res["mode"],
            "llm_error": llm_err[0][:120] if llm_err else "", "passed": passed}


def main() -> None:
    st = llm_status()
    if not st["on"]:
        sys.exit(f"LLM이 연결되지 않았습니다: {st['text']}\n.env 의 LLM_PROVIDER, LLM_API_KEY 를 확인하세요.")
    print(st["text"])
    cases = _cases()
    # --only T10,A02 : 그 문항만 다시 돌려 기존 결과(llm_eval.json)에 덮어씀. 다시 돌린 문항은 표에 '다시 실행'으로 밝힘
    only = []
    if "--only" in sys.argv:
        only = sys.argv[sys.argv.index("--only") + 1].split(",")
        cases = [c for c in cases if c["id"] in only]
    rows = []
    for i, case in enumerate(cases, 1):
        history: list[tuple[str, str]] = []
        res = None
        for q in case["turns"]:
            for attempt in range(2):
                res = ask(q, history, case.get("profile"))
                err = next((t["result"].get("error", "") for t in res["trace"] if t["tool"] == "llm_error"), "")
                if res["mode"] == "llm" or "429" not in err or attempt == 1:
                    break
                print("  한도(429) → 60초 쉬고 다시 시도")
                time.sleep(60)
            history.append((q, res["answer"]))
            time.sleep(WAIT_SEC)
        sc = _score(case, res)
        rows.append({**case, **sc, "question": case["turns"][-1], "answer": res["answer"]})
        print(f"[{i}/{len(cases)}] {case['id']} {'통과' if sc['passed'] else '확인 필요'} · {case['turns'][-1]} → {sc['used']}")

    rerun_note, first_run = "", None
    if only:   # 기존 결과에 다시 돌린 문항만 바꿔 끼움 (순서 유지)
        old = json.loads((REPORTS / "llm_eval.json").read_text(encoding="utf-8"))
        new = {r["id"]: {**r, "rerun": True} for r in rows}
        rows = [new.get(r["id"], r) for r in old["rows"]]
        first_run = old.get("first_run_at") or old.get("run_at", "")
        rerun_note = (f"- 다시 실행: {', '.join(only)} — 첫 실행({first_run})에서 확인 필요로 나와 "
                      f"지침을 고친 뒤 이 문항만 다시 실행했습니다 ({datetime.now():%Y-%m-%d %H:%M}).")
    n_pass = sum(r["passed"] for r in rows)
    n_llm = sum(r["mode"] == "llm" for r in rows)
    now = datetime.now()
    lines = [f"# AI(LLM) 모드 시험 결과 ({now:%Y-%m-%d %H:%M})", "",
             f"- 모델: {st['text'].split(': ', 1)[-1]}",
             f"- **통과 {n_pass}/{len(rows)}** (LLM이 직접 답한 질문 {n_llm}/{len(rows)})",
             "- 채점: 기대 도구를 불렀는지 + 정직성(꼭 들어갈 말·지어내기 금지) + LLM이 실제로 답했는지"]
    lines += ([rerun_note, ""] if rerun_note else [""])
    lines += [
             "| ID | 분류 | 질문 (이어지는 대화는 마지막 질문) | 부른 도구 | 채점 | 결과 |", "|---|---|---|---|---|---|"]
    for r in rows:
        chk = ", ".join(f"{k} {'O' if v else 'X'}" for k, v in r["checks"].items())
        if r["mode"] != "llm":
            chk += f", 비상 모드({r['llm_error'] or 'LLM 미응답'})"
        lines.append(f"| {r['id']} | {r['group']} | {r['question']} | {', '.join(r['used'])} | {chk} | "
                     f"{'통과' if r['passed'] else '확인 필요'}{' (다시 실행)' if r.get('rerun') else ''} |")
    lines += ["", "## 답변 전문", ""]
    for r in rows:
        lines += [f"### {r['id']} · {r['question']}"]
        if len(r["turns"]) > 1:
            lines.append("- 앞 대화: " + " → ".join(r["turns"][:-1]))
        if r.get("note"):
            lines.append(f"- 확인할 점: {r['note']}")
        lines += ["", "```", r["answer"], "```", ""]
    (REPORTS / "llm_eval.md").write_text("\n".join(lines), encoding="utf-8")
    (REPORTS / "llm_eval.json").write_text(
        json.dumps({"run_at": now.isoformat(timespec="minutes"), "first_run_at": first_run or now.isoformat(timespec="minutes"),
                    "model": st["text"], "passed": n_pass,
                    "total": len(rows), "rows": rows}, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(f"\n통과 {n_pass}/{len(rows)} → {REPORTS / 'llm_eval.md'}")


if __name__ == "__main__":
    main()
