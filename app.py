"""제주 잉여전력 도우미 — 화면 (Streamlit)

    streamlit run app.py

화면 구성: 왼쪽 = 예보 카드 · 지도 · 시간별 잉여 가능성 그래프 / 오른쪽 = 에이전트 대화 패널 / 오른쪽 맨 위 = 👤 내 정보(칸마다 바로 수정) / 사이드바 = 데이터 상태
"""
from __future__ import annotations

from time_utils import as_kst, now_kst, today_kst

import os
from pathlib import Path
from html import escape
from datetime import date

import altair as alt
import pandas as pd
import pydeck as pdk
import streamlit as st
import streamlit.components.v1 as components

from agent import ask, llm_status
from calendar_link import google_url, ics_bytes, pick_window
from collect_weather import refresh_forecast_if_stale
from dashboard_view import LEVEL_COLOR, best_windows, hourly_frame, night_bands, prob_color, region_capacity
import importlib
import nearby_map as _nearby_map
importlib.reload(_nearby_map)   # 지도 파일만 고쳐도 새로고침하면 바로 반영 (Streamlit 이 바뀐 모듈을 못 알아챌 때가 있음)
nearby_map_html = _nearby_map.nearby_map_html
from tools import PLACE_COORDS, charger_places, data_status, forecast_surplus
import user_profile as up

# 클라우드(Streamlit Community Cloud)에서는 키를 .env 대신 앱 설정의 Secrets 에 넣음 → 환경변수로 옮김
try:
    for _k in ("DATA_GO_KR_KEY", "KMA_APIHUB_KEY", "LLM_PROVIDER", "LLM_API_KEY", "LLM_MODEL", "KAKAO_JS_KEY"):
        if _k in st.secrets and not os.environ.get(_k):
            os.environ[_k] = str(st.secrets[_k])
except Exception:   # Secrets 파일이 없는 PC 실행이면 .env 를 씀
    pass

st.set_page_config(page_title="제주 잉여전력 도우미", page_icon="⚡", layout="wide", initial_sidebar_state="collapsed")


def _is_dark() -> bool:
    """오른쪽 위 ⋮ 메뉴의 Light/Dark 설정 (Streamlit 1.46+ st.context.theme). 모르면 밝은 화면으로 봄."""
    try:
        return getattr(st.context.theme, "type", "light") == "dark"
    except Exception:
        return False


DARK = _is_dark()
# 글자·패널 색: 다크 모드에서는 밝은 글자 + 어두운 반투명 패널 (색이 정해진 날짜 카드·알약은 어느 모드든 진한 글자 그대로)
INK = "#e8eeeb" if DARK else "#15211d"          # 그래프 위 글자·고른 시각 선
NIGHT = "#2a2f36" if DARK else "#f1f4f3"         # 그래프의 밤 배경
GUIDE = "#6f7c77" if DARK else "#9aa8a2"         # 20%·50% 점선
# 날짜 카드 배경: 다크 모드에서는 같은 등급 색을 어둡게 (낮음 진회색 · 보통 진초록 · 높음 진주황)
CARD_BG = {"높음": "#7a4a12", "보통": "#1f5c3f", "낮음": "#2b3137"} if DARK else LEVEL_COLOR
st.html(f"""<style>:root {{
  --ink: {'#e8eeeb' if DARK else '#1b1b1b'}; --ink2: {'#aab7b2' if DARK else '#5b6b66'};
  --ink-k: {'#cdd7d3' if DARK else '#3d4b46'}; --accent: {'#8ab8f0' if DARK else '#285b48'};
  --panel: {'rgba(255,255,255,.06)' if DARK else '#f7f8f5'}; --panel-border: {'rgba(255,255,255,.14)' if DARK else '#dfe3dd'};
  --myinfo: {'rgba(120,170,240,.08)' if DARK else '#fafbf8'}; --chip: {'rgba(255,255,255,.08)' if DARK else '#f4f7f6'};
  --header: {'rgba(14,17,23,.85)' if DARK else 'rgba(255,255,255,.85)'};
  --card-ink: {'#eef3f0' if DARK else '#1b1b1b'}; --card-ink2: {'#c3cfca' if DARK else '#33413c'};
  --card-border: {'rgba(255,255,255,.10)' if DARK else 'rgba(0,0,0,.05)'};
  --pill: {'#2b3137' if DARK else '#eef2f0'}; --pill-ink: {'#d6dfdb' if DARK else '#2d3b36'}; --pill-border: {'#3b434b' if DARK else '#dde4e0'};
  --ok: {'#1f4a36' if DARK else '#dff1e8'}; --ok-ink: {'#9fe0bf' if DARK else '#0d6b44'}; --ok-border: {'#2f6b4f' if DARK else '#a9dcc2'};
  --warn: {'#4a3a14' if DARK else '#fff4dc'}; --warn-ink: {'#f3cf7a' if DARK else '#8a5a00'}; --warn-border: {'#6b5520' if DARK else '#f2dcaa'};
}}</style>""")
st.html((Path(__file__).parent / 'main.css').read_text())


