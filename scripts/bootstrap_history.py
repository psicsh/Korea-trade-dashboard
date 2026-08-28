#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone

from _common import client_from_environment, concat, log, month_chunks

from trade_dashboard.config import (
    INDUSTRY_CSV,
    MONTHLY_CSV,
    MTI_MAJOR_CSV,
    MTI_MAPPING_XLSX,
    REGION_CSV,
    REGION_GROUPS_JSON,
    UPDATE_STATUS_JSON,
)
from trade_dashboard.mti import aggregate_industries, load_major_codes, load_mti_mapping
from trade_dashboard.regions import aggregate_regions, load_region_groups
from trade_dashboard.storage import atomic_write_json, merge_and_write_csv
from trade_dashboard.utils import latest_complete_month, period_range, shift_month


def parse_args() -> argparse.Namespace:
    latest = latest_complete_month()
    parser = argparse.ArgumentParser(description="한국무역 대시보드 최근 5년 자료 구축")
    parser.add_argument("--end", default=latest, help="종료월(YYYY-MM), 기본값: 전월")
    parser.add_argument("--skip-industries", action="store_true", help="20대 품목 최초 구축 생략")
    return parser.parse_args()


def fetch_total(client, start: str, end: str):
    frames = []
    # 최근 5년도 관세청 응답 부담을 줄이기 위해 1년씩 조회한다.
    for chunk_start, chunk_end in month_chunks(start, end, size=12):
        log(f"전체무역 {chunk_start}~{chunk_end} 조회")
        frames.append(client.fetch_total(chunk_start, chunk_end))
    return concat(frames)


def fetch_regions(client, start: str, end: str):
    groups = load_region_groups(REGION_GROUPS_JSON)
    frames = []
    for chunk_start, chunk_end in month_chunks(start, end, size=12):
        log(f"9대 지역 기초자료 {chunk_start}~{chunk_end} 조회")
        nations = client.fetch_nations(chunk_start, chunk_end)
        frames.append(aggregate_regions(nations, groups))
    result = concat(frames)
    if not result.empty:
        counts = result.groupby("period")["region_code"].nunique()
        if (counts != 9).any():
            bad = ", ".join(counts[counts != 9].index.astype(str).tolist()[:5])
            raise RuntimeError(f"9대 지역이 모두 집계되지 않은 월이 있습니다: {bad}")
    return result


def fetch_industries(client, start: str, end: str):
    mapping = load_mti_mapping(MTI_MAPPING_XLSX)
    major = load_major_codes(MTI_MAJOR_CSV)
    frames = []
    months = period_range(start, end)
    for index, month in enumerate(months, start=1):
        log(f"20대 품목 {month} HSK 원자료 조회 ({index}/{len(months)})")
        hs_rows = client.fetch_hs(month, month)
        if hs_rows.empty:
            raise RuntimeError(f"{month} 전체 HSK 자료가 비어 있습니다.")
        aggregated = aggregate_industries(hs_rows, mapping, major)
        if aggregated.empty:
            raise RuntimeError(f"{month} 20대 품목 집계 결과가 비어 있습니다.")
        frames.append(aggregated)
    return concat(frames)


def main() -> int:
    args = parse_args()
    client = client_from_environment()
    changed: dict[str, bool] = {}
    start = shift_month(args.end, -59)

    monthly = fetch_total(client, start, args.end)
    if monthly.empty or args.end not in set(monthly["period"]):
        raise RuntimeError("종료월 전체무역 자료를 받지 못했습니다.")
    changed["monthly"] = merge_and_write_csv(MONTHLY_CSV, monthly, "monthly")

    regions = fetch_regions(client, start, args.end)
    if regions.empty:
        raise RuntimeError("9대 지역 자료를 받지 못했습니다.")
    changed["region"] = merge_and_write_csv(REGION_CSV, regions, "region")

    if args.skip_industries:
        changed["industry"] = False
        industry_note = "사용자 선택으로 생략"
    else:
        industry_start = max("2022-01", start)
        industries = fetch_industries(client, industry_start, args.end)
        if industries.empty:
            raise RuntimeError("20대 품목 자료를 만들지 못했습니다.")
        changed["industry"] = merge_and_write_csv(INDUSTRY_CSV, industries, "industry")
        industry_note = "완료"

    status = {
        "status": "success",
        "mode": "bootstrap",
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "target_period": args.end,
        "start_period": start,
        "changed": changed,
        "industry": industry_note,
    }
    atomic_write_json(UPDATE_STATUS_JSON, status)
    log("최초 과거자료 구축 완료")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
