"""시험 시나리오 5개를 실행해 결과를 reports/scenario_results.md 로 남깁니다 (결과 설명자료용).

    python run_scenarios.py

.env 에 LLM 키가 있어도 항상 비상 모드(규칙 기반)로 답하게 해서 시험합니다.
"""
from __future__ import annotations

import os
from datetime import datetime

# 비상 모드(규칙 기반) 시험이라 .env 에 LLM 키가 있어도 LLM 을 끄고 돌림 (LLM 시험은 run_llm_eval.py)
os.environ["LLM_PROVIDER"] = "none"

from agent import ask  # noqa: E402  (LLM_PROVIDER 를 정한 뒤에 불러야 함)
from config import REPORTS

SCENARIOS = [
    ("1. 일반 가정", "이번 주에 빨래랑 식기세척기 언제 돌리면 좋아?",
     ["plan_appliance_use"], "기기마다 걸리는 시간·전력량을 계산하고 잉여 가능성 높은 연속 시간대를 안내"),
    ("2. 전기차 도민", "토요일에 노형동 근처에서 급속 충전하려는데?",
     ["recommend_actions", "find_chargers"], "토요일 예보 + 허브 862·1225 근거 (묻지 않은 내용은 덧붙이지 않음)"),
    ("3. 원인 설명", "잉여전력이 왜 생기는 거야?",
     ["explain_surplus"], "EPSIS 통계 + 허브 877·123·472 근거"),
    ("4. 예보 검증", "지난주 예보 맞았어?",
     ["check_past_forecast"], "지난 예보와 실제 SMP 비교"),
    ("5. 데이터·연결 상태", "데이터 상태 알려줘",
     ["data_status"], "실시간/저장 데이터 모드 판단"),
]


# 비상 모드(LLM 없음)에서 질문 → 도구 고르기가 맞는지 보는 추가 질문
ROUTING_TESTS = [
    ("내일 세탁기 돌려도 돼?", "plan_appliance_use"),
    ("이번 주말 빨래 언제가 좋아", "plan_appliance_use"),
    ("모레 식기세척기 언제 쓰면 좋아요", "plan_appliance_use"),
    ("다음주 예보 보여줘", "forecast_surplus"),
    ("며칠 동안 언제 전기가 남아?", "forecast_surplus"),
    ("애월 쪽 충전소 알려줘", "find_chargers"),
    ("공항 근처 급속 충전기 있어?", "find_chargers"),
    ("서귀포시청 근처에서 전기차 충전하려고", "find_chargers"),
    ("중문에서 금요일에 충전할 건데", "find_chargers"),
    ("전기차 언제 충전하는 게 좋아?", "recommend_actions"),
    ("EV 충전 시간 추천해줘", "recommend_actions"),
    ("다른 사람들은 보통 몇 시에 충전해?", "ev_charging_habits"),
    ("출력제어가 뭐야?", "explain_surplus"),
    ("왜 봄에 전기가 남아?", "explain_surplus"),
    ("SMP 0원이 무슨 뜻이야", "explain_surplus"),
    ("지난달 예보 정확했어?", "check_past_forecast"),
    ("저번 주 예보 맞았는지 알려줘", "check_past_forecast"),
    ("데이터 출처가 어디야?", "data_status"),
    ("지금 연결 상태 어때?", "data_status"),
    ("에어컨은 언제 트는 게 좋아?", "plan_appliance_use"),
    ("그래서 결국 도민들이 얻는 이득이 뭐야?", "explain_benefits"),
    ("이거 쓰면 전기요금이 싸져?", "explain_benefits"),
    ("이번주는 언제 전기가 남아? 언제 전기를 써야 싸게 쓸 수 있을까?", "recommend_actions"),
    ("내일 언제 써야 싸?", "recommend_actions"),
    ("이번주는 언제 전기가 남아?", "forecast_surplus"),
    ("이번주에 충전을 하면 뭐가 좋아?", "explain_benefits"),
    ("이번주에 충전을 하면 뭐가 좋아?", "recommend_actions"),
    ("충전을 하면 돈이 아껴져?", "explain_benefits"),
    ("전기차 충전하면 언제가 좋아?", "recommend_actions"),
    ("하귀리에서 충전하려는데", "find_chargers"),
    ("잉여전력은 어떻게 생겨?", "explain_surplus"),
    ("빨래를 아끼려면 어떻게 해야 해?", "how_to_act"),
    ("노형동에서 몇 시에 충전하면 좋아?", "recommend_actions"),
    # 생활 언어 (kWh 를 말하지 않는 질문) — 기기 사전으로 시간·전력량 계산
    ("오늘 저녁에 세탁기 돌리려고", "plan_appliance_use"),
    ("빨래 언제 돌려?", "plan_appliance_use"),
    ("차 배터리 반 남았어", "plan_appliance_use"),
    ("아이오닉5 30% 남았는데 내일 충전하려면?", "plan_appliance_use"),
    ("보일러 언제 틀어?", "plan_appliance_use"),
    ("토요일 오후에 건조기 돌려도 돼?", "plan_appliance_use"),
    ("밤에 식기세척기 돌릴건데", "plan_appliance_use"),
    ("음식물처리기 언제 돌려?", "plan_appliance_use"),
    ("히트펌프 축열조 언제 데워?", "plan_appliance_use"),
    ("스타일러 언제 돌리면 좋아?", "plan_appliance_use"),
    ("온풍기 틀어도 돼?", "plan_appliance_use"),
    ("휴대폰 충전 언제 해?", "plan_appliance_use"),
    ("냉장고 언제 켜?", "plan_appliance_use"),
    ("노형동에서 차 배터리 20% 남았는데 언제 충전해?", "find_chargers"),
    ("제주에 태양광이 얼마나 늘었어?", "explain_surplus"),
    ("출력제어 얼마나 했어?", "grid_records"),
    ("버려지는 전기가 얼마나 돼?", "grid_records"),
    ("제주에서 육지로 전기 보내기도 해?", "grid_records"),
    ("플러스DR이 뭐야?", "grid_records"),
    ("풍력 발전소 몇 개야?", "explain_surplus"),
    ("내일 9시 출근 6시 퇴근인데 전기차 언제 충전해?", "plan_appliance_use"),
    ("10시부터 4시까지 외출하는데 음식물처리기 언제 돌려?", "plan_appliance_use"),
    ("오늘 점심 뭐 먹지?", "(답할 수 없음)"),
    ("내가 말한 질문에 다른 답을 하는데?", "(답할 수 없음)"),
    ("제주 맛집 추천해줘", "(답할 수 없음)"),
]