# 예보가 4시간보다 오래됐으면 새로 받음 (기상청 단기예보는 하루 8번 발표). 30분 동안은 다시 확인하지 않음.
def _forecast_stamp() -> str:
    """예보 파일(단기·중기)과 모델이 바뀐 시각. 그래프 캐시 열쇠에 넣어, 새 예보가 들어오면 카드와 그래프가 같은 값을 보이게 함."""
    from config import FORECAST_HOURLY_CSV, FORECAST_MID_CSV, MODELS
    fs = (FORECAST_HOURLY_CSV, FORECAST_MID_CSV, MODELS / "surplus_model.joblib")
    return "|".join(str(int(f.stat().st_mtime)) if f.exists() else "-" for f in fs)


@st.cache_data(ttl=1800, show_spinner="최신 기상청 예보를 확인하고 있어요...")
def _refresh_forecast(stamp: str = "") -> dict:
    """stamp(예보 파일이 바뀐 시각)가 다르면 다시 확인. 코드를 새로 올리면 저장소의 옛 예보 파일로 바뀌는데,
    그때 30분 캐시 때문에 '최신'이라고 착각하지 않게 함."""
    return refresh_forecast_if_stale()


@st.cache_data(ttl=1800, show_spinner=False)
def _hourly(today: str, stamp: str = "") -> pd.DataFrame:
    from predict import forecast
    from config import MAX_HORIZON_DAYS
    return hourly_frame(forecast(today, MAX_HORIZON_DAYS + 1, log=False))


@st.cache_data(ttl=86400, show_spinner=False)
def _regions() -> pd.DataFrame:
    return region_capacity()


@st.cache_data(ttl=86400, show_spinner=False)
def _kakao_key():
    from config import get_key
    return get_key("KAKAO_JS_KEY")


def _nearby_data():
    from config import DATA
    g = charger_places()
    wf = DATA / "grid_raw" / "jeju_wind_farms_approx.csv"
    w = pd.read_csv(wf).rename(columns={"lat_approx": "lat", "lon_approx": "lon", "설비용량_MW": "mw"}) if wf.exists() else None
    return g, w


if "profile" not in st.session_state:
    try:
        st.session_state.profile = up.from_query({k: st.query_params.get(k) for k in ("area", "car", "ws", "we", "tou")})
    except Exception:
        st.session_state.profile = up.empty()
profile = st.session_state.profile
if "history" not in st.session_state:
    st.session_state.history = []

from guest_session import ensure_guest_session, render_guest_controls
from onboarding import render_onboarding, sync_onboarding_preference

sync_onboarding_preference()
ensure_guest_session()

fresh = _refresh_forecast(_forecast_stamp())
status = data_status()
_ls = llm_status()

# ---------------------------------------------------------------- 머리말
_today = today_kst()
_weekday = '월화수목금토일'[_today.weekday()]
st.markdown(f"""<div class="app-masthead"><div><div class="app-eyebrow">제주 생활 에너지</div>
<h1>제주 잉여전력 도우미</h1><p>전기 쓸 시간을 고르고, 내 일정에 맞춰 계획하세요.</p></div>
<div class="app-dateline">{_today.month}월 {_today.day}일 {_weekday}요일<span>제주특별자치도</span></div></div>""", unsafe_allow_html=True)

with st.sidebar:
    render_guest_controls()
    if st.button("처음 이용 안내 다시 보기", key="reopen_onboarding"):
        st.session_state.onboarding_done = False
        st.session_state.onboarding_step = 0
        st.session_state.pop('onboarding_draft', None)
        st.session_state.onboarding_open = True
        st.rerun()


def _select_forecast_day(day):
    st.session_state.pending_forecast_day = day


def _graph_selection_changed():
    st.session_state.graph_selection_changed = True


