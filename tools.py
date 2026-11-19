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

from datetime import date, datetime, timedelta
import math
from urllib.parse import quote
import re
from pathlib import Path

import pandas as pd

from config import (MAX_HORIZON_DAYS, DATA, FORECAST_HOURLY_CSV, HUB_DATA, HUB_FILE_DIRS, HUB_WEATHER_DAILY_CSV,
                    MODELS, PREDICTION_LOG, SMP_HOURLY_CSV, WEATHER_HOURLY_CSV)
from facts import FACTS
from features import load_labels
from predict import level_of

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


BASIS_TEXT = {"full": "기상청 단기예보 반영", "mid": "기상청 중기예보 반영(오후 하늘·비·최고기온) — 단기예보보다 거침",
              "calendar": "날씨 미반영(달력·최근 경향만) — 참고치"}


def _basis(model_used) -> str:
    """예보 근거 문구. model_used 가 여러 개면 가장 자세한 것(full > mid > calendar)."""
    used = set(model_used) if not isinstance(model_used, str) else {model_used}
    for k in ("full", "mid", "calendar"):
        if k in used:
            return BASIS_TEXT[k]
    return BASIS_TEXT["calendar"]


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
            out.append({
                "date": r["date"], "weekday": r["weekday"], "level": r["level"],
                "max_prob": r["max_prob"], "likely_hours": r["likely_hours"],
                "likely_time_text": _hours_text(r["likely_hours"]) or "가능성 높은 시간 없음",
                "basis": _basis(r["model_used"]),
            })
        if (fc["model_used"] == "full").any():
            sources += ["기상청 단기예보", "제주데이터허브 579 일별 기상(학습)"]
        if (fc["model_used"] == "mid").any():
            sources += ["기상청 중기예보(제주도)"]
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
    area = (area or "").strip()
    # '노형동'·'애월읍'·'하귀리'처럼 끝에 동·읍·면·리가 붙어도 대표 좌표가 있으면 반경으로 찾음
    if area not in PLACE_COORDS and len(area) >= 3 and area[-1] in "동읍면리" and area[:-1] in PLACE_COORDS:
        area = area[:-1]
    if area in PLACE_COORDS:
        lat, lon = PLACE_COORDS[area]
        g["distance_km"] = _km(lat, lon, g["lat"], g["lon"]).round(2)
        rad = radius_km if len(area) <= 2 and area not in ("공항", "시청") else radius_km
        if area in ("애월", "한림", "한경", "조천", "구좌", "우도", "추자", "대정", "안덕", "남원", "성산", "표선"):
            rad = max(radius_km, 4.0)   # 읍면은 넓으니 반경을 넓힘
        g = g[g["distance_km"] <= rad].sort_values(["distance_km"])
        how = f"{area} 중심 반경 {rad:g}km"
    elif area:
        hit = g[g["chargingPlace"].astype(str).str.contains(area, na=False, regex=False)]
        if hit.empty and len(area) >= 3 and area[-1] in "동읍면리":   # '하귀리' → '하귀'로 다시 찾기
            hit = g[g["chargingPlace"].astype(str).str.contains(area[:-1], na=False, regex=False)]
            area_txt = area[:-1]
        else:
            area_txt = area
        g = hit
        how = f"이름에 '{area_txt}' 포함"
    if quick_only:
        g = g[g["has_quick"]]
    crowd = _crowding()
    mid = _midday_use()
    # 허브 1226(낮 시간 이용)·1225(대기)로 순서를 정함: 가까운 곳 위주로, 낮에 붐볐거나 대기가 잦았던 곳은 뒤로
    g = g.copy()
    names = g["chargingPlace"].astype(str).str.strip()
    g["busy"] = names.map(mid["level"]) if mid is not None else None
    g["busy_n"] = names.map(mid["per_charger_day"]) if mid is not None else None

    def _wait(n):
        if crowd is None or "wait_rate" not in crowd:
            return None
        h = crowd[crowd["station"].apply(lambda s: s in n or n in s)]
        return float(h.iloc[0]["wait_rate"]) if len(h) else None
    g["wait"] = names.map(_wait)
    if area in PLACE_COORDS:
        # 기록이 없는 곳(2021년 뒤 생긴 곳 등)은 '보통'으로 봄 — 기록 없는 곳이 유리해지지 않게
        g["rank_km"] = (g["distance_km"] + g["busy"].map(BUSY_PENALTY_KM).fillna(BUSY_PENALTY_KM["보통"])
                        + (g["wait"].astype(float).fillna(0) >= 0.15) * WAIT_PENALTY_KM)
        g = g.sort_values(["has_quick", "rank_km", "distance_km"], ascending=[False, True, True]) if not quick_only \
            else g.sort_values(["rank_km", "distance_km"])
    shown = g.head(limit)
    moved = []
    if area in PLACE_COORDS and mid is not None:
        # 가까운 곳인데 낮에 붐볐거나 대기가 잦아 목록에서 빠진 곳은 이유와 함께 따로 알려 줌 (허브 데이터가 순서를 바꾼 경우)
        pool = g[g["has_quick"]] if g["has_quick"].any() else g
        near = pool.sort_values("distance_km").head(limit)
        for _, r in near[~near["chargingPlace"].isin(shown["chargingPlace"])].iterrows():
            busy = r.get("busy") == "붐빔"
            wait = r.get("wait") is not None and not pd.isna(r.get("wait")) and float(r["wait"]) >= 0.15
            if busy or wait:
                why = (["낮(10~15시)에 붐볐던 기록(허브 1226)"] if busy else []) + \
                      ([f"대기가 {float(r['wait']):.0%} 있었던 기록(허브 1225)"] if wait else [])
                moved.append({"name": str(r["chargingPlace"]), "distance_km": float(r["distance_km"]), "why": " · ".join(why)})
    rows = []
    for _, r in shown.iterrows():
        name = str(r["chargingPlace"])
        item = {"name": name, "quick_count": int(r["quick"]), "slow_count": int(r["slow"]),
                "has_quick": bool(r["has_quick"]),   # 주차요금(parkingFeeFlag)은 값의 뜻이 문서로 확인되지 않아 넣지 않음
                "lat": round(float(r["lat"]), 5), "lon": round(float(r["lon"]), 5),
                # 허브 862에는 주소가 없어 좌표로 카카오맵 위치 링크를 만듦 (누르면 지도·길찾기)
                "map_link": "https://map.kakao.com/link/map/" + quote(f"{name},{float(r['lat']):.5f},{float(r['lon']):.5f}", safe=","),
                # 카카오맵이 휴대폰의 현재 위치(GPS)에서 이 충전소까지 길을 안내 (우리 앱은 위치를 받지 않음)
                "route_link": kakao_route(name, float(r["lat"]), float(r["lon"]))}
        if "distance_km" in r:
            item["distance_km"] = float(r["distance_km"])
        hit = crowd[crowd["station"].apply(lambda s: s in name or name in s)] if crowd is not None else None
        if hit is not None and len(hit):
            item["crowding_2022"] = hit.iloc[0].drop("station").to_dict()
        why = []
        if isinstance(r.get("busy"), str):
            item["midday_use"] = {"level": r["busy"], "per_charger_day": float(r["busy_n"]),
                                  "period": mid.attrs.get("period", "")}
            why.append(f"낮(10~15시) 이용 {r['busy']} (지금 충전기 1대당 하루 {float(r['busy_n']):.1f}회꼴, "
                       f"허브 1226 {mid.attrs.get('period', '')} 기록)")
        if r.get("wait") is not None and not pd.isna(r.get("wait")):
            why.append(f"대기 발생 {float(r['wait']):.0%} (허브 1225, 2022년)")
        if why:
            item["reason"] = " · ".join(why)
        rows.append(item)
    src = ["제주데이터허브 862 전기자동차 충전소 정보 (기준일 " + str(st["baseDate"].iloc[0]) + ")"]
    if mid is not None and any("midday_use" in x for x in rows):
        src.append("제주데이터허브 1226 월별 전기자동차 충전 이력 (" + mid.attrs.get("period", "") + ", 충전소별 낮 시간 이용)")
    if crowd is not None:
        src.append("제주데이터허브 1225 일별 전기자동차 충전 이력")
    out = {"area": area, "search": how, "count": int(len(g)), "chargers": rows, "sources": src}
    if moved:
        out["moved_back"] = moved
    if area in PLACE_COORDS and mid is not None:
        out["ranking"] = ("가까운 순서가 기본이고, 낮(10~15시)에 붐볐던 곳은 0.25~0.5km, 대기가 잦았던 곳은 0.3km 더 먼 것처럼 "
                          "계산해 뒤로 보냈습니다(허브 1226·1225). 잉여 시간인 낮에 가도 자리가 있을 곳을 앞에 둡니다.")
    if area in PLACE_COORDS:
        out["center"] = {"lat": PLACE_COORDS[area][0], "lon": PLACE_COORDS[area][1]}
    return out


