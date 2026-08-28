from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from .storage import read_trade_csv


def load_monthly(path: Path) -> pd.DataFrame:
    return read_trade_csv(path, "monthly")


def load_industry(path: Path) -> pd.DataFrame:
    return read_trade_csv(path, "industry")


def load_region(path: Path) -> pd.DataFrame:
    return read_trade_csv(path, "region")


def recent_months(frame: pd.DataFrame, months: int) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    periods = sorted(frame["period"].dropna().astype(str).unique())
    keep = set(periods[-months:])
    return frame[frame["period"].astype(str).isin(keep)].copy()


def csv_bytes(frame: pd.DataFrame) -> bytes:
    return frame.to_csv(index=False).encode("utf-8-sig")


def read_status(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
