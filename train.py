"""잉여전력 시간 예측 모델 학습·평가.

    python train.py

1) 평가 (2026년 = 시험 기간, 학습에 쓰지 않음)
   - 고정 평가: 2025년까지로 한 번 학습 → 2026년 예측
   - 월별 재학습 평가: 2026년 각 달마다, 그 달 시작 5일 전까지의 데이터로 다시 학습 → 그 달 예측
     (실제 서비스처럼 '최신 데이터로 계속 다시 학습'할 때의 성능)
   - 기준선 2개(과거 비율, 단순 규칙)와 비교
2) 서비스용 모델: 모든 기간으로 다시 학습해 저장
   - calendar: 달력·최근 경향만 (예보가 없는 날짜용, 항상 학습)
   - full: + 날씨·허브 일별 기상 (날씨 파일이 있을 때만)
결과: models/surplus_model.joblib, reports/metrics.json, reports/report.md,
      data/backtest_predictions.csv (월별 재학습 평가의 날짜·시간별 예측 → 예보 검증 도구가 사용)
"""
from __future__ import annotations

import json
from datetime import datetime

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import average_precision_score, brier_score_loss

from config import DATA, MAX_HORIZON_DAYS, MODELS, REPORTS, TEST_START
from features import build_table

MODEL_PARAMS = dict(max_iter=300, learning_rate=0.05, max_leaf_nodes=15,
                    min_samples_leaf=120, l2_regularization=1.0, random_state=42)


def new_model() -> HistGradientBoostingClassifier:
    return HistGradientBoostingClassifier(**MODEL_PARAMS)


# ---------------------------------------------------------------- 기준선
def baseline_climatology(train: pd.DataFrame, test: pd.DataFrame) -> np.ndarray:
    keys = ["month", "hour", "is_offday"]
    rate = train.groupby(keys)["is_surplus"].mean()
    fallback = train.groupby(["month", "hour"])["is_surplus"].mean()
    p = pd.Series(test.set_index(keys).index.map(rate), index=test.index, dtype=float)
    fb = pd.Series(test.set_index(["month", "hour"]).index.map(fallback), index=test.index, dtype=float)
    return p.fillna(fb).fillna(0.0).to_numpy()


def baseline_rule(test: pd.DataFrame) -> np.ndarray:
    """6~9월을 빼고 12~14시이면 잉여로 보는 단순 규칙."""
    return ((~test["month"].isin([6, 7, 8, 9])) & test["hour"].between(12, 14)).astype(float).to_numpy()


# ---------------------------------------------------------------- 평가
def _pr(y, p, thr):
    pred = p >= thr
    tp, fp, fn = int((pred & (y == 1)).sum()), int((pred & (y == 0)).sum()), int((~pred & (y == 1)).sum())
    return (tp / (tp + fp) if tp + fp else None, tp / (tp + fn) if tp + fn else None)


def evaluate(y: np.ndarray, p: np.ndarray, frame: pd.DataFrame, thr: float) -> dict:
    hp, hr = _pr(y, p, thr)
    day = frame.assign(p=p, y=y).groupby("date").agg(y=("y", "max"), p=("p", "max"))
    dp, dr = _pr(day["y"].to_numpy(), day["p"].to_numpy(), thr)
    base_rate = float(day["y"].mean())
    return {
        "hour_pr_auc": float(average_precision_score(y, p)) if y.sum() else None,
        "hour_brier": float(brier_score_loss(y, np.clip(p, 0, 1))),
        "hour_precision": hp, "hour_recall": hr,
        "day_pr_auc": float(average_precision_score(day["y"], day["p"])) if day["y"].sum() else None,
        "day_precision": dp, "day_recall": dr,
        "day_base_rate": base_rate,
        "threshold": thr, "days": int(len(day)), "surplus_days": int(day["y"].sum()),
    }


