"""내 주변 충전소 지도 — 화면(app.py)의 '📍 내 주변' 탭.

세 가지가 함께 동작하도록 만들었습니다.
1) GPS: '📍 내 위치로 찾기'를 누르면 브라우저가 위치 허용을 묻고, 허용하면 내 위치와 가까운 충전소 5곳을 보여 줌
2) GPS가 안 되면(거부·미지원·차단) 저장한 '내 동네' 대표 좌표로 대신 보여 줌
3) 충전소마다 카카오맵 '여기까지 길찾기' 링크 — 카카오맵이 휴대폰의 현재 위치에서 길을 안내
위치는 브라우저 안에서만 계산하고 서버로 보내거나 저장하지 않습니다.
지도 라이브러리(Leaflet)를 불러오지 못해도 가까운 충전소 목록과 길찾기 링크는 그대로 나옵니다.
"""
from __future__ import annotations

import json

LEAFLET_JS = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"
LEAFLET_CSS = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"


def nearby_map_html(chargers, wind=None, home: dict | None = None, height: int = 430) -> str:
    """chargers: name·lat·lon·quick·quick_count 열이 있는 표. wind: lat·lon·mw 표(선택).
    home: {'name': '노형', 'lat': .., 'lon': ..} — 저장한 내 동네 (없으면 None)."""
    pts = [[round(float(r.lat), 5), round(float(r.lon), 5), int(bool(r.quick)), str(r.name).strip(), int(r.quick_count)]
           for r in chargers.itertuples()]
    wd = [] if wind is None else [[round(float(r.lat), 5), round(float(r.lon), 5), float(r.mw)] for r in wind.itertuples()]
    data = json.dumps({"p": pts, "w": wd, "home": home}, ensure_ascii=False).replace("</", "<\\/")
    return f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="stylesheet" href="{LEAFLET_CSS}">
