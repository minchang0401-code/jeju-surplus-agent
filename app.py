"""제주 잉여전력 도우미 — 화면 (Streamlit)

    streamlit run app.py

화면 구성: 왼쪽 = 예보 카드 · 지도 · 시간별 잉여 가능성 그래프 / 오른쪽 = 에이전트 대화 패널 / 오른쪽 맨 위 = 👤 내 정보(칸마다 바로 수정) / 사이드바 = 데이터 상태
"""
from __future__ import annotations

import os
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
st.markdown(f"""<style>:root {{
  --ink: {'#e8eeeb' if DARK else '#1b1b1b'}; --ink2: {'#aab7b2' if DARK else '#5b6b66'};
  --ink-k: {'#cdd7d3' if DARK else '#3d4b46'}; --accent: {'#8ab8f0' if DARK else '#1f4f8f'};
  --panel: {'rgba(255,255,255,.06)' if DARK else '#f6f8fb'}; --panel-border: {'rgba(255,255,255,.14)' if DARK else '#dfe6ef'};
  --myinfo: {'rgba(120,170,240,.08)' if DARK else '#f6f9fd'}; --chip: {'rgba(255,255,255,.08)' if DARK else '#f4f7f6'};
  --header: {'rgba(14,17,23,.85)' if DARK else 'rgba(255,255,255,.85)'};
}}</style>""", unsafe_allow_html=True)
st.markdown("""<style>
/* 한 화면(스크롤 없이)에 맞추기: 지도 높이 = 화면 높이 - 나머지(머리말·카드·버튼·그래프) → 화면이 크면 지도도 커짐 */
:root { --map-h: clamp(200px, calc(100vh - 436px), 620px); }
/* 지도 칸 자체의 높이를 정하고(넘치면 잘라서 아래 글과 겹치지 않게) 안의 지도는 그 칸을 꽉 채움 */
.st-key-mapbox { height: var(--map-h) !important; min-height: var(--map-h); overflow: hidden; flex: 0 0 auto !important; }
.st-key-mapboxfull { height: calc(var(--map-h) + 54px) !important; min-height: calc(var(--map-h) + 54px); overflow: hidden; flex: 0 0 auto !important; }
.st-key-mapbox [data-testid="stElementContainer"], .st-key-mapboxfull [data-testid="stElementContainer"],
.st-key-mapbox [data-testid="stIFrame"], .st-key-mapboxfull [data-testid="stIFrame"] { height: 100% !important; }
.st-key-mapbox iframe, .st-key-mapboxfull iframe { height: 100% !important; display: block; }   /* 시각 슬라이더가 없는 지도는 54px 더 크게 */

[data-testid="stColumn"]:has(.days) [data-testid="stVerticalBlock"] { gap: .5rem; }
[data-testid="stColumn"]:has(.days) [data-testid="stHorizontalBlock"] { align-items: center; }
[data-testid="stColumn"]:has(.days) [data-testid="stVegaLiteChart"] { margin-top: -.3rem; }
.block-container { padding-top: 2.7rem; padding-bottom: .2rem; padding-left: 1.6rem; padding-right: 1.6rem; max-width: 100%; }
header[data-testid="stHeader"] { height: 2.4rem; background: var(--header); }
/* 오른쪽 에너지 도우미: 스크롤해도 화면에 붙어 있고, 입력창은 화면 맨 아래 */
[data-testid="stColumn"]:has(.st-key-sidepanel), [data-testid="column"]:has(.st-key-sidepanel) { align-self: stretch; }
[data-testid="stLayoutWrapper"]:has(> .st-key-sidepanel) { position: sticky; top: 2.9rem; align-self: flex-start; z-index: 2; }
.st-key-sidepanel { gap: .45rem; }
.st-key-sidepanel button { min-height: 2rem; padding: .15rem .4rem; }
.st-key-sidepanel button p { font-size: .78rem; white-space: nowrap; }
.st-key-myinfo { gap: .45rem; background: var(--myinfo); }
.st-key-myinfo [data-testid="stHorizontalBlock"] { gap: .3rem; }
.st-key-myinfo [data-baseweb="select"] { font-size: .84rem; }
.me-title { font-weight: 700; font-size: .92rem; color: var(--accent); margin-bottom: .1rem; }
.me-note { font-weight: 400; font-size: .7rem; color: var(--ink2); margin-left: 4px; }
.me-k { color: var(--ink-k); font-size: .84rem; font-weight: 600; white-space: nowrap; }
.st-key-chatpanel { gap: .35rem; }
.st-key-quickq { gap: .3rem; }
.st-key-quickq button { min-height: 1.75rem; border-radius: 999px; background: var(--chip); color: var(--ink); }
.st-key-quickq button p { color: var(--ink); }
.st-key-quickq button p { font-size: .74rem; }
.st-key-sidepanel [data-testid="stHorizontalBlock"] { gap: .35rem; }
[data-testid="stLayoutWrapper"]:has(> .st-key-chatbox), .st-key-chatbox { flex: 0 0 calc(100vh - 33.5rem) !important; height: calc(100vh - 33.5rem) !important; min-height: 200px; }
.st-key-sidepanel [data-testid="stChatInput"] textarea { font-size: .82rem; }
h1 { font-size: 1.55rem !important; margin: 0 !important; padding: 0 !important; }
.sub { color: var(--ink2); font-size: .9rem; margin-top: .1rem; }
.pill { display:inline-block; font-size:.78rem; padding:3px 10px; border-radius:999px; margin-left:6px;
        background:#eef2f0; color:#2d3b36; border:1px solid #dde4e0; }
.pill.ok { background:#dff1e8; color:#0d6b44; border-color:#a9dcc2; }
.pill.warn { background:#fff4dc; color:#8a5a00; border-color:#f2dcaa; }
.days { display:flex; gap:8px; margin:.15rem 0 0; }
.day { flex:1; border-radius:10px; padding:4px 8px; text-align:center; color:#1b1b1b; border:1px solid rgba(0,0,0,.05); }
.day .d { font-size:.76rem; color:#33413c; line-height:1.3; }
.day .lv { font-size:1rem; font-weight:800; line-height:1.3; }
.day .t { font-size:.7rem; color:#33413c; line-height:1.25; }
.reco { font-size:.85rem; line-height:1.6; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.win { display:inline-block; margin:2px 6px 2px 0; padding:4px 10px; border-radius:999px; background:#dff1e8;
       color:#0d6b44; font-weight:700; font-size:.85rem; }
.panel-title { font-weight:800; font-size:1.05rem; margin-bottom:.2rem; }
.mapnote { background:var(--panel); border:1px solid var(--panel-border); border-radius:10px; padding:.3rem .6rem; margin:0;
           font-size:.8rem; line-height:1.4; color:var(--ink); white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.mapnote .why { color:var(--accent); cursor:help; border-bottom:1px dotted var(--accent); white-space:nowrap; }
.mapnote .dot { display:inline-block; width:.8rem; height:.8rem; border-radius:50%; margin-right:.35rem; vertical-align:-1px;
                border:1px solid #fff; box-shadow:0 0 0 1px #c9d2db; }
.mapnote .mn-sub { color:var(--ink2); }
.legend-row { font-size:.78rem; color:var(--ink2); }
div[data-testid="stChatMessage"] { padding: .4rem .5rem; }
</style>""", unsafe_allow_html=True)


