"""화면용 데이터 정리(dashboard_view) 시험 — 키·인터넷 없이 실행."""
import pandas as pd

from dashboard_view import best_windows, hourly_frame, night_bands, prob_color, region_capacity


def _fake_fc():
    rows = []
    for d in ("2026-11-21", "2026-11-22"):
        for h in range(1, 25):
            p = 0.6 if (d == "2026-11-22" and h in (12, 13, 14)) else 0.05
            rows.append({"date": pd.Timestamp(d), "hour": h, "prob": p, "level": "높음" if p >= .5 else "낮음", "model_used": "full"})
    return pd.DataFrame(rows)


def test_hour_convention_and_windows():
    df = hourly_frame(_fake_fc())
    assert df.loc[df["hour"] == 13, "label"].iloc[0].endswith("12~13시")   # SMP 1~24 표기 = 구간 끝
    w = best_windows(df, hours=3, top=2)
    assert w[0]["text"] == "11/22(일) 11~14시" and abs(w[0]["prob"] - 0.6) < 1e-9


def test_night_bands_and_colors():
    nb = night_bands(hourly_frame(_fake_fc()))
    assert (nb["e"] > nb["s"]).all()
    assert prob_color(0)[:3] == [200, 208, 214] and len(prob_color(0.9)) == 4


def test_region_capacity():
    r = region_capacity()
    assert len(r) == 8 and {"solar_mw", "wind_mw", "total_mw"} <= set(r.columns)
    assert r["total_mw"].sum() >= 0
