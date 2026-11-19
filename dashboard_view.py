"""대시보드 화면용 데이터 정리 (Streamlit과 분리해 테스트 가능하게 함).

- region_capacity(): 권역별 재생에너지 설비용량 = 허브 123(태양광, 읍면동) + 풍력발전현황(허브 472, 리 단위 좌표)
- hourly_frame(): 예보(predict.forecast) → 그래프·지도용 시간 축
- best_windows(): 잉여 가능성이 높은 연속 시간대
"""
from __future__ import annotations

import pandas as pd

from config import DATA

DOW = "월화수목금토일"
# 8개 권역(지도 원 위치 = 권역 대표 지점)
REGIONS = [
    ("jeju", "제주시 동지역", 33.475, 126.53), ("aewol", "애월", 33.425, 126.37),
    ("hallim", "한림·한경", 33.345, 126.235), ("daejeong", "대정·안덕", 33.255, 126.32),
    ("seogwi", "서귀포 동지역", 33.275, 126.52), ("namwon", "남원·표선", 33.33, 126.76),
    ("seongsan", "성산·구좌", 33.46, 126.85), ("jocheon", "조천", 33.47, 126.67),
]
TOWN_TO_REGION = {"애월읍": "aewol", "한림읍": "hallim", "한경면": "hallim", "대정읍": "daejeong", "안덕면": "daejeong",
                  "남원읍": "namwon", "표선면": "namwon", "성산읍": "seongsan", "구좌읍": "seongsan", "우도면": "seongsan",
                  "조천읍": "jocheon", "추자면": "jeju"}
LEVEL_COLOR = {"높음": "#f2a93b", "보통": "#7cc49a", "낮음": "#d5dbe1"}


def _town_region(city: str, town: str) -> str:
    if town in TOWN_TO_REGION:
        return TOWN_TO_REGION[town]
    return "seogwi" if str(city).startswith("서귀포") else "jeju"


def region_capacity() -> pd.DataFrame:
    reg = pd.DataFrame(REGIONS, columns=["id", "name", "lat", "lon"]).set_index("id")
    reg["solar_mw"] = 0.0
    reg["wind_mw"] = 0.0
    sp = DATA / "hub" / "123_solar_business_clean.csv"
    if sp.exists():
        s = pd.read_csv(sp)
        s["rid"] = [_town_region(c, t) for c, t in zip(s["city"], s["town"])]
        reg["solar_mw"] = s.groupby("rid")["capacity_mw"].sum().reindex(reg.index).fillna(0)
    wp = DATA / "grid_raw" / "jeju_wind_farms_approx.csv"
    if wp.exists():
        w = pd.read_csv(wp)
        if "region_id" in w:
            reg["wind_mw"] = pd.to_numeric(w["설비용량_MW"], errors="coerce").groupby(w["region_id"]).sum() \
                .reindex(reg.index).fillna(0)
    reg["total_mw"] = reg["solar_mw"] + reg["wind_mw"]
    return reg.reset_index()


def hourly_frame(fc: pd.DataFrame) -> pd.DataFrame:
    df = fc.copy()
    # 예보의 hour 는 SMP 표기(1~24, 구간 끝) → 구간 시작 시각으로 바꿔 그림 (예: hour 13 = 12~13시)
    df["ts"] = pd.to_datetime(df["date"]) + pd.to_timedelta(df["hour"].astype(int) - 1, unit="h")
    df = df.sort_values("ts").reset_index(drop=True)
    df["label"] = [f"{t.month}/{t.day}({DOW[t.dayofweek]}) {t.hour}~{t.hour + 1}시" for t in df["ts"]]
    df["pct"] = (df["prob"] * 100).round(0)
    df["basis"] = df["model_used"].map({"full": "기상청 단기예보 반영", "mid": "기상청 중기예보 반영(거침)",
                                         "calendar": "날씨 미반영(참고치)"}).fillna("")
    return df


def best_windows(df: pd.DataFrame, hours: int = 3, top: int = 3, min_prob: float = 0.2) -> list[dict]:
    """평균 잉여 가능성이 큰 연속 시간대(겹치지 않게). 같은 날 안에서만 찾음."""
    out = []
    for d, g in df.groupby(df["ts"].dt.date):
        g = g.sort_values("ts")
        p = g["prob"].to_numpy()
        for i in range(0, len(g) - hours + 1):
            if g.iloc[i + hours - 1]['ts'] - g.iloc[i]['ts'] != pd.Timedelta(hours=hours - 1):
                continue
            m = float(p[i:i + hours].mean())
            out.append((m, g.index[i], g.index[i + hours - 1]))
    out.sort(key=lambda x: -x[0])
    picked = []
    for m, a, b in out:
        if m < min_prob:
            break
        if all(b < pa or a > pb for _, pa, pb in picked):
            picked.append((m, a, b))
        if len(picked) >= top:
            break
    res = []
    for m, a, b in picked:
        t0, t1 = df.loc[a, "ts"], df.loc[b, "ts"] + pd.Timedelta(hours=1)
        res.append({"text": f"{t0.month}/{t0.day}({DOW[t0.dayofweek]}) {t0.hour}~{t1.hour if t1.hour else 24}시", "prob": m,
                    "start": t0, "end": t1})
    return res


def night_bands(df: pd.DataFrame) -> pd.DataFrame:
    """그래프 배경용 밤(18~7시) 구간."""
    rows = []
    for d in sorted(df["ts"].dt.normalize().unique()):
        d = pd.Timestamp(d)
        rows += [{"s": d, "e": d + pd.Timedelta(hours=7)}, {"s": d + pd.Timedelta(hours=18), "e": d + pd.Timedelta(hours=24)}]
    b = pd.DataFrame(rows)
    lo, hi = df["ts"].min(), df["ts"].max() + pd.Timedelta(hours=1)
    b["s"] = b["s"].clip(lower=lo, upper=hi)
    b["e"] = b["e"].clip(lower=lo, upper=hi)
    return b[b["e"] > b["s"]]


def prob_color(p: float) -> list[int]:
    """잉여 가능성 → 지도 원 색 (회색 → 초록 → 주황)."""
    stops = [(0.0, (200, 208, 214)), (0.2, (124, 196, 154)), (0.5, (23, 138, 87)), (0.8, (242, 169, 59))]
    p = max(0.0, min(1.0, float(p)))
    for (p0, c0), (p1, c1) in zip(stops, stops[1:]):
        if p <= p1:
            t = (p - p0) / (p1 - p0)
            return [round(a + (b - a) * t) for a, b in zip(c0, c1)] + [190]
    return list(stops[-1][1]) + [190]
