from __future__ import annotations

import pandas as pd
import pytest

from trade_dashboard.storage import (
    atomic_write_csv,
    empty_frame,
    merge_trade_frames,
    read_trade_csv,
    retain_recent_months,
    validate_trade_frame,
)


def monthly_row(period="2026-07", export=100, imports=60):
    return pd.DataFrame(
        [
            {
                "period": period,
                "export_usd": export,
                "import_usd": imports,
                "balance_usd": export - imports,
                "export_count": 1,
                "import_count": 1,
                "source": "test",
            }
        ]
    )


def test_header_only_csv_is_empty(tmp_path):
    path = tmp_path / "trade_monthly.csv"
    empty_frame("monthly").to_csv(path, index=False)
    assert read_trade_csv(path, "monthly").empty


def test_merge_replaces_same_period():
    merged = merge_trade_frames(monthly_row(export=100), monthly_row(export=120), "monthly")
    assert len(merged) == 1
    assert merged.iloc[0]["export_usd"] == 120


def test_atomic_write_and_backup(tmp_path):
    path = tmp_path / "trade_monthly.csv"
    assert atomic_write_csv(path, monthly_row(), "monthly") is True
    assert atomic_write_csv(path, monthly_row(export=110), "monthly") is True
    backups = list((tmp_path / "backups").glob("trade_monthly-*.csv"))
    assert backups
    assert read_trade_csv(path, "monthly").iloc[0]["export_usd"] == 110


def test_invalid_balance_rejected():
    frame = monthly_row()
    frame.loc[0, "balance_usd"] = 999
    with pytest.raises(ValueError, match="무역수지"):
        validate_trade_frame(frame, "monthly")


def test_only_latest_60_months_are_retained():
    periods = pd.period_range("2021-07", periods=61, freq="M")
    frames = [monthly_row(period=f"{period.year:04d}-{period.month:02d}") for period in periods]
    retained = retain_recent_months(pd.concat(frames, ignore_index=True), 60)
    assert retained["period"].nunique() == 60
    assert retained["period"].min() == "2021-08"
