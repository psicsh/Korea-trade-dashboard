from __future__ import annotations

import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from .utils import normalize_period

CSV_SPECS: dict[str, dict[str, Any]] = {
    "monthly": {
        "columns": [
            "period",
            "export_usd",
            "import_usd",
            "balance_usd",
            "export_count",
            "import_count",
            "source",
        ],
        "keys": ["period"],
    },
    "industry": {
        "columns": [
            "period",
            "industry_code",
            "industry_name",
            "export_usd",
            "import_usd",
            "balance_usd",
            "source",
        ],
        "keys": ["period", "industry_code"],
    },
    "region": {
        "columns": [
            "period",
            "region_code",
            "region_name",
            "export_usd",
            "import_usd",
            "balance_usd",
            "source",
        ],
        "keys": ["period", "region_code"],
    },
}


def empty_frame(kind: str) -> pd.DataFrame:
    return pd.DataFrame(columns=CSV_SPECS[kind]["columns"])


def read_trade_csv(path: Path, kind: str) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return empty_frame(kind)
    frame = pd.read_csv(path, dtype={"period": "string"})
    missing = set(CSV_SPECS[kind]["columns"]) - set(frame.columns)
    if missing:
        raise ValueError(f"{path.name}에 필수 열이 없습니다: {', '.join(sorted(missing))}")
    frame = frame[CSV_SPECS[kind]["columns"]].copy()
    for column in ["export_usd", "import_usd", "balance_usd"]:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    if kind == "monthly":
        for column in ["export_count", "import_count"]:
            frame[column] = pd.to_numeric(frame[column], errors="coerce").fillna(0).astype("int64")
    return frame


def validate_trade_frame(frame: pd.DataFrame, kind: str, *, allow_empty: bool = False) -> None:
    spec = CSV_SPECS[kind]
    missing = set(spec["columns"]) - set(frame.columns)
    if missing:
        raise ValueError(f"필수 열이 없습니다: {', '.join(sorted(missing))}")
    if frame.empty:
        if allow_empty:
            return
        raise ValueError("저장할 데이터가 비어 있습니다.")
    periods = frame["period"].map(normalize_period)
    if periods.isna().any() or not periods.eq(frame["period"].astype(str)).all():
        raise ValueError("period는 YYYY-MM 형식이어야 합니다.")
    if frame.duplicated(spec["keys"]).any():
        raise ValueError("동일한 기준월과 분류코드가 중복되어 있습니다.")
    for column in ["export_usd", "import_usd", "balance_usd"]:
        numeric = pd.to_numeric(frame[column], errors="coerce")
        if numeric.isna().any():
            raise ValueError(f"{column}에 숫자가 아닌 값이 있습니다.")
    if (pd.to_numeric(frame["export_usd"]) < 0).any() or (pd.to_numeric(frame["import_usd"]) < 0).any():
        raise ValueError("수출액과 수입액은 음수가 될 수 없습니다.")
    expected = pd.to_numeric(frame["export_usd"]) - pd.to_numeric(frame["import_usd"])
    actual = pd.to_numeric(frame["balance_usd"])
    tolerance = (expected.abs() * 1e-8).clip(lower=2.0)
    if ((expected - actual).abs() > tolerance).any():
        raise ValueError("무역수지가 수출액-수입액과 일치하지 않습니다.")


def merge_trade_frames(existing: pd.DataFrame, incoming: pd.DataFrame, kind: str) -> pd.DataFrame:
    columns = CSV_SPECS[kind]["columns"]
    keys = CSV_SPECS[kind]["keys"]
    combined = pd.concat([existing[columns], incoming[columns]], ignore_index=True)
    combined = combined.drop_duplicates(keys, keep="last")
    return combined.sort_values(keys).reset_index(drop=True)


def _backup_existing(path: Path, keep: int = 3) -> Path | None:
    if not path.exists() or path.stat().st_size == 0:
        return None
    backup_dir = path.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = backup_dir / f"{path.stem}-{timestamp}{path.suffix}"
    shutil.copy2(path, backup)
    old = sorted(backup_dir.glob(f"{path.stem}-*{path.suffix}"), reverse=True)
    for stale in old[keep:]:
        stale.unlink(missing_ok=True)
    return backup


def atomic_write_csv(path: Path, frame: pd.DataFrame, kind: str) -> bool:
    frame = frame[CSV_SPECS[kind]["columns"]].copy()
    validate_trade_frame(frame, kind)
    path.parent.mkdir(parents=True, exist_ok=True)

    existing_bytes = path.read_bytes() if path.exists() else None
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.stem}-", suffix=".csv", dir=path.parent)
    os.close(fd)
    temp_path = Path(temp_name)
    try:
        frame.to_csv(temp_path, index=False, encoding="utf-8")
        # 쓰기 직전 다시 읽어 CSV 직렬화 과정까지 검증한다.
        validate_trade_frame(read_trade_csv(temp_path, kind), kind)
        new_bytes = temp_path.read_bytes()
        if existing_bytes == new_bytes:
            temp_path.unlink(missing_ok=True)
            return False
        _backup_existing(path)
        os.replace(temp_path, path)
        return True
    finally:
        temp_path.unlink(missing_ok=True)


def merge_and_write_csv(path: Path, incoming: pd.DataFrame, kind: str) -> bool:
    existing = read_trade_csv(path, kind)
    merged = merge_trade_frames(existing, incoming, kind)
    return atomic_write_csv(path, merged, kind)


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.stem}-", suffix=".json", dir=path.parent)
    os.close(fd)
    temp_path = Path(temp_name)
    try:
        temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        json.loads(temp_path.read_text(encoding="utf-8"))
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)
