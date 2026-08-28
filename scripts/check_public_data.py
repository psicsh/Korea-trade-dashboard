#!/usr/bin/env python3
from __future__ import annotations

import argparse

from _common import client_from_environment, log

from trade_dashboard.utils import latest_complete_month


def main() -> int:
    parser = argparse.ArgumentParser(description="관세청 공공데이터 연결 확인")
    parser.add_argument("--period", default=latest_complete_month())
    parser.add_argument("--hs", default="8542", help="확인용 HS 2·4·6자리")
    args = parser.parse_args()

    client = client_from_environment()
    total = client.fetch_total(args.period, args.period)
    hs = client.fetch_hs(args.period, args.period, args.hs)
    nations = client.fetch_nations(args.period, args.period, "US")
    log(f"수출입총괄 응답 {len(total)}행")
    log(f"HS 품목 응답 {len(hs)}행")
    log(f"국가별 응답 {len(nations)}행")
    log("인증키와 요청 주소는 출력하지 않았습니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
