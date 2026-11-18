"""학습·예측에 쓰는 표(시간 단위)를 만듭니다.

변수 묶음
  1) 달력 (항상): 월, 연중 일자, 요일, 주말·공휴일, 시각
  2) 최근 잉여 경향 (항상): 예측 시점에 알 수 있는 과거 14일 잉여 횟수
     → MAX_HORIZON_DAYS 만큼 미뤄 계산하므로 5일 앞 예측에도 미래 정보가 섞이지 않습니다.
  3) 시간별 날씨 (파일이 있으면): 기온·풍속·하늘상태·강수 — 학습은 ASOS 관측, 예측은 단기예보
  4) 허브 일별 기상 (파일이 있으면, 대회 필수 데이터 579): 섬 평균 기온·강수·풍속
     — 학습은 허브 관측값, 예측은 단기예보에서 같은 의미로 계산한 값
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from config import (FORECAST_HOURLY_CSV, HOLIDAYS, HUB_WEATHER_DAILY_CSV,
                    MAX_HORIZON_DAYS, SMP_COMPACT_TXT, SMP_HOURLY_CSV,
                    WEATHER_HOURLY_CSV)

CALENDAR_FEATURES = [
    "month", "doy_sin", "doy_cos", "dow", "is_weekend", "is_holiday",
    "is_offday", "hour", "hour_sin", "hour_cos",
]
TREND_FEATURES = ["recent_surplus_days", "recent_surplus_hours_same_hour"]
WEATHER_FEATURES = ["w_ta", "w_ws", "w_sky", "w_rain"]
# hub_day_max_wind 는 뺌: 허브 579의 최대풍속은 순간 최대(평균 10.7m/s)라
# 시간 평균 풍속으로 만드는 ASOS·단기예보 값(약 6m/s)과 뜻이 달라 이어 붙일 수 없음
HUB_DAILY_FEATURES = ["hub_day_avg_temp", "hub_day_max_temp", "hub_day_rain", "hub_day_avg_wind"]


# ---------------------------------------------------------------- 정답 불러오기
def _load_compact(path: Path) -> pd.DataFrame:
    rows: dict[str, str] = {}
    start = end = None
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("RANGE"):
            _, start, end = line.split()
            continue
        day, codes = line.split()
        rows[day] = codes
    if start is None:
        raise ValueError("요약본에 RANGE 줄이 없습니다.")
    records = []
    for d in pd.date_range(pd.Timestamp(start), pd.Timestamp(end), freq="D"):
        codes = rows.get(d.strftime("%Y%m%d"), "." * 24)
        for h in range(1, 25):
            records.append({"date": d, "hour": h, "is_surplus": int(codes[h - 1] == "z")})
    return pd.DataFrame(records)


def load_labels() -> pd.DataFrame:
    if SMP_HOURLY_CSV.exists():
        df = pd.read_csv(SMP_HOURLY_CSV)
        source = SMP_HOURLY_CSV.name
    else:
        df = _load_compact(SMP_COMPACT_TXT)
        source = SMP_COMPACT_TXT.name
    df["date"] = pd.to_datetime(df["date"])
    df = df[["date", "hour", "is_surplus"] + (["smp"] if "smp" in df else [])]
    df.attrs["source"] = source
    return df


# ---------------------------------------------------------------- 변수 만들기
def add_calendar(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    d = out["date"]
    out["month"] = d.dt.month
    doy = d.dt.dayofyear
    out["doy_sin"] = np.sin(2 * np.pi * doy / 365.25)
    out["doy_cos"] = np.cos(2 * np.pi * doy / 365.25)
    out["dow"] = d.dt.dayofweek  # 0=월 ... 6=일
    out["is_weekend"] = (out["dow"] >= 5).astype(int)
    out["is_holiday"] = d.dt.strftime("%Y-%m-%d").isin(HOLIDAYS).astype(int)
    out["is_offday"] = ((out["is_weekend"] + out["is_holiday"]) > 0).astype(int)
    out["hour_sin"] = np.sin(2 * np.pi * out["hour"] / 24)
    out["hour_cos"] = np.cos(2 * np.pi * out["hour"] / 24)
    return out


def add_recent_trend(df: pd.DataFrame, history: pd.DataFrame,
                     window_days: int = 14, lag_days: int = MAX_HORIZON_DAYS) -> pd.DataFrame:
    """예측 대상일 D 에 대해, [D-lag-window+1, D-lag] 기간의 잉여 횟수를 붙입니다."""
    full_idx = pd.date_range(history["date"].min(),
                             max(history["date"].max(), df["date"].max()), freq="D")
    daily = history.groupby("date")["is_surplus"].max().reindex(full_idx, fill_value=0)
    by_hour = (history.pivot_table(index="date", columns="hour", values="is_surplus", aggfunc="max")
               .reindex(full_idx).fillna(0))
    days_feat = daily.rolling(window_days, min_periods=1).sum().shift(lag_days)
    hour_feat = by_hour.rolling(window_days, min_periods=1).sum().shift(lag_days)

    out = df.copy()
    out["recent_surplus_days"] = out["date"].map(days_feat)
    stacked = hour_feat.stack()
    stacked.index.names = ["date", "hour"]
    stacked.name = "recent_surplus_hours_same_hour"
    return out.merge(stacked.reset_index(), on=["date", "hour"], how="left")


def _read(path: Path) -> pd.DataFrame | None:
    if not path.exists():
        return None
    df = pd.read_csv(path)
    df["date"] = pd.to_datetime(df["date"])
    return df


DAY_WEATHER_FEATURES = ["wd_mid_sky", "wd_mid_ws", "wd_night_ws", "wd_mean_ta", "wd_rain_hours"]


def day_weather_summary(hourly: pd.DataFrame) -> pd.DataFrame:
    """시간별 날씨 → 하루 요약. 실험 결과 '그날 한낮 하늘·바람, 새벽 바람, 기온'이 잉여를 가장 잘 설명했습니다.
    (SMP 표기 기준 한낮 = 11~15시, 새벽 = 1~7시)"""
    h = hourly
    mid = h[h["hour"].between(11, 15)].groupby("date")
    night = h[h["hour"].between(1, 7)].groupby("date")
    out = pd.DataFrame({
        "wd_mid_sky": mid["w_sky"].mean(), "wd_mid_ws": mid["w_ws"].mean(),
        "wd_night_ws": night["w_ws"].mean(), "wd_mean_ta": h.groupby("date")["w_ta"].mean(),
        "wd_rain_hours": h.groupby("date")["w_rain"].sum(),
    })
    return out.reset_index()


def hub_like_daily(hourly: pd.DataFrame) -> pd.DataFrame:
    """시간별 날씨(ASOS 관측 또는 단기예보) → 허브 579와 같은 모양의 하루 값(hub_day_*).
    허브 579는 2025년 3월까지만 있어서, 그 뒤 날짜와 예보 날짜는 이 값으로 이어 붙입니다."""
    g = hourly.groupby("date")
    return pd.DataFrame({
        "hub_day_avg_temp": g["w_ta"].mean(), "hub_day_max_temp": g["w_ta"].max(),
        # 강수량(mm): 관측 파일의 w_rn(시간 강수량)을 하루 합계로. 없으면 비 온 시간 수로 대신함
        "hub_day_rain": g["w_rn"].sum() if "w_rn" in hourly else g["w_rain"].sum(),
        "hub_day_avg_wind": g["w_ws"].mean(),
        "hub_day_max_wind": g["w_ws"].max(),
    }).reset_index()


def add_weather(df: pd.DataFrame, mode: str = "history") -> tuple[pd.DataFrame, list[str]]:
    """mode='history' 는 관측 파일, mode='forecast' 는 단기예보 파일을 붙입니다."""
    cols: list[str] = []
    out = df.copy()
    if mode == "history":
        w = _read(WEATHER_HOURLY_CSV)
        if w is not None:
            out = out.merge(w[["date", "hour"] + WEATHER_FEATURES], on=["date", "hour"], how="left")
            out = out.merge(day_weather_summary(w), on="date", how="left")
            cols += WEATHER_FEATURES + DAY_WEATHER_FEATURES
        h = _read(HUB_WEATHER_DAILY_CSV)
        if h is not None:
            h = h[["date"] + HUB_DAILY_FEATURES]
            if w is not None:   # 허브 579가 끝난 뒤(2025-04~)는 ASOS 관측으로 같은 값을 만들어 이어 붙임
                fill = hub_like_daily(w)
                h = pd.concat([h, fill[~fill["date"].isin(h["date"])]], ignore_index=True)
            out = out.merge(h, on="date", how="left")
            cols += HUB_DAILY_FEATURES
    else:
        f = _read(FORECAST_HOURLY_CSV)
        if f is not None:
            keep = ["date", "hour"] + [c for c in WEATHER_FEATURES + HUB_DAILY_FEATURES if c in f]
            out = out.merge(f[keep], on=["date", "hour"], how="left")
            if all(c in f for c in WEATHER_FEATURES):
                # 예보가 하루 전체(1~24시)를 덮는 날만 하루 요약을 만듭니다.
                full_days = f.groupby("date")["hour"].nunique()
                fd = f[f["date"].isin(full_days[full_days >= 20].index)]
                out = out.merge(day_weather_summary(fd), on="date", how="left")
            cols += keep[2:]
    return out, cols


def build_table(labels: pd.DataFrame | None = None) -> tuple[pd.DataFrame, dict[str, list[str]]]:
    """학습 표와 '모델별 변수 목록'을 돌려줍니다.

    feature_sets["calendar"]: 날씨 없이 쓰는 기본 모델
    feature_sets["full"]: 날씨 파일이 있을 때만 (없으면 키 자체가 없음)
    """
    labels = load_labels() if labels is None else labels
    table = add_calendar(labels)
    table = add_recent_trend(table, labels)
    table, weather_cols = add_weather(table, "history")
    base = CALENDAR_FEATURES + TREND_FEATURES
    sets = {"calendar": base}
    if weather_cols:
        sets["full"] = base + weather_cols
    table.attrs["source"] = labels.attrs.get("source", "")
    return table, sets


def build_future_frame(start: str, days: int, history: pd.DataFrame) -> pd.DataFrame:
    """앞으로의 날짜(정답 없음)에 대한 변수 표. 예보 파일이 있으면 날씨도 붙습니다."""
    dates = pd.date_range(pd.Timestamp(start), periods=days, freq="D")
    frame = pd.DataFrame([(d, h) for d in dates for h in range(1, 25)], columns=["date", "hour"])
    frame = add_calendar(frame)
    frame = add_recent_trend(frame, history)
    frame, _ = add_weather(frame, "forecast")
    return frame
