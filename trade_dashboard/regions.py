from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


def load_region_groups(path: Path) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    groups = payload.get("groups", [])
    if len(groups) != 9:
        raise ValueError("9대 지역 정의에는 정확히 9개 그룹이 있어야 합니다.")
    seen: set[str] = set()
    for group in groups:
        codes = [str(code).upper() for code in group.get("country_codes", [])]
        overlap = seen.intersection(codes)
        if overlap:
            raise ValueError(f"지역 그룹의 국가코드가 중복됩니다: {sorted(overlap)}")
        seen.update(codes)
        group["country_codes"] = codes
    return groups


def aggregate_regions(nations: pd.DataFrame, groups: list[dict]) -> pd.DataFrame:
    columns = [
        "period",
        "region_code",
        "region_name",
        "export_usd",
        "import_usd",
        "balance_usd",
        "source",
    ]
    if nations.empty:
        return pd.DataFrame(columns=columns)
    rows: list[pd.DataFrame] = []
    for group in groups:
        selected = nations[nations["country_code"].isin(group["country_codes"])]
        if selected.empty:
            continue
        summed = selected.groupby("period", as_index=False)[["export_usd", "import_usd"]].sum()
        summed["balance_usd"] = summed["export_usd"] - summed["import_usd"]
        summed["region_code"] = group["code"]
        summed["region_name"] = group["name"]
        summed["source"] = "관세청 국가별 수출입실적 집계"
        rows.append(summed[columns])
    if not rows:
        return pd.DataFrame(columns=columns)
    result = pd.concat(rows, ignore_index=True)
    return result.sort_values(["period", "region_code"]).reset_index(drop=True)