# 예보가 4시간보다 오래됐으면 새로 받음 (기상청 단기예보는 하루 8번 발표). 30분 동안은 다시 확인하지 않음.
@st.cache_data(ttl=1800, show_spinner="최신 기상청 예보를 확인하고 있어요...")
def _refresh_forecast() -> dict:
    return refresh_forecast_if_stale()


@st.cache_data(ttl=1800, show_spinner=False)
def _hourly(today: str) -> pd.DataFrame:
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


fresh = _refresh_forecast()
status = data_status()
_ls = llm_status()

if "profile" not in st.session_state:
    try:
        st.session_state.profile = up.from_query({k: st.query_params.get(k) for k in ("area", "car", "ws", "we", "tou")})
    except Exception:
        st.session_state.profile = up.empty()
profile = st.session_state.profile
if "history" not in st.session_state:
    st.session_state.history = []

# ---------------------------------------------------------------- 머리말
pills = []
if fresh.get("issued_at"):
    pills.append(f"<span class='pill ok'>기상청 단기예보 {fresh['issued_at']}</span>")
if fresh["status"] == "failed":
    pills.append("<span class='pill warn'>최신 예보 수신 실패 · 저장된 예보 사용</span>")
if status["mode"].startswith("저장"):
    pills.append(f"<span class='pill warn'>{status['mode']}</span>")
pills.append(f"<span class='pill {'ok' if _ls['on'] else ''}'>{'AI 연결' if _ls['on'] else 'AI 비상 모드'}</span>")
st.markdown(f"<h1 title='제주 재생에너지가 남는 시간을 미리 알려 드려요. 그 시간에 전기를 쓰면 버려질 전기를 살릴 수 있어요. "
            f"(데이터 상태는 왼쪽 위 ▸ 메뉴)'>⚡ 제주 잉여전력 도우미 {''.join(pills)}</h1>", unsafe_allow_html=True)

