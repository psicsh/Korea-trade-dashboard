from __future__ import annotations

import pandas as pd

from trade_dashboard.mti import aggregate_industries, related_major_industries
from trade_dashboard.regions import aggregate_regions


def test_industry_aggregation_and_related_names():
    hs = pd.DataFrame(
        [
            {
                "period": "2026-07",
                "hs_code": "8542311000",
                "hs_name": "IC",
                "export_usd": 100,
                "import_usd": 40,
                "balance_usd": 60,
            },
            {
                "period": "2026-07",
                "hs_code": "3304991000",
                "hs_name": "화장품",
                "export_usd": 20,
                "import_usd": 5,
                "balance_usd": 15,
            },
        ]
    )
    mapping = pd.DataFrame(
        [
            {"hsk10": "8542311000", "mti_code": "831110"},
            {"hsk10": "3304991000", "mti_code": "227310"},
        ]
    )
    major = pd.DataFrame(
        [
            {"industry_code": "SEMICON", "industry_name": "반도체", "mti_prefixes": "831", "display_order": 1},
            {"industry_code": "COSMETICS", "industry_name": "화장품", "mti_prefixes": "2273", "display_order": 2},
        ]
    )
    result = aggregate_industries(hs, mapping, major)
    assert set(result["industry_name"]) == {"반도체", "화장품"}
    assert related_major_industries("8542", mapping, major) == ["반도체"]


def test_region_aggregation():
    nations = pd.DataFrame(
        [
            {
                "period": "2026-07",
                "country_code": "US",
                "country_name": "미국",
                "export_usd": 10,
                "import_usd": 6,
                "balance_usd": 4,
            },
            {
                "period": "2026-07",
                "country_code": "CA",
                "country_name": "캐나다",
                "export_usd": 4,
                "import_usd": 3,
                "balance_usd": 1,
            },
        ]
    )
    groups = [
        {"code": "US", "name": "미국", "country_codes": ["US"]},
        {"code": "OTHER", "name": "기타", "country_codes": ["CA"]},
    ]
    result = aggregate_regions(nations, groups)
    assert result["export_usd"].sum() == 14
    assert result["balance_usd"].sum() == 5