# (앞 질문, 이어지는 질문, 기대 도구) — 대화 흐름을 이어 받는지 확인
FOLLOWUP_TESTS = [
    ("잉여전력이 생기는 시간에 충전을 하면 어떤 점이 좋아?", "그렇게 하려면 어떻게 해야해?", "how_to_act"),
    ("잉여전력이 생기는 시간에 충전을 하면 어떤 점이 좋아?", "그럼 언제 하면 돼?", "recommend_actions"),
    ("노형동 충전소 알려줘", "그럼 거기는 몇 시가 좋아?", "recommend_actions"),
    ("내일 빨래 언제 돌려?", "그럼 그거 어떻게 하면 돼?", "how_to_act"),
    ("보일러 언제 틀어?", "기름 보일러야", "plan_appliance_use"),
    ("보일러 언제 틀어?", "기름이야", "plan_appliance_use"),
    ("전기차 언제 충전해?", "30퍼 남았어", "plan_appliance_use"),
    ("잉여전력이 생기는 시간에 충전을 하면 어떤 점이 좋아?", "그럼 맛집은?", "(답할 수 없음)"),
]


def followup_check() -> list[str]:
    from agent import _route, _with_context
    lines, ok = [f"## 이어지는 질문 이해 시험 ({len(FOLLOWUP_TESTS)}개)", "", "| 앞 질문 | 이어지는 질문 | 기대 도구 | 고른 도구 | 결과 |", "|---|---|---|---|---|"], 0
    for prev, q, expected in FOLLOWUP_TESTS:
        routed, _ = _with_context(q, [prev])
        tools = [name for name, _ in _route(routed)] or ["(답할 수 없음)"]
        hit = expected in tools
        ok += hit
        lines.append(f"| {prev} | {q} | {expected} | {', '.join(tools)} | {'통과' if hit else '실패'} |")
    lines.insert(1, f"\n통과 {ok}/{len(FOLLOWUP_TESTS)}\n")
    print(f"이어지는 질문 이해 {ok}/{len(FOLLOWUP_TESTS)}")
    return lines