def _hourly_chart(hourly, cur, wins, height: int) -> bool:
    """시간별 잉여 가능성 막대그래프 (밤은 회색 배경, 추천 3시간은 초록 띠, 고른 시각은 검은 선).
    그래프 아무 데나 누르면 그 시각이 골라짐(검은 선이 옮겨 가고 지도 색이 바뀜). 누르기를 못 쓰는 옛 Streamlit 이면 False."""
    night = night_bands(hourly)
    x = alt.X("ts:T", title=None, axis=alt.Axis(format="%m/%d %H시", labelAngle=0, tickCount="day", grid=False))
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
        st.altair_chart(chart, use_container_width=True, on_select="rerun", selection_mode="pick", key="hourpick")
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


left, right = st.columns([0.79, 0.21], gap="small")

# ================================================================ 왼쪽: 예보 · 지도 · 그래프
with left:
    try:
        fc = forecast_surplus(5)
        cards = "".join(
            f"<div class='day' style='background:{LEVEL_COLOR[d['level']]}'>"
            f"<div class='d'>{d['date'][5:].replace('-', '/')} ({d['weekday']})</div>"
            f"<div class='lv'>{d['level']} · {d['max_prob']:.0%}</div>"
            f"<div class='t'>{d['likely_time_text'] if d['likely_hours'] else '-'}</div></div>"
            for d in fc["forecast"])
        _html(f"<div class='days'>{cards}</div>")
        hourly = _hourly(str(date.today()))
    except FileNotFoundError:
        st.error("학습된 모델이 없습니다. 먼저 `python train.py` 를 실행하세요.")
        hourly = None

    MODES = ["⚡ 잉여 예보 지도", "🔌 충전소 지도"]
    MAP_H = 440   # 기본값. 실제 높이는 CSS(--map-h)가 화면 높이에 맞춰 정함
    g, w = _nearby_data()

    if hourly is not None and len(hourly):
        wins = best_windows(hourly, hours=3, top=3)
        default = hourly.loc[hourly["prob"].idxmax(), "label"]
        try:   # 그래프에서 누른 시각 (안 눌렀으면 이전에 고른 시각, 처음엔 가능성이 가장 높은 시각)
            _rows = (st.session_state.get("hourpick") or {}).get("selection", {}).get("pick") or []
            if _rows and _rows[0].get("label") in set(hourly["label"]):
                st.session_state.sel_label = _rows[0]["label"]
        except Exception:
            pass
        sel = st.session_state.get("sel_label") or st.session_state.get("sel_time") or default
        if sel not in set(hourly["label"]):
            sel = default
        cur = hourly[hourly["label"] == sel].iloc[0]
    else:
        wins, cur, sel = [], None, None

    # 지도 고르는 버튼과 지도 설명을 한 줄에 (세로 공간 절약)
    c_mode, c_note = st.columns([0.46, 0.54], gap="small")
    with c_mode:
        if hasattr(st, "segmented_control"):
            mode = st.segmented_control("지도", MODES, default=MODES[0], label_visibility="collapsed") or MODES[0]
        else:
            mode = st.radio("지도", MODES, horizontal=True, label_visibility="collapsed")
    with c_note:   # 한 줄 설명 (길면 말줄임, 전체 글은 마우스를 올리면 보임)
        if mode == MODES[0]:
            pass   # 고른 시각의 가능성은 지도 안 왼쪽 위 배지에 이미 크게 보임
        else:
            _html("<div class='mapnote' title='위치는 이 화면(브라우저) 안에서만 쓰고 서버로 보내거나 저장하지 않아요. "
                  "허용하지 않거나 제주 밖이면 오른쪽 👤 내 정보의 동네로 보여 드려요.'>🔌 제주 공용 충전소 전체 · "
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
        if not _hourly_chart(hourly, cur, wins, 150):   # 옛 Streamlit 이면 슬라이더로 대신
            _p = dict(zip(hourly["label"], zip(hourly["pct"], hourly["level"])))
            st.select_slider("지도·그래프 시각", options=hourly["label"].tolist(), value=sel, key="sel_time",
                             label_visibility="collapsed",
                             format_func=lambda l: f"{l} · 전기가 남을 가능성 {_p[l][0]:.0f}% ({_p[l][1]})")
    if cur is not None:
        _src = "출처: " + ", ".join(fc["sources"]) + " · " + fc["note"]
        if wins:
            _html("<div class='reco'><b>추천 시간대(3시간)</b> " + "".join(f"<span class='win'>{v['text']} · {v['prob']:.0%}</span>" for v in wins)
                  + f"<span class='legend-row' title='{_src}'> · 그래프를 누르거나 끌면 그 시각으로 지도가 바뀌어요 ⓘ 출처·안내</span></div>")
        else:
            # 3시간 연속으로는 20%를 못 넘어도, 한 시간이라도 넘는 때가 있으면 그 시간을 알려 줌 (카드·그래프와 어긋나지 않게)
            one = best_windows(hourly, hours=1, top=3)
            if one:
                _html("<div class='reco'><b>가능성 있는 시간(짧음)</b> " + "".join(f"<span class='win'>{v['text']} · {v['prob']:.0%}</span>" for v in one)
                      + f"<span class='legend-row' title='{_src}'> · 3시간 이어지는 때는 없어요 · 그래프를 누르거나 끌면 그 시각으로 지도가 바뀌어요 ⓘ 출처·안내</span></div>")
            else:
                _html("<div class='reco'><span class='legend-row'>앞으로 며칠은 재생에너지가 남을 가능성이 20%를 넘는 시간이 없어요.</span>"
                      f"<span class='legend-row' title='{_src}'> · 그래프를 누르거나 끌면 그 시각으로 지도가 바뀌어요 ⓘ 출처·안내</span></div>")


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
        """칸 값 → 내 정보 저장 + 주소창(즐겨찾기용)"""
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
        try:
            st.query_params.from_dict(up.to_query(new_))
        except Exception:
            pass

    _me_sync()
    with st.container(key="myinfo", border=True):
        st.markdown("<div class='me-title'>👤 내 정보</div>",
                    unsafe_allow_html=True)

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
        st.markdown("<div class='panel-title'>💬 에너지 도우미</div>", unsafe_allow_html=True)
        chat_box = _chatbox()
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
        question = st.chat_input("궁금한 것을 물어보세요") or preset

if question:
    with right:
        with st.spinner("데이터를 확인하고 있어요..."):
            # 앞 질문·답변을 함께 넘겨 이어지는 질문과 '지금까지 정리해줘'를 이해
            res = ask(question, [(q_, r_["answer"]) for q_, r_ in st.session_state.history], profile)
    st.session_state.history.append((question, res))

with chat_box:
    if not st.session_state.history:
        st.chat_message("assistant").markdown(
            "안녕하세요! 왼쪽 **그래프**에서 재생에너지가 남을 가능성이 높은 시간을 볼 수 있어요.\n\n"
            "세탁기·식기세척기·전기차 충전처럼 **시간을 옮길 수 있는 전기 사용**이 있다면 언제가 좋을지 물어보세요.")
    for i, (q_, res) in enumerate(st.session_state.history):
        st.chat_message("user").write(q_)
        with st.chat_message("assistant"):
            st.markdown(res["answer"].replace("~", "～"))  # '~' 두 개가 취소선으로 바뀌는 것을 막음
            win = pick_window(res["trace"])
            if win:
                st.caption(f"📅 {win['date'][5:].replace('-', '/')} {win['time_text']} — 캘린더에 넣으면 10분 전에 알려 줘요")
                c1, c2 = st.columns(2)
                c1.link_button("구글 캘린더", google_url(win), use_container_width=True)
                c2.download_button("아이폰·아웃룩 (.ics)", ics_bytes(win), file_name=f"jeju_surplus_{win['date']}.ics",
                                   mime="text/calendar", key=f"ics_{i}", use_container_width=True)
            _render_evidence(res)

# ================================================================ 사이드바: 데이터 상태
with st.sidebar:
    st.subheader("데이터 상태")
    for k, v in status["available"].items():
        st.write(("✅ " if v else "⬜ ") + k)
    st.caption(("🟢 " if _ls["on"] else "⚪ ") + _ls["text"])
    _mid = {"fresh": "받음", "updated": "방금 새로 받음", "failed": "받지 못함 → 3~5일 뒤는 참고치", "no_key": "키 없음"}
    if fresh.get("mid"):
        st.caption("기상청 중기예보(3~5일 뒤): " + _mid.get(fresh["mid"], fresh["mid"]))
    if fresh.get("issued_at"):
        st.caption(f"기상청 단기예보 발표: {fresh['issued_at']}" + (" (방금 새로 받음)" if fresh["status"] == "updated" else ""))
