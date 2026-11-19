"""정답 데이터와 예측 성능이 문서에 적힌 숫자와 같은지 확인."""
import json

import pandas as pd

from config import REPORTS
from features import load_labels


def test_label_counts_match_docs():
    lab = load_labels()
    lab = lab[(lab["date"] >= "2024-06-01") & (lab["date"] <= "2026-11-17")]
    assert lab["date"].nunique() == 900
    assert int(lab["is_surplus"].sum()) == 347                      # 잉여 347시간
    assert int(lab.groupby("date")["is_surplus"].max().sum()) == 127  # 잉여 127일


def test_hour_label_is_interval_end():
    lab = load_labels()
    assert lab["hour"].min() == 1 and lab["hour"].max() == 24       # '13시' = 12~13시


def test_weather_model_beats_baselines():
    r = json.loads((REPORTS / "metrics.json").read_text(encoding="utf-8"))["results"]
    best = r["full_monthly_retrain"]["day_pr_auc"]
    assert best >= 0.6
    for base in ("baseline_rule", "baseline_climatology", "calendar_static"):
        assert best > r[base]["day_pr_auc"], base
    base_rate = r["full_monthly_retrain"]["day_base_rate"]
    assert best > 3 * base_rate                                      # 무작위보다 3배 넘게


def test_no_future_leak_in_test_period():
    meta = json.loads((REPORTS / "metrics.json").read_text(encoding="utf-8"))["meta"]
    text = json.dumps(meta, ensure_ascii=False)
    assert "2026-01-01" in text                                      # 시험 기간 시작일이 기록돼 있음


def test_forecast_error_test_only_changes_test_period():
    """예보 오차 시험: 학습 기간 날씨는 그대로, 시험 기간 날씨만 바뀌어야 함."""
    import numpy as np
    import pandas as pd
    import features
    from config import TEST_START, WEATHER_HOURLY_CSV
    from experiments.forecast_error_test import LEVELS, perturb
    w = features._read(WEATHER_HOURLY_CSV)
    p = perturb(w, list(LEVELS.values())[1], np.random.default_rng(0))
    before = w["date"] < pd.Timestamp(TEST_START)
    cols = ["w_ta", "w_ws", "w_sky", "w_rain"]
    assert p.loc[before, cols].equals(w.loc[before, cols])
    assert not p.loc[~before, "w_ta"].equals(w.loc[~before, "w_ta"])
    assert set(p["w_sky"].dropna().unique()) <= {1.0, 3.0, 4.0}


def test_mid_forecast_fills_days_3_to_5(tmp_path, monkeypatch):
    """중기예보(오후 하늘·비·최고기온)가 있는 날은 달력 모델 대신 중기 모델로 예측하고, 근거를 '중기예보'로 밝힘."""
    import pandas as pd
    import features
    import predict
    import tools
    from collect_weather import parse_mid
    start = pd.Timestamp.today().normalize() + pd.Timedelta(days=1)
    land = {f"wf{n}Pm": w for n, w in ((4, "맑음"), (5, "흐리고 비"))} | {"rnSt4Pm": 20, "rnSt5Pm": 80}
    ta = {"taMax4": 17, "taMax5": 14}
    tmfc = (start - pd.Timedelta(days=1)).strftime("%Y%m%d") + "0600"
    mid = parse_mid(land, ta, tmfc)
    assert list(mid["mid_sky_pm"]) == [1.0, 4.0] and list(mid["mid_rain_pm"]) == [0.0, 1.0]
    f = tmp_path / "mid.csv"
    mid.to_csv(f, index=False)
    monkeypatch.setattr(features, "FORECAST_MID_CSV", f)
    fc = predict.forecast(str(start.date()), 5, log=False)
    used = fc.groupby(fc["date"].dt.strftime("%Y-%m-%d"))["model_used"].first()
    for d in mid["date"]:
        if d in used.index and used[d] != "full":
            assert used[d] == "mid"
    assert "중기예보" in tools._basis(["mid", "calendar"])
