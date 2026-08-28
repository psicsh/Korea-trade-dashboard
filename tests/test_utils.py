from datetime import date

import pytest

from trade_dashboard.utils import (
    compact_period,
    latest_complete_month,
    normalize_period,
    period_range,
    validate_hs_code,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("202607", "2026-07"), ("2026.07", "2026-07"), ("2026-07", "2026-07")],
)
def test_normalize_period(raw, expected):
    assert normalize_period(raw) == expected


def test_period_helpers():
    assert compact_period("2026-07") == "202607"
    assert period_range("2026-05", "2026-07") == ["2026-05", "2026-06", "2026-07"]
    assert latest_complete_month(date(2026, 8, 28)) == "2026-07"


@pytest.mark.parametrize("code", ["85", "8542", "854231"])
def test_validate_hs_code(code):
    assert validate_hs_code(code) == code


@pytest.mark.parametrize("code", ["8", "854", "85423100", "85A2", ""])
def test_invalid_hs_code(code):
    with pytest.raises(ValueError, match="2자리·4자리·6자리"):
        validate_hs_code(code)
