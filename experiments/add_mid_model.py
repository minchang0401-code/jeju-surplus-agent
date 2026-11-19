"""중기 모델(3~5일 뒤용)만 학습해 기존 모델 묶음에 더합니다. 다른 모델과 이미 낸 성능 숫자는 그대로 둡니다.
(처음부터 다시 만들 때는 python train.py 한 번이면 중기 모델까지 함께 학습·평가됩니다.)

    python experiments/add_mid_model.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import joblib
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import DATA, MODELS, REPORTS, TEST_START  # noqa: E402
from features import build_table  # noqa: E402
from train import evaluate, new_model, walk_forward, write_report  # noqa: E402


def main() -> None:
    table, sets = build_table()
    table = table.dropna(subset=["recent_surplus_days"]).reset_index(drop=True)
    feats = sets["mid"]
    train, test = table[table["date"] < TEST_START], table[table["date"] >= TEST_START]
    y = test["is_surplus"].to_numpy()
    bundle = joblib.load(MODELS / "surplus_model.joblib")
    thr = bundle["thresholds"].get("full", 0.2)
    static = new_model().fit(train[feats], train["is_surplus"]).predict_proba(test[feats])[:, 1]
    rolling = walk_forward(table, feats)
    metrics = json.loads((REPORTS / "metrics.json").read_text(encoding="utf-8"))
    metrics["results"]["mid_static"] = evaluate(y, static, test, thr)
    metrics["results"]["mid_monthly_retrain"] = evaluate(y, rolling, test, thr)
    metrics["meta"]["feature_sets"]["mid"] = feats
    bundle["models"]["mid"] = new_model().fit(table[feats], table["is_surplus"])
    bundle["feature_sets"]["mid"] = feats
    bundle["thresholds"]["mid"] = thr
    bundle["meta"]["feature_sets"]["mid"] = feats
    joblib.dump(bundle, MODELS / "surplus_model.joblib")
    (REPORTS / "metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    bt = pd.read_csv(DATA / "backtest_predictions.csv", parse_dates=["date"])
    bt = bt.merge(test[["date", "hour"]].assign(p_mid=rolling), on=["date", "hour"], how="left")
    bt.to_csv(DATA / "backtest_predictions.csv", index=False, encoding="utf-8-sig")
    write_report(metrics["meta"], metrics["results"], bt)
    for k in ("mid_static", "mid_monthly_retrain"):
        r = metrics["results"][k]
        print(k, f"날짜 PR-AUC {r['day_pr_auc']:.3f}, 날짜 정밀도 {r['day_precision']:.3f}, 시간 PR-AUC {r['hour_pr_auc']:.3f}")


if __name__ == "__main__":
    main()
