"""제주 잉여전력 도우미 — 화면 (Streamlit)

    streamlit run app.py
"""
from __future__ import annotations

import os

import pandas as pd
import streamlit as st

from agent import ask, llm_status
from calendar_link import google_url, ics_bytes, pick_window
from tools import PLACE_COORDS
import user_profile as up
from collect_weather import refresh_forecast_if_stale
from tools import charger_places, data_status, explain_surplus, forecast_surplus, map_points
from nearby_map import nearby_map_html
import streamlit.components.v1 as components

# 클라우드(Streamlit Community Cloud)에서는 키를 .env 대신 앱 설정의 Secrets 에 넣음 → 환경변수로 옮김
try:
    for _k in ("DATA_GO_KR_KEY", "KMA_APIHUB_KEY", "LLM_PROVIDER", "LLM_API_KEY", "LLM_MODEL", "KAKAO_JS_KEY"):
        if _k in st.secrets and not os.environ.get(_k):
            os.environ[_k] = str(st.secrets[_k])
except Exception:   # Secrets 파일이 없는 PC 실행이면 .env 를 씀
    pass

st.set_page_config(page_title="제주 잉여전력 도우미", page_icon="⚡", layout="centered")
st.markdown("""<style>
html, body, [class*="css"] { font-size: 19px; }
.big { font-size: 1.35rem; font-weight: 700; }
.card { border-radius: 14px; padding: 12px 10px; text-align: center; color: #1b1b1b; }
</style>""", unsafe_allow_html=True)

st.title("⚡ 제주 잉여전력 도우미")
st.caption("제주 재생에너지가 남는 시간을 미리 알려 드려요. 그 시간에 전기를 쓰면 버려질 전기를 살릴 수 있어요.")

# 예보가 4시간보다 오래됐으면 새로 받음 (기상청 단기예보는 하루 8번 발표). 30분 동안은 다시 확인하지 않음.
@st.cache_data(ttl=1800, show_spinner="최신 기상청 예보를 확인하고 있어요...")
def _refresh_forecast() -> dict:
    return refresh_forecast_if_stale()


fresh = _refresh_forecast()
if fresh["status"] == "failed":
    st.warning("최신 기상청 예보를 받지 못해 저장된 예보로 안내합니다. 잠시 뒤 새로고침해 주세요."
               + (f" (저장된 예보 발표: {fresh['issued_at']})" if fresh.get("issued_at") else ""))
status = data_status()
if status["mode"].startswith("저장"):
    st.info(f"실시간 예보가 연결되지 않아 저장된 데이터로 안내합니다. ({status['mode']})")

# ---------------------------------------------------------------- 내 정보 (주소창에 담아 즐겨찾기로 다시 불러옴)
if "profile" not in st.session_state:
    try:
        st.session_state.profile = up.from_query({k: st.query_params.get(k) for k in ("area", "car", "ws", "we", "tou")})
    except Exception:
        st.session_state.profile = up.empty()
profile = st.session_state.profile

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

# ---------------------------------------------------------------- 지도 (팀원 B 대시보드의 지도 아이디어)
@st.cache_data(ttl=86400, show_spinner=False)
def _map_points(quick_only: bool) -> pd.DataFrame:
    return map_points(quick_only)


@st.cache_data(ttl=86400, show_spinner=False)
def _nearby_data():
    from config import DATA
    g = charger_places()
    wf = DATA / "grid_raw" / "jeju_wind_farms_approx.csv"
    w = pd.read_csv(wf).rename(columns={"lat_approx": "lat", "lon_approx": "lon", "설비용량_MW": "mw"}) if wf.exists() else None
    return g, w


def _all_map():
    quick_only = st.toggle("급속 충전소만 보기", value=False)
    pts = _map_points(quick_only)
    if len(pts):
        st.map(pts, latitude="lat", longitude="lon", color="color", size="size", zoom=9)
        n = pts["종류"].value_counts()
        st.caption(f"🔵 급속 충전소 {n.get('급속 충전소', 0):,}곳 · ⚪ 완속 충전소 {n.get('완속 충전소', 0):,}곳 · "
                   f"🟠 풍력발전소 {n.get('풍력발전소', 0)}곳(원 크기 = 설비용량, 위치는 리 단위 대략값) · "
                   "출처: 제주데이터허브 862, 제주특별자치도 풍력발전현황(허브 472)")
    else:
        st.info("지도에 표시할 데이터가 없어요.")


