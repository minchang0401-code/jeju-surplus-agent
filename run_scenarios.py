"""시험 시나리오 5개를 실행해 결과를 reports/scenario_results.md 로 남깁니다 (결과 설명자료용).

    python run_scenarios.py
"""
from __future__ import annotations

from datetime import datetime

from agent import ask
from config import REPORTS

SCENARIOS = [
    ("1. 일반 가정", "이번 주에 빨래랑 식기세척기 언제 돌리면 좋아?",
     ["recommend_actions"], "잉여 가능성 높은 날·시간과 생활 행동을 안내"),
    ("2. 전기차 도민", "토요일에 노형동 근처에서 급속 충전하려는데?",
     ["recommend_actions", "find_chargers"], "토요일 예보 + 허브 862·1225 근거 (묻지 않은 내용은 덧붙이지 않음)"),
    ("3. 원인 설명", "잉여전력이 왜 생기는 거야?",
     ["explain_surplus"], "EPSIS 통계 + 허브 877·123·472 근거"),
    ("4. 예보 검증", "지난주 예보 맞았어?",
     ["check_past_forecast"], "지난 예보와 실제 SMP 비교"),
    ("5. 데이터·연결 상태", "데이터 상태 알려줘",
     ["data_status"], "실시간/저장 데이터 모드 판단"),
]


# 비상 모드(LLM 없음)에서 질문 → 도구 고르기가 맞는지 보는 추가 질문 20개
ROUTING_TESTS = [
    ("내일 세탁기 돌려도 돼?", "recommend_actions"),
    ("이번 주말 빨래 언제가 좋아", "recommend_actions"),
    ("모레 식기세척기 언제 쓰면 좋아요", "recommend_actions"),
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
    ("에어컨은 언제 트는 게 좋아?", "recommend_actions"),
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
    ("오늘 점심 뭐 먹지?", "(답할 수 없음)"),
    ("내가 말한 질문에 다른 답을 하는데?", "(답할 수 없음)"),
    ("제주 맛집 추천해줘", "(답할 수 없음)"),
]


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
    lines += [""] + routing_check()
    REPORTS.mkdir(exist_ok=True)
    out = REPORTS / "scenario_results.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"통과 {passed}/{len(SCENARIOS)} → {out}")


if __name__ == "__main__":
    main()
