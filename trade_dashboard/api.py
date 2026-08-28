from __future__ import annotations

import re
import time
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .config import ITEM_ENDPOINT, NATION_ENDPOINT, TOTAL_ENDPOINT
from .utils import compact_period, normalize_period, to_number


class PublicDataError(RuntimeError):
    """외부에 인증키나 요청 URL을 노출하지 않는 공공데이터 오류."""


class PublicDataAuthError(PublicDataError):
    pass


class PublicDataLimitError(PublicDataError):
    pass


class PublicDataTemporaryError(PublicDataError):
    pass


ERROR_TEXT = {
    "01": "공공데이터 제공기관 내부 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.",
    "04": "공공데이터 요청 방식이 올바르지 않습니다.",
    "05": "공공데이터 응답 시간이 초과되었습니다. 잠시 후 다시 시도해 주세요.",
    "10": "공공데이터 요청 조건이 올바르지 않습니다.",
    "12": "요청한 공공데이터 서비스가 존재하지 않습니다.",
    "20": "공공데이터 인증키 또는 서비스 이용 권한을 확인해 주세요.",
    "22": "공공데이터 일일 호출 한도를 초과했습니다.",
    "23": "공공데이터 초당 호출 한도를 초과했습니다. 잠시 후 다시 시도해 주세요.",
    "29": "현재 접속 환경에서 공공데이터 호출이 차단되었습니다.",
    "30": "등록되지 않은 공공데이터 인증키입니다.",
    "31": "공공데이터 인증키 사용 기한이 만료되었습니다.",
}

AUTH_CODES = {"20", "30", "31"}
LIMIT_CODES = {"22", "23"}
TEMP_CODES = {"01", "05"}
SUCCESS_CODES = {"00", "0", "INFO-000"}


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _element_text(root: ET.Element, name: str) -> str | None:
    for element in root.iter():
        if _local_name(element.tag).lower() == name.lower():
            return (element.text or "").strip()
    return None


def _item_dict(element: ET.Element) -> dict[str, str]:
    return {_local_name(child.tag): (child.text or "").strip() for child in list(element)}


def _raise_api_error(code: str, message: str = "") -> None:
    normalized = (code or "").strip()
    if normalized in SUCCESS_CODES:
        return
    safe_message = ERROR_TEXT.get(normalized, "공공데이터 조회에 실패했습니다.")
    if normalized in AUTH_CODES:
        raise PublicDataAuthError(safe_message)
    if normalized in LIMIT_CODES:
        raise PublicDataLimitError(safe_message)
    if normalized in TEMP_CODES:
        raise PublicDataTemporaryError(safe_message)
    raise PublicDataError(safe_message)


def parse_xml_items(content: bytes | str) -> list[dict[str, str]]:
    raw = content.encode("utf-8") if isinstance(content, str) else content
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise PublicDataError("공공데이터 응답 형식을 읽을 수 없습니다.") from exc

    code = _element_text(root, "resultCode") or _element_text(root, "returnReasonCode")
    message = _element_text(root, "resultMsg") or _element_text(root, "returnAuthMsg") or ""

    upper_message = message.upper()
    if not code:
        for known in [
            "SERVICE_KEY_IS_NOT_REGISTERED_ERROR",
            "DEADLINE_HAS_EXPIRED_ERROR",
            "SERVICE_ACCESS_DENIED_ERROR",
            "LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS_ERROR",
        ]:
            if known in upper_message:
                mapped = (
                    "30"
                    if "NOT_REGISTERED" in known
                    else "31"
                    if "EXPIRED" in known
                    else "22"
                    if "LIMITED" in known
                    else "20"
                )
                _raise_api_error(mapped, message)
    elif code not in SUCCESS_CODES:
        _raise_api_error(code, message)

    items = [_item_dict(element) for element in root.iter() if _local_name(element.tag).lower() == "item"]
    return [item for item in items if item]


