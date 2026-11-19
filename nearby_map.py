"""충전소 지도 — 화면(app.py)의 '📍 내 주변'·'🗺️ 제주 전체' 탭과 답변의 '근거 보기' 지도가 모두 이 지도를 씀.

세 가지가 함께 동작하도록 만들었습니다.
1) GPS: '📍 내 위치로 찾기'를 누르면 브라우저가 위치 허용을 묻고, 허용하면 내 위치와 가까운 충전소 5곳을 보여 줌
2) GPS가 안 되면(거부·미지원·차단·제주 밖) 저장한 '내 동네' 대표 좌표로 대신 보여 줌
3) 충전소마다 카카오맵 '여기까지 길찾기' 링크 — 카카오맵이 휴대폰의 현재 위치에서 길을 안내
위치는 브라우저 안에서만 계산하고 서버로 보내거나 저장하지 않습니다.

배경 지도
- 카카오맵: KAKAO_JS_KEY(카카오 개발자 JavaScript 키, 앱 주소 등록 필요)가 있으면 카카오맵으로 그림
- 키가 없거나 카카오맵을 5초 안에 못 불러오면 Leaflet + OpenStreetMap(실패 시 Esri)으로 자동 전환
- 지도 그림을 하나도 못 불러와도 가까운 충전소 목록과 길찾기 링크는 그대로 나옴
"""
from __future__ import annotations

import json

LEAFLET_JS = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"
LEAFLET_CSS = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"
KAKAO_SDK = "https://dapi.kakao.com/v2/maps/sdk.js?autoload=false&libraries=clusterer&appkey="