def _hourly_chart(hourly, cur, wins, height: int) -> bool:
    """시간별 잉여 가능성 막대그래프 (밤은 회색 배경, 추천 3시간은 초록 띠, 고른 시각은 검은 선).
    그래프 아무 데나 누르면 그 시각이 골라짐(검은 선이 옮겨 가고 지도 색이 바뀜). 누르기를 못 쓰는 옛 Streamlit 이면 False."""
    night = night_bands(hourly)
    x = alt.X("ts:T", title=None, axis=alt.Axis(labelAngle=0, tickCount="day", grid=False, labelExpr=(
        "timeFormat(datum.value, '%-m/%-d') + ' (' + ['일','월','화','수','목','금','토'][day(datum.value)] + ')'")))
    y = alt.Y("prob:Q", title=None, scale=alt.Scale(domain=[0, max(0.6, float(hourly["prob"].max()) + .05)]),
              axis=alt.Axis(format="%"))
    bg = alt.Chart(night).mark_rect(color=NIGHT).encode(x="s:T", x2="e:T")
    top = max(0.6, float(hourly["prob"].max()) + .05)
    hd = hourly.assign(ts2=hourly["ts"] + pd.Timedelta(minutes=54), top=top)
    bars = alt.Chart(hd).mark_bar().encode(
        x=x, x2="ts2:T", y=y,
        color=alt.Color("level:N", scale=alt.Scale(domain=list(LEVEL_COLOR), range=["#f2a93b", "#3fb37c", "#c3ccd3"]),
                        legend=None))   # 색 = 등급(높음 주황·보통 초록·낮음 회색), 위 카드와 같은 색
    # 누르기 판: 시간마다 그래프 높이 전체를 덮는 투명 칸 → 막대가 낮아도 그 시각 어디를 눌러도 골라짐
    # 끌기: 누른 채 움직이는 동안은 점선(drag)만 브라우저 안에서 따라오고, 손을 떼면(pick) 그 시각으로 확정 → 지도 갱신
    drag = alt.selection_point(name="drag", fields=["label"], on="mousedown, mousemove[event.buttons > 0]",
                               nearest=True, clear="mouseup", empty=False)
    pick = alt.selection_point(name="pick", fields=["label"], on="mouseup", nearest=True, clear=False)
    hit = alt.Chart(hd).mark_bar(opacity=0.001, cursor="pointer").encode(
        x="ts:T", x2="ts2:T", y=alt.Y("top:Q", scale=alt.Scale(domain=[0, top])), y2=alt.datum(0),
        tooltip=[alt.Tooltip("label:N", title="시간"), alt.Tooltip("pct:Q", title="가능성(%)"),
                 alt.Tooltip("level:N", title="등급"), alt.Tooltip("basis:N", title="근거")]).add_params(drag, pick)
    drag_rule = alt.Chart(hd).mark_rule(color=INK, strokeWidth=2, strokeDash=[4, 3]).encode(x="ts:T").transform_filter(drag)
    drag_txt = alt.Chart(hd.assign(t=hd["label"] + " · " + hd["pct"].round().astype(int).astype(str) + "%")).mark_text(
        align="left", dx=5, dy=16, baseline="top", fontSize=12, color=INK).encode(
        x="ts:T", y=alt.value(0), text="t:N").transform_filter(drag)
    rules = alt.Chart(pd.DataFrame({"y": [0.2, 0.5]})).mark_rule(strokeDash=[4, 4], color=GUIDE).encode(y="y:Q")
    now_rule = alt.Chart(pd.DataFrame({"ts": [cur["ts"]]})).mark_rule(color=INK, strokeWidth=2).encode(x="ts:T")
    win_df = pd.DataFrame([{"s": v["start"], "e": v["end"]} for v in wins]) if wins else pd.DataFrame(columns=["s", "e"])
    win_rect = alt.Chart(win_df).mark_rect(color="#3fb37c", opacity=0.13).encode(x="s:T", x2="e:T")
    _late = cur["ts"] > hourly["ts"].min() + (hourly["ts"].max() - hourly["ts"].min()) * 0.8   # 오른쪽 끝이면 글을 선 왼쪽에
    _al, _dx = ("right", -5) if _late else ("left", 5)
    now_txt = alt.Chart(pd.DataFrame({"ts": [cur["ts"]], "t": [f"{cur['label']} · {cur['pct']:.0f}%"]})).mark_text(
        align=_al, dx=_dx, dy=2, baseline="top", fontSize=12, fontWeight="bold", color=INK).encode(
        x="ts:T", y=alt.value(0), text="t:N")
    chart = (bg + win_rect + bars + rules + now_rule + now_txt + drag_rule + drag_txt + hit).properties(height=height)
    try:
        st.altair_chart(chart, use_container_width=True, on_select=_graph_selection_changed, selection_mode="pick", key="hourpick")
        return True
    except TypeError:   # 누르기(on_select)를 모르는 옛 Streamlit
        st.altair_chart(chart, use_container_width=True)
        return False


def _html(h: str) -> None:
    """HTML 조각. st.html 은 마크다운 여백(아래쪽 음수 여백)이 없어 촘촘히 붙여도 겹치지 않음."""
    if hasattr(st, "html"):
        st.html(h)
    else:
        st.markdown(h, unsafe_allow_html=True)


