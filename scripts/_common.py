from __future__ import annotations

import os
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from trade_dashboard.api import PublicDataAuthError, PublicDataClient  # noqa: E402
from trade_dashboard.config import SERVICE_KEY_NAME  # noqa: E402
from trade_dashboard.utils import normalize_period, shift_month  # noqa: E402


def client_from_environment() -> PublicDataClient:
    key = os.environ.get(SERVICE_KEY_NAME, "").strip()
    if not key:
        raise PublicDataAuthError(f"환경변수 {SERVICE_KEY_NAME}가 없습니다. GitHub Actions Secret을 설정해 주세요.")
    return PublicDataClient(key)


def month_chunks(start: str, end: str, size: int = 12) -> list[tuple[str, str]]:
    start_n, end_n = normalize_period(start), normalize_period(end)
    if not start_n or not end_n or start_n > end_n:
        raise ValueError("조회기간을 확인해 주세요.")
    chunks: list[tuple[str, str]] = []
    cursor = start_n
    while cursor <= end_n:
        chunk_end = min(shift_month(cursor, size - 1), end_n)
        chunks.append((cursor, chunk_end))
        cursor = shift_month(chunk_end, 1)
    return chunks


def concat(frames: list[pd.DataFrame], columns: list[str] | None = None) -> pd.DataFrame:
    nonempty = [frame for frame in frames if not frame.empty]
    if not nonempty:
        return pd.DataFrame(columns=columns or [])
    return pd.concat(nonempty, ignore_index=True)


def log(message: str) -> None:
    print(f"[korea-trade] {message}", flush=True)
