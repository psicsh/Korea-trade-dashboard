from __future__ import annotations

import re
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pandas as pd


def normalize_period(value: object) -> str | None:
    """관세청의 YYYYMM/YYY.YY/YYY-MM 값을 YYYY-MM으로 통일한다."""
    text = re.sub(r"[^0-9]", "", str(value or ""))
    if len(text) != 6:
        return None
    year, month = int(text[:4]), int(text[4:])
    if year < 1900 or not 1 <= month <= 12:
        return None
    return f"{year:04d}-{month:02d}"


def compact_period(period: str) -> str:
    normalized = normalize_period(period)
    if not normalized:
        raise ValueError(f"잘못된 연월입니다: {period!r}")
    return normalized.replace("-", "")


def latest_complete_month(today: date | None = None) -> str:
    today = today or datetime.now(ZoneInfo("Asia/Seoul")).date()
    first = pd.Timestamp(today.year, today.month, 1)
    return (first - pd.offsets.MonthBegin(1)).strftime("%Y-%m")


def shift_month(period: str, months: int) -> str:
    normalized = normalize_period(period)
    if not normalized:
        raise ValueError(f"잘못된 연월입니다: {period!r}")
    return (pd.Period(normalized, freq="M") + months).strftime("%Y-%m")


def period_range(start: str, end: str) -> list[str]:
    start_n, end_n = normalize_period(start), normalize_period(end)
    if not start_n or not end_n or start_n > end_n:
        raise ValueError("시작 연월과 종료 연월을 확인해 주세요.")
    return [p.strftime("%Y-%m") for p in pd.period_range(start_n, end_n, freq="M")]


def validate_hs_code(raw: str) -> str:
    code = re.sub(r"\s+", "", raw or "")
    if not code.isdigit() or len(code) not in {2, 4, 6}:
        raise ValueError("HS 코드는 숫자 2자리·4자리·6자리만 입력할 수 있습니다.")
    return code


def to_number(value: object) -> float:
    text = str(value if value is not None else "").strip().replace(",", "")
    if text in {"", "-", "None", "nan"}:
        return 0.0
    try:
        return float(text)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"숫자로 바꿀 수 없는 값입니다: {value!r}") from exc


def safe_hs_text(value: object) -> str:
    raw = str(value or "").strip()
    if re.fullmatch(r"\d+\.0+", raw):
        raw = raw.split(".", 1)[0]
    text = re.sub(r"\D", "", raw)
    if not text:
        return ""
    if len(text) < 10:
        return text.zfill(10)
    return text[:10]