def _surplus_pydeck(reg, q, w, cur, sel, height):
    """잉여 예보 지도 대체용(pydeck). HTML 지도를 못 그릴 때만 씀."""
    reg = reg.copy()
    reg["radius"] = 900 + reg["total_mw"].clip(lower=0) ** 0.5 * 430
    reg["color"] = [prob_color(cur["prob"])] * len(reg)
    reg["tip"] = [f"<b>{n}</b><br>태양광 {s_:.0f}MW · 풍력 {w_:.0f}MW<br>{sel} 잉여 가능성 {cur['pct']:.0f}% (섬 전체)"
                  for n, s_, w_ in zip(reg["name"], reg["solar_mw"], reg["wind_mw"])]
    q = q.assign(tip=[f"<b>{n}</b><br>급속 {int(a)}기" for n, a in zip(q["name"], q["quick_count"])])
    layers = [pdk.Layer("ScatterplotLayer", reg, get_position="[lon, lat]", get_radius="radius", get_fill_color="color",
                        get_line_color=[255, 255, 255], line_width_min_pixels=2, stroked=True, pickable=True),
              pdk.Layer("ScatterplotLayer", q, get_position="[lon, lat]", get_radius=260, get_fill_color=[42, 120, 214, 170],
                        pickable=True)]
    st.pydeck_chart(pdk.Deck(layers=layers, initial_view_state=pdk.ViewState(latitude=33.37, longitude=126.56, zoom=9.3),
                             tooltip={"html": "{tip}", "style": {"fontSize": "12px"}}, map_style=None),
                    height=height, use_container_width=True)


with st.container(key="workspace"):
    left, right = st.columns([0.68, 0.32], gap="large")

