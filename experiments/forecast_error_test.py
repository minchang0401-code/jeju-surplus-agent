"""예보 날씨 오차 시험 — '관측 날씨로 학습한 모델에 예보(틀릴 수 있는 날씨)를 넣으면 성능이 얼마나 떨어지나?'

실제 서비스는 기상청 단기예보를 넣지만, 과거 예보 기록이 없어 시험 기간(2026-01-01~)의 관측 날씨에
예보만큼의 오차를 일부러 섞어 다시 채점합니다. 학습은 관측 날씨 그대로(실제 서비스와 같음).

오차 3단계 (하루 단위로 같은 방향으로 틀리게 = 예보 오차는 하루 내내 이어지는 경향)
- 기온: 기상청 공개 '월별 예보평가'의 최고기온 평균절대오차 1.0~1.7℃(2025.10~2026.9)에 맞춰
  평균절대오차 1.0 / 1.5 / 2.0℃ (정규분포 σ = 평균절대오차 × 1.25)
- 풍속·하늘상태·비: 공개 정확도 수치를 찾지 못해 가정값 (아래 LEVELS)
각 단계를 서로 다른 난수로 20번 반복해 평균과 범위를 냅니다.

    python experiments/forecast_error_test.py
→ reports/forecast_error_test.md, reports/figures/report_7_forecast_error.png
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import features  # noqa: E402
from config import REPORTS, TEST_START, WEATHER_HOURLY_CSV  # noqa: E402
from train import evaluate, new_model  # noqa: E402

LEVELS = {
    # 이름: (기온 평균절대오차 ℃, 풍속 오차 σ m/s, 하늘상태가 한 단계 틀릴 확률, 비 여부가 틀릴 확률)
    "작음 (내일 예보 수준)": (1.0, 0.8, 0.15, 0.08),
    "보통 (2~3일 뒤 예보 수준)": (1.5, 1.2, 0.30, 0.15),
    "큼 (4~5일 뒤 예보 수준)": (2.0, 1.8, 0.45, 0.25),
}
REPEAT = 20
SKY = [1.0, 3.0, 4.0]   # 맑음·구름많음·흐림


def perturb(w: pd.DataFrame, level: tuple, rng: np.random.Generator) -> pd.DataFrame:
    """시험 기간 날짜의 날씨만 틀리게 만듦 (학습 기간은 그대로)."""
    t_mae, ws_sd, p_sky, p_rain = level
    out = w.copy()
    test = out["date"] >= pd.Timestamp(TEST_START)
    days = out.loc[test, "date"].unique()
    n = len(days)
    t_err = pd.Series(rng.normal(0, t_mae * 1.25, n), index=days)
    ws_err = pd.Series(rng.normal(0, ws_sd, n), index=days)
    sky_shift = pd.Series(np.where(rng.random(n) < p_sky, rng.choice([-1, 1], n), 0), index=days)
    rain_flip = pd.Series(rng.random(n) < p_rain, index=days)
    d = out.loc[test, "date"]
    out.loc[test, "w_ta"] = out.loc[test, "w_ta"] + d.map(t_err).to_numpy() + rng.normal(0, 0.5, test.sum())
    out.loc[test, "w_ws"] = (out.loc[test, "w_ws"] + d.map(ws_err).to_numpy() + rng.normal(0, 0.4, test.sum())).clip(lower=0)
    # 하늘상태: 맑음↔구름많음↔흐림 한 단계 이동
    idx = out.loc[test, "w_sky"].map({1.0: 0, 3.0: 1, 4.0: 2}).fillna(1).astype(int).to_numpy()
    idx = np.clip(idx + d.map(sky_shift).to_numpy(), 0, 2)
    out.loc[test, "w_sky"] = np.array(SKY)[idx]
    # 비: 틀린 날은 비 온 날 → 안 옴, 안 온 날 → 오후 3시간 비
    flip_rows = test & out["date"].map(rain_flip).fillna(False).astype(bool)
    rainy_day = out.groupby("date")["w_rain"].transform("max") > 0
    out.loc[flip_rows & rainy_day, ["w_rain", "w_rn"]] = 0
    add = flip_rows & ~rainy_day & out["hour"].between(13, 15)
    out.loc[add, "w_rain"], out.loc[add, "w_rn"] = 1, 1.0
    return out


def build(w: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    real = features._read

    def fake(path):
        return w.copy() if Path(path) == Path(WEATHER_HOURLY_CSV) else real(path)

    features._read = fake
    try:
        table, sets = features.build_table()
    finally:
        features._read = real
    return table.dropna(subset=["recent_surplus_days"]).reset_index(drop=True), sets


def main() -> None:
    w0 = features._read(WEATHER_HOURLY_CSV)
    table, sets = build(w0)
    train = table[table["date"] < TEST_START]
    test = table[table["date"] >= TEST_START]
    y = test["is_surplus"].to_numpy()
    feats = sets["full"]
    model = new_model().fit(train[feats], train["is_surplus"])   # 관측 날씨로 학습 (서비스와 같음)
    cal = new_model().fit(train[sets["calendar"]], train["is_surplus"])
    thr = 0.2
    rows = [("관측 날씨 그대로 (오차 0, 지금까지 보고한 값)", evaluate(y, model.predict_proba(test[feats])[:, 1], test, thr), None)]
    rng = np.random.default_rng(2026)
    for name, lv in LEVELS.items():
        rs = []
        for _ in range(REPEAT):
            tb, _ = build(perturb(w0, lv, rng))
            te = tb[tb["date"] >= TEST_START]
            assert (te["is_surplus"].to_numpy() == y).all()
            rs.append(evaluate(y, model.predict_proba(te[feats])[:, 1], te, thr))
        mean = {k: float(np.mean([r[k] for r in rs])) for k in ("day_pr_auc", "hour_pr_auc", "day_precision", "day_recall")}
        rng_ = (min(r["day_pr_auc"] for r in rs), max(r["day_pr_auc"] for r in rs))
        rows.append((name, mean, rng_))
    rows.append(("날씨 없이 (달력·최근 경향만, 가장 나쁜 경우)", evaluate(y, cal.predict_proba(test[sets["calendar"]])[:, 1], test, thr), None))

    base = rows[0][1]["day_pr_auc"]
    lines = ["# 예보 날씨 오차 시험", "",
             f"- 시험 기간: {TEST_START} ~ {test['date'].max():%Y-%m-%d} (잉여일 {int(test.groupby('date')['is_surplus'].max().sum())}일)",
             "- 학습: 시험 기간 전의 관측 날씨로 한 번 (고정 학습). 시험: 시험 기간 날씨에만 오차를 넣음",
             f"- 각 오차 단계는 {REPEAT}번 반복한 평균 (괄호 = 날짜 PR-AUC 최소~최대). 기준값 0.2(보통 이상)로 정밀도·재현율 계산",
             "- 무작위로 찍었을 때 날짜 정밀도(잉여일 비율): 0.165", "",
             "| 넣은 날씨 | 날짜 PR-AUC | 오차 0 대비 | 시간 PR-AUC | 날짜 정밀도 | 날짜 재현율 |", "|---|---|---|---|---|---|"]
    for name, m, r in rows:
        rr = f" ({r[0]:.3f}~{r[1]:.3f})" if r else ""
        lines.append(f"| {name} | {m['day_pr_auc']:.3f}{rr} | {m['day_pr_auc'] / base:.0%} | {m['hour_pr_auc']:.3f} | "
                     f"{m['day_precision'] or 0:.3f} | {m['day_recall'] or 0:.3f} |")
    lines += ["", "오차 단계 (하루 단위로 같은 방향으로 틀림)", "",
              "| 단계 | 기온 평균절대오차 | 풍속 오차(표준편차) | 하늘상태 한 단계 틀림 | 비 여부 틀림 |", "|---|---|---|---|---|"]
    for name, (t, ws, ps, pr) in LEVELS.items():
        lines.append(f"| {name} | {t}℃ | {ws}m/s | {ps:.0%}의 날 | {pr:.0%}의 날 |")
    lines += ["", "- 기온 오차는 기상청 '월별 예보평가'(최고기온 예보 평균절대오차 1.0~1.7℃, 2025.10~2026.9, 전국)에 맞췄습니다.",
              "- 풍속·하늘상태·비 오차는 공개 수치를 찾지 못해 가정한 값입니다.",
              "- 실제 예보 성적은 화면이 낸 예보를 `data/forecast_log.csv`에 2026-11-19부터 쌓아 '지난 예보 맞았어?'로 확인합니다."]
    (REPORTS / "forecast_error_test.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib import font_manager
        for f in ("Noto Sans CJK KR", "AppleGothic", "Malgun Gothic", "NanumGothic"):
            if any(f in x.name for x in font_manager.fontManager.ttflist):
                plt.rcParams["font.family"] = f
                break
        names = ["오차 0\n(관측)", "작음\n(내일)", "보통\n(2~3일 뒤)", "큼\n(4~5일 뒤)", "날씨 없이"]
        vals = [r[1]["day_pr_auc"] for r in rows]
        lo = [vals[i] - (rows[i][2][0] if rows[i][2] else vals[i]) for i in range(len(rows))]
        hi = [(rows[i][2][1] if rows[i][2] else vals[i]) - vals[i] for i in range(len(rows))]
        colors = ["#2a78d6", "#5b98e0", "#8db8ea", "#bcd5f2", "#c3ccd3"]
        fig, ax = plt.subplots(figsize=(7.2, 3.6), dpi=160)
        ax.bar(names, vals, color=colors, width=0.62)
        err = [i for i in range(len(rows)) if rows[i][2]]
        ax.errorbar(err, [vals[i] for i in err], yerr=[[lo[i] for i in err], [hi[i] for i in err]],
                    fmt="none", ecolor="#15211d", capsize=4, lw=1.2)
        for i, v in enumerate(vals):
            ax.text(i, v * 0.62, f"{v:.2f}", ha="center", va="center", fontsize=11, fontweight="bold",
                    color="white" if i < 2 else "#15211d")
        ax.axhline(0.165, ls="--", color="#9aa8a2", lw=1)
        ax.text(3.5, 0.18, "무작위\n0.165", ha="center", va="bottom", fontsize=8, color="#6b7671")
        ax.set_ylabel("날짜 PR-AUC")
        ax.set_ylim(0, max(vals) + 0.12)
        ax.set_title("예보가 틀려도 성능은 얼마나 유지될까 (시험 기간 2026.1~11)", fontsize=11)
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
        fig.tight_layout()
        out = REPORTS / "figures" / "report_7_forecast_error.png"
        fig.savefig(out)
        print(out)
    except ImportError:
        pass


if __name__ == "__main__":
    main()