def best_threshold(y: np.ndarray, p: np.ndarray) -> float:
    best, best_f1 = 0.5, -1.0
    for t in np.linspace(0.05, 0.9, 35):
        prec, rec = _pr(y, p, t)
        prec, rec = prec or 0.0, rec or 0.0
        f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
        if f1 > best_f1:
            best, best_f1 = float(t), f1
    return best


def walk_forward(table: pd.DataFrame, feats: list[str]) -> np.ndarray:
    test = table[table["date"] >= TEST_START]
    preds = pd.Series(index=test.index, dtype=float)
    for month in sorted(test["date"].dt.to_period("M").unique()):
        idx = test.index[test["date"].dt.to_period("M") == month]
        cutoff = month.start_time - pd.Timedelta(days=MAX_HORIZON_DAYS)
        train = table[table["date"] < cutoff]
        model = new_model().fit(train[feats], train["is_surplus"])
        preds[idx] = model.predict_proba(test.loc[idx, feats])[:, 1]
    return preds.to_numpy()


# ---------------------------------------------------------------- 메인
def main() -> None:
    table, sets = build_table()
    table = table.dropna(subset=["recent_surplus_days"]).reset_index(drop=True)
    train = table[table["date"] < TEST_START]
    test = table[table["date"] >= TEST_START]
    y = test["is_surplus"].to_numpy()

    results: dict[str, dict] = {}
    thresholds: dict[str, float] = {}
    backtest = test[["date", "hour", "is_surplus"]].copy()
    for name, feats in sets.items():
        # 기준값: 학습 기간 안의 마지막 25%를 검증 구간으로 써서 결정 (시험 기간은 보지 않음)
        split = train["date"].quantile(0.75)
        inner = new_model().fit(train.loc[train["date"] < split, feats],
                                train.loc[train["date"] < split, "is_surplus"])
        val = train[train["date"] >= split]
        thr = best_threshold(val["is_surplus"].to_numpy(), inner.predict_proba(val[feats])[:, 1])
        thresholds[name] = thr

        static = new_model().fit(train[feats], train["is_surplus"]).predict_proba(test[feats])[:, 1]
        rolling = walk_forward(table, feats)
        results[f"{name}_static"] = evaluate(y, static, test, thr)
        results[f"{name}_monthly_retrain"] = evaluate(y, rolling, test, thr)
        backtest[f"p_{name}"] = rolling

    results["baseline_climatology"] = evaluate(y, baseline_climatology(train, test), test, thresholds["calendar"])
    results["baseline_rule"] = evaluate(y, baseline_rule(test), test, 0.5)

    # 서비스용: 전체 기간으로 학습
    models = {name: new_model().fit(table[feats], table["is_surplus"]) for name, feats in sets.items()}
    meta = {
        "trained_at": datetime.now().isoformat(timespec="seconds"),
        "label_source": table.attrs.get("source", ""),
        "feature_sets": sets,
        "data_period": [str(table["date"].min().date()), str(table["date"].max().date())],
        "test_period": [str(test["date"].min().date()), str(test["date"].max().date())],
        "total_surplus_hours": int(table["is_surplus"].sum()),
        "test_surplus_hours": int(y.sum()),
        "thresholds": thresholds,
        "model_params": MODEL_PARAMS,
    }
    MODELS.mkdir(exist_ok=True)
    REPORTS.mkdir(exist_ok=True)
    joblib.dump({"models": models, "feature_sets": sets, "thresholds": thresholds, "meta": meta},
                MODELS / "surplus_model.joblib")
    backtest.to_csv(DATA / "backtest_predictions.csv", index=False, encoding="utf-8-sig")
    (REPORTS / "metrics.json").write_text(
        json.dumps({"meta": meta, "results": results}, ensure_ascii=False, indent=2), encoding="utf-8")
    write_report(meta, results, backtest)
    print((REPORTS / "report.md").read_text(encoding="utf-8"))


