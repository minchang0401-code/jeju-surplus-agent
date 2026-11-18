"""결과 설명자료용 그림 (모두 실제 대회 데이터·결과 파일로 그림).

    python experiments/make_report_figures.py

결과: reports/figures/report_*.png
- report_1_architecture.png  Agent 구조도
- report_2_when.png           월별 잉여일 비율 · 시각별 잉여 시간 (EPSIS)
- report_3_models.png         예측 방법별 성능 (reports/metrics.json)
- report_4_ev_vs_surplus.png  도민 충전 시작 시각 vs 잉여 시간 (허브 1226 · EPSIS)
- report_6_grid.png           출력제어 시간 vs 잉여 시간, 잉여 날의 낮 수요·연계선 (한국전력거래소 · EPSIS)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.patches import FancyBboxPatch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import pandas as pd  # noqa: E402

from features import load_labels  # noqa: E402

OUT = ROOT / "reports" / "figures"
OUT.mkdir(parents=True, exist_ok=True)

# ---- 글꼴·색 (밝은 배경 1종, 검증한 2색: 파랑=우리 모델/잉여, 주황=비교 대상/도민 행동)
for name in ("Noto Sans CJK KR", "AppleGothic", "Malgun Gothic", "NanumGothic"):
    if any(name in f.name for f in font_manager.fontManager.ttflist):
        plt.rcParams["font.family"] = name
        break
plt.rcParams["axes.unicode_minus"] = False
SURFACE, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
BLUE, ORANGE, GRAY = "#2a78d6", "#eb6834", "#b9b8b1"


def style(ax):
    ax.set_facecolor(SURFACE)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(colors=INK2, length=0, labelsize=10)
    ax.yaxis.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def title(fig, main, sub):
    fig.text(0.02, 0.965, main, fontsize=14, fontweight="bold", color=INK, va="top")
    fig.text(0.02, 0.905, sub, fontsize=9.5, color=INK2, va="top")


# ------------------------------------------------------------------ 1. 구조도
def fig_architecture():
    fig = plt.figure(figsize=(11, 5.6), facecolor=SURFACE)
    ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, 110); ax.set_ylim(0, 56); ax.axis("off")

    def box(x, y, w, h, head, body, edge=GRAY, fill="#ffffff"):
        ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.4,rounding_size=1.2",
                                    linewidth=1.2, edgecolor=edge, facecolor=fill))
        ax.text(x + 1.2, y + h - 1.6, head, fontsize=10.5, fontweight="bold", color=INK, va="top")
        ax.text(x + 1.2, y + h - 5.0, body, fontsize=8.6, color=INK2, va="top", linespacing=1.45)

    def arrow(x1, y1, x2, y2):
        ax.annotate("", xy=(x2, y2), xytext=(x1, y1),
                    arrowprops=dict(arrowstyle="-|>", color=INK2, linewidth=1.2, mutation_scale=12))

    ax.text(1.5, 54, "제주 잉여전력 도우미 — Agent 구조", fontsize=14, fontweight="bold", color=INK, va="top")
    ax.text(1.5, 50.2, "LLM은 도구를 고르고 말로 정리만 한다. 숫자는 모두 도구(예측 모델·데이터)에서 나온다.",
            fontsize=9.5, color=INK2, va="top")
    # 데이터
    box(1.5, 27, 25, 19, "데이터", "EPSIS 제주 시간별 SMP (정답)\n기상청 ASOS · 단기예보\n허브 579 일별 기상\n"
                                  "허브 862·1225·1226 (충전)\n허브 877·123·472 (기후·설비)")
    box(1.5, 4, 25, 18, "예측 모델", "HistGradientBoosting\n달력 + 최근 경향 + 날씨\n→ 시간별 잉여 확률\n"
                                    "(오늘~5일 뒤, 날씨 반영 2~3일)", edge=BLUE)
    arrow(14, 27, 14, 22.6)
    # 도구
    box(32, 4, 30, 42, "도구 9개 (tools.py)", "① 잉여 예보\n② 가전·충전 추천 시간\n③ 동네 충전소 찾기\n"
                                             "④ 도민 충전 습관\n⑤ 잉여 원인 설명\n⑥ 지난 예보 검증\n⑦ 데이터 상태\n"
                                             "⑧ 도민이 얻는 것(솔직하게)\n⑨ 실천 방법", edge=BLUE)
    arrow(26.9, 36, 31.6, 36); arrow(26.9, 13, 31.6, 13)
    # LLM
    box(68, 24, 22, 22, "Gemini 3.5 Flash-Lite", "질문 이해 · 기간 해석\n도구 고르기(함수 호출)\n결과로만 답하기\n출처 한 줄 표시",
        edge=ORANGE, fill="#fff7f2")
    box(68, 4, 22, 15, "비상 모드 (규칙)", "키 없음·한도 초과·장애 시\n자동 전환, 같은 도구 사용")
    ax.annotate("", xy=(67.6, 35), xytext=(62.4, 35),
                arrowprops=dict(arrowstyle="<|-|>", color=INK2, linewidth=1.2, mutation_scale=12))
    ax.text(64.9, 36.6, "호출·결과", fontsize=8, color=INK2, ha="center")
    arrow(62.4, 11.5, 67.6, 11.5)
    # 화면
    box(95, 4, 13.5, 42, "화면", "5일 예보 카드\n빠른 질문\n대화창\n근거 보기\n(도구·입력·출처)\nAI 연결 상태\n예보 발표 시각")
    arrow(90.4, 35, 94.6, 35); arrow(90.4, 11.5, 94.6, 11.5)
    fig.savefig(OUT / "report_1_architecture.png", dpi=170, facecolor=SURFACE)
    plt.close(fig)


# ------------------------------------------------------------------ 2. 언제 남나
def fig_when():
    lab = load_labels()
    day = lab.groupby("date")["is_surplus"].max()
    month = day.groupby(day.index.month).mean() * 100
    hour = lab.groupby("hour")["is_surplus"].sum()
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(11, 4.4), facecolor=SURFACE,
                                 gridspec_kw={"width_ratios": [1, 1.25]})
    fig.subplots_adjust(top=0.78, bottom=0.13, left=0.06, right=0.98, wspace=0.18)
    title(fig, "제주 잉여전력은 봄·가을 한낮에 몰립니다",
          f"제주 SMP 0원 이하 = 잉여 · EPSIS {lab['date'].min():%Y.%m.%d}~{lab['date'].max():%Y.%m.%d} "
          f"({day.size}일, 잉여 {int(lab['is_surplus'].sum())}시간)")
    for ax in (a1, a2):
        style(ax)
    m = list(range(1, 13))
    vals = [month.get(i, 0) for i in m]
    a1.bar(m, vals, color=[BLUE if v >= 20 else GRAY for v in vals], width=0.68)
    a1.set_xticks(m, [f"{i}월" for i in m], fontsize=9)
    a1.set_title("월별: 잉여가 생긴 날의 비율(%)", fontsize=10.5, color=INK, loc="left")
    for i, v in zip(m, vals):
        if v >= 20:
            a1.text(i, v + 1.2, f"{v:.0f}%", ha="center", fontsize=8.5, color=INK)
    hs = list(range(1, 25))
    hv = [hour.get(h, 0) for h in hs]
    a2.bar(hs, hv, color=[BLUE if 11 <= h <= 15 else GRAY for h in hs], width=0.7)
    a2.set_xticks([3, 6, 9, 12, 15, 18, 21, 24], ["3시", "6시", "9시", "12시", "15시", "18시", "21시", "24시"], fontsize=9)
    a2.set_title("시각별: 잉여 시간 수 (시각 = 구간의 끝, 13시 = 12~13시)", fontsize=10.5, color=INK, loc="left")
    share = sum(hour.get(h, 0) for h in range(11, 16)) / hour.sum() * 100
    a2.text(16.2, max(hv) * 0.62, f"파란 막대(오전 10시~오후 3시)에\n잉여 시간의 {share:.0f}%", ha="left",
            fontsize=9.5, color=BLUE, fontweight="bold")
    fig.savefig(OUT / "report_2_when.png", dpi=170, facecolor=SURFACE)
    plt.close(fig)


# ------------------------------------------------------------------ 3. 모델 성능
def fig_models():
    r = json.loads((ROOT / "reports" / "metrics.json").read_text(encoding="utf-8"))["results"]
    rows = [("단순 규칙\n(6~9월 제외 12~14시)", "baseline_rule"), ("과거 비율\n(월·시각·휴일)", "baseline_climatology"),
            ("1차 모델\n(달력·최근 경향)", "calendar_static"), ("날씨 모델\n(고정 학습)", "full_static"),
            ("날씨 모델\n(월별 재학습)", "full_monthly_retrain")]
    fig, ax = plt.subplots(figsize=(11, 4.6), facecolor=SURFACE)
    fig.subplots_adjust(top=0.78, bottom=0.2, left=0.06, right=0.98)
    style(ax)
    base = r["full_static"]["day_base_rate"]
    title(fig, "날씨를 넣자 '잉여가 생길 날' 예측이 크게 좋아졌습니다",
          "시험 기간 2026.01.01~11.17 (학습에 쓰지 않음) · PR-AUC: 드문 사건을 골라내는 능력, 1에 가까울수록 좋음 · "
          "주의: 날씨 모델은 관측 날씨 기준")
    x = range(len(rows))
    w = 0.36
    day = [r[k]["day_pr_auc"] for _, k in rows]
    hour = [r[k]["hour_pr_auc"] for _, k in rows]
    cols = [BLUE if "full" in k else GRAY for _, k in rows]
    ax.bar([i - w / 2 - 0.01 for i in x], day, width=w, color=cols)
    ax.bar([i + w / 2 + 0.01 for i in x], hour, width=w, color=cols, alpha=0.55)
    for i, (d, h) in enumerate(zip(day, hour)):
        ax.text(i - w / 2 - 0.01, d + 0.015, f"{d:.2f}", ha="center", fontsize=9, color=INK)
        ax.text(i + w / 2 + 0.01, h + 0.015, f"{h:.2f}", ha="center", fontsize=9, color=INK2)
    ax.axhline(base, color=ORANGE, linewidth=1.2, linestyle=(0, (4, 3)))
    ax.text(-0.45, 0.665, f"주황 점선 = 무작위로 찍었을 때의 날짜 정밀도 {base:.3f}", ha="left", fontsize=9, color=ORANGE)
    ax.set_xticks(list(x), [n for n, _ in rows], fontsize=9.5)
    ax.set_ylim(0, 0.75)
    ax.text(-0.45, 0.71, "막대 두 개씩: 왼쪽(진한 색) = 날짜 단위, 오른쪽(옅은 색) = 시간 단위", fontsize=9, color=INK2)
    fig.savefig(OUT / "report_3_models.png", dpi=170, facecolor=SURFACE)
    plt.close(fig)


# ------------------------------------------------------------------ 4. 충전 vs 잉여
def fig_ev():
    c = pd.read_csv(ROOT / "data" / "hub" / "1226_ev_charging_month.csv")
    c["h"] = pd.to_numeric(c["chargingStartHour"], errors="coerce")
    cnt = c.groupby("h")["chargingCount"].sum()
    ev = (cnt / cnt.sum() * 100).reindex(range(24), fill_value=0)
    lab = load_labels()
    # 잉여 시각(구간의 끝) → 그 구간이 시작하는 시각으로 맞춤 (13시 라벨 = 12시대)
    sur = lab[lab["is_surplus"] == 1].groupby(lab["hour"] - 1).size()
    sur = (sur / sur.sum() * 100).reindex(range(24), fill_value=0)
    fig, ax = plt.subplots(figsize=(11, 4.5), facecolor=SURFACE)
    fig.subplots_adjust(top=0.78, bottom=0.13, left=0.06, right=0.98)
    style(ax)
    period = f"{str(int(c['baseYearMonth'].min()))[:4]}.{str(int(c['baseYearMonth'].min()))[4:]}~" \
             f"{str(int(c['baseYearMonth'].max()))[4:]}월"
    title(fig, "전기가 남는 시간과 도민이 충전하는 시간이 어긋납니다",
          f"허브 1226 제주 공용 충전 이력 {period} {int(cnt.sum()):,}회 vs EPSIS 잉여 시간 (시작 시각 기준, 각각 전체 = 100%)")
    hrs = list(range(24))
    ax.axvspan(15.5, 21.5, color=ORANGE, alpha=0.07)
    ax.text(18.5, max(sur.max(), ev.max()) * 0.97, "저녁 4~10시\n(계시별 요금 최대부하)", ha="center", fontsize=8.5, color=ORANGE)
    ax.plot(hrs, sur.values, color=BLUE, linewidth=2, marker="o", markersize=4)
    ax.plot(hrs, ev.values, color=ORANGE, linewidth=2, marker="o", markersize=4)
    ax.text(12.6, sur.max(), "잉여 시간", color=BLUE, fontsize=10, fontweight="bold")
    peak = int(ev.idxmax())
    ax.text(peak + 0.3, ev.max() + 0.6, f"충전 시작 ({peak}시 최다)", color=ORANGE, fontsize=10, fontweight="bold")
    ax.set_xticks(range(0, 24, 3), [f"{h}시" for h in range(0, 24, 3)])
    ax.set_ylabel("비중(%)", color=INK2, fontsize=9)
    fig.savefig(OUT / "report_4_ev_vs_surplus.png", dpi=170, facecolor=SURFACE)
    plt.close(fig)


# ------------------------------------------------------------------ 6. 전력 계통 기록 (팀원 B 데이터)
def fig_grid():
    import grid
    g = grid.grid_stats()
    lab = load_labels()
    hs = list(range(1, 25))
    smp = lab.groupby("hour")["is_surplus"].sum().reindex(hs, fill_value=0)
    wind = pd.Series(g["curtailment"]["wind_mwh_by_hour"]).reindex(hs, fill_value=0)
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(11, 4.4), facecolor=SURFACE, gridspec_kw={"width_ratios": [1.35, 1]})
    fig.subplots_adjust(top=0.78, bottom=0.13, left=0.06, right=0.98, wspace=0.22)
    title(fig, "실제로 전기가 버려진 시간과 우리 정답(SMP 0원 이하) 시간이 겹칩니다",
          "왼쪽: 풍력 출력제어량(2021.1~2024.5, 한국전력거래소) vs SMP 0원 이하 시간(2024.6~2026.11, EPSIS) · "
          "오른쪽: 낮 11시~오후 2시 평균(2026.1~9)")
    for ax in (a1, a2):
        style(ax)
    a1.plot(hs, smp / smp.sum() * 100, color=BLUE, linewidth=2, marker="o", markersize=4)
    a1.plot(hs, wind / wind.sum() * 100, color=ORANGE, linewidth=2, marker="o", markersize=4)
    a1.text(15.6, (smp / smp.sum() * 100).max() * 0.92, "SMP 0원 이하 시간", color=BLUE, fontsize=9.5, fontweight="bold")
    a1.text(15.6, (wind / wind.sum() * 100).max() * 0.62, f"풍력 출력제어량\n(모두 {g['curtailment']['wind_mwh_total']:,}MWh)",
            color=ORANGE, fontsize=9.5, fontweight="bold")
    a1.set_xticks([3, 6, 9, 12, 15, 18, 21, 24], ["3시", "6시", "9시", "12시", "15시", "18시", "21시", "24시"], fontsize=9)
    a1.set_title("시각별 비중(%) (시각 = 구간의 끝)", fontsize=10.5, color=INK, loc="left")
    d = g["demand_hvdc"]
    cats = ["전력수요", "육지에서 받는 전기\n(연계선 HVDC)"]
    sur = [d["midday_demand_mw"]["잉여 있는 날"], d["midday_hvdc_import_mw"]["잉여 있는 날"]]
    oth = [d["midday_demand_mw"]["다른 날"], d["midday_hvdc_import_mw"]["다른 날"]]
    x = [0, 1]
    a2.bar([i - 0.19 for i in x], sur, width=0.36, color=BLUE)
    a2.bar([i + 0.19 for i in x], oth, width=0.36, color=GRAY)
    for i in x:
        a2.text(i - 0.19, sur[i] + 12, f"{sur[i]}", ha="center", fontsize=9, color=INK)
        a2.text(i + 0.19, oth[i] + 12, f"{oth[i]}", ha="center", fontsize=9, color=INK)
    a2.set_xticks(x, cats, fontsize=9.5)
    a2.set_title(f"MW · 파랑 = 잉여 있는 날({d['days_surplus']}일), 회색 = 다른 날({d['days_other']}일)",
                 fontsize=10.5, color=INK, loc="left")
    fig.savefig(OUT / "report_6_grid.png", dpi=170, facecolor=SURFACE)
    plt.close(fig)


if __name__ == "__main__":
    fig_architecture(); fig_when(); fig_models(); fig_ev(); fig_grid()
    print("저장:", ", ".join(p.name for p in sorted(OUT.glob("report_*.png"))))