_PAGE = r"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="stylesheet" href="__LEAFLET_CSS__">
<style>
 body{margin:0;font-family:"Noto Sans KR",system-ui,-apple-system,sans-serif;color:#1b1b1b;font-size:15px}
 .bar{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:2px 0 6px}
 /* 채우기 배치(focus 를 뺀 모드): iframe 높이 전체를 쓰고, 지도가 남는 높이를 다 차지 → 화면 크기에 맞춰 늘고 줄어듦 */
 html.fill, html.fill body{height:100%}
 html.fill body{display:flex;flex-direction:column;overflow:hidden}
 html.fill #main{flex:1;min-height:0;display:flex;gap:10px}
 html.fill #wrap{flex:1;min-width:0}
 html.fill #map{height:100%;min-height:180px}
 html.fill #list{width:280px;overflow:auto;margin-top:0}
 html.fill #list .row{flex-direction:column;gap:2px;font-size:13.5px;padding:6px 2px}
 @media (max-width:640px){ html.fill #main{flex-direction:column} html.fill #list{width:auto;max-height:40%} }
 #legend{position:absolute;left:10px;bottom:10px;z-index:1050;background:rgba(255,255,255,.92);border-radius:8px;
   padding:5px 9px;font-size:12px;color:#33413c;box-shadow:0 1px 4px rgba(0,0,0,.12);max-width:75%}
 #legend:empty{display:none}
 /* 잉여 예보 지도: 고른 시각의 가능성을 지도 위에 크게 */
 #badge{position:absolute;left:10px;top:10px;z-index:1060;background:rgba(255,255,255,.95);border-radius:10px;
   padding:7px 12px;font-size:15px;font-weight:700;color:#15211d;box-shadow:0 2px 8px rgba(0,0,0,.15);display:flex;gap:8px;align-items:center}
 #badge:empty{display:none}
 #badge .bd{width:14px;height:14px;border-radius:50%;border:2px solid #fff;box-shadow:0 0 0 1px #c9d2db}
 #engine{margin-left:auto}
 button{font-size:15px;padding:8px 14px;border-radius:10px;border:1px solid #2a78d6;background:#2a78d6;color:#fff;cursor:pointer}
 button.sub{background:#fff;color:#2a78d6}
 button.on{background:#1a7f4b;border-color:#1a7f4b;color:#fff;font-weight:600}
 #msg{color:#52514e;font-size:14px;min-height:20px}
 #engine{color:#7a7974;font-size:12px}
 #map{height:__HEIGHT__px;border-radius:12px;background:#e8eff3}
 #wrap{position:relative}
 /* 꼭 봐야 하는 안내(제주 밖·위치 실패): 지도 위쪽에 겹쳐 띄움 → 높이가 늘지 않아 스크롤이 생기지 않음 */
 #warn{position:absolute;top:10px;left:10px;right:58px;z-index:1100;display:none;gap:8px;align-items:flex-start;
   background:rgba(255,255,255,.96);border:1px solid #f1b5b3;border-left:5px solid #d32f2f;border-radius:10px;
   padding:9px 10px 9px 12px;box-shadow:0 2px 8px rgba(0,0,0,.12);color:#c62828;font-size:15.5px;font-weight:600;line-height:1.45}
 #warn.show{display:flex}
 #warn span{flex:1}
 #warn button{background:none;border:none;color:#c62828;font-size:16px;padding:0 2px;line-height:1}
 #msg:empty{min-height:0;margin:0}
 #msg.ok{color:#1251a8;font-weight:600}
 #msg.warn{color:#c62828;font-weight:600}
 #list{margin-top:8px}
 .row{display:flex;justify-content:space-between;gap:8px;padding:8px 2px;border-bottom:1px solid #e4e3df}
 .row b{font-weight:600} .q{color:#2a78d6} .s{color:#7a7974}
 a{color:#2a78d6;white-space:nowrap}
 .me{width:16px;height:16px;border-radius:50%;border:3px solid #fff;box-shadow:0 0 0 1px #888}
 .pop{padding:8px 10px;font-size:13px;line-height:1.5;white-space:nowrap}
 .rlabel{font-size:12px;font-weight:700;color:#15211d;text-align:center;white-space:pre;text-shadow:0 0 3px #fff,0 0 3px #fff}
 .rlabel-l{background:none;border:none;box-shadow:none;font-size:12px;font-weight:700;color:#15211d;white-space:pre;
   text-shadow:0 0 3px #fff,0 0 3px #fff}
</style></head><body>
<div class="bar" id="bar">
 <button id="gps">📍 내 위치로 찾기</button>
 <button class="sub" id="quick" aria-pressed="false">급속만 보기: 끔</button>
 <a id="kksearch" target="_blank" rel="noopener" href="https://map.kakao.com/link/search/%EC%A0%84%EA%B8%B0%EC%B0%A8%EC%B6%A9%EC%A0%84%EC%86%8C">카카오맵에서 내 주변 충전소 검색 ↗</a>
 <span id="engine"></span>
</div>
<div id="msg"></div>
<div id="main">
<div id="wrap"><div id="map"></div><div id="badge"></div><div id="legend"></div><div id="warn" role="alert"><span id="warnText"></span><button id="warnX" title="닫기" aria-label="안내 닫기">✕</button></div></div>
<div id="list"></div>
</div>
<script>
const D = __DATA__;
const P = D.p, W = D.w, HOME = D.home, KKEY = D.kakao_key, MODE = D.mode || "near";
const R = D.regions || [], RCOLOR = D.region_color || "#7cc49a";
if (MODE !== "focus") document.documentElement.className = "fill";
let quickOnly = false, eng = null, last = null, touched = false;
const $ = (id) => document.getElementById(id);
// kind: "warn" = 빨간 안내를 지도 위에 띄움(제주 밖·위치 실패), "ok" = GPS 성공(파란 글씨), 없으면 보통 안내
function say(t, kind) {
  $("warn").className = "";
  if (kind === "warn" && $("map").style.display !== "none") {
    $("warnText").textContent = t; $("warn").className = "show";
    $("msg").textContent = ""; $("msg").className = "";
    return;
  }
  $("msg").textContent = t; $("msg").className = kind || "";
}
function km(a, b, c, d) {
  const R = 6371, r = Math.PI / 180, x = (c - a) * r, y = (d - b) * r;
  const h = Math.sin(x / 2) ** 2 + Math.cos(a * r) * Math.cos(c * r) * Math.sin(y / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(h));
}
function route(p) { return "https://map.kakao.com/link/to/" + encodeURIComponent(p[3].replace(/,/g, " ")) + "," + p[0] + "," + p[1]; }
function shown() { return P.filter(p => !quickOnly || p[2]); }
function nearest(lat, lon, k) {
  return shown().map(p => [km(lat, lon, p[0], p[1]), p]).sort((a, b) => a[0] - b[0]).slice(0, k);
}
function popupNode(p) {
  const box = document.createElement("div"); box.className = "pop";
  const t = document.createElement("b"); t.textContent = p[3]; box.appendChild(t);
  box.appendChild(document.createElement("br"));
  box.appendChild(document.createTextNode(p[2] ? "급속 " + p[4] + "대 " : "완속만 "));
  const a = document.createElement("a"); a.href = route(p); a.target = "_blank"; a.rel = "noopener";
  a.textContent = "여기까지 길찾기 ↗"; box.appendChild(a);
  return box;
}
function loadScript(src) {
  return new Promise(function (ok, bad) {
    const s = document.createElement("script"); s.src = src; s.onload = ok; s.onerror = bad;
    document.head.appendChild(s);
  });
}
// 탭 안에 숨겨진 채로 지도가 만들어지면 크기가 0이라 위치가 엉뚱해짐(예: 일본이 보임).
// 크기가 바뀌거나 화면에 보이게 될 때마다 지도를 다시 맞추고, 사용자가 지도를 움직이기 전까지는 다시 제주에 맞춤.
function watchResize(fn) {
  const again = function () {
    if (!$("map").clientWidth) return;
    fn();
    if (eng && !touched) { if (MODE !== "near") eng.fit(fitPoints()); else if (last) eng.me.apply(null, last); else eng.home(); }
  };
  if (window.ResizeObserver) new ResizeObserver(again).observe($("map"));
  if (window.IntersectionObserver) new IntersectionObserver(function (es) { if (es.some(e => e.isIntersecting)) again(); }).observe($("map"));
  if (window.addEventListener) window.addEventListener("resize", again);
  [300, 1000, 2500].forEach(function (t) { setTimeout(again, t); });
}

// ---------- 카카오맵
function makeKakao() {
  return loadScript("__KAKAO_SDK__" + encodeURIComponent(KKEY)).then(function () {
    return new Promise(function (ok, bad) {
      if (!window.kakao || !kakao.maps) { bad(new Error("no kakao")); return; }
      kakao.maps.load(function () {
        try {
          const K = kakao.maps;
          const map = new K.Map($("map"), {center: new K.LatLng(33.38, 126.55), level: 9});
          map.addControl(new K.ZoomControl(), K.ControlPosition.RIGHT);
          const dot = (c, s) => new K.MarkerImage("data:image/svg+xml;charset=utf-8," + encodeURIComponent(
            '<svg xmlns="http://www.w3.org/2000/svg" width="' + s + '" height="' + s + '"><circle cx="' + s / 2 + '" cy="' + s / 2 +
            '" r="' + (s / 2 - 1.5) + '" fill="' + c + '" stroke="white" stroke-width="1.5"/></svg>'), new K.Size(s, s), {offset: new K.Point(s / 2, s / 2)});
          const imgQ = dot("#2a78d6", MODE === "surplus" ? 8 : 13), imgS = dot("#9a9a96", 11);
          // 잉여 예보 지도는 권역 원·이름표가 잘 보이도록 충전소를 묶지 않음(작은 점으로)
          const cl = new K.MarkerClusterer({map: map, averageCenter: true, minLevel: MODE === "surplus" ? 15 : 6, disableClickZoom: false});
          const info = new K.InfoWindow({removable: true});
          const meOverlays = [];
          for (const g of R) {   // 잉여 예보 지도: 권역 원 (크기 = 재생에너지 설비, 색 = 섬 전체 잉여 가능성)
            const rc = new K.Circle({center: new K.LatLng(g[0], g[1]), radius: g[2], strokeWeight: 2, strokeColor: "#ffffff",
              fillColor: RCOLOR, fillOpacity: 0.6});
            rc.setMap(map);
            const lb = document.createElement("div"); lb.className = "rlabel"; lb.textContent = g[3];
            new K.CustomOverlay({position: new K.LatLng(g[0], g[1]), content: lb, map: map, yAnchor: 0.5, zIndex: 3});
            K.event.addListener(rc, "click", function () {
              const box = document.createElement("div"); box.className = "pop"; box.textContent = g[4];
              info.setContent(box); info.setPosition(new K.LatLng(g[0], g[1])); info.open(map);
            });
          }
          for (const w of W) {
            const wc = new K.Circle({center: new K.LatLng(w[0], w[1]), radius: 250 + w[2] * 12, strokeWeight: 1, strokeColor: "#ffffff",
              fillColor: "#eb6834", fillOpacity: 0.75});
            wc.setMap(map);
            K.event.addListener(wc, "click", function () {
              const box = document.createElement("div"); box.className = "pop";
              box.textContent = "풍력발전소 " + w[2] + "MW (위치는 리 단위 대략값)";
              info.setContent(box); info.setPosition(new K.LatLng(w[0], w[1])); info.open(map);
            });
          }
          const api = {
            name: "카카오맵",
            draw: function () {
              cl.clear();
              cl.addMarkers(shown().map(function (p) {
                const m = new K.Marker({position: new K.LatLng(p[0], p[1]), image: p[2] ? imgQ : imgS, title: p[3]});
                K.event.addListener(m, "click", function () { info.setContent(popupNode(p)); info.open(map, m); });
                return m;
              }));
            },
            me: function (lat, lon, label, acc, isGps) {
              while (meOverlays.length) meOverlays.pop().setMap(null);
              const c = new K.LatLng(lat, lon);
              if (acc) meOverlays.push(new K.Circle({center: c, radius: acc, strokeWeight: 1, strokeColor: "#2a78d6",
                fillColor: "#2a78d6", fillOpacity: 0.08, map: map}));
              const el = document.createElement("div"); el.className = "me"; el.title = label;
              el.style.background = isGps ? "#1251a8" : "#eb6834";
              meOverlays.push(new K.CustomOverlay({position: c, content: el, map: map, zIndex: 5}));
              map.setLevel(4); map.setCenter(c);
            },
            fit: function (pts) {
              if (!pts.length) return;
              const b = new K.LatLngBounds();
              for (const q of pts) b.extend(new K.LatLng(q[0], q[1]));
              map.setBounds(b);
            }
          };
          api.home = function () { map.setLevel(9); map.setCenter(new K.LatLng(33.38, 126.55)); };
          K.event.addListener(map, "dragstart", function () { touched = true; });
          watchResize(function () { map.relayout(); });
          ok(api);
        } catch (e) { bad(e); }
      });
    });
  });
}

// ---------- Leaflet + OpenStreetMap (카카오 키가 없거나 실패했을 때)
function makeLeaflet() {
  return (window.L ? Promise.resolve() : loadScript("__LEAFLET_JS__")).then(function () {
    if (!window.L) throw new Error("no leaflet");
    const map = L.map("map", {scrollWheelZoom: false, preferCanvas: true, zoomControl: false}).setView([33.38, 126.55], 10);
    L.control.zoom({position: "topright"}).addTo(map);   // 왼쪽 위는 빨간 안내 자리
    let fails = 0, switched = false;
    const osm = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {attribution: "© OpenStreetMap contributors", maxZoom: 19});
    osm.on("tileerror", function () {
      if (++fails >= 4 && !switched) {
        switched = true; map.removeLayer(osm);
        L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}",
          {attribution: "Tiles © Esri", maxZoom: 19}).addTo(map);
      }
    });
    osm.addTo(map);
    const layer = L.layerGroup().addTo(map), meLayer = L.layerGroup().addTo(map);
    for (const g of R) {
      L.circle([g[0], g[1]], {radius: g[2], weight: 2, color: "#fff", fillColor: RCOLOR, fillOpacity: 0.6})
        .bindTooltip(g[3], {permanent: true, direction: "center", className: "rlabel-l"}).bindPopup(g[4]).addTo(map);
    }
    for (const w of W) {
      L.circleMarker([w[0], w[1]], {radius: 5 + Math.sqrt(w[2]) * 1.2, weight: 1, color: "#fff", fillColor: "#eb6834",
        fillOpacity: 0.85}).bindTooltip("풍력발전소 " + w[2] + "MW").addTo(map);
    }
    map.on("dragstart", function () { touched = true; });
    watchResize(function () { map.invalidateSize(); });
    return {
      home: function () { map.setView([33.38, 126.55], 10); },
      name: "OpenStreetMap",
      draw: function () {
        layer.clearLayers();
        for (const p of shown()) {
          L.circleMarker([p[0], p[1]], {radius: p[2] ? 5 : 4, weight: 1, color: "#fff", fillColor: p[2] ? "#2a78d6" : "#9a9a96",
            fillOpacity: 0.9}).bindPopup(popupNode(p)).addTo(layer);
        }
      },
      me: function (lat, lon, label, acc, isGps) {
        meLayer.clearLayers();
        if (acc) L.circle([lat, lon], {radius: acc, color: "#2a78d6", weight: 1, fillOpacity: 0.08}).addTo(meLayer);
        L.circleMarker([lat, lon], {radius: 9, weight: 3, color: "#fff", fillColor: isGps ? "#1251a8" : "#eb6834",
          fillOpacity: 1}).bindTooltip(label).addTo(meLayer);
        map.setView([lat, lon], 14);
      },
      fit: function (pts) {
        if (pts.length) map.fitBounds(L.latLngBounds(pts.map(q => [q[0], q[1]])), {padding: [20, 20], maxZoom: 15});
      }
    };
  });
}

function withTimeout(promise, ms) {
  return Promise.race([promise, new Promise(function (_, bad) { setTimeout(function () { bad(new Error("timeout")); }, ms); })]);
}

// ---------- 목록·위치 (어떤 지도든 같은 방식)
function showList(lat, lon, label) {
  const box = $("list"); box.innerHTML = "";
  const h = document.createElement("div"); h.style.margin = "6px 0";
  const hb = document.createElement("b"); hb.textContent = label + " 가까운 충전소" + (quickOnly ? " (급속)" : "");
  h.appendChild(hb); box.appendChild(h);
  for (const [d, p] of nearest(lat, lon, 5)) {
    const row = document.createElement("div"); row.className = "row";
    const left = document.createElement("div");
    const n = document.createElement("b"); n.textContent = p[3]; left.appendChild(n);
    const s = document.createElement("span"); s.className = p[2] ? "q" : "s";
    s.textContent = "  " + d.toFixed(1) + "km · " + (p[2] ? "급속 " + p[4] + "대" : "완속만");
    left.appendChild(s);
    const a = document.createElement("a"); a.href = route(p); a.target = "_blank"; a.rel = "noopener";
    a.textContent = "여기까지 길찾기 ↗";
    row.appendChild(left); row.appendChild(a); box.appendChild(row);
  }
}
function showAt(lat, lon, label, acc, isGps) {
  last = [lat, lon, label, acc, isGps];
  showList(lat, lon, label);
  if (eng) eng.me(lat, lon, label, acc, isGps);
}
function useHome(reason) {
  if (HOME) {
    say(reason + " 저장한 내 동네(" + HOME.name + ") 중심으로 보여 드려요.", "warn");
    showAt(HOME.lat, HOME.lon, "내 동네(" + HOME.name + ")", 0, false);
  } else {
    say(reason + " 오른쪽 '에너지 도우미' 맨 위 '👤 내 정보'에 동네를 저장하면 그 기준으로 보여 드려요.", "warn");
  }
}
$("gps").onclick = function () {
  if (!navigator.geolocation) { useHome("이 브라우저는 위치를 지원하지 않아요."); return; }
  say("위치를 확인하고 있어요… (브라우저가 허용을 물으면 '허용'을 눌러 주세요)");
  navigator.geolocation.getCurrentPosition(function (pos) {
    const c = pos.coords;
    if (c.latitude < 33.0 || c.latitude > 34.2 || c.longitude < 126.0 || c.longitude > 127.1) {
      // GPS는 잡혔지만 제주 밖(예: 육지에서 시연)일 때: 잡힌 것은 알려 주고, 충전소는 제주에만 있으니 저장한 동네로 보여 줌
      const far = Math.round(km(c.latitude, c.longitude, 33.4996, 126.5312));
      useHome("📍 GPS로 위치는 확인했어요. 지금은 제주에서 약 " + far + "km 떨어진 곳이에요(충전소 정보는 제주만 있어요).");
      return;
    }
    say("📍 내 위치(정확도 약 " + Math.round(c.accuracy) + "m)를 기준으로 보여 드려요. 위치는 이 화면에서만 쓰고 저장하지 않아요.", "ok");
    showAt(c.latitude, c.longitude, "지금 내 위치", Math.min(c.accuracy, 2000), true);
  }, function (e) {
    const why = e.code === 1 ? "위치 사용이 허용되지 않았어요(주소창 왼쪽 아이콘 → 위치 → 허용)."
      : (e.code === 3 ? "위치 확인이 오래 걸려요."
      : "위치를 확인할 수 없어요(컴퓨터의 위치 서비스가 꺼져 있을 수 있어요).");
    useHome(why);
  }, {enableHighAccuracy: true, timeout: 10000, maximumAge: 60000});
};
$("warnX").onclick = function () { $("warn").className = ""; };
$("quick").onclick = function () {
  quickOnly = !quickOnly;
  // 켜졌는지 한눈에 보이도록: 끔 = 흰 바탕, 켬 = 초록 바탕 + ✓
  this.textContent = quickOnly ? "✓ 급속만 보기: 켬" : "급속만 보기: 끔";
  this.className = quickOnly ? "on" : "sub";
  this.setAttribute("aria-pressed", quickOnly ? "true" : "false");
  if (eng) eng.draw();
  if (last) showAt.apply(null, last);
};

// ---------- 시작: 카카오맵 → (실패) OpenStreetMap → (실패) 목록만
// '잉여 예보'·'충전소 전체'는 제주 본섬에 맞춤 (추자도처럼 멀리 떨어진 점 때문에 섬이 작게 보이지 않게)
function fitPoints() {
  if (MODE === "all" || MODE === "surplus") return [[33.19, 126.15], [33.57, 126.97]];
  const pts = shown().map(p => [p[0], p[1]]);
  if (MODE === "all" || MODE === "surplus") for (const w of W) pts.push([w[0], w[1]]);
  for (const g of R) pts.push([g[0], g[1]]);
  if (MODE === "focus" && HOME) pts.push([HOME.lat, HOME.lon]);
  return pts;
}
function ready(api) {
  eng = api; eng.draw();
  $("engine").textContent = "지도: " + api.name;
  if (last) eng.me.apply(null, last);
  if (MODE !== "near" && $("map").clientWidth) eng.fit(fitPoints());   // 제주 전체·답변 지도는 점이 모두 보이게 맞춤
}
function noMap() {
  $("map").style.display = "none";
  say("지도 그림을 불러오지 못했어요. 가까운 충전소 목록과 길찾기는 그대로 쓸 수 있어요.", "warn");
}
const startMap = KKEY
  ? withTimeout(makeKakao(), 5000).catch(function () {
      $("map").innerHTML = "";
      $("engine").textContent = "카카오맵을 불러오지 못해 기본 지도로 바꿨어요.";
      return makeLeaflet();
    })
  : makeLeaflet();
startMap.then(ready).catch(noMap);
// 모드: near = 내 주변(GPS·목록) / all = 제주 전체(GPS·목록 없음) / focus = 답변에서 찾은 충전소만
if (MODE !== "near") { $("gps").style.display = "none"; $("kksearch").style.display = "none"; }
const nQ = P.filter(p => p[2]).length;
if (MODE === "all") {
  $("list").style.display = "none";
  $("legend").textContent = "🔵 급속 " + nQ.toLocaleString() + "곳 · ⚪ 완속만 " + (P.length - nQ).toLocaleString() +
    "곳 · 🟠 풍력발전소 · 숫자 원 = 여러 곳 모임(누르면 확대) · 허브 862·472";
} else if (MODE === "surplus") {
  $("list").style.display = "none"; $("quick").style.display = "none";
  if (D.badge) {
    const dot = document.createElement("span"); dot.className = "bd"; dot.style.background = RCOLOR;
    const t = document.createElement("span"); t.textContent = D.badge;
    $("badge").appendChild(dot); $("badge").appendChild(t);
  }
  $("legend").textContent = "원 크기 = 권역 재생에너지 설비(허브 123 태양광 + 풍력발전현황) · 🔵 급속 충전소(허브 862) · 🟠 풍력발전소";
} else if (MODE === "focus") {
  $("list").style.display = "none"; $("quick").style.display = "none";
  $("legend").textContent = "🟠 찾은 동네 중심 · 🔵 급속 있음 · ⚪ 완속만";
  if (HOME) showAt(HOME.lat, HOME.lon, HOME.name, 0, false);
} else if (HOME) { showAt(HOME.lat, HOME.lon, "내 동네(" + HOME.name + ")", 0, false); }
else { say("'📍 내 위치로 찾기'를 누르면 가까운 충전소와 길찾기를 보여 드려요."); }
</script></body></html>"""


def nearby_map_html(chargers, wind=None, home: dict | None = None, height: int = 430, kakao_key: str | None = None,
                    mode: str = "near", regions: list | None = None, region_color: str | None = None,
                    badge: str | None = None) -> str:
    """mode: 'near'(내 주변: GPS 버튼·가까운 5곳 목록) / 'all'(제주 전체: 모든 점, 목록 없음)
    / 'focus'(답변에서 찾은 충전소만, home=찾은 동네 중심) / 'surplus'(잉여 예보 지도: 권역 원 regions + 급속 충전소).
    focus 를 뺀 모드는 iframe 높이를 꽉 채움(화면 크기에 맞춰 지도 높이가 바뀜). height 는 focus 에서만 씀.
    chargers: name·lat·lon·quick·quick_count 열이 있는 표. wind: lat·lon·mw 표(선택).
    home: {'name': '노형', 'lat': .., 'lon': ..} — 저장한 내 동네 (없으면 None).
    kakao_key: 카카오 JavaScript 키 (없으면 OpenStreetMap). 브라우저용 공개 키이며 등록한 앱 주소에서만 동작."""
    pts = [[round(float(r.lat), 5), round(float(r.lon), 5), int(bool(r.quick)), str(r.name).strip(), int(r.quick_count)]
           for r in chargers.itertuples()]
    wd = [] if wind is None else [[round(float(r.lat), 5), round(float(r.lon), 5), float(r.mw)] for r in wind.itertuples()]
    data = json.dumps({"p": pts, "w": wd, "home": home, "kakao_key": (kakao_key or None),
                       "mode": mode if mode in ("near", "all", "focus", "surplus") else "near",
                       # 잉여 예보 지도: [[위도, 경도, 반지름(m), 이름표, 누르면 나오는 글], ...], 색 = 섬 전체 잉여 가능성
                       "regions": regions or [], "region_color": region_color, "badge": badge},
                      ensure_ascii=False).replace("</", "<\\/")
    return (_PAGE.replace("__LEAFLET_CSS__", LEAFLET_CSS).replace("__LEAFLET_JS__", LEAFLET_JS)
            .replace("__KAKAO_SDK__", KAKAO_SDK).replace("__HEIGHT__", str(int(height))).replace("__DATA__", data))