<style>
 body{{margin:0;font-family:"Noto Sans KR",system-ui,-apple-system,sans-serif;color:#1b1b1b;font-size:15px}}
 .bar{{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:2px 0 8px}}
 button{{font-size:15px;padding:8px 14px;border-radius:10px;border:1px solid #2a78d6;background:#2a78d6;color:#fff;cursor:pointer}}
 button.sub{{background:#fff;color:#2a78d6}}
 #msg{{color:#52514e;font-size:14px}}
 #map{{height:{height}px;border-radius:12px;background:#e8eff3}}
 #list{{margin-top:8px}}
 .row{{display:flex;justify-content:space-between;gap:8px;padding:8px 2px;border-bottom:1px solid #e4e3df}}
 .row b{{font-weight:600}} .q{{color:#2a78d6}} .s{{color:#7a7974}}
 a{{color:#2a78d6;white-space:nowrap}}
</style></head><body>
<div class="bar">
 <button id="gps">📍 내 위치로 찾기</button>
 <button class="sub" id="quick">급속만 보기: 끔</button>
 <a target="_blank" rel="noopener" href="https://map.kakao.com/link/search/%EC%A0%84%EA%B8%B0%EC%B0%A8%EC%B6%A9%EC%A0%84%EC%86%8C">카카오맵에서 내 주변 충전소 검색 ↗</a>
</div>
<div id="msg"></div>
<div id="map"></div>
<div id="list"></div>
<script src="{LEAFLET_JS}"></script>
<script>
const D = {data};
const P = D.p, W = D.w, HOME = D.home;
let quickOnly = false, map = null, layer = null, meLayer = null, last = null;
const $ = (id) => document.getElementById(id);
function say(t) {{ $("msg").textContent = t; }}
function km(a, b, c, d) {{
  const R = 6371, r = Math.PI / 180, x = (c - a) * r, y = (d - b) * r;
  const h = Math.sin(x / 2) ** 2 + Math.cos(a * r) * Math.cos(c * r) * Math.sin(y / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(h));
}}
function route(p) {{ return "https://map.kakao.com/link/to/" + encodeURIComponent(p[3].replace(/,/g, " ")) + "," + p[0] + "," + p[1]; }}
function nearest(lat, lon, k) {{
  return P.filter(p => !quickOnly || p[2]).map(p => [km(lat, lon, p[0], p[1]), p])
          .sort((a, b) => a[0] - b[0]).slice(0, k);
}}
function drawPoints() {{
  if (!map) return;
  layer.clearLayers();
  for (const p of P) {{
    if (quickOnly && !p[2]) continue;
    const m = L.circleMarker([p[0], p[1]], {{radius: p[2] ? 5 : 4, weight: 1, color: "#fff",
      fillColor: p[2] ? "#2a78d6" : "#9a9a96", fillOpacity: 0.9}});
    const box = document.createElement("div");
    const t = document.createElement("b"); t.textContent = p[3]; box.appendChild(t);
    box.appendChild(document.createElement("br"));
    box.appendChild(document.createTextNode(p[2] ? "급속 " + p[4] + "대 " : "완속만 "));
    const a = document.createElement("a"); a.href = route(p); a.target = "_blank"; a.rel = "noopener";
    a.textContent = "여기까지 길찾기 ↗"; box.appendChild(a);
    m.bindPopup(box); m.addTo(layer);
  }}
  for (const w of W) {{
    L.circleMarker([w[0], w[1]], {{radius: 5 + Math.sqrt(w[2]) * 1.2, weight: 1, color: "#fff",
      fillColor: "#eb6834", fillOpacity: 0.85}}).bindTooltip("풍력발전소 " + w[2] + "MW").addTo(layer);
  }}
}}
function showList(lat, lon, label) {{
  const box = $("list"); box.innerHTML = "";
  const h = document.createElement("div"); h.style.margin = "6px 0";
  h.innerHTML = "<b></b>"; h.firstChild.textContent = label + " 가까운 충전소" + (quickOnly ? " (급속)" : "");
  box.appendChild(h);
  for (const [d, p] of nearest(lat, lon, 5)) {{
    const row = document.createElement("div"); row.className = "row";
    const left = document.createElement("div");
    const n = document.createElement("b"); n.textContent = p[3]; left.appendChild(n);
    const s = document.createElement("span"); s.className = p[2] ? "q" : "s";
    s.textContent = "  " + d.toFixed(1) + "km · " + (p[2] ? "급속 " + p[4] + "대" : "완속만");
    left.appendChild(s);
    const a = document.createElement("a"); a.href = route(p); a.target = "_blank"; a.rel = "noopener";
    a.textContent = "여기까지 길찾기 ↗";
    row.appendChild(left); row.appendChild(a); box.appendChild(row);
  }}
}}
function showAt(lat, lon, label, acc, isGps) {{
  last = [lat, lon, label, acc, isGps];
  showList(lat, lon, label);
  if (!map) return;
  meLayer.clearLayers();
  if (acc) L.circle([lat, lon], {{radius: acc, color: "#2a78d6", weight: 1, fillOpacity: 0.08}}).addTo(meLayer);
  L.circleMarker([lat, lon], {{radius: 9, weight: 3, color: "#fff", fillColor: isGps ? "#1251a8" : "#eb6834",
    fillOpacity: 1}}).bindTooltip(label, {{permanent: false}}).addTo(meLayer);
  map.setView([lat, lon], 14);
}}
function useHome(reason) {{
  if (HOME) {{
    say(reason + " 저장한 내 동네(" + HOME.name + ") 중심으로 보여 드려요.");
    showAt(HOME.lat, HOME.lon, "내 동네(" + HOME.name + ")", 0, false);
  }} else {{
    say(reason + " 왼쪽(휴대폰은 왼쪽 위 '>' 버튼) '👤 내 정보'에 동네를 저장하면 그 기준으로 보여 드려요.");
  }}
}}
$("gps").onclick = function () {{
  if (!navigator.geolocation) {{ useHome("이 브라우저는 위치를 지원하지 않아요."); return; }}
  say("위치를 확인하고 있어요… (브라우저가 허용을 물으면 '허용'을 눌러 주세요)");
  navigator.geolocation.getCurrentPosition(function (pos) {{
    const c = pos.coords;
    if (c.latitude < 33.0 || c.latitude > 34.2 || c.longitude < 126.0 || c.longitude > 127.1) {{
      useHome("지금 위치가 제주 밖이에요.");
      return;
    }}
    say("내 위치(정확도 약 " + Math.round(c.accuracy) + "m)를 기준으로 보여 드려요. 위치는 이 화면에서만 쓰고 저장하지 않아요.");
    showAt(c.latitude, c.longitude, "지금 내 위치", Math.min(c.accuracy, 2000), true);
  }}, function (e) {{
    const why = e.code === 1 ? "위치 사용이 허용되지 않았어요." : (e.code === 3 ? "위치 확인이 오래 걸려요." : "위치를 확인할 수 없어요.");
    useHome(why);
  }}, {{enableHighAccuracy: true, timeout: 10000, maximumAge: 60000}});
}};
$("quick").onclick = function () {{
  quickOnly = !quickOnly; this.textContent = "급속만 보기: " + (quickOnly ? "켬" : "끔");
  drawPoints(); if (last) showAt.apply(null, last);
}};
if (window.L) {{
  map = L.map("map", {{scrollWheelZoom: false}}).setView([33.38, 126.55], 10);
  L.tileLayer("https://{{s}}.basemaps.cartocdn.com/light_all/{{z}}/{{x}}/{{y}}{{r}}.png",
    {{attribution: "© OpenStreetMap contributors © CARTO", maxZoom: 19}}).addTo(map);
  layer = L.layerGroup().addTo(map); meLayer = L.layerGroup().addTo(map);
  drawPoints();
  // 접힌 칸·다른 탭에 있다가 펼쳐지면 지도 크기를 다시 계산 (회색 화면 방지)
  if (window.ResizeObserver) new ResizeObserver(function () {{ map.invalidateSize(); }}).observe($("map"));
}} else {{
  $("map").style.display = "none";
  say("지도 그림을 불러오지 못했어요. 가까운 충전소 목록과 길찾기는 그대로 쓸 수 있어요.");
}}
if (HOME) {{ showAt(HOME.lat, HOME.lon, "내 동네(" + HOME.name + ")", 0, false); }}
else if (!$("msg").textContent) {{ say("'📍 내 위치로 찾기'를 누르면 가까운 충전소와 길찾기를 보여 드려요."); }}
</script></body></html>"""