def kakao_route(name: str, lat: float, lon: float) -> str:
    """카카오맵 길찾기 링크: 열면 사용자의 현재 위치에서 목적지까지 경로를 보여 줌."""
    name = str(name).replace(",", " ").strip()   # 카카오 링크는 쉼표로 이름·좌표를 나눔
    return "https://map.kakao.com/link/to/" + quote(f"{name},{lat:.5f},{lon:.5f}", safe=",")


def charger_places() -> pd.DataFrame:
    """충전소를 장소 단위로 합친 표 (이름·좌표·급속 여부·대수). 화면의 내 주변 지도에 씀."""
    st_ = _hub_csv(862)
    if st_ is None:
        return pd.DataFrame(columns=["name", "lat", "lon", "quick", "quick_count", "slow_count"])
    df = st_.copy()
    df["lat"] = pd.to_numeric(df["latitude"], errors="coerce")
    df["lon"] = pd.to_numeric(df["longitude"], errors="coerce")
    df = df[df["lat"].between(33.1, 34.0) & df["lon"].between(126.1, 127.0)]
    df["q"] = df["quickChargingFlag"].astype(str).str.lower().isin(["true", "1", "y"])
    for c in ("chargerCount", "quickChargerCount"):
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)
    g = df.groupby("chargingPlace").agg(lat=("lat", "mean"), lon=("lon", "mean"), quick=("q", "max"),
                                        quick_count=("quickChargerCount", "sum"),
                                        slow_count=("chargerCount", "sum")).reset_index()
    g["chargingPlace"] = g["chargingPlace"].astype(str).str.strip()
    return g.rename(columns={"chargingPlace": "name"})


