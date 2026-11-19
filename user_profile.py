"""내 정보 — 동네·차종·출퇴근·요금제를 한 번 넣으면 질문마다 기본값으로 씀.

화면(app.py)은 내 정보를 주소창(URL)에 담아 두므로, 그 주소를 즐겨찾기하면 다음에도 그대로 불러옵니다.
개인 이름·연락처는 받지 않습니다 (동네는 대표 지명 수준).
"""
from __future__ import annotations

# 화면에 보이는 이름 → appliances.EV_MODELS 의 차종 이름
CARS = {
    "없음 / 모름": "",
    "레이EV (35.2kWh)": "레이",
    "니로EV·코나 일렉트릭 (64.8kWh)": "니로",
    "아이오닉5·아이오닉6·EV6 (84kWh)": "아이오닉5",
}
TOU = ("모름", "가입", "미가입")   # 계시별(시간대별) 요금제


def empty() -> dict:
    return {"area": "", "car": "", "work_start": None, "work_end": None, "tou": "모름"}


def from_query(q: dict) -> dict:
    """주소창 값(area, car, ws, we, tou) → 내 정보."""
    p = empty()
    p["area"] = str(q.get("area", "") or "")
    p["car"] = str(q.get("car", "") or "")
    try:
        ws, we = int(q.get("ws")), int(q.get("we"))
        if 0 <= ws < we <= 24:
            p["work_start"], p["work_end"] = ws, we
    except (TypeError, ValueError):
        pass
    tou = str(q.get("tou", "모름"))
    p["tou"] = tou if tou in TOU else "모름"
    return p


def to_query(p: dict) -> dict:
    q = {}
    if p.get("area"):
        q["area"] = p["area"]
    if p.get("car"):
        q["car"] = p["car"]
    if p.get("work_start") is not None and p.get("work_end") is not None:
        q["ws"], q["we"] = str(p["work_start"]), str(p["work_end"])
    if p.get("tou") and p["tou"] != "모름":
        q["tou"] = p["tou"]
    return q


def is_set(p: dict | None) -> bool:
    return bool(p) and any([p.get("area"), p.get("car"), p.get("work_start") is not None, p.get("tou") not in (None, "모름")])


def summary(p: dict | None) -> str:
    if not is_set(p):
        return ""
    bits = []
    if p.get("area"):
        bits.append(f"동네 {p['area']}")
    if p.get("car"):
        bits.append(f"차 {p['car']}")
    if p.get("work_start") is not None:
        bits.append(f"평일 {p['work_start']}~{p['work_end']}시 집에 없음")
    if p.get("tou") != "모름":
        bits.append(f"계시별 요금제 {p['tou']}")
    return " · ".join(bits)


def to_prompt(p: dict | None) -> str:
    """LLM 지침에 붙일 문장."""
    if not is_set(p):
        return ""
    return f"""사용자가 저장한 내 정보: {summary(p)}
- 질문에 동네·차종·시간이 없으면 이 정보를 기본값으로 쓴다: 충전소는 area, 전기차 계산은 car,
  출근 일정은 away_start·away_end(평일). 질문에 다른 값이 있으면 질문이 우선이다.
- 계시별 요금제 '가입'이면 낮 시간 사용이 요금에도 유리하다고 말해도 되고, '미가입'이면 지금 요금 이득은 없다고 솔직히 말한다.
- 내 정보를 매번 되풀이해 말하지 않는다. 쓴 경우에만 "저장한 내 정보(…) 기준"이라고 짧게 밝힌다.
"""


def apply_defaults(steps: list[tuple[str, dict]], question: str, p: dict | None) -> list[tuple[str, dict]]:
    """규칙 기반 모드: 질문에 없는 값을 내 정보로 채움."""
    if not is_set(p):
        return steps
    q = (question or "").replace(" ", "")
    mentions_time = any(w in q for w in ("출근", "퇴근", "외출", "부터", "까지"))
    out = []
    for name, args in steps:
        args = dict(args)
        if name == "find_chargers" and not args.get("area") and p.get("area"):
            args["area"] = p["area"]
        if name == "recommend_actions" and args.get("target") == "전기차" and (p.get("car") or p.get("work_start") is not None):
            # 차·출퇴근을 알면 기기 사전 계산(배터리 반쯤 가정)으로 더 구체적으로 답함
            name, args = "plan_appliance_use", {"appliance": "전기차", "day": args.get("day", ""), "question": question}
        if name == "plan_appliance_use":
            if (args.get("appliance") == "전기차" or "전기차" in str(args.get("appliance"))) and not args.get("car") and p.get("car"):
                args["car"] = p["car"]
            if args.get("away_start") is None and not mentions_time and p.get("work_start") is not None:
                args.update({"away_start": p["work_start"], "away_end": p["work_end"], "away_weekdays_only": True})
        out.append((name, args))
    return out