def _f(v) -> str:
    return "-" if v is None else f"{v:.3f}"


NAMES = {
    "calendar_static": "1차 모델(달력·경향) · 고정 학습",
    "calendar_monthly_retrain": "1차 모델(달력·경향) · 월별 재학습",
    "full_static": "날씨 모델(+기상청·허브579) · 고정 학습",
    "full_monthly_retrain": "날씨 모델(+기상청·허브579) · 월별 재학습",
    "mid_static": "중기 모델(달력 + 오후 하늘·오후 비·최고기온) · 고정 학습",
    "mid_monthly_retrain": "중기 모델(달력 + 오후 하늘·오후 비·최고기온) · 월별 재학습",
    "baseline_climatology": "기준선: 과거 비율(월·시각·휴일)",
    "baseline_rule": "기준선: 단순 규칙(6~9월 제외 12~14시)",
}


def write_report(meta: dict, results: dict, backtest: pd.DataFrame) -> None:
    has_full = "full" in meta["feature_sets"]
    lines = [
        "# 제주 잉여전력 시간 예측 — 평가 결과", "",
        f"- 정답: EPSIS 제주 시간별 SMP 0원 이하 ({meta['label_source']})",
        f"- 데이터 기간: {meta['data_period'][0]} ~ {meta['data_period'][1]} "
        f"(잉여 {meta['total_surplus_hours']}시간)",
        f"- 시험 기간: {meta['test_period'][0]} ~ {meta['test_period'][1]} "
        f"(잉여 {meta['test_surplus_hours']}시간). 고정 학습은 이 기간을 전혀 보지 않고, "
        f"월별 재학습은 각 달 시작 {MAX_HORIZON_DAYS}일 전까지의 데이터만 씁니다.",
        f"- 날씨 변수: {'사용' if has_full else '아직 없음 (기상청·허브 키를 받은 뒤 추가)'}", "",
        "| 방법 | 날짜 PR-AUC | 날짜 정밀도 | 날짜 재현율 | 시간 PR-AUC | 시간 정밀도 | 시간 재현율 |",
        "|---|---|---|---|---|---|---|",
    ]
    for key, r in results.items():
        lines.append(f"| {NAMES.get(key, key)} | {_f(r['day_pr_auc'])} | {_f(r['day_precision'])} | "
                     f"{_f(r['day_recall'])} | {_f(r['hour_pr_auc'])} | {_f(r['hour_precision'])} | "
                     f"{_f(r['hour_recall'])} |")
    any_r = next(iter(results.values()))
    lines += [
        "", f"- 날짜 단위 = '그날 잉여 시간이 하나라도 있나'. 아무렇게나 찍었을 때의 정밀도(잉여일 비율)는 "
        f"{any_r['day_base_rate']:.3f} 입니다.",
        "- 정밀도 = 잉여라고 예측한 것 중 맞은 비율 / 재현율 = 실제 잉여 중 미리 잡은 비율",
        "- PR-AUC = 드문 사건을 얼마나 잘 골라내는지 (1에 가까울수록 좋음)", "",
        "## 월별 시험 결과 (월별 재학습)", "",
        "| 월 | 실제 잉여일 | 실제 잉여일의 평균 예측확률(1차) |" + (" 날씨 모델 |" if has_full else ""),
        "|---|---|---|" + ("---|" if has_full else ""),
    ]
    day = backtest.groupby("date").max(numeric_only=True)
    day["month"] = pd.to_datetime(day.index).to_period("M")
    for m, g in day.groupby("month"):
        hit = g[g["is_surplus"] == 1]
        p1 = f"{hit['p_calendar'].mean():.2f}" if len(hit) else "-"
        row = f"| {m} | {int(g['is_surplus'].sum())} | {p1} |"
        if has_full:
            row += f" {hit['p_full'].mean():.2f} |" if len(hit) else " - |"
        lines.append(row)
    (REPORTS / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
