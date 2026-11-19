"""학습된 모델로 앞으로 며칠의 '잉여전력 가능성'을 시간별로 예측합니다.

    python predict.py --start 2026-11-18 --days 5

- 단기예보 파일(data/forecast_jeju_hourly.csv)이 있는 날짜는 날씨 모델(full)로,
  없는 날짜는 1차 모델(calendar)로 예측하고, 어느 모델을 썼는지 함께 돌려줍니다.
- 예측 결과는 data/forecast_log.csv 에 쌓아 두었다가 나중에 실제와 비교합니다.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta
from functools import lru_cache

import joblib
import pandas as pd

from config import MAX_HORIZON_DAYS, MODELS, PREDICTION_LOG
from features import build_future_frame, load_labels


def level_of(p: float) -> str:
    return "높음" if p >= 0.5 else ("보통" if p >= 0.2 else "낮음")


@lru_cache(maxsize=1)
def load_bundle() -> dict:
    """학습된 모델을 읽음. 파일이 없거나 scikit-learn 버전이 달라 그대로 쓰기 어려우면
    (예: 다른 PC·클라우드에 새로 설치한 경우) 들어 있는 데이터로 그 자리에서 다시 학습합니다(1분 안팎)."""
    import warnings
    path = MODELS / "surplus_model.joblib"
    try:
        from sklearn.exceptions import InconsistentVersionWarning
    except ImportError:  # 아주 옛 버전
        InconsistentVersionWarning = UserWarning
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", InconsistentVersionWarning)
            return joblib.load(path)
    except Exception as e:
        print(f"[모델] 저장된 모델을 쓸 수 없어 다시 학습합니다: {type(e).__name__}")
        import train
        train.main()
        return joblib.load(path)


def forecast(start: str | None = None, days: int = MAX_HORIZON_DAYS, log: bool = True) -> pd.DataFrame:
    bundle = load_bundle()
    history = load_labels()
    start = start or str(date.today() + timedelta(days=1))
    frame = build_future_frame(start, days, history)
    frame["model_used"] = "calendar"
    frame["prob"] = bundle["models"]["calendar"].predict_proba(
        frame[bundle["feature_sets"]["calendar"]])[:, 1]
    if "full" in bundle["models"]:
        feats = bundle["feature_sets"]["full"]
        has_weather = frame[[c for c in feats if c.startswith("w_")]].notna().all(axis=1) \
            if any(c.startswith("w_") for c in feats) else pd.Series(False, index=frame.index)
        if has_weather.any():
            frame.loc[has_weather, "prob"] = bundle["models"]["full"].predict_proba(
                frame.loc[has_weather, feats])[:, 1]
            frame.loc[has_weather, "model_used"] = "full"
    frame["level"] = frame["prob"].map(level_of)
    out = frame[["date", "hour", "prob", "level", "model_used"]].copy()
    if log:
        _log(out)
    return out


def _log(fc: pd.DataFrame) -> None:
    rec = fc.assign(issued_at=datetime.now().isoformat(timespec="minutes"))
    rec["date"] = rec["date"].dt.strftime("%Y-%m-%d")
    header = not PREDICTION_LOG.exists()
    rec.to_csv(PREDICTION_LOG, mode="a", header=header, index=False, encoding="utf-8")


def summarize(fc: pd.DataFrame) -> pd.DataFrame:
    """날짜별 요약: 가장 가능성 높은 시각, 가능성 20% 이상 시간대, 사용 모델."""
    rows = []
    for d, g in fc.groupby("date"):
        best = g.sort_values("prob", ascending=False).iloc[0]
        likely = sorted(int(h) for h in g.loc[g["prob"] >= 0.2, "hour"])
        rows.append({"date": pd.Timestamp(d).strftime("%Y-%m-%d"),
                     "weekday": "월화수목금토일"[pd.Timestamp(d).day_of_week],
                     "max_prob": round(float(best["prob"]), 3), "best_hour": int(best["hour"]),
                     "likely_hours": likely, "level": level_of(float(best["prob"])),
                     "model_used": g["model_used"].iloc[0]})
    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default=None)
    parser.add_argument("--days", type=int, default=MAX_HORIZON_DAYS)
    args = parser.parse_args()
    print(summarize(forecast(args.start, args.days)).to_string(index=False))


if __name__ == "__main__":
    main()
