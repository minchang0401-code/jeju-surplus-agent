"""전력 계통 기록 — 팀원 B(JEJU_SURPLUS_FORECAST)가 공공데이터포털에서 받은 파일을 합쳐 씀.

- 제주 풍력 출력제어 횟수·제어량(2021-01~2024-05), 제주 태양광 출력제어 횟수(2021-10~2024-06)
  : 한국전력거래소_전국 태양광 풍력 제어횟수 및 제주 풍력 제어량 (data.go.kr 15132422)
- 시간별 제주 전력수요 (2026-01~09) : 한국전력거래소_시간별 제주전력수요 (data.go.kr 15065239)
- 연계선(HVDC #1~#3) 시간별 수전전력 (2026-01~09) : 한국전력거래소_제주 일별 시간대별 연계선 수전전력 (data.go.kr 15100403)
- 제주 플러스 DR 실적 (2021~2023) : 한국전력거래소_제주 플러스 DR 실적 (data.go.kr 15109039)
모든 파일의 시각은 '구간 끝'(13시 = 12~13시) 표기로, 이 프로젝트의 SMP 정답과 같습니다.
"""
from __future__ import annotations

from functools import lru_cache

import pandas as pd

from config import DATA
from features import load_labels

RAW = DATA / "grid_raw"
SOURCES = {
    "curtail": "한국전력거래소 제주 풍력·태양광 출력제어 기록 (공공데이터포털 15132422)",
    "demand": "한국전력거래소 시간별 제주전력수요 (공공데이터포털 15065239)",
    "hvdc": "한국전력거래소 제주 연계선(HVDC) 시간별 수전전력 (공공데이터포털 15100403)",
    "plusdr": "한국전력거래소 제주 플러스 DR 실적 (공공데이터포털 15109039)",
}


def _read(name: str) -> pd.DataFrame:
    for enc in ("utf-8", "cp949"):
        try:
            return pd.read_csv(RAW / name, encoding=enc)
        except UnicodeDecodeError:
            continue
    raise ValueError(f"읽을 수 없는 파일: {name}")


def _long(df: pd.DataFrame, date_col: str) -> pd.DataFrame:
    hours = [c for c in df.columns if c.endswith("시") and c[:-1].isdigit()]
    m = df.melt(id_vars=[date_col], value_vars=hours, var_name="h", value_name="v")
    m["hour"] = m["h"].str[:-1].astype(int)
    m["date"] = pd.to_datetime(m[date_col])
    return m[["date", "hour", "v"]]


def available() -> bool:
    return (RAW / "jeju_wind_curtailment.csv").exists()


@lru_cache(maxsize=1)
def grid_stats() -> dict:
    out: dict = {}
    # ① 출력제어 (버려진 재생에너지)
    w = _read("jeju_wind_curtailment.csv")
    wl = _long(w, "일자")
    wl["v"] = pd.to_numeric(wl["v"], errors="coerce").fillna(0)
    wd = pd.to_datetime(w["일자"])
    s = _read("jeju_solar_curtailment.csv")
    sl = _long(s, "일자")
    sl["c"] = (sl["v"].astype(str) == "출력제어").astype(int)
    sd = pd.to_datetime(s["일자"])
    wind_hour = wl.groupby("hour")["v"].sum()
    out["curtailment"] = {
        "wind_period": f"{wd.min():%Y-%m} ~ {wd.max():%Y-%m}",
        "wind_days": int(wd.nunique()),
        "wind_mwh_total": round(float(wl["v"].sum())),
        "wind_mwh_by_year": {int(k): round(float(v)) for k, v in wl.groupby(wl["date"].dt.year)["v"].sum().items()},
        "wind_days_by_year": {int(k): int(v) for k, v in wd.dt.year.value_counts().sort_index().items()},
        "wind_share_10_16": round(float(wind_hour.loc[11:16].sum() / wind_hour.sum()), 3),
        "wind_mwh_by_hour": {int(k): round(float(v)) for k, v in wind_hour.items()},
        "solar_period": f"{sd.min():%Y-%m} ~ {sd.max():%Y-%m}",
        "solar_days": int(sd.nunique()),
        "solar_days_by_month": {int(k): int(v) for k, v in sd.dt.month.value_counts().sort_index().items()},
        "solar_count_by_hour": {int(k): int(v) for k, v in sl.groupby("hour")["c"].sum().items()},
        "note": "출력제어 = 전기가 남아 발전기를 강제로 멈춘 것. 기록은 2024년 상반기까지 공개됨.",
    }
    # ② 수요·연계선 vs 잉여(SMP≤0) — 2026년 1~9월, 같은 시각끼리 비교
    dem = _long(_read("jeju_demand_2026.csv"), "날짜").rename(columns={"v": "demand"})
    dem["demand"] = pd.to_numeric(dem["demand"], errors="coerce")
    hv = None
    for i in (1, 2, 3):
        h = _long(_read(f"jeju_hvdc{i}.csv"), "날짜").set_index(["date", "hour"])["v"]
        h = pd.to_numeric(h, errors="coerce")
        hv = h if hv is None else hv.add(h, fill_value=0)
    hv = hv.rename("hvdc").reset_index()
    lab = load_labels().copy()
    lab["date"] = pd.to_datetime(lab["date"])
    x = lab.merge(dem, on=["date", "hour"]).merge(hv, on=["date", "hour"])
    mid = x[x["hour"].between(12, 14)]          # 낮 11시~오후 2시
    day = mid.groupby("date").agg(s=("is_surplus", "max"), demand=("demand", "mean"), hvdc=("hvdc", "mean"))
    g = day.groupby("s")[["demand", "hvdc"]].mean()
    rev = x[x["hvdc"] < 0]
    out["demand_hvdc"] = {
        "period": f"{x['date'].min():%Y-%m-%d} ~ {x['date'].max():%Y-%m-%d}",
        "days_surplus": int(day["s"].sum()), "days_other": int((day["s"] == 0).sum()),
        "midday_demand_mw": {"잉여 있는 날": round(float(g.loc[1, "demand"])), "다른 날": round(float(g.loc[0, "demand"]))},
        "midday_hvdc_import_mw": {"잉여 있는 날": round(float(g.loc[1, "hvdc"])), "다른 날": round(float(g.loc[0, "hvdc"]))},
        "reverse_hours": int(len(rev)),
        "reverse_hours_in_surplus": int(rev["is_surplus"].sum()),
        "note": "낮 11시~오후 2시 평균. 연계선 값이 음수면 제주에서 육지로 전기를 보낸(역송) 시간.",
    }
    # ③ 플러스 DR (남는 시간에 전기를 더 쓰면 보상) 실적
    p = _read("jeju_plus_dr_2021_2023.csv")
    p["증대량"] = pd.to_numeric(p["증대량(MWh)"], errors="coerce")
    yr = p.groupby("연도").agg(days=("증대일", "nunique"), hours=("증대시간", "count"), mwh=("증대량", "sum"))
    out["plus_dr"] = {
        "period": "2021 ~ 2023",
        "by_year": {int(k): {"발령일": int(r.days), "시간": int(r.hours), "증대량_MWh": round(float(r.mwh), 1)}
                    for k, r in yr.iterrows()},
        "total_mwh": round(float(p["증대량"].sum()), 1),
        "hours_most": [int(h) for h in p["증대시간"].value_counts().head(3).index],
        "note": "플러스 DR = 전기가 남을 때 미리 약속한 고객이 사용량을 늘리고 보상받는 제도(주로 기업·기관 대상).",
    }
    return out