def _base_trade_frame(items: list[dict[str, Any]]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for item in items:
        period = normalize_period(item.get("year"))
        if not period:
            continue
        export = to_number(item.get("expDlr"))
        imports = to_number(item.get("impDlr"))
        balance_raw = item.get("balPayments")
        balance = to_number(balance_raw) if balance_raw not in (None, "") else export - imports
        rows.append(
            {
                "period": period,
                "export_usd": export,
                "import_usd": imports,
                "balance_usd": balance,
                "export_count": int(to_number(item.get("expCnt"))),
                "import_count": int(to_number(item.get("impCnt"))),
            }
        )
    return pd.DataFrame(rows)


def normalize_total_items(items: list[dict[str, Any]]) -> pd.DataFrame:
    frame = _base_trade_frame(items)
    if frame.empty:
        return pd.DataFrame(
            columns=["period", "export_usd", "import_usd", "balance_usd", "export_count", "import_count", "source"]
        )
    frame["source"] = "관세청 수출입총괄"
    return frame.sort_values("period").drop_duplicates("period", keep="last").reset_index(drop=True)


def normalize_hs_items(items: list[dict[str, Any]]) -> pd.DataFrame:
    base = _base_trade_frame(items)
    if base.empty:
        return pd.DataFrame(columns=["period", "hs_code", "hs_name", "export_usd", "import_usd", "balance_usd"])
    valid_items = [item for item in items if normalize_period(item.get("year"))]
    base["hs_code"] = [re.sub(r"\D", "", str(item.get("hsCode", ""))) for item in valid_items]
    base["hs_name"] = [str(item.get("statKor", "")).strip() for item in valid_items]
    return (
        base[["period", "hs_code", "hs_name", "export_usd", "import_usd", "balance_usd"]]
        .sort_values("period")
        .reset_index(drop=True)
    )


def normalize_nation_items(items: list[dict[str, Any]]) -> pd.DataFrame:
    base = _base_trade_frame(items)
    if base.empty:
        return pd.DataFrame(
            columns=["period", "country_code", "country_name", "export_usd", "import_usd", "balance_usd"]
        )
    valid_items = [item for item in items if normalize_period(item.get("year"))]
    base["country_code"] = [str(item.get("statCd", "")).strip().upper() for item in valid_items]
    base["country_name"] = [str(item.get("statCdCntnKor1", "")).strip() for item in valid_items]
    return (
        base[["period", "country_code", "country_name", "export_usd", "import_usd", "balance_usd"]]
        .sort_values(["period", "country_code"])
        .reset_index(drop=True)
    )


def _normalise_service_key(key: str) -> str:
    value = (key or "").strip()
    if not value:
        raise PublicDataAuthError("공공데이터 인증키가 설정되지 않았습니다.")
    # 공공데이터포털의 'Encoding' 키를 붙여 넣은 경우 requests의 이중 인코딩을 피한다.
    return urllib.parse.unquote(value)


def _session() -> requests.Session:
    retry = Retry(
        total=3,
        connect=3,
        read=3,
        backoff_factor=0.8,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
        raise_on_status=False,
    )
    session = requests.Session()
    session.headers.update({"User-Agent": "korea-trade-dashboard/1.0"})
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session


@dataclass
class PublicDataClient:
    service_key: str
    timeout: tuple[int, int] = (10, 90)
    min_interval_seconds: float = 0.15

    def __post_init__(self) -> None:
        self.service_key = _normalise_service_key(self.service_key)
        self._session = _session()
        self._last_call = 0.0

    def _get(self, endpoint: str, params: dict[str, str]) -> list[dict[str, str]]:
        elapsed = time.monotonic() - self._last_call
        if elapsed < self.min_interval_seconds:
            time.sleep(self.min_interval_seconds - elapsed)
        request_params = {"serviceKey": self.service_key, **params}
        try:
            response = self._session.get(endpoint, params=request_params, timeout=self.timeout)
            self._last_call = time.monotonic()
        except requests.RequestException as exc:
            raise PublicDataTemporaryError("공공데이터 서버에 연결할 수 없습니다.") from exc

        if response.status_code in {401, 403}:
            raise PublicDataAuthError("공공데이터 인증키 또는 서비스 이용 권한을 확인해 주세요.")
        if response.status_code == 429:
            raise PublicDataLimitError("공공데이터 호출 한도를 초과했습니다.")
        if response.status_code >= 500:
            raise PublicDataTemporaryError("공공데이터 서버가 일시적으로 응답하지 않습니다.")
        if response.status_code != 200:
            raise PublicDataError(f"공공데이터 조회에 실패했습니다(HTTP {response.status_code}).")
        return parse_xml_items(response.content)

    def fetch_total(self, start: str, end: str) -> pd.DataFrame:
        items = self._get(
            TOTAL_ENDPOINT,
            {"strtYymm": compact_period(start), "endYymm": compact_period(end)},
        )
        return normalize_total_items(items)

    def fetch_hs(self, start: str, end: str, hs_code: str | None = None) -> pd.DataFrame:
        params = {"strtYymm": compact_period(start), "endYymm": compact_period(end)}
        if hs_code:
            params["hsSgn"] = hs_code
        items = self._get(ITEM_ENDPOINT, params)
        return normalize_hs_items(items)

    def fetch_nations(self, start: str, end: str, country_code: str | None = None) -> pd.DataFrame:
        params = {"strtYymm": compact_period(start), "endYymm": compact_period(end)}
        if country_code:
            params["cntyCd"] = country_code.upper()
        items = self._get(NATION_ENDPOINT, params)
        return normalize_nation_items(items)