# (질문, 답에 꼭 있어야 할 말, 답에 있으면 안 되는 말) — 생활 언어 질문에 계산·정직성까지 맞는지 확인
ANSWER_TESTS = [
    ("오늘 저녁에 세탁기 돌리려고", ["0.4~1kWh", "거의 없", "예약"], ["kWh를 알려"]),
    ("아이오닉5 30% 남았는데 내일 충전하려면?", ["84", "42kWh", "급속"], []),
    ("차 배터리 반 남았어", ["50% → 80%", "2시간 50분"], ["몇 %"]),
    ("보일러 언제 틀어?", ["기름·가스", "전기보일러인가요"], []),
    ("크리스마스에 빨래하려고", ["예보할 수 있는 기간", "밖"], ["가능성 보통"]),
    ("냉장고 언제 켜?", ["옮기기 어려워"], ["연속)"]),
    ("전기장판 써도 돼?", ["억지로 옮길 필요는 없어요"], ["연속)"]),
    ("9시 출근 6시 퇴근인데 빨래 언제 돌려?", ["9시~18시", "예약"], []),
    ("노형동 근처 급속 충전소 알려줘", ["노형 중심 반경", "수덕공영주차장"], ["유료"]),
    ("9시 출근 6시 퇴근인데 전기차 언제 충전해?", ["회사·목적지 근처", "집에 있을 때"], []),
]


def answer_check() -> list[str]:
    lines, ok = [f"## 생활 언어 답변 시험 ({len(ANSWER_TESTS)}개)", "", "| 질문 | 꼭 있어야 할 말 | 결과 |", "|---|---|---|"], 0
    for q, must, must_not in ANSWER_TESTS:
        a = ask(q)["answer"]
        hit = all(m in a for m in must) and not any(m in a for m in must_not)
        ok += hit
        lines.append(f"| {q} | {', '.join(must)} | {'통과' if hit else '실패'} |")
    lines.insert(1, f"\n통과 {ok}/{len(ANSWER_TESTS)}\n")
    print(f"생활 언어 답변 {ok}/{len(ANSWER_TESTS)}")
    return lines


def routing_check() -> list[str]:
    from agent import _route
    lines, ok = [f"## 비상 모드 질문 이해 시험 ({len(ROUTING_TESTS)}개)", "", "| 질문 | 기대 도구 | 고른 도구 | 결과 |", "|---|---|---|---|"], 0
    for q, expected in ROUTING_TESTS:
        tools = [name for name, _ in _route(q)] or ["(답할 수 없음)"]
        hit = expected in tools
        ok += hit
        lines.append(f"| {q} | {expected} | {', '.join(tools)} | {'통과' if hit else '실패'} |")
    lines.insert(1, f"\n통과 {ok}/{len(ROUTING_TESTS)}\n")
    print(f"비상 모드 질문 이해 {ok}/{len(ROUTING_TESTS)}")
    return lines


def main() -> None:
    lines = [f"# 시험 시나리오 결과 ({datetime.now():%Y-%m-%d %H:%M})", ""]
    passed = 0
    for title, q, expected, purpose in SCENARIOS:
        res = ask(q)
        used = [t["tool"] for t in res["trace"]]
        ok = all(e in used for e in expected)
        errors = [t["result"]["error"] for t in res["trace"] if isinstance(t["result"], dict) and "error" in t["result"]]
        passed += ok
        lines += [f"## {title} — {'통과' if ok else '확인 필요'}", "",
                  f"- 질문: {q}", f"- 목적: {purpose}", f"- 응답 방식: {res['mode']}",
                  f"- 기대 도구: {expected} / 실제 도구: {used}"]
        if errors:
            lines.append(f"- 데이터 부족 안내: {errors}")
        lines += ["", "```", res["answer"], "```", ""]
    lines.insert(1, f"\n통과 {passed}/{len(SCENARIOS)}\n")
    lines += [""] + routing_check() + [""] + followup_check() + [""] + answer_check()
    REPORTS.mkdir(exist_ok=True)
    out = REPORTS / "scenario_results.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"통과 {passed}/{len(SCENARIOS)} → {out}")


if __name__ == "__main__":
    main()