def map_points(quick_only: bool = False) -> pd.DataFrame:
    """화면 지도용 점: 충전소(허브 862, 장소 단위) + 풍력발전소(위치는 리 단위 대략값, 팀원 B 정리).
    색: 파랑=급속 있는 충전소, 회색=완속만, 주황=풍력발전소(크기=설비용량)."""
    pts = []
    st_ = _hub_csv(862)
    if st_ is not None:
        df = st_.copy()
        df["lat"] = pd.to_numeric(df["latitude"], errors="coerce")
        df["lon"] = pd.to_numeric(df["longitude"], errors="coerce")
        df = df[df["lat"].between(33.1, 34.0) & df["lon"].between(126.1, 127.0)]
        df["q"] = df["quickChargingFlag"].astype(str).str.lower().isin(["true", "1", "y"])
        g = df.groupby("chargingPlace").agg(lat=("lat", "mean"), lon=("lon", "mean"), q=("q", "max")).reset_index()
        if quick_only:
            g = g[g["q"]]
        pts.append(pd.DataFrame({"lat": g["lat"], "lon": g["lon"], "종류": g["q"].map({True: "급속 충전소", False: "완속 충전소"}),
                                 "color": g["q"].map({True: "#2a78d6", False: "#9a9a96"}), "size": 60.0}))
    wf = DATA / "grid_raw" / "jeju_wind_farms_approx.csv"
    if wf.exists():
        w = pd.read_csv(wf)
        pts.append(pd.DataFrame({"lat": w["lat_approx"], "lon": w["lon_approx"], "종류": "풍력발전소",
                                 "color": "#eb6834", "size": 300.0 + pd.to_numeric(w["설비용량_MW"], errors="coerce").fillna(0) * 25}))
    return pd.concat(pts, ignore_index=True) if pts else pd.DataFrame(columns=["lat", "lon", "종류", "color", "size"])


_MIDDAY_CACHE: dict = {}


