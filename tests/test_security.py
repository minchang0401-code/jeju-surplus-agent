"""제출물에 API 키가 들어가지 않았는지 검사."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATTERNS = [re.compile(p) for p in (
    r"AIza[0-9A-Za-z_\-]{30,}",                 # Google(Gemini) API 키
    r"sk-[A-Za-z0-9_\-]{20,}",                  # OpenAI·Anthropic 계열 키
    r"(?i)serviceKey=[0-9A-Za-z%+/=]{20,}",     # 공공데이터포털 키가 주소에 들어간 경우
)]
SKIP_DIRS = {".venv", "venv", "__pycache__", ".git", "_github_upload", "_upload_figs", "_upload_grid", "_to_delete"}


def _files():
    for p in ROOT.rglob("*"):
        if p.is_file() and not (set(p.relative_to(ROOT).parts) & SKIP_DIRS) and p.name != ".env" \
                and p.suffix in {".py", ".md", ".txt", ".json", ".toml", ".example", ".bat", ".command", ".cfg", ".ini"}:
            yield p


def test_no_api_keys_in_files():
    hits = []
    for p in _files():
        text = p.read_text(encoding="utf-8", errors="ignore")
        for pat in PATTERNS:
            if pat.search(text):
                hits.append(f"{p.relative_to(ROOT)}: {pat.pattern}")
    assert not hits, hits


def test_env_is_ignored_and_example_is_empty():
    assert ".env" in (ROOT / ".gitignore").read_text(encoding="utf-8").split()
    for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            v = v.split("#")[0].strip()
            assert v in ("", "gemini", "none"), f"{k} 에 값이 들어 있음"
