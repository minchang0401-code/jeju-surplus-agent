"""pytest 공통 설정 — 키·인터넷 없이 같은 결과가 나오도록 LLM 호출을 끕니다.

    pip install pytest
    python -m pytest            (프로젝트 폴더에서)
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def no_llm(monkeypatch):
    """.env 에 LLM 키가 있어도 시험 중에는 Gemini 를 부르지 않음 (규칙 기반 모드로 재현)."""
    import agent
    monkeypatch.setattr(agent, "_llm_config", lambda: None)
    yield
