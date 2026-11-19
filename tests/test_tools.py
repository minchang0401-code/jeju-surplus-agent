"""도구가 정직하게(범위 밖은 예보하지 않고, 계산이 맞게) 동작하는지 확인."""
from datetime import date, timedelta

import pytest

import tools
from appliances import APPLIANCES, ev_energy, find_all, find_appliance
from config import MAX_HORIZON_DAYS


def test_tool_specs_match_functions():
    names = [s["name"] for s in tools.TOOL_SPECS]
    assert sorted(names) == sorted(tools.TOOLS)
    assert len(names) == 11
    for s in tools.TOOL_SPECS:
        assert s["description"] and s["parameters"]["type"] == "object"


def test_forecast_never_beyond_horizon():
    far = (date.today() + timedelta(days=40)).isoformat()
    r = tools.forecast_surplus(days=3, start=far)
    assert r["forecast"] == []                          # 40일 뒤는 예보하지 않음
    assert r["not_forecast"]["dates"]
    r2 = tools.forecast_surplus(days=MAX_HORIZON_DAYS + 1, start=date.today().isoformat())
    last = date.today() + timedelta(days=MAX_HORIZON_DAYS)
    assert all(d["date"] <= last.isoformat() for d in r2["forecast"])


@pytest.mark.parametrize("text,key", [
    ("빨래 돌리려고", "세탁기"), ("식세기 언제", "식기세척기"), ("차 배터리 반 남았어", "전기차"),
    ("전기보일러", "전기보일러"), ("보일러 언제 틀어", "보일러"), ("김치냉장고", "옮기기 어려운 기기"),
    ("스타일러", "의류관리기"), ("온풍기", "전기히터"),
])
def test_find_appliance(text, key):
    assert find_appliance(text) == key


def test_find_all_two_devices():
    assert find_all("빨래랑 식기세척기") == ["세탁기", "식기세척기"]


def test_appliance_values_have_sources():
    for k, v in APPLIANCES.items():
        assert v["source"], k
        if v.get("kwh"):
            assert v["kwh"][0] <= v["kwh"][1]


def test_ev_energy_math():
    ev = ev_energy(30, "아이오닉5")                       # 84kWh × (80−30)% = 42kWh
    assert ev["kwh"] == 42.0 and ev["hours"] == 6.0       # 7kW 완속
    assert ev_energy(None)["assumed_percent"] is True     # 모르면 50%로 가정하고 알림


def test_plan_evening_is_honest():
    r = tools.plan_appliance_use("세탁기", day=date.today().isoformat(), start_hour=18, end_hour=22)
    assert "evening_note" in r                            # 저녁엔 남는 전기가 거의 없다고 알림
    assert r.get("alternatives") is not None


def test_plan_out_of_range_day():
    r = tools.plan_appliance_use("세탁기", day=(date.today() + timedelta(days=30)).isoformat())
    assert "not_forecast" in r and "best_windows" not in r


def test_plan_boiler_asks_fuel_then_points_to_heatpump():
    assert "ask_user" in tools.plan_appliance_use("보일러")
    oil = tools.plan_appliance_use("보일러", fuel="기름·가스")
    assert "히트펌프" in oil["support_program"] and "ask_user" not in oil


def test_plan_schedule_ev_split():
    r = tools.plan_appliance_use("전기차", battery_percent=40, away_start=9, away_end=18)
    s = r["schedule"]
    assert "while_away" in s and "at_home" in s
    for w in s["while_away"]:                             # 밖에 있는 동안 = 평일 9~18시 안
        assert w["weekday"] not in "토일" and w["start_hour"] < 18 and w["end_hour"] > 9


def test_chargers_area_suffix_and_no_fee_claim():
    a = tools.find_chargers("노형동", quick_only=True)
    b = tools.find_chargers("노형", quick_only=True)
    assert a["count"] == b["count"] > 10                  # '노형동'도 동네 반경으로 찾음
    c = a["chargers"][0]
    assert "parking_fee" not in c                         # 뜻이 확인 안 된 주차요금은 내보내지 않음
    assert c["map_link"].startswith("https://map.kakao.com/link/map/")
    assert all(x["distance_km"] <= 2.0 for x in a["chargers"])     # 반경 안에서만


def test_chargers_ranked_by_hub_midday_use():
    """허브 1226(낮 이용)·1225(대기)가 순서를 바꾸고, 그 이유를 답에 쓸 수 있게 내보내는지."""
    r = tools.find_chargers("노형")
    assert "ranking" in r and any("1226" in s for s in r["sources"])
    levels = [c.get("midday_use", {}).get("level") for c in r["chargers"]]
    assert "붐빔" not in levels[:2]                                   # 낮에 붐볐던 곳은 앞에 두지 않음
    moved = r.get("moved_back", [])
    assert moved and all("붐볐" in m["why"] or "대기" in m["why"] for m in moved)
    assert any("reason" in c for c in r["chargers"])
    m = tools._midday_use()
    assert set(m["level"]) == {"한산", "보통", "붐빔"} and m.attrs["period"] == "2021년 1~3월"


def test_grid_records_numbers():
    g = tools.grid_records()
    assert g["curtailment"]["wind_mwh_total"] == 73224
    assert g["curtailment"]["wind_days"] == 336
    d = g["demand_hvdc"]
    assert d["midday_demand_mw"]["잉여 있는 날"] < d["midday_demand_mw"]["다른 날"]
    assert d["midday_hvdc_import_mw"]["잉여 있는 날"] < d["midday_hvdc_import_mw"]["다른 날"]


def test_map_points():
    p = tools.map_points()
    assert {"lat", "lon", "color", "size"} <= set(p.columns)
    assert p["lat"].between(33.1, 34.0).all() and p["lon"].between(126.1, 127.0).all()