with st.expander("🗺️ 지도로 보기 — 내 주변 충전소와 풍력발전소", expanded=False):
    tab_me, tab_all = st.tabs(["📍 내 주변 (길찾기)", "🗺️ 제주 전체"])
    with tab_me:
        g, w = _nearby_data()
        home = None
        if profile.get("area") in PLACE_COORDS:
            lat, lon = PLACE_COORDS[profile["area"]]
            home = {"name": profile["area"], "lat": lat, "lon": lon}
        if len(g):
            try:
                from config import get_key
                components.html(nearby_map_html(g, w, home, kakao_key=get_key("KAKAO_JS_KEY")), height=780, scrolling=True)
            except Exception:   # Streamlit 버전이 바뀌어 HTML 지도를 못 그려도 목록과 길찾기는 보여 줌
                if home:
                    from tools import find_chargers
                    near = find_chargers(home["name"], limit=5)["chargers"]
                    st.markdown("**내 동네(" + home["name"] + ") 가까운 충전소**\n" + "\n".join(
                        f"- {c['name']} ({c.get('distance_km', 0):.1f}km) — [여기까지 길찾기]({c['route_link']})" for c in near))
                else:
                    st.info("'👤 내 정보'에 동네를 저장하면 가까운 충전소와 길찾기를 보여 드려요.")
            st.caption("📍 위치는 이 화면(브라우저) 안에서만 쓰고 서버로 보내거나 저장하지 않아요. "
                       "위치를 허용하지 않으면 '👤 내 정보'에 저장한 동네 기준으로 보여 드려요. "
                       "'여기까지 길찾기'를 누르면 카카오맵이 지금 위치에서 길을 안내해요.")
        else:
            st.info("충전소 데이터(허브 862)가 없어 내 주변 지도를 그릴 수 없어요.")
    with tab_all:
        _all_map()


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
        # 앞 질문·답변을 함께 넘겨 이어지는 질문과 '지금까지 정리해줘'를 이해
        res = ask(question, [(q, r["answer"]) for q, r in st.session_state.history], profile)
    st.session_state.history.append((question, res))

for i, (q, res) in enumerate(st.session_state.history):
    with st.chat_message("user"):
        st.write(q)
    with st.chat_message("assistant"):
        # 마크다운에서 '~' 두 개가 취소선으로 바뀌는 것을 막음
        st.markdown(res["answer"].replace("~", "～"))
        # 추천 시간대를 휴대폰 캘린더에 넣기 (10분 전 알림)
        win = pick_window(res["trace"])
        if win:
            st.caption(f"📅 {win['date'][5:].replace('-', '/')} {win['time_text']} — 캘린더에 넣으면 10분 전에 알려 줘요")
            c1, c2 = st.columns(2)
            c1.link_button("구글 캘린더에 넣기", google_url(win), use_container_width=True)
            c2.download_button("아이폰·아웃룩 (.ics)", ics_bytes(win), file_name=f"jeju_surplus_{win['date']}.ics",
                               mime="text/calendar", key=f"ics_{i}", use_container_width=True)
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
                    cdf = pd.DataFrame(r["chargers"])
                    if {"lat", "lon"} <= set(cdf.columns):
                        mp = cdf[["lat", "lon"]].assign(color=cdf["has_quick"].map({True: "#2a78d6", False: "#9a9a96"}),
                                                         size=40.0)
                        if r.get("center"):
                            mp = pd.concat([mp, pd.DataFrame([{**r["center"], "color": "#eb6834", "size": 70.0}])],
                                           ignore_index=True)
                        st.map(mp, latitude="lat", longitude="lon", color="color", size="size", zoom=13)
                        st.caption("🔵 급속 있음 · ⚪ 완속만 · 🟠 찾은 동네 중심")
                    show = cdf.drop(columns=[c for c in ("lat", "lon", "has_quick") if c in cdf.columns]).rename(
                        columns={"name": "충전소", "quick_count": "급속", "slow_count": "완속", "distance_km": "거리(km)",
                                 "map_link": "위치", "route_link": "길찾기"})
                    # 좁은 화면에서도 거리·길찾기가 먼저 보이도록 순서를 정함
                    order = [c for c in ("충전소", "거리(km)", "길찾기", "급속", "완속", "위치") if c in show.columns]
                    show = show[order + [c for c in show.columns if c not in order]]
                    st.dataframe(show, hide_index=True, column_config={
                        "위치": st.column_config.LinkColumn("위치", display_text="카카오맵 열기"),
                        "길찾기": st.column_config.LinkColumn("길찾기", display_text="내 위치에서 길찾기")})
                elif t["tool"] == "grid_records" and "curtailment" in r:
                    h = pd.Series(r["curtailment"]["wind_mwh_by_hour"]).rename(index=lambda x: f"{int(x):02d}시")
                    st.bar_chart(h, y_label="풍력 출력제어량(MWh)")
                    d = r["demand_hvdc"]
                    st.dataframe(pd.DataFrame({"낮 전력수요(MW)": d["midday_demand_mw"],
                                               "육지에서 받는 전기(MW)": d["midday_hvdc_import_mw"]}))
                elif t["tool"] == "llm_error":
                    st.warning("AI(LLM) 연결 오류 — 그래서 규칙 기반으로 답했어요: " + str(r.get("error", "")))
                elif t["tool"] == "plan_appliance_use" and (r.get("alternatives") or r.get("best_windows")):
                    w = pd.DataFrame(r.get("alternatives") or r["best_windows"])
                    w = w.rename(columns={"date": "날짜", "weekday": "요일", "time_text": "시간대",
                                          "avg_prob": "남을 가능성", "level": "등급", "basis": "근거"})
                    st.dataframe(w[["날짜", "요일", "시간대", "남을 가능성", "등급", "근거"]], hide_index=True)
                    if r.get("ev"):
                        st.caption(f"계산: {r['ev']['battery_note']}, {r['ev']['assumption']} → {r['ev']['kwh']}kWh")
                elif t["tool"] == "check_past_forecast" and r.get("days"):
                    st.dataframe(pd.DataFrame(r["days"]), hide_index=True)
                st.caption("출처: " + ", ".join(map(str, r.get("sources", []))))