# ================================================================ 왼쪽: 예보 · 지도 · 그래프
with left:
    try:
        from config import MAX_HORIZON_DAYS
        fc = forecast_surplus(MAX_HORIZON_DAYS + 1, start=str(today_kst()))
        hourly = _hourly(str(today_kst()), _forecast_stamp())
    except FileNotFoundError:
        st.error("학습된 모델이 없습니다. 먼저 `python train.py` 를 실행하세요.")
        hourly = None

    MODES = ["전력 흐름", "충전소 찾기"]
    MAP_H = 440   # 기본값. 실제 높이는 CSS(--map-h)가 화면 높이에 맞춰 정함
    g, w = _nearby_data()

    if hourly is not None and len(hourly):
        # 추천·처음 고르는 시각은 아직 지나지 않은 시간에서만 (오후에 열면 오늘 낮은 이미 지났음)
        upcoming = hourly[hourly["ts"] >= pd.Timestamp(now_kst())]
        if upcoming.empty:
            upcoming = hourly
        wins = best_windows(upcoming, hours=3, top=3)
        default = upcoming.loc[upcoming["prob"].idxmax(), "label"]
        if st.session_state.pop('graph_selection_changed', False):
            rows = (st.session_state.get('hourpick') or {}).get('selection', {}).get('pick') or []
            if rows and rows[0].get('label') in set(hourly['label']):
                st.session_state.sel_label = rows[0]['label']
        pending_day = st.session_state.pop('pending_forecast_day', None)
        if pending_day:
            day_rows = upcoming[upcoming['ts'].dt.strftime('%Y-%m-%d') == pending_day]
            if not day_rows.empty:
                st.session_state.sel_label = day_rows.loc[day_rows['prob'].idxmax(), 'label']
        sel = st.session_state.get("sel_label") or st.session_state.get("sel_time") or default
        if sel not in set(hourly["label"]):
            sel = default
        cur = hourly[hourly["label"] == sel].iloc[0]
        selected_upcoming = upcoming[upcoming['ts'].dt.date == cur['ts'].date()]
        wins = best_windows(selected_upcoming, hours=3, top=3)
    else:
        wins, cur, sel = [], None, None

    st.markdown('<div class="section-label">날짜 선택 <span>오늘부터 5일 뒤까지 살펴볼 수 있어요</span></div>', unsafe_allow_html=True)
    if hourly is not None and len(hourly):
        with st.container(key='forecast_dates'):
            dates = list(upcoming.groupby(upcoming['ts'].dt.date, sort=True))
            for col, (day, rows) in zip(st.columns(len(dates), gap='small'), dates):
                peak = rows.loc[rows['prob'].idxmax()]
                selected = cur is not None and cur['ts'].date() == day
                weekday = '월화수목금토일'[day.weekday()] + '요일'
                day_text = f'오늘 · {weekday}' if day == today_kst() else weekday
                col.button(f"**{day.month}.{day.day:02d}**\n\n{day_text}",
                           key=f"forecast_day_{day}", type='primary' if selected else 'secondary',
                           width='stretch', on_click=_select_forecast_day, args=(str(day),),
                           help=f"{day.month}월 {day.day}일 {weekday} · 시간별 최대 가능성 {peak['prob']:.0%} ({peak['level']}). 누르면 해당 날짜의 예측 시각으로 이동합니다.")
        if wins:
            top_window = wins[0]
            summary = (f'<span>선택한 날짜의 추천 시간 · 3시간 평균</span>'
                       f'<strong>{top_window["text"]}</strong>'
                       f'<p>전기가 남을 가능성 {top_window["prob"]:.0%} · 제주 전체 기준</p>')
        else:
            summary = ('<span>선택한 날짜의 추천 시간</span><strong>뚜렷한 추천 시간이 없습니다.</strong>'
                       '<p>선택한 날짜의 남은 시간 중 3시간 평균 가능성이 20% 이상인 구간이 없어요.</p>')
        note = ('<div class="forecast-note" role="note"><span class="forecast-note-label">자료 안내</span>'
                '<p>일부 시간은 최근 전력가격 자료가 부족해 참고 예측으로 표시됩니다.</p></div>') if fc.get('warnings') else ''
        # 요약·구분선·안내를 한 레이아웃 안에 배치해 별도 caption과 겹치지 않게 한다.
        _html(f'<div class="forecast-summary">{summary}{note}</div>')

    # 지도 고르는 버튼과 지도 설명을 한 줄에 (세로 공간 절약)
    c_mode, c_note = st.columns([0.48, 0.52], gap="small")
    with c_mode:
        if hasattr(st, "segmented_control"):
            mode = st.segmented_control("지도", MODES, default=MODES[0], label_visibility="collapsed") or MODES[0]
        else:
            mode = st.radio("지도", MODES, horizontal=True, label_visibility="collapsed")
    with c_note:   # 한 줄 설명 (길면 말줄임, 전체 글은 마우스를 올리면 보임)
        if mode == MODES[0]:
            st.caption('지도 색: 제주 전체 예측 · 원 크기: 지역별 설비 규모')
        else:
            _html("<div class='mapnote' title='위치는 이 화면(브라우저) 안에서만 쓰고 서버로 보내거나 저장하지 않아요. "
                  "허용하지 않거나 제주 밖이면 오른쪽 내 생활 설정의 동네로 보여 드려요.'>제주 공용 충전소 · "
                  "<b>📍 내 주변 충전소</b>를 누르면 내 위치로 확대돼요 (위치는 저장 안 함) <span class='why'>ⓘ</span></div>")

    with_slider = cur is not None   # 시각 슬라이더와 시간별 그래프는 지도 아래에 늘 보임
    with st.container(key="mapbox"):
        if mode == MODES[0] and cur is not None:
            # ---- 잉여 예보 지도: 권역 원(크기 = 재생에너지 설비, 색 = 선택 시각 잉여 가능성) + 풍력발전소 (충전소는 충전소 지도에서)
            reg = _regions().copy()
            _c = prob_color(cur["prob"])
            regions = [[float(r.lat), float(r.lon), float(900 + max(r.total_mw, 0) ** 0.5 * 430),
                        f"{r.name}\n{r.total_mw:.0f}MW",
                        f"{r.name} · 태양광 {r.solar_mw:.0f}MW · 풍력 {r.wind_mw:.0f}MW · {sel} 잉여 가능성 {cur['pct']:.0f}% (섬 전체)"]
                       for r in reg.itertuples()]
            q = g.iloc[0:0]   # 충전소 점은 넣지 않음
            try:   # 다른 지도와 같은 카카오맵(→ OpenStreetMap)
                components.html(nearby_map_html(q, w, None, height=MAP_H, kakao_key=_kakao_key(), mode="surplus",
                                                regions=regions, region_color=f"rgb({_c[0]},{_c[1]},{_c[2]})",
                                                badge=f"{sel} · 제주에 전기가 남을 가능성 {cur['pct']:.0f}% ({cur['level']})"),
                                height=MAP_H)
            except Exception:   # HTML 지도를 못 그리면 pydeck 지도로
                _surplus_pydeck(reg, q, w, cur, sel, MAP_H)
        else:
            # ---- 충전소 지도: 제주 전체 → '📍 내 주변 충전소'로 확대(GPS → 저장한 동네). 카카오맵 → OpenStreetMap → pydeck
            home = None
            if profile.get("area") in PLACE_COORDS:
                lat, lon = PLACE_COORDS[profile["area"]]
                home = {"name": profile["area"], "lat": lat, "lon": lon}
            try:
                components.html(nearby_map_html(g, None, home, height=MAP_H, kakao_key=_kakao_key(), mode="all"), height=MAP_H)   # 풍력발전소는 잉여 예보 지도에만
            except Exception:
                pts = g.assign(color=[[42, 120, 214, 190] if v else [154, 154, 150, 150] for v in g["quick"]],
                               tip=[f"<b>{n}</b><br>급속 {int(a)}기 · 완속 {int(b)}기" for n, a, b in
                                    zip(g["name"], g["quick_count"], g["slow_count"])])
                st.pydeck_chart(pdk.Deck(layers=[pdk.Layer("ScatterplotLayer", pts, get_position="[lon, lat]", get_radius=230,
                                                           get_fill_color="color", pickable=True)],
                                         initial_view_state=pdk.ViewState(latitude=33.37, longitude=126.56, zoom=9.3),
                                         tooltip={"html": "{tip}", "style": {"fontSize": "12px"}}, map_style=None),
                                height=MAP_H, use_container_width=True)

    if with_slider:   # 시각 고르기: 그래프를 누르면 검은 선이 옮겨 가고 잉여 예보 지도 색이 바뀜
        _src = "출처: " + ", ".join(fc["sources"]) + " · " + fc["note"]
        if wins:
            cand_lbl, cand = "추천 시간대(3시간)", wins
        else:   # 3시간 연속으로는 20%를 못 넘어도, 한 시간이라도 넘는 때가 있으면 그 시간 (카드·그래프와 어긋나지 않게)
            cand_lbl, cand = "가능성 있는 시간", best_windows(upcoming, hours=1, top=3)
        chips = ("".join(f"<span class='chip'>{v['text']} · {v['prob']:.0%}</span>" for v in cand) if cand
                 else "<span class='lbl'>앞으로 며칠은 가능성이 20%를 넘는 시간이 없어요</span>")
        try:
            gbox = st.container(key="graphcard")
        except TypeError:   # 아주 옛날 Streamlit
            gbox = st.container()
        with gbox:
            _html("<div class='ghead'><span class='gt'>시간별 예측</span>"
                  "<span class='lbl'>그래프를 눌러 지도 시각을 바꿔보세요</span>"
                  f"<span class='info' title='{escape(_src, quote=True)}'>출처·안내</span></div>")
            if not _hourly_chart(hourly, cur, wins, 180):   # 옛 Streamlit 이면 슬라이더로 대신
                _p = dict(zip(hourly["label"], zip(hourly["pct"], hourly["level"])))
                st.select_slider("지도·그래프 시각", options=hourly["label"].tolist(), value=sel, key="sel_time",
                                 label_visibility="collapsed",
                                 format_func=lambda l: f"{l} · 전기가 남을 가능성 {_p[l][0]:.0f}% ({_p[l][1]})")

    st.caption(f"기상예보 {fresh.get('issued_at') or '자료 없음'} · 전력가격 자료 {status.get('label_last_date') or '자료 없음'} 기준")


