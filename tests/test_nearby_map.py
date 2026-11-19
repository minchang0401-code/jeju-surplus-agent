"""내 주변 지도: GPS → 실패하면 저장한 동네 → 카카오맵 길찾기."""
import re
import shutil
import subprocess

import pandas as pd
import pytest

import tools
from nearby_map import nearby_map_html


def _html(home=True):
    g = tools.charger_places().head(300)
    w = pd.DataFrame({"lat": [33.5], "lon": [126.8], "mw": [30.0]})
    lat, lon = tools.PLACE_COORDS["노형"]
    return nearby_map_html(g, w, {"name": "노형", "lat": lat, "lon": lon} if home else None)


def test_three_ways_are_in_page():
    h = _html()
    assert "navigator.geolocation.getCurrentPosition" in h          # 1) GPS
    assert "useHome(" in h and '"home": {"name": "노형"' in h         # 2) 저장한 동네로 대신
    assert "https://map.kakao.com/link/to/" in h                    # 3) 카카오맵 길찾기
    assert "저장하지 않아요" in h                                       # 위치를 저장하지 않는다는 안내


def test_names_cannot_break_script():
    g = pd.DataFrame({"name": ["</script><b>x"], "lat": [33.48], "lon": [126.47], "quick": [True], "quick_count": [1]})
    h = nearby_map_html(g, None, None)
    script = re.findall(r"<script>(.*?)</script>", h, re.S)[0]
    assert "</script><b>" not in script


def test_route_link_from_tools():
    c = tools.find_chargers("노형", quick_only=True)["chargers"][0]
    assert c["route_link"].startswith("https://map.kakao.com/link/to/")
    assert tools.kakao_route("a,b", 33.5, 126.5).count(",") == 2      # 이름 속 쉼표가 형식을 깨지 않음


@pytest.mark.skipif(shutil.which("node") is None, reason="node 가 없으면 자바스크립트 문법 검사는 건너뜀")
def test_javascript_syntax(tmp_path):
    js = re.findall(r"<script>(.*?)</script>", _html(), re.S)[0]
    f = tmp_path / "m.js"
    f.write_text(js, encoding="utf-8")
    assert subprocess.run(["node", "--check", str(f)], capture_output=True).returncode == 0


def test_kakao_only_with_key_and_falls_back():
    g = tools.charger_places().head(50)
    with_key = nearby_map_html(g, None, None, kakao_key="TEST")
    no_key = nearby_map_html(g, None, None)
    assert '"kakao_key": "TEST"' in with_key and '"kakao_key": null' in no_key
    assert "dapi.kakao.com/v2/maps/sdk.js" in with_key
    assert "makeLeaflet()" in with_key                       # 카카오맵 실패 시 OpenStreetMap


def test_whole_island_and_answer_maps_use_same_map():
    g = tools.charger_places().head(80)
    lat, lon = tools.PLACE_COORDS["노형"]
    whole = nearby_map_html(g, None, None, kakao_key="TEST", mode="all")
    focus = nearby_map_html(g.head(5), None, {"name": "노형 중심", "lat": lat, "lon": lon}, kakao_key="TEST", mode="focus")
    assert '"mode": "all"' in whole and '"mode": "focus"' in focus
    for h in (whole, focus):
        assert "dapi.kakao.com/v2/maps/sdk.js" in h and "makeLeaflet()" in h   # 카카오맵 → OpenStreetMap
        assert "eng.fit(fitPoints())" in h                                     # 점이 모두 보이게 맞춤
    assert '"mode": "near"' in nearby_map_html(g, None, None, mode="이상한값")   # 모르는 값은 내 주변으로


def test_outside_jeju_warning_is_red_banner_over_map():
    h = _html()
    assert 'id="warn" role="alert"' in h and "#d32f2f" in h        # 빨간 안내 상자
    assert 'useHome("📍 GPS로 위치는 확인했어요' in h                   # 제주 밖이면 잡힌 거리 안내
    assert "position:absolute" in h                                  # 지도 위에 겹쳐 높이가 늘지 않음


def test_surplus_mode_and_fill_layout():
    """잉여 예보 지도도 같은 지도(카카오맵 → OpenStreetMap)로 그리고, focus 를 뺀 모드는 iframe 높이를 꽉 채움."""
    g = tools.charger_places().head(30)
    regs = [[33.47, 126.53, 5000.0, "제주시 동지역\n300MW", "설명"]]
    h = nearby_map_html(g, None, None, kakao_key="TEST", mode="surplus", regions=regs, region_color="rgb(1,2,3)")
    assert '"mode": "surplus"' in h and '"region_color": "rgb(1,2,3)"' in h and "for (const g of R)" in h
    assert 'if (MODE !== "focus") document.documentElement.className = "fill"' in h
    assert "html.fill #map{height:100%" in h


def test_quick_and_slow_look_different():
    """급속(파란 점)과 완속(보라 고리)이 모양·색으로 구분되고, 지금 무엇을 보는지 범례에 나옴."""
    h = _html()
    assert 'QUICK = "#2a78d6", SLOW = "#5a4fcf"' in h and "fill=\"white\" stroke=\"' + SLOW" in h
    assert "지금: 급속만 보는 중" in h and "지금: 전체 보는 중" in h