with st.sidebar:
    with st.expander("👤 내 정보 (한 번 넣으면 질문마다 반영)", expanded=not up.is_set(profile)):
        places = ["선택 안 함"] + [p for p in PLACE_COORDS if p not in ("공항", "시청", "터미널", "도청")]
        cars = list(up.CARS)
        with st.form("profile_form"):
            area = st.selectbox("사는 동네", places, index=places.index(profile["area"]) if profile["area"] in places else 0)
            car_label = next((k for k, v in up.CARS.items() if v == profile["car"]), cars[0])
            car = st.selectbox("전기차", cars, index=cars.index(car_label))
            work = st.checkbox("평일에 출근해요", value=profile["work_start"] is not None)
            hrs = list(range(0, 25))
            cs, ce = st.columns(2)
            ws = cs.selectbox("나가는 시각", hrs, index=profile["work_start"] if profile["work_start"] is not None else 9,
                              format_func=lambda h: f"{h}시")
            we = ce.selectbox("돌아오는 시각", hrs, index=profile["work_end"] if profile["work_end"] is not None else 18,
                              format_func=lambda h: f"{h}시")
            tou = st.radio("계시별(시간대별) 요금제", up.TOU, index=up.TOU.index(profile["tou"]), horizontal=True)
            if st.form_submit_button("저장", use_container_width=True):
                new = up.empty()
                new["area"] = "" if area == "선택 안 함" else area
                new["car"] = up.CARS[car]
                if work and ws < we:
                    new["work_start"], new["work_end"] = int(ws), int(we)
                new["tou"] = tou
                st.session_state.profile = new
                try:
                    st.query_params.from_dict(up.to_query(new))
                except Exception:
                    pass
                st.rerun()
        if up.is_set(profile):
            st.caption("저장됨: " + up.summary(profile))
            st.caption("이 페이지 주소를 즐겨찾기하면 다음에도 내 정보가 그대로 불러와져요. "
                       "이름·연락처는 받지 않아요.")
    st.subheader("데이터 상태")
    for k, v in status["available"].items():
        st.write(("✅ " if v else "⬜ ") + k)
    st.caption("허브 = 제주데이터허브 (대회 필수 데이터)")
    _ls = llm_status()
    st.caption(("🟢 " if _ls["on"] else "⚪ ") + _ls["text"])
    if fresh.get("issued_at"):
        st.caption(f"기상청 단기예보 발표: {fresh['issued_at']}"
                   + (" (방금 새로 받음)" if fresh["status"] == "updated" else ""))
