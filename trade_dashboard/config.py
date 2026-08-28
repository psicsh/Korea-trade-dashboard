from __future__ import annotations

from pathlib import Path

APP_NAME = "한국무역 한눈에 보기"
APP_VERSION = "1.0.0"

ROOT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT_DIR / "data"

MONTHLY_CSV = DATA_DIR / "trade_monthly.csv"
INDUSTRY_CSV = DATA_DIR / "trade_industry.csv"
REGION_CSV = DATA_DIR / "trade_region.csv"
MTI_MAPPING_XLSX = DATA_DIR / "mti_hsk_mapping.xlsx"
MTI_MAJOR_CSV = DATA_DIR / "mti_major_codes_2026.csv"
REGION_GROUPS_JSON = DATA_DIR / "region_groups_reference.json"
UPDATE_STATUS_JSON = DATA_DIR / "update_status.json"

TOTAL_ENDPOINT = "https://apis.data.go.kr/1220000/Newtrade/getNewtradeList"
ITEM_ENDPOINT = "https://apis.data.go.kr/1220000/Itemtrade/getItemtradeList"
NATION_ENDPOINT = "https://apis.data.go.kr/1220000/nationtrade/getNationtradeList"

SERVICE_KEY_NAME = "DATA_GO_KR_SERVICE_KEY"

TRADE_VALUE_COLUMNS = ["export_usd", "import_usd", "balance_usd"]
