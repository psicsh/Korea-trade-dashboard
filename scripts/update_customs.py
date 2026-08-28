#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone

from _common import client_from_environment, concat, log

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
from trade_dashboard.utils import latest_complete_month, shift_month


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="한국무역 대시보드 월별 증분 갱신")
    parser.add_argument("--target", default=latest_complete_month(), help="대상월(YYYY-MM), 기본값: 전월")
    parser.add_argument("--recheck-months", type=int, default=3, choices=range(1, 7))
    parser.add_argument("--skip-industries", action="store_true")
    return parser.parse_args()


def _status(target: str, status: str, **extra):
    payload = {
        "status": status,
        "mode": "monthly-update",
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "target_period": target,
        **extra,
    }
    atomic_write_json(UPDATE_STATUS_JSON, payload)


def main() -> int:
    args = parse_args()
    client = client_from_environment()
    start = shift_month(args.target, -(args.recheck_months - 1))
    log(f"전체무역 {start}~{args.target} 재검증")
    monthly = client.fetch_total(start, args.target)
    if monthly.empty or args.target not in set(monthly["period"]):
        _status(args.target, "pending", message="관세청 전월 자료가 아직 제공되지 않았습니다.")
        log("전월 자료 미제공: 다음 예약 실행에서 다시 확인")
        return 0

    groups = load_region_groups(REGION_GROUPS_JSON)
    log(f"9대 지역 {start}~{args.target} 재검증")
    nations = client.fetch_nations(start, args.target)
    regions = aggregate_regions(nations, groups)
    if regions.empty or args.target not in set(regions["period"]):
        raise RuntimeError("전체무역은 제공되었지만 9대 지역 자료를 만들 수 없습니다.")
    target_region_count = regions.loc[regions["period"] == args.target, "region_code"].nunique()
    if target_region_count != 9:
        raise RuntimeError(f"대상월 9대 지역 중 {target_region_count}개만 집계되었습니다.")

    industry_note = "생략"
    industries = None
    if not args.skip_industries:
        try:
            mapping = load_mti_mapping(MTI_MAPPING_XLSX)
            major = load_major_codes(MTI_MAJOR_CSV)
            frames = []
            # 전체 HSK 응답은 크므로 20대 품목은 새 대상월만 한 번 수집한다.
            log(f"20대 품목 {args.target} 갱신")
            hs_rows = client.fetch_hs(args.target, args.target)
            if hs_rows.empty:
                raise RuntimeError(f"{args.target} 전체 HSK 자료가 비어 있습니다.")
            aggregated = aggregate_industries(hs_rows, mapping, major)
            if aggregated.empty:
                raise RuntimeError(f"{args.target} 20대 품목 집계 결과가 비어 있습니다.")
            frames.append(aggregated)
            industries = concat(frames)
            industry_note = "완료"
        except (FileNotFoundError, ValueError) as exc:
            industry_note = f"건너뜀: {exc}"
            log("공식 2026 MTI-HSK 연계표가 준비되지 않아 품목 갱신을 건너뜁니다.")

    changed = {
        "monthly": merge_and_write_csv(MONTHLY_CSV, monthly, "monthly"),
        "region": merge_and_write_csv(REGION_CSV, regions, "region"),
        "industry": False,
    }
    if industries is not None and not industries.empty:
        changed["industry"] = merge_and_write_csv(INDUSTRY_CSV, industries, "industry")

    _status(args.target, "success", changed=changed, industry=industry_note)
    log("월별 갱신 완료")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
