"""제주 잉여전력 도우미 — 화면 (Streamlit)

    streamlit run app.py
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from agent import ask
from tools import data_status, explain_surplus, forecast_surplus

st.set_page_config(page_title="제주 잉여전력 도우미", page_icon="⚡", layout="centered")
st.markdown("""<style>
html, body, [class*="css"] { font-size: 19px; }
.big { font-size: 1.35rem; font-weight: 700; }
.card { border-radius: 14px; padding: 12px 10px; text-align: center; color: #1b1b1b; }
</style>""", unsafe_allow_html=True)

st.title("⚡ 제주 잉여전력 도우미")
st.caption("제주 재생에너지가 남는 시간을 미리 알려 드려요. 그 시간에 전기를 쓰면 버려질 전기를 살릴 수 있어요.")

status = data_status()
if status["mode"].startswith("저장"):
    st.info(f"실시간 예보가 연결되지 않아 저장된 데이터로 안내합니다. ({status['mode']})")

# ---------------------------------------------------------------- 5일 예보 달력
COLORS = {"높음": "#ffd166", "보통": "#cdeac0", "낮음": "#e9ecef"}
try:
    fc = forecast_surplus(5)
    cols = st.columns(len(fc["forecast"]))
    for col, d in zip(cols, fc["forecast"]):
        with col:
            st.markdown(
                f"<div class='card' style='background:{COLORS[d['level']]}'>"
                f"<div>{d['date'][5:]} ({d['weekday']})</div>"
                f"<div class='big'>{d['level']}</div>"
                f"<div style='font-size:0.85rem'>{d['likely_time_text'] if d['likely_hours'] else '-'}</div>"
                f"</div>", unsafe_allow_html=True)
    st.caption("노란색일수록 재생에너지가 남을 가능성이 높아요. · " + fc["note"] + " · 출처: " + ", ".join(fc["sources"]))
except FileNotFoundError:
    st.error("학습된 모델이 없습니다. 먼저 `python train.py` 를 실행하세요.")

# ---------------------------------------------------------------- 대화
st.divider()
if "history" not in st.session_state:
    st.session_state.history = []

quick = st.columns(3)
preset = None
if quick[0].button("이번 주 언제가 좋아?", use_container_width=True):
    preset = "이번 주에 빨래랑 식기세척기 언제 돌리면 좋아?"
if quick[1].button("전기차 충전", use_container_width=True):
    preset = "이번 주에 전기차 충전은 언제 어디서 하면 좋아?"
if quick[2].button("왜 생기는 거야?", use_container_width=True):
    preset = "잉여전력이 왜 생기는 거야?"

question = st.chat_input("궁금한 것을 물어보세요 (예: 토요일에 노형동에서 충전하려는데?)") or preset
if question:
    with st.spinner("데이터를 확인하고 있어요..."):
        res = ask(question)
    st.session_state.history.append((question, res))

for q, res in st.session_state.history:
    with st.chat_message("user"):
        st.write(q)
    with st.chat_message("assistant"):
        # 마크다운에서 '~' 두 개가 취소선으로 바뀌는 것을 막음
        st.markdown(res["answer"].replace("~", "～"))
        with st.expander("근거 보기 (사용한 도구와 데이터)"):
            st.caption("응답 방식: " + ("AI(LLM)" if res["mode"] == "llm" else "규칙 기반(비상 모드)"))
            for t in res["trace"]:
                st.markdown(f"**{t['tool']}** · 입력 `{t['args']}`")
                r = t["result"]
                if t["tool"] == "explain_surplus" and "surplus_day_rate_by_month" in r:
                    m = pd.Series(r["surplus_day_rate_by_month"]).rename(index=lambda x: f"{x}월")
                    st.bar_chart(m, y_label="잉여일 비율")
                    h = pd.Series(r["surplus_hours_by_hour"]).rename(index=lambda x: f"{x:02d}시")
                    st.bar_chart(h, y_label="잉여 시간 수")
                elif t["tool"] == "ev_charging_habits" and "charging_start_share" in r:
                    both = pd.DataFrame({"도민 충전 시작 비중": pd.Series(r["charging_start_share"]),
                                         "잉여 시간 비중": pd.Series(r["surplus_hour_share"])}).fillna(0)
                    st.line_chart(both)
                elif t["tool"] == "find_chargers" and r.get("chargers"):
                    st.dataframe(pd.DataFrame(r["chargers"]), hide_index=True)
                elif t["tool"] == "check_past_forecast" and r.get("days"):
                    st.dataframe(pd.DataFrame(r["days"]), hide_index=True)
                st.caption("출처: " + ", ".join(map(str, r.get("sources", []))))

with st.sidebar:
    st.subheader("데이터 상태")
    for k, v in status["available"].items():
        st.write(("✅ " if v else "⬜ ") + k)
    st.caption("허브 = 제주데이터허브 (대회 필수 데이터)")