def _midday_use() -> pd.DataFrame | None:
    """허브 1226(2021년 1~9월, 충전기별·시작 시각별 충전 횟수) + 허브 862(지금 충전기 수)
    → 충전소별 '낮(10~15시)에 얼마나 붐볐나' (한산·보통·붐빔).
    잉여 시간(낮)에 충전하러 갔을 때 자리가 있을 가능성을 가늠하는 데 씀.
    2021년 뒤 충전기를 늘린 곳이 많아, 2021년 낮 충전 횟수를 '지금 충전기 수'(허브 862)로 나눠 비교합니다.
    급속이 있는 곳과 완속만 있는 곳은 원래 이용 횟수가 달라 따로 3등분합니다."""
    if "v" in _MIDDAY_CACHE:
        return _MIDDAY_CACHE["v"]
    r, st = _hub_csv(1226), _hub_csv(862)
    if r is None or st is None or "evChargingStationName" not in r:
        _MIDDAY_CACHE["v"] = None
        return None
    r = r.assign(name=r["evChargingStationName"].astype(str).str.strip(),
                 h=pd.to_numeric(r["chargingStartHour"], errors="coerce"),
                 n=pd.to_numeric(r["chargingCount"], errors="coerce").fillna(0))
    days = max(1, r["baseYearMonth"].nunique() * 30)
    mid = r[r["h"].between(10, 14)].groupby("name")["n"].sum() / days
    now = st.assign(name=st["chargingPlace"].astype(str).str.strip(),
                    c=pd.to_numeric(st["chargerCount"], errors="coerce").fillna(0)     # 완속 대수
                    + pd.to_numeric(st["quickChargerCount"], errors="coerce").fillna(0),  # + 급속 대수
                    q=st["quickChargingFlag"].astype(str).str.lower().isin(["true", "1", "y"]))
    now = now.groupby("name").agg(chargers=("c", "sum"), fast=("q", "max"))
    out = now.join(mid.rename("mid_per_day"), how="inner")
    out = out[out["chargers"] > 0]
    out["per_charger_day"] = (out["mid_per_day"] / out["chargers"]).round(2)
    out["level"] = "보통"
    for fast in (True, False):
        m = out["fast"] == fast
        if m.sum() >= 3:
            lo, hi = out.loc[m, "per_charger_day"].quantile([1 / 3, 2 / 3])
            out.loc[m & (out["per_charger_day"] <= lo), "level"] = "한산"
            out.loc[m & (out["per_charger_day"] >= hi), "level"] = "붐빔"
    months = sorted(r["baseYearMonth"].astype(str).unique())
    out.attrs["period"] = f"{months[0][:4]}년 {int(months[0][4:])}~{int(months[-1][4:])}월"
    _MIDDAY_CACHE["v"] = out
    return out


BUSY_PENALTY_KM = {"한산": 0.0, "보통": 0.25, "붐빔": 0.5}   # 낮에 붐볐던 곳은 그만큼 먼 것처럼 계산해 뒤로
WAIT_PENALTY_KM = 0.3                                     # 대기가 잦았던 곳(허브 1225, 15% 이상)


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
_SEASON = {12: "겨울", 1: "겨울", 2: "겨울", 3: "봄", 4: "봄", 5: "봄",
           6: "여름", 7: "여름", 8: "여름", 9: "가을", 10: "가을", 11: "가을"}