# ================================================================ 오른쪽: 에이전트 대화 패널
def _chatbox():
    try:
        return st.container(height=520, border=False, key="chatbox")   # 높이는 CSS 가 화면에 맞춰 덮어씀
    except TypeError:
        return st.container(height=520, border=False)


def _hub_badge(res: dict) -> str:
    """이 답에 실제로 쓰인 제주데이터허브 데이터 번호 (도구 결과의 출처에서 모음)."""
    import re
    nums = []
    for t in res.get("trace", []):
        for src in (t.get("result") or {}).get("sources", []) if isinstance(t.get("result"), dict) else []:
            for n in re.findall(r"(?:제주데이터허브|허브)\s*(\d{3,4})", str(src)):
                if n not in nums:
                    nums.append(n)
    return ("🏝️ 이 답에 쓰인 제주데이터허브: " + " · ".join(nums)) if nums else ""


def _render_evidence(res: dict) -> None:
    badge = _hub_badge(res)
    if badge:
        st.caption(badge)
    with st.expander("근거 보기 (사용한 도구와 데이터)"):
        st.caption("응답 방식: " + ("AI(LLM)" if res["mode"] == "llm" else "규칙 기반(비상 모드)"))
        for t in res["trace"]:
            st.markdown(f"**{t['tool']}** · 입력 `{t['args']}`")
            r = t["result"]
            if t["tool"] == "explain_surplus" and "surplus_day_rate_by_month" in r:
                st.bar_chart(pd.Series(r["surplus_day_rate_by_month"]).rename(index=lambda x: f"{x}월"), y_label="잉여일 비율", height=160)
                st.bar_chart(pd.Series(r["surplus_hours_by_hour"]).rename(index=lambda x: f"{x:02d}시"), y_label="잉여 시간 수", height=160)
            elif t["tool"] == "ev_charging_habits" and "charging_start_share" in r:
                st.line_chart(pd.DataFrame({"도민 충전 시작 비중": pd.Series(r["charging_start_share"]),
                                            "잉여 시간 비중": pd.Series(r["surplus_hour_share"])}).fillna(0), height=180)
            elif t["tool"] == "find_chargers" and r.get("chargers"):
                cdf = pd.DataFrame(r["chargers"])
                if {"lat", "lon"} <= set(cdf.columns):
                    center = None
                    if r.get("center"):
                        area = t["args"].get("area") if isinstance(t["args"], dict) else None
                        center = {"name": (area or "찾은 동네") + " 중심", **r["center"]}
                    try:   # '내 주변'과 같은 지도(카카오맵 → OpenStreetMap)에 찾은 충전소만
                        fcd = cdf.rename(columns={"has_quick": "quick"}).assign(quick_count=cdf.get("quick_count", 0))
                        components.html(nearby_map_html(fcd, None, center, height=300, kakao_key=_kakao_key(),
                                                        mode="focus"), height=370)
                    except Exception:
                        mp = cdf[["lat", "lon"]].assign(
                            color=cdf["has_quick"].map({True: "#2a78d6", False: "#9a9a96"}), size=40.0)
                        st.map(mp, latitude="lat", longitude="lon", color="color", size="size", zoom=13)
                if "midday_use" in cdf.columns:   # 허브 1226: 낮(10~15시) 이용 정도
                    cdf["낮 이용(허브 1226)"] = cdf["midday_use"].map(lambda m: m.get("level") if isinstance(m, dict) else "기록 없음")
                if r.get("ranking"):
                    st.caption("순서: " + r["ranking"])
                for m in r.get("moved_back", []):
                    st.caption(f"↘ {m['name']}({m['distance_km']:.1f}km)는 더 가깝지만 {m['why']}이 있어 뒤로 뺐어요.")
                drop = ("lat", "lon", "has_quick", "midday_use", "crowding_2022", "reason")
                show = cdf.drop(columns=[c for c in drop if c in cdf.columns]).rename(
                    columns={"name": "충전소", "quick_count": "급속", "slow_count": "완속", "distance_km": "거리(km)",
                             "map_link": "위치", "route_link": "길찾기"})
                # 좁은 화면에서도 거리·길찾기가 먼저 보이도록 순서를 정함
                order = [c for c in ("충전소", "거리(km)", "길찾기", "낮 이용(허브 1226)", "급속", "완속", "위치") if c in show.columns]
                show = show[order + [c for c in show.columns if c not in order]]
                st.dataframe(show, hide_index=True, column_config={
                    "위치": st.column_config.LinkColumn("위치", display_text="카카오맵 열기"),
                    "길찾기": st.column_config.LinkColumn("길찾기", display_text="내 위치에서 길찾기")})
            elif t["tool"] == "grid_records" and "curtailment" in r:
                st.bar_chart(pd.Series(r["curtailment"]["wind_mwh_by_hour"]).rename(index=lambda x: f"{int(x):02d}시"),
                             y_label="풍력 출력제어량(MWh)", height=160)
                d = r["demand_hvdc"]
                st.dataframe(pd.DataFrame({"낮 전력수요(MW)": d["midday_demand_mw"],
                                           "육지에서 받는 전기(MW)": d["midday_hvdc_import_mw"]}))
            elif t["tool"] == "llm_error":
                st.warning("AI(LLM) 연결 오류 — 그래서 규칙 기반으로 답했어요: " + str(r.get("error", "")))
            elif t["tool"] == "plan_appliance_use" and (r.get("alternatives") or r.get("best_windows")):
                wdf = pd.DataFrame(r.get("alternatives") or r["best_windows"]).rename(columns={
                    "date": "날짜", "weekday": "요일", "time_text": "시간대", "avg_prob": "남을 가능성", "level": "등급", "basis": "근거"})
                st.dataframe(wdf[[c for c in ["날짜", "요일", "시간대", "남을 가능성", "등급", "근거"] if c in wdf]], hide_index=True)
                if r.get("ev"):
                    st.caption(f"계산: {r['ev']['battery_note']}, {r['ev']['assumption']} → {r['ev']['kwh']}kWh")
            elif t["tool"] == "check_past_forecast" and r.get("days"):
                st.dataframe(pd.DataFrame(r["days"]), hide_index=True)
            st.caption("출처: " + ", ".join(map(str, r.get("sources", []))))


