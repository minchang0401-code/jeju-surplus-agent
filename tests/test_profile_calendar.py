"""내 정보(기본값)와 캘린더 알림."""
from datetime import datetime, timezone

import agent
import user_profile as up
from calendar_link import google_url, ics_bytes, pick_window

P = {"area": "노형", "car": "아이오닉5", "work_start": 9, "work_end": 18, "tou": "미가입"}


def test_query_roundtrip():
    assert up.from_query(up.to_query(P)) == P
    bad = up.from_query({"ws": "20", "we": "8", "tou": "아무거나"})   # 잘못된 값은 버림
    assert bad["work_start"] is None and bad["tou"] == "모름"


def test_profile_fills_missing_area_and_car():
    steps = up.apply_defaults([("find_chargers", {"area": "", "quick_only": False})], "충전소 알려줘", P)
    assert steps[0][1]["area"] == "노형"
    steps = up.apply_defaults([("recommend_actions", {"target": "전기차", "day": ""})], "전기차 언제 충전해?", P)
    name, args = steps[0]
    assert name == "plan_appliance_use" and args["car"] == "아이오닉5" and args["away_start"] == 9


def test_question_overrides_profile():
    steps = up.apply_defaults([("find_chargers", {"area": "애월", "quick_only": False})], "애월 충전소", P)
    assert steps[0][1]["area"] == "애월"
    steps = up.apply_defaults([("plan_appliance_use", {"appliance": "음식물처리기", "away_start": 10, "away_end": 16})],
                              "10시부터 4시까지 외출", P)
    assert steps[0][1]["away_start"] == 10


def test_no_profile_no_change():
    s = [("find_chargers", {"area": ""})]
    assert up.apply_defaults(s, "충전소", up.empty()) == s


def test_fallback_answer_uses_profile():
    r = agent.ask("충전소 알려줘", profile=P)
    assert "저장한 내 정보 기준" in r["answer"] and "노형 중심" in r["answer"]
    assert "사용자가 저장한 내 정보" in agent._system_prompt(P)
    assert "사용자가 저장한 내 정보" not in agent._system_prompt(None)


def test_calendar_from_plan():
    res = agent.ask("빨래 언제 돌려?")
    w = pick_window(res["trace"])
    assert w and w["appliance"] == "세탁기" and w["end_hour"] > w["start_hour"]
    url = google_url(w)
    assert url.startswith("https://calendar.google.com/calendar/render?") and "ctz=Asia%2FSeoul" in url
    ics = ics_bytes(w, now=datetime(2026, 11, 19, tzinfo=timezone.utc))
    assert b"BEGIN:VEVENT" in ics and b"TRIGGER:-PT10M" in ics          # 10분 전 알림
    assert max(len(line) for line in ics.split(b"\r\n")) <= 75           # iCalendar 줄 길이 규칙
    start = datetime.strptime(w["date"], "%Y-%m-%d").replace(hour=w["start_hour"]) .strftime("%Y%m%d")
    assert start.encode() in ics


def test_no_calendar_for_non_plan_answers():
    assert pick_window(agent.ask("출력제어가 뭐야?")["trace"]) is None
    assert pick_window(agent.ask("다음 달 크리스마스에 빨래하면 전기가 남아?")["trace"]) is None
