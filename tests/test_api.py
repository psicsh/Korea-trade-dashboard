from __future__ import annotations

import pytest
import requests

from trade_dashboard.api import (
    PublicDataAuthError,
    PublicDataClient,
    PublicDataTemporaryError,
    normalize_hs_items,
    normalize_nation_items,
    normalize_total_items,
    parse_xml_items,
)

SUCCESS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<response><header><resultCode>00</resultCode><resultMsg>NORMAL SERVICE.</resultMsg></header>
<body><items>
<item><year>2026.06</year><expDlr>1000</expDlr><impDlr>700</impDlr><balPayments>300</balPayments><expCnt>3</expCnt><impCnt>2</impCnt></item>
<item><year>2026.07</year><expDlr>1200</expDlr><impDlr>800</impDlr><balPayments>400</balPayments><expCnt>4</expCnt><impCnt>3</impCnt></item>
</items></body></response>"""


def test_parse_and_normalize_total():
    items = parse_xml_items(SUCCESS_XML)
    frame = normalize_total_items(items)
    assert frame["period"].tolist() == ["2026-06", "2026-07"]
    assert frame.iloc[-1]["balance_usd"] == 400


def test_normalize_hs_and_nation():
    hs = normalize_hs_items(
        [
            {
                "year": "202607",
                "hsCode": "8542",
                "statKor": "전자집적회로",
                "expDlr": "10",
                "impDlr": "4",
                "balPayments": "6",
            }
        ]
    )
    assert hs.iloc[0]["hs_name"] == "전자집적회로"
    nation = normalize_nation_items(
        [
            {
                "year": "202607",
                "statCd": "US",
                "statCdCntnKor1": "미국",
                "expDlr": "10",
                "impDlr": "4",
                "balPayments": "6",
            }
        ]
    )
    assert nation.iloc[0]["country_code"] == "US"


@pytest.mark.parametrize(
    ("code", "message"),
    [("20", "인증키"), ("30", "등록되지"), ("31", "만료")],
)
def test_auth_errors_are_not_empty_results(code, message):
    xml = f"<response><header><resultCode>{code}</resultCode><resultMsg>secret-value</resultMsg></header></response>"
    with pytest.raises(PublicDataAuthError, match=message) as caught:
        parse_xml_items(xml)
    assert "secret-value" not in str(caught.value)


class FakeResponse:
    status_code = 200
    content = SUCCESS_XML.encode()


class FakeSession:
    def __init__(self):
        self.params = None

    def get(self, endpoint, params, timeout):
        self.params = params
        return FakeResponse()


def test_official_parameter_names_and_no_num_of_rows():
    client = PublicDataClient("encoded%2Btest%3D")
    fake = FakeSession()
    client._session = fake
    client.fetch_hs("2026-06", "2026-07", "8542")
    assert fake.params["strtYymm"] == "202606"
    assert fake.params["endYymm"] == "202607"
    assert fake.params["hsSgn"] == "8542"
    assert "numOfRows" not in fake.params
    assert fake.params["serviceKey"] == "encoded+test="


def test_network_error_does_not_leak_endpoint_or_key():
    client = PublicDataClient("very-secret-key")

    class BrokenSession:
        def get(self, *args, **kwargs):
            raise requests.ConnectionError("URL with very-secret-key")

    client._session = BrokenSession()
    with pytest.raises(PublicDataTemporaryError) as caught:
        client.fetch_total("2026-07", "2026-07")
    assert "very-secret-key" not in str(caught.value)
    assert "http" not in str(caught.value).lower()