try:
    side = right.container(key="sidepanel")
except TypeError:   # 아주 옛날 Streamlit
    side = right.container()
with side:
    # ---- 위: 👤 내 정보 — 칸마다 바로 고르면 그 자리에서 저장 (모달 없음)
    _PLACES = ["선택 안 함"] + [p_ for p_ in PLACE_COORDS if p_ not in ("공항", "시청", "터미널", "도청")]
    _CARS = list(up.CARS)
    _OUT = ["집에 있음"] + [f"{h}시" for h in range(0, 24)]
    _IN = [f"{h}시" for h in range(1, 25)]
    _TOU = {"모름": "모름", "가입": "계시별 가입", "미가입": "미가입"}

    def _me_sync() -> None:
        """현재 내 정보 → 칸 값 (주소창으로 불러온 값도 그대로 보이도록 매번 맞춤)"""
        p_ = st.session_state.profile
        st.session_state.me_area = p_["area"] if p_["area"] in _PLACES else "선택 안 함"
        st.session_state.me_car = next((k for k, v in up.CARS.items() if v == p_["car"]), _CARS[0])
        st.session_state.me_out = f"{p_['work_start']}시" if p_["work_start"] is not None else "집에 있음"
        st.session_state.me_in = f"{p_['work_end']}시" if p_["work_end"] is not None else "18시"
        st.session_state.me_tou = p_["tou"] if p_["tou"] in _TOU else "모름"

    def _me_save() -> None:
        """칸 값 → 현재 세션의 내 정보"""
        ss = st.session_state
        new_ = up.empty()
        new_["area"] = "" if ss.me_area == "선택 안 함" else ss.me_area
        new_["car"] = up.CARS[ss.me_car]
        if ss.me_out != "집에 있음":
            ws_, we_ = int(ss.me_out[:-1]), int(ss.me_in[:-1])
            if ws_ < we_:
                new_["work_start"], new_["work_end"] = ws_, we_
            else:
                st.toast("돌아오는 시각은 나가는 시각보다 늦어야 해요.")
                new_["work_start"], new_["work_end"] = profile["work_start"], profile["work_end"]
        new_["tou"] = ss.me_tou
        ss.profile = new_

    _me_sync()
    st.markdown('<div class="section-label">내 생활 설정</div>', unsafe_allow_html=True)
    _profile_summary = up.short(st.session_state.profile) or '동네와 생활시간을 설정하면 추천에 반영됩니다.'
    st.caption(_profile_summary)
    with st.expander('설정 변경', expanded=False):

        def _row(label: str):
            c1, c2 = st.columns([0.27, 0.73], vertical_alignment="center")
            c1.markdown(f"<span class='me-k'>{label}</span>", unsafe_allow_html=True)
            return c2

        _row("동네").selectbox("동네", _PLACES, key="me_area", on_change=_me_save, label_visibility="collapsed")
        _row("전기차").selectbox("전기차", _CARS, key="me_car", on_change=_me_save, label_visibility="collapsed")
        c1, wa, wb = st.columns([0.27, 0.365, 0.365], vertical_alignment="center")   # 열 안에 열을 또 넣지 않음
        c1.markdown("<span class='me-k'>출퇴근</span>", unsafe_allow_html=True)
        wa.selectbox("나가는 시각", _OUT, key="me_out", on_change=_me_save, label_visibility="collapsed")
        wb.selectbox("돌아오는 시각", _IN, key="me_in", on_change=_me_save, label_visibility="collapsed",
                     disabled=st.session_state.me_out == "집에 있음")
        _row("요금제").selectbox("요금제", list(_TOU), key="me_tou", on_change=_me_save,
                               format_func=lambda k: _TOU[k], label_visibility="collapsed")

    # ---- 아래: 💬 에너지 도우미 (대화 → 예시 질문 → 입력창)
    with st.container(key="chatpanel", border=True):
        st.markdown("<div class='panel-title'>생활 계획</div><div class='panel-description'>내 일정에 맞는 시간을 함께 찾아보세요.</div>", unsafe_allow_html=True)
        preset = None
        with st.container(key="quickq"):
            qa, qb = st.columns(2)
            if qa.button("이번 주 언제가 좋아?", use_container_width=True):
                preset = "이번 주에 빨래랑 식기세척기 언제 돌리면 좋아?"
            if qb.button("전기차 충전", use_container_width=True):
                preset = "이번 주에 전기차 충전은 언제 어디서 하면 좋아?"
            qc, qd = st.columns(2)
            if qc.button("왜 생기는 거야?", use_container_width=True):
                preset = "잉여전력이 왜 생기는 거야?"
            if qd.button("지난 예보 맞았어?", use_container_width=True):
                preset = "지난주 예보가 실제로 맞았는지 알려줘"
        chat_box = _chatbox()
        question = st.chat_input("예: 내일 9시 출근인데 언제 충전할까요?") or preset