def explain_surplus() -> dict:
    lab = load_labels()
    day = lab.groupby("date")["is_surplus"].max()
    month = day.groupby(day.index.month).mean().round(3)
    hour = lab.groupby("hour")["is_surplus"].sum()
    dow = day.groupby(day.index.day_of_week).mean().round(3)
    out = {
        "period": f"{lab['date'].min():%Y-%m-%d} ~ {lab['date'].max():%Y-%m-%d}",
        "days": int(day.size), "surplus_days": int(day.sum()), "surplus_hours": int(lab["is_surplus"].sum()),
        "surplus_day_rate_by_month": {int(k): v for k, v in month.items()},
        "surplus_hours_by_hour": {int(k): int(v) for k, v in hour.items()},
        "surplus_day_rate_by_weekday": {WEEKDAYS[int(k)]: v for k, v in dow.items()},
        # 계절을 잘못 붙이지 않도록 달마다 계절을 함께 줌 (예: 11월은 가을)
        "top_months_with_season": [f"{int(m)}월({_SEASON[int(m)]}) {v:.0%}" for m, v in month.sort_values(ascending=False).head(4).items()],
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
        rows.append({"date": f"{d:%Y-%m-%d}", "weekday": WEEKDAYS[d.day_of_week],
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


# ---------------------------------------------------------------- ⑩ 기기 사용 계획 (생활 언어 → 시간·전력량 계산)
def _hour_label_text(start_hour: int, length: int) -> str:
    """시작 시각 s, 길이 L → '낮 12시~오후 2시' (SMP 표기 시각은 구간 끝이라 s+1..s+L)."""
    return _hours_text(list(range(start_hour + 1, start_hour + length + 1)))


def plan_appliance_use(appliance: str = "", day: str = "", start_hour: int | None = None, end_hour: int | None = None,
                       battery_percent: float | None = None, car: str = "", fuel: str = "", question: str = "",
                       away_start: int | None = None, away_end: int | None = None, away_weekdays_only: bool = True) -> dict:
    """기기 이름(또는 질문 문장)으로 걸리는 시간·전력량을 정하고, 예보에서 남는 전기가 가장 많은 연속 시간대를 찾음.
    day: 'YYYY-MM-DD' 또는 요일 한 글자('토') 또는 '' (예보 기간 전체)
    start_hour/end_hour: 사용자가 원하는 시간대(시작 시각 기준 0~24). 주면 그 시간대도 따로 평가함."""
    from appliances import APPLIANCES, EV_SOURCE, DEFAULT_EARLIEST, DEFAULT_LATEST, ev_energy, find_appliance
    from predict import forecast
    key = appliance if appliance in APPLIANCES else find_appliance(appliance or question)
    if key is None:
        return {"error": "어떤 기기인지 찾지 못했어요.",
                "supported": list(APPLIANCES), "sources": []}
    a = APPLIANCES[key]
    out = {"appliance": key, "shift": a["shift"], "mode": a["mode"], "how": a["how"],
           "basis": a["basis"], "note": a["note"], "sources": [a["source"]]}
    # --- 전력량·시간
    if key == "전기차":
        ev = ev_energy(battery_percent, car)
        out["ev"] = ev
        out["sources"].append(EV_SOURCE)
        length = ev["hours_ceil"]
        if ev["assumed_percent"]:
            out["ask_user"] = "배터리가 지금 몇 % 남았는지 알려 주시면 더 정확해요. (지금은 반쯤 남았다고 보고 계산했어요)"
    else:
        if a.get("kwh"):
            out["kwh_range"] = list(a["kwh"])
        if a.get("kwh_per_hour"):
            out["kwh_per_hour_range"] = list(a["kwh_per_hour"])
        if a.get("hours"):
            out["hours_range"] = list(a["hours"])
        length = math.ceil(a["hours"][1]) if a.get("hours") else 2
    text = f"{appliance} {fuel} {question}"
    if a["mode"] == "ask" and any(w in text for w in ("기름", "가스", "석유", "등유", "LPG", "lpg")):
        out["fuel"] = "기름·가스"
        out["how"] = ("기름·가스 보일러는 연료를 태워 난방해서 전기를 거의 쓰지 않아요. 그래서 켜는 시간을 옮겨도 "
                      "남는 전기를 쓰는 효과는 없어요. 대신 전기로 난방하는 히트펌프로 바꾸면 낮에 남는 전기로 물을 데워 둘 수 있어요.")
        out["support_program"] = ("제주도 '생활 속 히트펌프 보급사업'이 기름·가스 보일러를 히트펌프로 바꾸는 비용을 지원해요"
                                  "(모집 시기·조건은 제주도 공고 확인).")
        return out
    if a["mode"] == "ask" and (fuel.startswith("전기") or re.search(r"전기(보일러|야|예요|에요|이에요|입니다|로|거)", text.replace(" ", ""))):
        return plan_appliance_use("전기보일러", day, start_hour, end_hour)
    if a["mode"] == "ask":
        out["ask_user"] = "전기보일러인가요, 기름·가스 보일러인가요?"
        out["support_program"] = ("기름·가스 보일러 가구는 제주도 '생활 속 히트펌프 보급사업'으로 "
                                  "히트펌프 교체를 지원받을 수 있어요(모집 시기·조건은 제주도 공고 확인).")
        return out
    if a["shift"] == "불가":
        return out
    # --- 예보에서 연속 시간대 찾기 (오늘~5일 뒤)
    today = date.today()
    last = today + timedelta(days=MAX_HORIZON_DAYS)
    fc = forecast(str(today), MAX_HORIZON_DAYS + 1, log=False)
    fc["d"] = fc["date"].dt.date
    now_h = datetime.now().hour
    days = sorted(fc["d"].unique())
    day = (day or "").strip()
    rel = {"오늘": 0, "내일": 1, "모레": 2}
    if day in rel:
        day = str(today + timedelta(days=rel[day]))
    elif day.endswith("요일") and len(day) == 3:
        day = day[0]
    if day:
        wd = "월화수목금토일"
        days = [d for d in days if str(d) == day or (len(day) == 1 and wd[d.weekday()] == day)]
        if not days:
            out["not_forecast"] = f"{day}은(는) 예보할 수 있는 기간({today} ~ {last}) 밖이에요."
            return out
    lo = DEFAULT_EARLIEST if start_hour is None else int(start_hour)
    hi = DEFAULT_LATEST if end_hour is None else int(end_hour)
    cands = []
    for d in days:
        g = fc[fc["d"] == d].set_index("hour")
        basis = _basis(g["model_used"])
        for s in range(0, 24 - length + 1):
            if d == today and s < now_h:
                continue
            p = [float(g.loc[h, "prob"]) for h in range(s + 1, s + length + 1) if h in g.index]
            if len(p) < length:
                continue
            cands.append({"date": str(d), "weekday": "월화수목금토일"[d.weekday()], "start_hour": s,
                          "end_hour": s + length, "time_text": _hour_label_text(s, length),
                          "avg_prob": round(sum(p) / len(p), 3), "level": level_of(sum(p) / len(p)),
                          "basis": basis,
                          "in_requested": lo <= s and s + length <= hi})
    def top3(cs):
        best = []
        for c in sorted(cs, key=lambda c: -c["avg_prob"]):   # 날짜마다 하나씩, 상위 3개
            if all(b["date"] != c["date"] for b in best):
                best.append(c)
            if len(best) == 3:
                break
        return best

    usable = [c for c in cands if DEFAULT_EARLIEST <= c["start_hour"] and c["end_hour"] <= DEFAULT_LATEST]
    # --- 일정(출근·외출) 반영 — 팀원 C(TIMEFLOW)의 '시간 제약 안에서 계획' 방식
    if away_start is not None and away_end is not None:
        a0, a1 = int(away_start), int(away_end)
        wd_only = bool(away_weekdays_only)

        def away(c):   # 그 시간대에 집에 없는지
            if wd_only and "월화수목금토일".index(c["weekday"]) >= 5:
                return False
            return c["start_hour"] < a1 and c["end_hour"] > a0
        sched = {"away": f"{a0}시~{a1}시" + (" (평일)" if wd_only else ""),
                 "reservable": bool(a.get("reserve"))}
        if key == "전기차":
            # 차는 사람과 함께 움직임 → 밖에 있는 동안은 그곳(회사 근처) 충전소, 집에서는 집에 있는 시간에만
            sched["while_away"] = top3([c for c in usable if away(c)])
            sched["at_home"] = top3([c for c in usable if not away(c)])
            sched["note"] = ("나가 있는 동안에는 회사·목적지 근처 공용 충전소에서, 집 충전기는 집에 있는 시간에만 쓸 수 있어요.")
        elif a.get("reserve"):
            sched["note"] = "예약·타이머 기능이 있어 집에 없어도 남는 전기 시간에 돌아가게 할 수 있어요."
        else:
            usable = [c for c in usable if not away(c)]
            sched["note"] = "집에 있을 때 직접 켜야 하는 기기라, 나가 있는 시간은 빼고 찾았어요."
        out["schedule"] = sched
    out["length_hours"] = length
    out["best_windows"] = top3(usable)
    want_alt = bool(day and not out["best_windows"]) or (start_hour is not None and int(start_hour) >= 16)
    if (start_hour is not None or end_hour is not None or day):
        req = [c for c in cands if c["in_requested"]]
        want_alt = want_alt or not req or max(c["avg_prob"] for c in req) < 0.2
    if want_alt:
        # 원한 날·시간에 마땅한 자리가 없으면 예보 기간 전체에서 대안을 함께 줌
        alt = []
        for d in sorted(fc["d"].unique()):
            g = fc[fc["d"] == d].set_index("hour")
            basis = _basis(g["model_used"])
            for s in range(DEFAULT_EARLIEST, DEFAULT_LATEST - length + 1):
                if d == today and s < now_h:
                    continue
                p = [float(g.loc[h, "prob"]) for h in range(s + 1, s + length + 1) if h in g.index]
                if len(p) == length:
                    alt.append({"date": str(d), "weekday": "월화수목금토일"[d.weekday()], "start_hour": s,
                                "end_hour": s + length, "time_text": _hour_label_text(s, length),
                                "avg_prob": round(sum(p) / len(p), 3), "level": level_of(sum(p) / len(p)),
                                "basis": basis})
        out["alternatives"] = top3(alt)
    # 원한 때보다 확실히 나은 때가 있으면 따로 담아 둠 (LLM 이 빠뜨리지 않도록)
    ref = out.get("requested_window_best") or (out["best_windows"][0] if out["best_windows"] else None)
    pool = out.get("alternatives") or out["best_windows"]
    if pool:
        top = max(pool, key=lambda c: c["avg_prob"])
        if ref is None or top["avg_prob"] >= ref["avg_prob"] + 0.05:
            out["better_option"] = {**top, "note": "원하신 때보다 남는 전기 가능성이 더 높은 때 — 답에 꼭 함께 알려 줄 것"}
    if start_hour is not None or end_hour is not None or day:
        req = [c for c in cands if c["in_requested"]]
        if req:
            r = max(req, key=lambda c: c["avg_prob"])
            out["requested_window_best"] = r
        else:
            out["requested_window_best"] = None
            out["requested_note"] = f"원하신 시간대 안에 {length}시간 연속으로 돌릴 자리가 없어요."
    # 저녁·밤 사용 안내 (남는 전기는 거의 낮에 생김)
    if start_hour is not None and int(start_hour) >= 16:
        out["evening_note"] = ("저녁에는 제주에 남는 전기가 거의 없어요(잉여 시간의 약 91%가 오전 10시~오후 3시). "
                               "꼭 저녁에 써야 하면, 계시별 요금제 가입 가구는 밤 10시 이후(경부하)가 저녁 4~10시보다 요금이 싸요.")
        out["sources"].append(FACTS["jeju_tou_tariff"]["source"])
    out["forecast_range"] = f"{today} ~ {last}"
    out["sources"] += ["EPSIS 제주 시간별 SMP(학습 정답)", "기상청 단기예보"]
    return out


# ---------------------------------------------------------------- ⑪ 전력 계통 기록 (출력제어·연계선·수요·플러스 DR)
def grid_records() -> dict:
    """버려진 재생에너지(출력제어), 육지로 보낸 전기(연계선 역송), 잉여 날의 낮 수요, 플러스 DR 실적.
    팀원 B 가 공공데이터포털에서 받은 한국전력거래소 파일로 계산."""
    import grid
    if not grid.available():
        return {"error": "전력 계통 기록 파일(data/grid_raw)이 없어요.", "sources": []}
    out = dict(grid.grid_stats())
    out["sources"] = list(grid.SOURCES.values()) + ["EPSIS 제주 시간별 SMP(잉여 정답)"]
    return out


TOOLS = {
    "explain_benefits": explain_benefits,
    "how_to_act": how_to_act,
    "plan_appliance_use": plan_appliance_use,
    "grid_records": grid_records,
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
    {"name": "find_chargers", "description": "지역 이름으로 전기차 충전소(위치·급속 여부·관광객 이용 비중)를 찾는다. 결과 순서는 가까운 곳 위주이되, 허브 1226(충전소별 낮 시간 이용)·1225(대기)로 낮에 붐볐던 곳을 뒤로 보낸 것이다(reason, moved_back, ranking).",
     "parameters": {"type": "object", "properties": {
         "area": {"type": "string", "description": "동네·장소 이름 (예: 노형, 애월, 서귀포시청)"},
         "quick_only": {"type": "boolean", "default": False},
         "limit": {"type": "integer", "default": 5}}}},
    {"name": "ev_charging_habits", "description": "제주 도민이 보통 몇 시에 충전하는지와 잉여 시간대를 비교한다.",
     "parameters": {"type": "object", "properties": {}}},
    {"name": "explain_surplus", "description": "잉여전력이 언제·왜 생기는지 과거 통계(월·시간·요일)로 설명한다. 제주 기후(일사·일조·바람, 허브 877), 태양광 발전 설비가 해마다 얼마나 늘었는지(사업체 수·누적 MW, 허브 123), 풍력발전 설비(허브 472)도 함께 돌려준다. '태양광이 얼마나 늘었어?', '풍력은 몇 MW야?' 같은 질문에도 이 도구를 쓴다.",
     "parameters": {"type": "object", "properties": {}}},
    {"name": "check_past_forecast", "description": "지난 기간의 예보가 실제로 맞았는지 비교한다.",
     "parameters": {"type": "object", "properties": {
         "start": {"type": "string", "description": "YYYY-MM-DD"}, "end": {"type": "string", "description": "YYYY-MM-DD"}}}},
    {"name": "explain_benefits", "description": "이 서비스를 쓰면 도민이 얻는 이득(지금 바로/조건부/앞으로)과 얻지 못하는 것을 솔직하게 정리한다.",
     "parameters": {"type": "object", "properties": {}}},
    {"name": "plan_appliance_use", "description": "도민이 말한 기기(세탁기·건조기·식기세척기·전기차·히트펌프·온수기·전기보일러·음식물처리기·"
     "의류관리기·밥솥·작은 충전기기·에어컨·전기히터·전기장판·보일러)의 걸리는 시간·전력량을 기기 사전으로 계산하고, "
     "예보에서 남는 전기가 가장 많은 연속 시간대를 찾는다. 사용자가 원하는 날·시간대가 있으면 그 시간대도 평가한다. "
     "사용자에게 kWh·kW를 묻지 말고 이 도구를 먼저 부른다.",
     "parameters": {"type": "object", "properties": {
         "appliance": {"type": "string", "description": "기기 이름 또는 사용자가 쓴 말 (예: '빨래', '차 충전', '보일러')"},
         "day": {"type": "string", "description": "YYYY-MM-DD 또는 요일 한 글자('토'). 없으면 예보 기간 전체"},
         "start_hour": {"type": "integer", "description": "원하는 시작 시각(0~23). 예: '오늘 저녁'이면 18"},
         "end_hour": {"type": "integer", "description": "원하는 시간대의 끝 시각(1~24)"},
         "battery_percent": {"type": "number", "description": "전기차 현재 배터리 %. '반쯤'=50, 모르면 비움"},
         "car": {"type": "string", "description": "전기차 차종 (예: 아이오닉5, 레이). 모르면 비움"},
         "fuel": {"type": "string", "description": "보일러 연료: '전기' 또는 '기름·가스'. 사용자가 말하지 않았으면 비움"},
         "away_start": {"type": "integer", "description": "사용자가 집에 없는 시작 시각(0~23). 예: '9시 출근' → 9"},
         "away_end": {"type": "integer", "description": "집에 돌아오는 시각(1~24). 예: '6시 퇴근'·'18시 퇴근' → 18"},
         "away_weekdays_only": {"type": "boolean", "description": "출근처럼 평일에만 집에 없으면 true(기본), 그날만 외출이면 false"}}}},
    {"name": "grid_records", "description": "제주 전력 계통 기록을 돌려준다: 남아서 버려진 재생에너지(풍력 출력제어 MWh·횟수, 태양광 출력제어 횟수, "
     "2021~2024), 잉여가 생긴 날 낮의 전력수요와 육지에서 받는 전기(연계선 HVDC, 2026년 1~9월, 역송 시간), "
     "플러스 DR(남을 때 더 쓰면 보상) 실적(2021~2023). '출력제어 얼마나 했어?', '버려지는 전기가 얼마야?', "
     "'육지로 전기 보내?', '플러스 DR이 뭐야?' 같은 질문에 쓴다.",
     "parameters": {"type": "object", "properties": {}}},
    {"name": "how_to_act", "description": "잉여 시간에 맞춰 전기를 쓰려면 실제로 무엇을 하면 되는지(예약 기능, 피할 시간, 요금제 문의) 단계별로 알려 준다.",
     "parameters": {"type": "object", "properties": {
         "target": {"type": "string", "enum": ["가전", "전기차"], "default": "전기차"}}}},
    {"name": "data_status", "description": "어떤 데이터가 준비됐는지, 실시간 예보가 연결됐는지 확인한다.",
     "parameters": {"type": "object", "properties": {}}},
]
