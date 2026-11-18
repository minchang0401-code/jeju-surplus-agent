"""기획서용 그래프 4장 → reports/figures/*.png

    python experiments/make_figures.py
"""
import sys
sys.path.insert(0, ".")
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
import numpy as np
import pandas as pd

import features as F
import train as T

OUT = Path("reports/figures")
OUT.mkdir(parents=True, exist_ok=True)

# 한글 글꼴 (없으면 기본 글꼴)
for name in ("Noto Sans CJK KR", "NanumGothic", "Malgun Gothic", "AppleGothic"):
    if any(name in f.name for f in font_manager.fontManager.ttflist):
        plt.rcParams["font.family"] = name
        break
plt.rcParams["axes.unicode_minus"] = False

SURFACE, INK, INK2, MUTED, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#e1e0d9"
BLUE, ORANGE = "#2a78d6", "#eb6834"
SEQ = ["#fcfcfb", "#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]


def style(ax):
    ax.set_facecolor(SURFACE)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(GRID)
    ax.tick_params(colors=INK2, labelsize=10)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def fig(w=9, h=4.6):
    f, ax = plt.subplots(figsize=(w, h), dpi=200)
    f.patch.set_facecolor(SURFACE)
    style(ax)
    return f, ax


def title(f, main, sub):
    f.text(0.01, 0.98, main, fontsize=14, fontweight="bold", color=INK, va="top")
    f.text(0.01, 0.91, sub, fontsize=10, color=INK2, va="top")


lab = F.load_labels()
period = f"{lab['date'].min():%Y.%m.%d}~{lab['date'].max():%Y.%m.%d}"

# ---------------------------------------------------------------- 1. 월 × 시각 잉여 시간
grid = (lab.assign(m=lab["date"].dt.month).pivot_table(index="m", columns="hour", values="is_surplus", aggfunc="sum")
        .reindex(index=range(1, 13), columns=range(1, 25)).fillna(0))
f, ax = fig(10, 5.2)
ax.grid(False)
cmap = matplotlib.colors.ListedColormap(SEQ)
bounds = [0, 0.5, 1.5, 3.5, 6.5, 10.5, 15.5, 25.5, 100]
norm = matplotlib.colors.BoundaryNorm(bounds, cmap.N)
im = ax.imshow(grid.values, cmap=cmap, norm=norm, aspect="auto")
ax.set_xticks(range(24), [f"{h}" for h in range(1, 25)], fontsize=9)
ax.set_yticks(range(12), [f"{m}월" for m in range(1, 13)])
ax.set_xlabel("시각 (전력거래소 표기: 13시 = 12~13시)", color=INK2, fontsize=10)
for (i, j), v in np.ndenumerate(grid.values):
    if v >= 10:
        ax.text(j, i, int(v), ha="center", va="center", fontsize=8, color="white" if v >= 16 else INK)
cb = f.colorbar(im, ax=ax, fraction=0.03, pad=0.02, ticks=[0, 1, 3, 6, 10, 15, 25])
cb.outline.set_visible(False)
title(f, "제주 잉여전력은 봄(3~5월)과 가을(10~11월)의 한낮(11~15시)에 몰립니다",
      f"제주 SMP 0원 이하 시간 수, 월×시각 합계 ({period}, 전력거래소 EPSIS)")
f.subplots_adjust(top=0.84, left=0.07, right=0.97, bottom=0.12)
f.savefig(OUT / "fig1_month_hour.png", facecolor=SURFACE)

# ---------------------------------------------------------------- 2. 월별 잉여일 비율
day = lab.groupby("date")["is_surplus"].max()
rate = day.groupby(day.index.month).mean() * 100
f, ax = fig()
bars = ax.bar([f"{m}월" for m in rate.index], rate.values, color=BLUE, width=0.62, edgecolor=SURFACE, linewidth=2)
for b, v in zip(bars, rate.values):
    if v >= 20 or v == 0:
        ax.text(b.get_x() + b.get_width() / 2, v + 1, f"{v:.0f}%", ha="center", fontsize=9, color=INK2)
ax.set_ylabel("잉여가 생긴 날의 비율(%)", color=INK2)
title(f, "3월은 절반 가까운 날에 잉여전력이 생기고, 6~9월은 거의 없습니다",
      f"월별 '하루 중 한 시간이라도 SMP 0원 이하'인 날의 비율 ({period}, EPSIS)")
f.subplots_adjust(top=0.82, left=0.08, right=0.98, bottom=0.1)
f.savefig(OUT / "fig2_month_rate.png", facecolor=SURFACE)

# ---------------------------------------------------------------- 3. 날씨 × 휴일
lines = Path("experiments/openmeteo_daily.txt").read_text(encoding="utf-8").splitlines()
start = [l for l in lines if l.startswith("START")][0].split()[1]
W = pd.DataFrame([list(map(float, x.split(","))) for x in lines[-1].split(";")],
                 columns=["rad", "cloud", "wind_mid", "wind_night", "temp", "rain"])
W["date"] = pd.date_range(start, periods=len(W))
cal = F.add_calendar(lab.drop_duplicates("date")[["date"]].assign(hour=13))
d = pd.DataFrame({"date": day.index, "y": day.values}).merge(W, on="date").merge(cal[["date", "month", "is_offday"]], on="date")
d = d[~d["month"].isin([6, 7, 8, 9])]
d["sky"] = pd.cut(d["cloud"], [-1, 3, 7, 10], labels=["맑음", "구름 조금·많음", "흐림"])
tab = d.groupby(["sky", "is_offday"], observed=True)["y"].agg(["mean", "size"]).reset_index()
f, ax = fig()
x = np.arange(3)
for k, (off, color, name) in enumerate([(0, BLUE, "평일"), (1, ORANGE, "주말·공휴일")]):
    sub = tab[tab["is_offday"] == off].set_index("sky").reindex(["맑음", "구름 조금·많음", "흐림"])
    bars = ax.bar(x + (k - 0.5) * 0.36, sub["mean"] * 100, width=0.34, color=color, label=name,
                  edgecolor=SURFACE, linewidth=2)
    for b, v, n in zip(bars, sub["mean"] * 100, sub["size"]):
        ax.text(b.get_x() + b.get_width() / 2, v + 1, f"{v:.0f}%\n({n}일)", ha="center", fontsize=9, color=INK2)
ax.set_xticks(x, ["맑음\n(구름 0~3)", "구름\n(4~7)", "흐림\n(8~10)"])
ax.set_ylabel("잉여가 생긴 날의 비율(%)", color=INK2)
ax.set_ylim(0, 85)
ax.legend(frameon=False, loc="upper right", fontsize=10, labelcolor=INK)
title(f, "맑은 주말·공휴일 한낮이면 3일 중 2일꼴로 잉여전력이 생깁니다",
      "6~9월 제외, 한낮(10~14시) 구름양별 잉여일 비율 (날씨: Open-Meteo 재분석 · 실험용, 잉여: EPSIS)")
f.subplots_adjust(top=0.82, left=0.08, right=0.98, bottom=0.14)
f.savefig(OUT / "fig3_weather_offday.png", facecolor=SURFACE)

# ---------------------------------------------------------------- 4. 모델 비교
t = F.add_recent_trend(F.add_calendar(lab), lab).merge(
    W.rename(columns={c: "om_" + c for c in ["rad", "cloud", "wind_mid", "wind_night", "temp", "rain"]}), on="date", how="left")
t = t.dropna(subset=["recent_surplus_days"]).reset_index(drop=True)
t["sky"] = pd.cut(t["om_cloud"], [-1, 5, 8, 10], labels=[1, 3, 4]).astype(float)
t["rain_flag"] = (t["om_rain"] >= 1).astype(int)
tr, te = t[t.date < T.TEST_START], t[t.date >= T.TEST_START]
y = te["is_surplus"].to_numpy()
base = F.CALENDAR_FEATURES + F.TREND_FEATURES
def day_pr(cols):
    p = T.new_model().fit(tr[cols], tr["is_surplus"]).predict_proba(te[cols])[:, 1]
    return T.evaluate(y, p, te, 0.3)["day_pr_auc"]
rows = [
    ("단순 규칙 (6~9월 제외 12~14시)", T.evaluate(y, T.baseline_rule(te), te, 0.5)["day_pr_auc"], False),
    ("과거 비율 (월·시각·휴일)", T.evaluate(y, T.baseline_climatology(tr, te), te, 0.3)["day_pr_auc"], False),
    ("1차 모델 (달력·최근 경향)", day_pr(base), False),
    ("+ 날씨: 단기예보에 있는 변수만", day_pr(base + ["sky", "om_temp", "om_wind_mid", "om_wind_night", "rain_flag"]), True),
    ("+ 날씨: 일사량 포함 전체", day_pr(base + ["om_rad", "om_cloud", "om_wind_mid", "om_wind_night", "om_temp", "om_rain"]), True),
]
f, ax = fig(9, 4.4)
ax.grid(axis="y", visible=False)
ax.grid(axis="x", color=GRID, linewidth=0.8)
names = [r[0] for r in rows][::-1]
vals = [r[1] for r in rows][::-1]
exp = [r[2] for r in rows][::-1]
bars = ax.barh(names, vals, color=[BLUE if not e else "#86b6ef" for e in exp], height=0.55,
               edgecolor=[SURFACE if not e else BLUE for e in exp], linewidth=1.2,
               hatch=[None if not e else "///" for e in exp])
for b, v in zip(bars, vals):
    ax.text(v + 0.01, b.get_y() + b.get_height() / 2, f"{v:.2f}", va="center", fontsize=10, color=INK)
base_rate = te.groupby("date")["is_surplus"].max().mean()
ax.axvline(base_rate, color=MUTED, linestyle="--", linewidth=1)
ax.text(base_rate + 0.005, 4.45, f"무작위 수준 {base_rate:.2f}", fontsize=9, color=MUTED, va="bottom")
ax.set_xlim(0, 0.8)
ax.set_xlabel("날짜 단위 PR-AUC (1에 가까울수록 좋음)", color=INK2)
title(f, "날씨를 붙이면 '잉여가 생길 날' 예측이 크게 좋아집니다",
      "2026.1.1~11.16 시험 기간(학습에 미사용). 빗금 = 실제 관측 날씨를 쓴 실험값 — 예보를 쓰면 더 낮아질 수 있음")
f.subplots_adjust(top=0.82, left=0.30, right=0.97, bottom=0.14)
f.savefig(OUT / "fig4_model_comparison.png", facecolor=SURFACE)
print("저장:", sorted(p.name for p in OUT.glob("*.png")))