if question:
    with right:
        with st.spinner("데이터를 확인하고 있어요..."):
            # 앞 질문·답변을 함께 넘겨 이어지는 질문과 '지금까지 정리해줘'를 이해
            res = ask(question, [(q_, r_["answer"]) for q_, r_ in st.session_state.history], profile)
    st.session_state.history.append((question, res))

with chat_box:
    if not st.session_state.history:
        st.markdown('<div class="chat-empty"><span>어떤 시간을 찾고 계세요?</span>'
                    '<p>위의 질문을 선택하거나<br>사용할 기기와 원하는 시간을 적어주세요.</p>'
                    '<small>예측과 계산 근거를 함께 안내합니다.</small></div>', unsafe_allow_html=True)
    for i, (q_, res) in enumerate(st.session_state.history):
        st.chat_message("user").write(q_)
        with st.chat_message("assistant"):
            st.markdown(res["answer"].replace("~", "～"))  # '~' 두 개가 취소선으로 바뀌는 것을 막음
            win = pick_window(res["trace"], now=now_kst())
            if win:
                st.caption(f"{win['date'][5:].replace('-', '/')} {win['time_text']} — 내 캘린더에 사용 계획을 저장해요")
                c1, c2 = st.columns(2)
                c1.link_button("구글 캘린더", google_url(win), use_container_width=True)
                c2.download_button("아이폰·아웃룩 (.ics)", ics_bytes(win), file_name=f"jeju_surplus_{win['date']}.ics",
                                   help="ICS 파일에는 10분 전 알림이 포함돼요. 구글 캘린더의 알림은 저장할 때 직접 확인해주세요.", mime="text/calendar", key=f"ics_{i}", use_container_width=True)
            _render_evidence(res)

# ================================================================ 사이드바: 데이터 상태
with st.sidebar:
    with st.expander('데이터 및 연결 상태', expanded=False):
        from status_view import render_status_panel
        render_status_panel(status, fresh, _ls)
    st.caption('SMP 0원 이하 발생 가능성을 예측합니다. 실제 잉여량이나 요금 할인을 뜻하지 않습니다.')


# 메인 화면을 배경으로 이용 안내 팝업을 표시합니다.
render_onboarding(PLACE_COORDS)
