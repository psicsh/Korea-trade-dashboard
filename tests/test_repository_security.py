from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_sensitive_files_are_ignored():
    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    for name in [".streamlit/secrets.toml", ".env", "secrets.toml"]:
        assert name in ignore


def test_repository_contains_no_probable_service_key_literal():
    probable_key = re.compile(r"(?<![A-Za-z0-9+/])[A-Za-z0-9+/]{80,}={0,2}(?![A-Za-z0-9+/])")
    skip_suffixes = {".xlsx", ".png", ".jpg", ".zip", ".pyc"}
    for path in ROOT.rglob("*"):
        if not path.is_file() or path.suffix.lower() in skip_suffixes or ".git" in path.parts:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        assert not probable_key.search(text), f"인증키로 의심되는 긴 문자열: {path.relative_to(ROOT)}"


def test_no_num_of_rows_parameter():
    source = (ROOT / "trade_dashboard" / "api.py").read_text(encoding="utf-8")
    assert "numOfRows" not in source
