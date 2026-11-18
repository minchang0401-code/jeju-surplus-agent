"""에이전트 도구 7개. 모든 도구는 JSON으로 바꿀 수 있는 dict 를 돌려주고,
어떤 데이터(허브 번호 포함)를 썼는지 'sources' 에 남깁니다.

  ① forecast_surplus        잉여 예보 (5일, 시간별)            허브 579(학습), 기상청 예보, EPSIS
  ② recommend_actions       생활 행동 추천 (가전·충전)          ①의 결과 + 확인된 요금 사실
  ③ find_chargers           충전소 찾기 (위치·급속·붐빔)        허브 862, 1225
  ④ ev_charging_habits      도민 충전 시각 vs 잉여 시간         허브 1226, EPSIS
  ⑤ explain_surplus         원인 설명 (통계)                    EPSIS, 허브 877·123·472
  ⑥ check_past_forecast     지난 예보 검증                       예보 기록 / 월별 재학습 백테스트, EPSIS
  ⑦ data_status             데이터·연결 상태 (비상 모드 판단)    전체
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from config import (MAX_HORIZON_DAYS, DATA, FORECAST_HOURLY_CSV, HUB_DATA, HUB_FILE_DIRS, HUB_WEATHER_DAILY_CSV,
                    MODELS, PREDICTION_LOG, SMP_HOURLY_CSV, WEATHER_HOURLY_CSV)
from facts import FACTS
from features import load_labels

WEEKDAYS = "월화수목금토일"


def _hub_csv(no: int) -> pd.DataFrame | None:
    path = HUB_DATA[no][1]
    return pd.read_csv(path) if path.exists() else None


def _hub_folder(no: int) -> list[Path]:
    folder = HUB_FILE_DIRS[no]
    return sorted(folder.glob("*.csv")) if folder.exists() else []


def _read_any_csv(path: Path) -> pd.DataFrame:
    for enc in ("utf-8-sig", "cp949", "euc-kr"):
        try:
            return pd.read_csv(path, encoding=enc)
        except UnicodeDecodeError:
            continue
    return pd.read_csv(path, encoding="utf-8", encoding_errors="ignore")


def _col(df: pd.DataFrame, *keys: str) -> str | None:
    for c in df.columns:
        if any(k.lower() in str(c).lower() for k in keys):
            return c
    return None


def _hours_text(hours: list[int]) -> str:
    """SMP 표기 시각(1~24, 구간 끝)을 사람이 읽는 시간대로. 예: [12,13,14] → '오전 11시~오후 2시'"""
    if not hours:
        return ""
    s, e = min(hours) - 1, max(hours)

    def fmt(h: int) -> str:
        h = h % 24
        return f"오전 {h}시" if h < 12 else ("낮 12시" if h == 12 else f"오후 {h - 12}시")
    return f"{fmt(s)}~{fmt(e)}"


# ---------------------------------------------------------------- ① 잉여 예보
def _past_month_rate(months: set[int]) -> dict:
    """과거(정답 데이터 전체 기간) 월별 잉여일 비율 — 예보가 아니라 참고용."""
    lab = load_labels()
    day = lab.groupby("date")["is_surplus"].max()
    rate = day.groupby(day.index.month).mean()
    return {f"{m}월": round(float(rate.get(m, 0.0)), 3) for m in sorted(months)}


def forecast_surplus(days: int = 5, start: str | None = None) -> dict:
    """start(없으면 내일)부터 days 일. 예보는 오늘~MAX_HORIZON_DAYS 일 뒤까지만 함.
    범위 밖 날짜는 예보하지 않고 'not_forecast' 에 담아 과거 같은 달 잉여일 비율(참고)만 줌."""
    from predict import forecast, summarize
    today = date.today()
    last = today + timedelta(days=MAX_HORIZON_DAYS)
    try:
        s = pd.Timestamp(start).date() if start else today + timedelta(days=1)
    except (ValueError, TypeError):
        return {"error": f"날짜를 이해하지 못했어요: {start}", "sources": []}
    days = max(1, int(days or 5))
    wanted = [s + timedelta(days=i) for i in range(days)]
    past = [d for d in wanted if d < today]
    inside = [d for d in wanted if today <= d <= last]
    outside = [d for d in wanted if d > last]
    out, sources = [], ["EPSIS 제주 시간별 SMP(학습 정답)"]
    if inside:
        fc = forecast(str(inside[0]), len(inside))
        summ = summarize(fc)
        for _, r in summ.iterrows():
            full = r["model_used"] == "full"
            out.append({
                "date": r["date"], "weekday": r["weekday"], "level": r["level"],
                "max_prob": r["max_prob"], "likely_hours": r["likely_hours"],
                "likely_time_text": _hours_text(r["likely_hours"]) or "가능성 높은 시간 없음",
                "basis": "기상청 단기예보 반영" if full else "날씨 미반영(달력·최근 경향만) — 참고치",
            })
        if (fc["model_used"] == "full").any():
            sources += ["기상청 단기예보", "제주데이터허브 579 일별 기상(학습)"]
    res = {"forecast": out, "sources": sources,
           "forecast_range": f"{today:%Y-%m-%d} ~ {last:%Y-%m-%d} (오늘부터 {MAX_HORIZON_DAYS}일 뒤까지)",
           "note": "확률이 20% 이상인 시간을 '가능성 있는 시간'으로 표시합니다. 예보는 확률이며 틀릴 수 있습니다."}
    if outside:
        res["not_forecast"] = {
            "dates": f"{outside[0]:%Y-%m-%d} ~ {outside[-1]:%Y-%m-%d}",
            "reason": "예보 범위 밖이라 예보할 수 없음",
            "past_surplus_day_rate_same_month": _past_month_rate({d.month for d in outside}),
            "past_note": "과거 같은 달에 잉여가 생긴 날의 비율일 뿐, 그 날짜의 예보가 아님",
        }
    if past:
        res["past_dates"] = {"dates": f"{past[0]:%Y-%m-%d} ~ {past[-1]:%Y-%m-%d}",
                             "reason": "이미 지난 날짜 — 예보가 아니라 check_past_forecast 로 실제와 비교 가능"}
    return res


# ---------------------------------------------------------------- ② 행동 추천
def recommend_actions(target: str = "가전", days: int = 5, day: str = "") -> dict:
    """day: 특정 날만 보고 싶을 때 요일('토') 또는 날짜('2026-11-21')."""
    fres = forecast_surplus(days)
    fc = fres["forecast"]
    tips = []
    if day:
        hit = [d for d in fc if day in (d["weekday"], d["date"])]
        if not hit:   # 예보 범위 밖 날짜·요일 → 다른 날 목록으로 바꿔치기하지 않고 솔직하게 알림
            other = forecast_surplus(1, day) if len(day) == 10 else {}
            rng = fres["forecast_range"].split(" (")[0]
            what = f"{day}요일" if len(day) == 1 else day
            msg = (f"{what}은(는) 예보할 수 있는 기간({rng}) 밖이라 "
                   "언제가 좋을지 미리 알 수 없어요. 가까워지면 다시 물어봐 주세요.")
            res = {"target": target, "day": day, "forecast_used": [], "tips": [msg],
                   "forecast_range": fres["forecast_range"], "sources": fres["sources"]}
            if other.get("not_forecast"):
                res["not_forecast"] = other["not_forecast"]
            return res
        fc = hit
    good = sorted([d for d in fc if d["level"] in ("높음", "보통")], key=lambda d: -d["max_prob"])
    if day and len(fc) == 1 and not good:
        d = fc[0]
        tips.append(f"{d['date']}({d['weekday']})는 재생에너지가 남을 가능성이 낮아요({d['max_prob']:.0%}). "
                    "이날은 시간을 옮겨도 효과가 작습니다.")
    elif good:
        for d in good[:3]:
            what = "전기차 충전" if target == "전기차" else "세탁기·식기세척기·건조기 같은 큰 가전"
            ref = " (날씨 미반영 참고치)" if d.get("basis", "").startswith("날씨 미반영") else ""
            tips.append(f"{d['date']}({d['weekday']}) {d['likely_time_text']}: 재생에너지가 남을 가능성 "
                        f"{d['level']}({d['max_prob']:.0%}){ref} → {what}을 이 시간에")
    else:
        tips.append("앞으로 며칠은 재생에너지가 남을 가능성이 낮아요. 이번에는 시간 이동 효과가 크지 않습니다.")
    tips.append("저녁 4~10시는 제주 계시별 요금의 최대부하 시간이라, 계시별 요금 가입 가구는 이 시간을 피하면 요금이 줄어요.")
    return {"target": target, "day": day, "forecast_used": fc, "tips": tips,
            "facts": [FACTS["jeju_tou_tariff"], FACTS["jeju_new_tariff_plan"]],
            "sources": fres["sources"] + [FACTS["jeju_tou_tariff"]["source"]]}


# ---------------------------------------------------------------- ③ 충전소 찾기
# 동네·장소 → 대략의 중심 좌표 (충전소 거리 계산용, 읍면동 주민센터·대표 지점 근처)
PLACE_COORDS = {
    "일도": (33.511, 126.531), "이도": (33.502, 126.533), "삼도": (33.509, 126.517), "용담": (33.511, 126.508),
    "건입": (33.517, 126.536), "화북": (33.517, 126.565), "삼양": (33.521, 126.588), "봉개": (33.474, 126.596),
    "아라": (33.476, 126.545), "오라": (33.487, 126.512), "연동": (33.488, 126.493), "노형": (33.483, 126.475),
    "외도": (33.490, 126.432), "이호": (33.497, 126.456), "도두": (33.506, 126.468), "신제주": (33.488, 126.488),
    "구제주": (33.511, 126.525),
    "애월": (33.463, 126.331), "한림": (33.411, 126.266), "한경": (33.339, 126.188), "조천": (33.538, 126.633),
    "구좌": (33.524, 126.853), "우도": (33.506, 126.953), "추자": (33.962, 126.299), "대정": (33.226, 126.256),
    "안덕": (33.252, 126.338), "남원": (33.278, 126.718), "성산": (33.447, 126.912), "표선": (33.326, 126.836),
    "송산": (33.247, 126.570), "정방": (33.246, 126.566), "중앙": (33.249, 126.562), "천지": (33.246, 126.559),
    "효돈": (33.265, 126.613), "영천": (33.276, 126.594), "동홍": (33.258, 126.571), "서홍": (33.256, 126.555),
    "대륜": (33.243, 126.534), "대천": (33.251, 126.515), "중문": (33.252, 126.418), "예래": (33.240, 126.391),
    "제주공항": (33.507, 126.493), "공항": (33.507, 126.493), "도청": (33.489, 126.498),
    "제주시청": (33.500, 126.531), "시청": (33.500, 126.531), "서귀포시청": (33.254, 126.560),
    "터미널": (33.500, 126.515), "함덕": (33.543, 126.669), "협재": (33.394, 126.240), "월정": (33.556, 126.796),
}


def _km(lat1, lon1, lat2, lon2):
    import numpy as np
    dy = (lat2 - lat1) * 111.0
    dx = (lon2 - lon1) * 111.0 * np.cos(np.radians(33.4))
    return np.sqrt(dx * dx + dy * dy)


def find_chargers(area: str = "", quick_only: bool = False, limit: int = 5, radius_km: float = 2.0) -> dict:
    """동네 이름 → 그 주변 충전소. 허브 862에는 주소가 없어 위도·경도로 거리를 잽니다."""
    st = _hub_csv(862)
    if st is None:
        return {"error": "허브 862(전기자동차 충전소 정보)가 아직 없습니다. collect_hub.py --only 862 를 실행하세요.",
                "sources": []}
    df = st.copy()
    df["latitude"] = pd.to_numeric(df["latitude"], errors="coerce")
    df["longitude"] = pd.to_numeric(df["longitude"], errors="coerce")
    df = df[df["latitude"].between(33.1, 34.0) & df["longitude"].between(126.1, 127.0)]   # 제주 밖 좌표 제외
    # 같은 장소에 운영사별로 여러 줄 → 장소 하나로 합침
    for c in ("chargerCount", "quickChargerCount"):
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)
    df["is_quick"] = df["quickChargingFlag"].astype(str).str.lower().isin(["true", "1", "y"])
    df["fee"] = df["parkingFeeFlag"].astype(str).str.lower().isin(["true", "1", "y"])
    g = df.groupby("chargingPlace").agg(lat=("latitude", "mean"), lon=("longitude", "mean"),
                                        slow=("chargerCount", "sum"), quick=("quickChargerCount", "sum"),
                                        has_quick=("is_quick", "max"), parking_fee=("fee", "max"),
                                        hours=("startTime", "first"), operators=("provider", "nunique")).reset_index()
    how = "전체"
    if area in PLACE_COORDS:
        lat, lon = PLACE_COORDS[area]
        g["distance_km"] = _km(lat, lon, g["lat"], g["lon"]).round(2)
        rad = radius_km if len(area) <= 2 and area not in ("공항", "시청") else radius_km
        if area in ("애월", "한림", "한경", "조천", "구좌", "우도", "추자", "대정", "안덕", "남원", "성산", "표선"):
            rad = max(radius_km, 4.0)   # 읍면은 넓으니 반경을 넓힘
        g = g[g["distance_km"] <= rad].sort_values(["distance_km"])
        how = f"{area} 중심 반경 {rad:g}km"
    elif area:
        g = g[g["chargingPlace"].astype(str).str.contains(area, na=False)]
        how = f"이름에 '{area}' 포함"
    if quick_only:
        g = g[g["has_quick"]]
    if area in PLACE_COORDS:
        g = g.sort_values(["has_quick", "distance_km"], ascending=[False, True]) if not quick_only else g
    crowd = _crowding()
    rows = []
    for _, r in g.head(limit).iterrows():
        name = str(r["chargingPlace"])
        item = {"name": name, "quick_count": int(r["quick"]), "slow_count": int(r["slow"]),
                "has_quick": bool(r["has_quick"]), "parking_fee": bool(r["parking_fee"])}
        if "distance_km" in r:
            item["distance_km"] = float(r["distance_km"])
        hit = crowd[crowd["station"].apply(lambda s: s in name or name in s)] if crowd is not None else None
        if hit is not None and len(hit):
            item["crowding_2022"] = hit.iloc[0].drop("station").to_dict()
        rows.append(item)
    src = ["제주데이터허브 862 전기자동차 충전소 정보 (기준일 " + str(st["baseDate"].iloc[0]) + ")"]
    if crowd is not None:
        src.append("제주데이터허브 1225 일별 전기자동차 충전 이력")
    return {"area": area, "search": how, "count": int(len(g)), "chargers": rows, "sources": src}


def _crowding() -> pd.DataFrame | None:
    """허브 1225(2022.7~10, 충전소 17곳): 충전소별 관광객 비중·대기 발생 비율."""
    w = _hub_csv(1225)
    if w is None or "evChargingStationName" not in w:
        return None
    g = w.groupby("evChargingStationName")
    out = pd.DataFrame({"station": list(g.groups.keys())})
    out["records"] = out["station"].map(g.size())
    if "userCategory" in w:
        out["tourist_share"] = out["station"].map(
            w.assign(t=w["userCategory"].astype(str) == "관광객").groupby("evChargingStationName")["t"].mean()).round(2)
    if "waitingCategory" in w:
        out["wait_rate"] = out["station"].map(
            w.assign(t=w["waitingCategory"].astype(str).str.startswith("대기Y"))
             .groupby("evChargingStationName")["t"].mean()).round(2)
    return out


# ---------------------------------------------------------------- ④ 도민 충전 습관
def ev_charging_habits() -> dict:
    rec = _hub_csv(1226)
    lab = load_labels()
    surplus_by_hour = lab.groupby("hour")["is_surplus"].sum()
    surplus_share = (surplus_by_hour / surplus_by_hour.sum()).round(3)
    if rec is None:
        return {"error": "허브 1226(월별 전기자동차 충전 이력)이 아직 없습니다. collect_hub.py --only 1226 를 실행하세요.",
                "surplus_hour_share": surplus_share.to_dict(), "sources": ["EPSIS 제주 시간별 SMP"]}
    hour_c = _col(rec, "chargingStartHour")
    cnt_c = _col(rec, "chargingCount", "count", "Count", "횟수")
    w = rec[cnt_c] if cnt_c else 1
    by_hour = rec.assign(w=w).groupby(rec[hour_c].astype(int))["w"].sum()
    share = (by_hour / by_hour.sum()).round(3)
    # EPSIS 표기(구간 끝)에 맞추기: 충전 시작 h시 → h+1시 구간
    share_aligned = share.rename(index=lambda h: h + 1)
    overlap = float(sum(share_aligned.get(h, 0) for h in (11, 12, 13, 14, 15)))
    peak = int(share.idxmax())
    return {"charging_start_share": share.to_dict(), "surplus_hour_share": surplus_share.to_dict(),
            "peak_charging_start_hour": peak,
            "share_of_charging_in_surplus_window": round(overlap, 3),
            "surplus_window_text": "오전 10시~오후 3시 (잉여의 약 91%가 이 시간대)",
            "period": _period_text(rec),
            "evening_peak_share": round(float(sum(share.get(h, 0) for h in range(16, 22))), 3),
            "sources": ["제주데이터허브 1226 월별 전기자동차 충전 이력", "EPSIS 제주 시간별 SMP"]}


def _period_text(rec: pd.DataFrame) -> str:
    ym = _col(rec, "baseYearMonth")
    if not ym:
        return "충전 이력 기간 미상"
    v = rec[ym].astype(str).str[:6]
    return f"충전 이력 {v.min()[:4]}.{v.min()[4:]}~{v.max()[:4]}.{v.max()[4:]}, {int(len(rec)):,}건"


# ---------------------------------------------------------------- ⑤ 원인 설명
def explain_surplus() -> dict:
    lab = load_labels()
    day = lab.groupby("date")["is_surplus"].max()
    month = day.groupby(day.index.month).mean().round(3)
    hour = lab.groupby("hour")["is_surplus"].sum()
    dow = day.groupby(day.index.dayofweek).mean().round(3)
    out = {
        "period": f"{lab['date'].min():%Y-%m-%d} ~ {lab['date'].max():%Y-%m-%d}",
        "days": int(day.size), "surplus_days": int(day.sum()), "surplus_hours": int(lab["is_surplus"].sum()),
        "surplus_day_rate_by_month": {int(k): v for k, v in month.items()},
        "surplus_hours_by_hour": {int(k): int(v) for k, v in hour.items()},
        "surplus_day_rate_by_weekday": {WEEKDAYS[int(k)]: v for k, v in dow.items()},
        "definition": FACTS["surplus_definition"]["text"],
        "sources": ["EPSIS 제주 시간별 SMP"],
    }
    clean = HUB_FILE_DIRS[877].parent / "877_daily_climate_clean.csv"
    climate = _hub_folder(877)
    if clean.exists():
        cl = pd.read_csv(clean, parse_dates=["Date"])
        m = cl["Date"].dt.month
        out["climate_by_month_2000_2021"] = {
            "solar_hourly_mean_MJ_gosan": cl[cl["station"] == "고산"].groupby(m)["Solar_mean"].mean().round(2).to_dict(),
            "sunshine_hours": cl.groupby(m)["Sunshine_mean"].mean().round(1).to_dict(),
            "wind_mean_ms": cl.groupby(m)["Wspeed_mean"].mean().round(1).to_dict(),
        }
        out["sources"].append("제주데이터허브 877 2000-2021 제주도 일간 기후(4지점, 일사는 고산)")
    elif climate:
        frames = [_read_any_csv(p) for p in climate]
        cl = pd.concat(frames, ignore_index=True)
        dcol, scol = _col(cl, "일시", "date", "tm"), _col(cl, "일사", "solar", "si")
        if dcol and scol:
            cl[dcol] = pd.to_datetime(cl[dcol], errors="coerce")
            cl[scol] = pd.to_numeric(cl[scol], errors="coerce")
            out["solar_by_month_MJ"] = {int(k): round(float(v), 2)
                                        for k, v in cl.groupby(cl[dcol].dt.month)[scol].mean().items()}
            out["sources"].append("제주데이터허브 877 2000-2021 제주도 일간 기후(일사)")
    solar_p = HUB_FILE_DIRS[123].parent / "123_solar_business_clean.csv"
    if solar_p.exists():
        sb = pd.read_csv(solar_p, parse_dates=["start_date"])
        by_year = sb.groupby(sb["start_date"].dt.year)["capacity_mw"].sum()
        out["solar_business"] = {
            "count": int(len(sb)), "total_mw": round(float(sb["capacity_mw"].sum()), 1),
            "cumulative_mw_by_year": {int(k): round(float(v), 1) for k, v in by_year.cumsum().items()},
            "mw_by_city": sb.groupby("city")["capacity_mw"].sum().round(1).to_dict(),
            "base_date": str(sb["base_date"].iloc[0]),
            "note": "제주도에 등록된 전기사업체(태양광) 기준. 정부가 직접 허가한 대형 발전소 등은 빠질 수 있음",
        }
        out["sources"].append("제주데이터허브 123 전기사업체(태양광) 등록현황")
    wind_p = HUB_FILE_DIRS[472].parent / "472_wind_power_clean.csv"
    if wind_p.exists():
        wp = pd.read_csv(wind_p)
        out["wind_power"] = {
            "count": int(len(wp)), "total_mw": round(float(wp["capacity_mw"].sum()), 1),
            "offshore_mw": round(float(wp.loc[wp["offshore"], "capacity_mw"].sum()), 1),
            "mw_by_town": wp.groupby("town")["capacity_mw"].sum().round(1).sort_values(ascending=False).to_dict(),
            "base_date": str(wp["base_date"].iloc[0]),
        }
        out["sources"].append("제주데이터허브 472 풍력발전현황")
    return out


# ---------------------------------------------------------------- ⑥ 예보 검증
def check_past_forecast(start: str | None = None, end: str | None = None) -> dict:
    lab = load_labels()
    actual = lab.groupby("date")["is_surplus"].max()
    end_d = pd.Timestamp(end) if end else lab["date"].max()
    start_d = pd.Timestamp(start) if start else end_d - pd.Timedelta(days=6)
    source = None
    if PREDICTION_LOG.exists():
        log = pd.read_csv(PREDICTION_LOG, parse_dates=["date"])
        log = log[(log["date"] >= start_d) & (log["date"] <= end_d)]
        if len(log):
            log = log.sort_values("issued_at").groupby(["date", "hour"]).tail(1)
            pred = log.groupby("date")["prob"].max()
            source = "실제로 낸 예보 기록"
    if source is None:
        bt_path = DATA / "backtest_predictions.csv"
        if not bt_path.exists():
            return {"error": "검증할 예보 기록이 없습니다.", "sources": []}
        bt = pd.read_csv(bt_path, parse_dates=["date"])
        col = "p_full" if "p_full" in bt else "p_calendar"
        bt = bt[(bt["date"] >= start_d) & (bt["date"] <= end_d)]
        pred = bt.groupby("date")[col].max()
        source = "시험 기간 재현 예보(각 달 시작 5일 전까지의 데이터로 학습한 모델이 냈을 예보)"
    rows, hit, said = [], 0, 0
    for d, p in pred.items():
        a = int(actual.get(d, 0))
        flag = p >= 0.2
        said += flag
        hit += int(flag and a == 1)
        rows.append({"date": f"{d:%Y-%m-%d}", "weekday": WEEKDAYS[d.dayofweek],
                     "predicted_level": "높음" if p >= 0.5 else ("보통" if p >= 0.2 else "낮음"),
                     "max_prob": round(float(p), 3), "actual_surplus": bool(a)})
    missed = sum(1 for r in rows if r["actual_surplus"] and r["predicted_level"] == "낮음")
    return {"period": f"{start_d:%Y-%m-%d} ~ {end_d:%Y-%m-%d}", "basis": source, "days": rows,
            "said_possible": int(said), "correct_when_said": int(hit), "missed_surplus_days": int(missed),
            "sources": ["EPSIS 제주 시간별 SMP(실제)", source]}


# ---------------------------------------------------------------- ⑦ 데이터 상태
def data_status() -> dict:
    items = {
        "EPSIS SMP 원자료": SMP_HOURLY_CSV.exists(),
        "학습된 모델": (MODELS / "surplus_model.joblib").exists(),
        "기상청 관측(학습)": WEATHER_HOURLY_CSV.exists(),
        "기상청 단기예보(예측)": FORECAST_HOURLY_CSV.exists(),
        "허브 579 일별 기상": HUB_WEATHER_DAILY_CSV.exists(),
    }
    for no in (862, 1225, 1226):
        items[f"허브 {no} {HUB_DATA[no][2]}"] = HUB_DATA[no][1].exists()
    for no in (877, 123, 472):
        items[f"허브 {no} (파일)"] = bool(_hub_folder(no))
    fc_date = None
    if FORECAST_HOURLY_CSV.exists():
        f = pd.read_csv(FORECAST_HOURLY_CSV)
        fc_date = str(f["base"].iloc[0]) if "base" in f and len(f) else None
        stale = fc_date is None or pd.to_datetime(fc_date[:8]) < pd.Timestamp(date.today() - timedelta(days=1))
    else:
        stale = True
    return {"available": items, "forecast_issued": fc_date,
            "mode": "저장 데이터 모드(실시간 예보 없음)" if stale else "실시간 예보 모드",
            "hub_datasets_ready": sum(v for k, v in items.items() if k.startswith("허브"))}


# ---------------------------------------------------------------- ⑧ 도민이 얻는 이득 (솔직하게)
def explain_benefits() -> dict:
    """지금 바로 얻는 것 / 조건이 맞아야 얻는 것 / 앞으로 얻을 수 있는 것 / 얻지 못하는 것을 나눠서 알려 줌."""
    out = {
        "now_if_tou": FACTS["jeju_tou_tariff"]["text"]
        + " 이 요금제 가입 가구는 저녁 4~10시(최대부하) 사용을 낮이나 밤으로 옮기면 요금이 줄어듭니다.",
        "not_for_standard": "일반(누진제) 주택용 요금 가구는 한 달 사용량으로 요금이 정해져서, 쓰는 시간만 옮겨서는 지금 당장 요금이 달라지지 않습니다.",
        "public": "남는 재생에너지 시간에 전기를 쓰면 발전기를 강제로 멈추는 출력제어를 줄이는 데 보탬이 됩니다.",
        "future": FACTS["jeju_new_tariff_plan"]["text"],
        "sources": [FACTS["jeju_tou_tariff"]["source"], FACTS["jeju_new_tariff_plan"]["source"]],
    }
    try:
        h = ev_charging_habits()
        if "evening_peak_share" in h:
            out["ev_evening_share"] = h["evening_peak_share"]
            out["ev_period"] = h["period"]
            out["sources"] += [x for x in h.get("sources", []) if "1226" in x]
    except Exception:
        pass
    return out


def how_to_act(target: str = "전기차") -> dict:
    """'그렇게 하려면 어떻게 해야 해?'에 대한 실천 방법. 사실은 FACTS·허브 데이터에 있는 것만 씀."""
    ev = target == "전기차"
    steps = [
        "위에 나온 '잉여 가능성이 높은 날·시간'에 " + ("충전을 시작하세요. 제주는 주로 낮 시간에 전기가 남아요."
                                             if ev else "세탁기·식기세척기·건조기처럼 시간을 옮길 수 있는 가전을 돌리세요."),
        ("차나 충전기에 예약 충전 기능이 있으면 시작 시간을 그 시간으로 맞춰 두세요."
         if ev else "가전에 예약(타이머) 기능이 있으면 그 시간에 돌아가도록 맞춰 두세요."),
    ]
    if ev:
        steps.append("충전소는 '노형동 근처 충전소', '애월 급속 충전기'처럼 동네 이름으로 물어보면 가까운 곳을 찾아 드려요.")
    steps.append("저녁 4~10시는 가능하면 피하세요. 제주 계시별 요금의 최대부하 시간이고, 남는 전기도 거의 없는 시간이에요.")
    steps.append("집에서 쓰는 전기 요금까지 줄이고 싶다면: 일반(누진제) 요금은 쓰는 시간을 옮겨도 요금이 그대로예요. "
                 "주택용 계시별 선택요금제가 우리 집에 유리한지, 가입 조건은 무엇인지 한전(국번 없이 123, 한전:ON)에 먼저 문의하세요.")
    return {"target": target, "steps": steps,
            "sources": [FACTS["jeju_tou_tariff"]["source"], "한전:ON(online.kepco.co.kr) 고객 상담 창구"]}


TOOLS = {
    "explain_benefits": explain_benefits,
    "how_to_act": how_to_act,
    "forecast_surplus": forecast_surplus,
    "recommend_actions": recommend_actions,
    "find_chargers": find_chargers,
    "ev_charging_habits": ev_charging_habits,
    "explain_surplus": explain_surplus,
    "check_past_forecast": check_past_forecast,
    "data_status": data_status,
}

TOOL_SPECS = [
    {"name": "forecast_surplus", "description": "제주 재생에너지 잉여전력이 생길 가능성(날짜·시간대별)을 예보한다. "
     "오늘부터 5일 뒤까지만 예보하고, 그 밖의 날짜는 not_forecast(예보 불가 + 과거 같은 달 참고 기록)로 돌려준다.",
     "parameters": {"type": "object", "properties": {
         "start": {"type": "string", "description": "시작 날짜 YYYY-MM-DD (없으면 내일). 오늘을 물으면 오늘 날짜"},
         "days": {"type": "integer", "description": "시작 날짜부터 며칠 (예: 다음 주 전체면 7)", "default": 5}}}},
    {"name": "recommend_actions", "description": "잉여 예보를 바탕으로 가전 사용·전기차 충전 시간을 추천한다.",
     "parameters": {"type": "object", "properties": {
         "target": {"type": "string", "enum": ["가전", "전기차"], "default": "가전"},
         "days": {"type": "integer", "default": 5},
         "day": {"type": "string", "description": "특정 날만: 요일 한 글자('토') 또는 YYYY-MM-DD"}}}},
    {"name": "find_chargers", "description": "지역 이름으로 전기차 충전소(위치·급속 여부·관광객 이용 비중)를 찾는다.",
     "parameters": {"type": "object", "properties": {
         "area": {"type": "string", "description": "동네·장소 이름 (예: 노형, 애월, 서귀포시청)"},
         "quick_only": {"type": "boolean", "default": False},
         "limit": {"type": "integer", "default": 5}}}},
    {"name": "ev_charging_habits", "description": "제주 도민이 보통 몇 시에 충전하는지와 잉여 시간대를 비교한다.",
     "parameters": {"type": "object", "properties": {}}},
    {"name": "explain_surplus", "description": "잉여전력이 언제·왜 생기는지 과거 통계(월·시간·요일, 일사, 설비)로 설명한다.",
     "parameters": {"type": "object", "properties": {}}},
    {"name": "check_past_forecast", "description": "지난 기간의 예보가 실제로 맞았는지 비교한다.",
     "parameters": {"type": "object", "properties": {
         "start": {"type": "string", "description": "YYYY-MM-DD"}, "end": {"type": "string", "description": "YYYY-MM-DD"}}}},
    {"name": "explain_benefits", "description": "이 서비스를 쓰면 도민이 얻는 이득(지금 바로/조건부/앞으로)과 얻지 못하는 것을 솔직하게 정리한다.",
     "parameters": {"type": "object", "properties": {}}},
    {"name": "how_to_act", "description": "잉여 시간에 맞춰 전기를 쓰려면 실제로 무엇을 하면 되는지(예약 기능, 피할 시간, 요금제 문의) 단계별로 알려 준다.",
     "parameters": {"type": "object", "properties": {
         "target": {"type": "string", "enum": ["가전", "전기차"], "default": "전기차"}}}},
    {"name": "data_status", "description": "어떤 데이터가 준비됐는지, 실시간 예보가 연결됐는지 확인한다.",
     "parameters": {"type": "object", "properties": {}}},
]
