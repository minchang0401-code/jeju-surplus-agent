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
