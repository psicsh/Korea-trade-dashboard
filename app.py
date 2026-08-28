from __future__ import annotations

import time
from datetime import datetime
from zoneinfo import ZoneInfo

import altair as alt
import pandas as pd
import streamlit as st
from streamlit.errors import StreamlitSecretNotFoundError

from trade_dashboard.api import PublicDataClient, PublicDataError, PublicDataTemporaryError
from trade_dashboard.config import (
    APP_NAME,
    APP_VERSION,
    INDUSTRY_CSV,
    MONTHLY_CSV,
    MTI_MAJOR_CSV,
    MTI_MAPPING_XLSX,
    REGION_CSV,
    SERVICE_KEY_NAME,
    UPDATE_STATUS_JSON,
)
from trade_dashboard.data import (
    csv_bytes,
    load_industry,
    load_monthly,
    load_region,
    read_status,
    recent_months,
)
from trade_dashboard.mti import load_major_codes, load_mti_mapping, related_major_industries
from trade_dashboard.utils import latest_complete_month, shift_month, validate_hs_code

st.set_page_config(page_title=APP_NAME, page_icon="🇰🇷", layout="wide")

COLORS = {"수출": "#0B5AA6", "수입": "#E97828", "무역수지": "#16836B"}


def _secret_key() -> str:
    try:
        return str(st.secrets.get(SERVICE_KEY_NAME, "")).strip()
    except (FileNotFoundError, KeyError, StreamlitSecretNotFoundError):
        return ""


@st.cache_data(ttl=21_600, show_spinner=False)
def query_hs_cached(hs_code: str, period: str) -> pd.DataFrame:
    key = _secret_key()
    if not key:
        raise PublicDataError("Streamlit Secrets에 공공데이터 인증키가 설정되지 않았습니다.")
    return PublicDataClient(key).fetch_hs(period, period, hs_code)


def enforce_hs_rate_limit() -> None:
    now = time.time()
    history = [stamp for stamp in st.session_state.get("hs_query_history", []) if now - stamp < 600]
    if history and now - history[-1] < 2:
        raise ValueError("연속 조회 간격은 2초 이상이어야 합니다. 잠시 후 다시 눌러 주세요.")
    if len(history) >= 10:
        raise ValueError("한 세션에서는 10분에 10회까지 조회할 수 있습니다.")
    history.append(now)
    st.session_state["hs_query_history"] = history


def usd_100m(value: float) -> str:
    return f"{value / 100_000_000:,.1f}억 달러"


def _period_label(period: str) -> str:
    return f"{period[:4]}년 {int(period[5:]):d}월"


def _latest_available(*frames: pd.DataFrame) -> str:
    periods = []
    for frame in frames:
        if not frame.empty:
            periods.extend(frame["period"].dropna().astype(str).tolist())
    return max(periods) if periods else latest_complete_month()


def trade_charts(frame: pd.DataFrame, title: str) -> None:
    if frame.empty:
        st.info("표시할 자료가 없습니다.")
        return
    data = frame.copy()
    data["period_date"] = pd.to_datetime(data["period"] + "-01")
    data["수출"] = data["export_usd"] / 100_000_000
    data["수입"] = data["import_usd"] / 100_000_000
    data["무역수지"] = data["balance_usd"] / 100_000_000
    lines = data.melt(
        id_vars=["period_date"],
        value_vars=["수출", "수입"],
        var_name="구분",
        value_name="억 달러",
    )
    line_chart = (
        alt.Chart(lines, title=title)
        .mark_line(point=True, strokeWidth=2)
        .encode(
            x=alt.X("period_date:T", title=None, axis=alt.Axis(format="%Y-%m")),
            y=alt.Y("억 달러:Q", title="억 달러", scale=alt.Scale(zero=False)),
            color=alt.Color(
                "구분:N",
                scale=alt.Scale(domain=["수출", "수입"], range=[COLORS["수출"], COLORS["수입"]]),
                legend=alt.Legend(orient="top"),
            ),
            tooltip=[
                alt.Tooltip("period_date:T", title="연월", format="%Y-%m"),
                "구분:N",
                alt.Tooltip("억 달러:Q", format=",.1f"),
            ],
        )
        .properties(height=330)
    )
    balance = (
        alt.Chart(data, title="월별 무역수지")
        .mark_bar(color=COLORS["무역수지"])
        .encode(
            x=alt.X("period_date:T", title=None, axis=alt.Axis(format="%Y-%m")),
            y=alt.Y("무역수지:Q", title="억 달러"),
            color=alt.condition(alt.datum["무역수지"] >= 0, alt.value(COLORS["무역수지"]), alt.value("#C63D3D")),
            tooltip=[
                alt.Tooltip("period_date:T", title="연월", format="%Y-%m"),
                alt.Tooltip("무역수지:Q", format=",.1f"),
            ],
        )
        .properties(height=220)
    )
    st.altair_chart(line_chart, use_container_width=True)
    st.altair_chart(balance, use_container_width=True)


def latest_metrics(frame: pd.DataFrame, period: str) -> None:
    row = frame[frame["period"] == period]
    if row.empty:
        st.info("최신 월 지표가 없습니다.")
        return
    current = row.iloc[-1]
    previous_period = shift_month(period, -12)
    previous = frame[frame["period"] == previous_period]

    def delta(column: str) -> str | None:
        if previous.empty or float(previous.iloc[-1][column]) == 0:
            return None
        rate = (float(current[column]) / float(previous.iloc[-1][column]) - 1) * 100
        return f"전년동월 대비 {rate:+.1f}%"

    columns = st.columns(3)
    columns[0].metric("수출", usd_100m(float(current["export_usd"])), delta("export_usd"), border=True)
    columns[1].metric("수입", usd_100m(float(current["import_usd"])), delta("import_usd"), border=True)
    columns[2].metric("무역수지", usd_100m(float(current["balance_usd"])), border=True)


def comparison_table(frame: pd.DataFrame, period: str, code_col: str, name_col: str) -> pd.DataFrame:
    current = frame[frame["period"] == period].copy()
    previous = frame[frame["period"] == shift_month(period, -12)][[code_col, "export_usd"]].rename(
        columns={"export_usd": "export_prev"}
    )
    current = current.merge(previous, how="left", on=code_col)
    current["수출 증감률(%)"] = (current["export_usd"] / current["export_prev"] - 1) * 100
    current["수출(억 달러)"] = current["export_usd"] / 100_000_000
    current["수입(억 달러)"] = current["import_usd"] / 100_000_000
    current["무역수지(억 달러)"] = current["balance_usd"] / 100_000_000
    return current[
        [code_col, name_col, "수출(억 달러)", "수입(억 달러)", "무역수지(억 달러)", "수출 증감률(%)"]
    ].sort_values("수출(억 달러)", ascending=False)


def category_tab(frame: pd.DataFrame, kind: str) -> None:
    if frame.empty:
        st.warning("아직 과거자료가 구축되지 않았습니다. GitHub Actions에서 최초 구축을 실행해 주세요.")
        return
    if kind == "industry":
        code_col, name_col, label = "industry_code", "industry_name", "품목"
    else:
        code_col, name_col, label = "region_code", "region_name", "지역"
    latest = max(frame["period"])
    st.caption(f"최신 비교 기준: {_period_label(latest)}")
    table = comparison_table(frame, latest, code_col, name_col)
    st.dataframe(
        table,
        use_container_width=True,
        hide_index=True,
        column_config={
            "수출(억 달러)": st.column_config.NumberColumn(format="%.1f"),
            "수입(억 달러)": st.column_config.NumberColumn(format="%.1f"),
            "무역수지(억 달러)": st.column_config.NumberColumn(format="%.1f"),
            "수출 증감률(%)": st.column_config.NumberColumn(format="%+.1f"),
        },
    )
    options = frame[[code_col, name_col]].drop_duplicates().sort_values(name_col)
    option_map = {f"{row[name_col]} ({row[code_col]})": row[code_col] for _, row in options.iterrows()}
    selected_label = st.selectbox(f"{label} 선택", list(option_map), key=f"{kind}_select")
    months = (
        12
        if st.radio("조회기간", ["최근 12개월", "최근 5년"], horizontal=True, key=f"{kind}_period") == "최근 12개월"
        else 60
    )
    selected = frame[frame[code_col].astype(str) == str(option_map[selected_label])]
    selected = recent_months(selected, months)
    trade_charts(selected, f"{selected_label} 월별 수출입")
    st.download_button(
        f"{label} CSV 다운로드",
        csv_bytes(selected),
        f"trade_{kind}_{option_map[selected_label]}.csv",
        "text/csv",
        key=f"{kind}_download",
    )


def hs_tab(latest_period: str) -> None:
    st.subheader("HS 상세조회")
    st.caption("HS 2자리·4자리·6자리의 선택한 한 달 자료만 조회합니다. 조회 버튼을 누를 때만 API를 호출합니다.")
    with st.form("hs_lookup_form"):
        hs_input = st.text_input("HS 코드", placeholder="예: 85, 8542, 854231", max_chars=6)
        available_periods = [shift_month(latest_period, -offset) for offset in range(60)]
        selected_period = st.selectbox("조회월", available_periods, format_func=_period_label)
        submitted = st.form_submit_button("조회", type="primary")

    if submitted:
        try:
            hs_code = validate_hs_code(hs_input)
            enforce_hs_rate_limit()
            with st.spinner("관세청 자료를 조회하고 있습니다."):
                result = query_hs_cached(hs_code, selected_period)
            if result.empty:
                st.warning("해당 조건의 자료가 없습니다. 인증키 권한과 HS 코드를 확인해 주세요.")
            else:
                st.session_state["hs_result"] = result
                st.session_state["hs_code"] = hs_code
                st.session_state["hs_period"] = selected_period
        except PublicDataTemporaryError:
            st.error(
                "관세청 실시간 HS 조회 서버가 일시적으로 응답하지 않습니다. "
                "저장된 전체 무역·20대 품목·9대 지역 자료에는 영향이 없으므로 잠시 후 다시 조회해 주세요."
            )
        except (ValueError, PublicDataError) as exc:
            st.error(str(exc))

    result = st.session_state.get("hs_result")
    hs_code = st.session_state.get("hs_code")
    hs_period = st.session_state.get("hs_period")
    if result is None or not hs_code or not hs_period:
        if not _secret_key():
            st.info(f"Streamlit Settings → Secrets에 `{SERVICE_KEY_NAME}`를 설정하면 조회할 수 있습니다.")
        return

    result = result.copy()
    # 2·4·6자리 조회가 여러 행으로 반환되어도 선택 월의 값으로 안전하게 합산한다.
    summary = result[["export_usd", "import_usd", "balance_usd"]].sum()
    hs_names = [name for name in result["hs_name"].dropna().astype(str).unique() if name]
    st.markdown(f"#### HS {hs_code} · {hs_names[0] if hs_names else '공식 명칭 미제공'}")
    st.caption(f"조회 기준: {_period_label(hs_period)}")

    try:
        mapping = load_mti_mapping(MTI_MAPPING_XLSX)
        major = load_major_codes(MTI_MAJOR_CSV)
        related = related_major_industries(hs_code, mapping, major)
        st.caption("관련 20대 MTI 품목: " + (", ".join(related) if related else "해당 없음"))
    except (FileNotFoundError, ValueError):
        st.caption("관련 MTI 품목은 공식 2026 MTI-HSK 연계표를 넣은 뒤 표시됩니다.")

    columns = st.columns(3)
    columns[0].metric("조회월 수출", usd_100m(float(summary["export_usd"])), border=True)
    columns[1].metric("조회월 수입", usd_100m(float(summary["import_usd"])), border=True)
    columns[2].metric("조회월 무역수지", usd_100m(float(summary["balance_usd"])), border=True)
    st.download_button(
        "HS 조회결과 CSV 다운로드",
        csv_bytes(result),
        f"hs_{hs_code}_{str(hs_period).replace('-', '')}.csv",
        "text/csv",
    )


def main() -> None:
    st.title(f"🇰🇷 {APP_NAME}")
    st.caption(f"관세청 수출입무역통계 · 앱 버전 {APP_VERSION}")

    try:
        monthly = load_monthly(MONTHLY_CSV)
        industry = load_industry(INDUSTRY_CSV)
        region = load_region(REGION_CSV)
    except ValueError as exc:
        st.error(f"저장 데이터 검증 오류: {exc}")
        st.stop()

    latest = _latest_available(monthly, industry, region)
    status = read_status(UPDATE_STATUS_JSON)
    with st.sidebar:
        st.header("데이터 안내")
        st.write(f"가용 최신월: **{latest}**")
        if status.get("checked_at_utc"):
            checked = str(status["checked_at_utc"]).replace("T", " ")[:19]
            st.caption(f"마지막 자동 확인(UTC): {checked}")
        st.caption("금액은 미화 달러 기준입니다. 수출은 FOB, 수입은 CIF 기준입니다.")
        st.markdown(
            "[관세청 수출입총괄](https://www.data.go.kr/data/15102108/openapi.do)  \n"
            "[관세청 품목별 실적](https://www.data.go.kr/data/15101609/openapi.do)"
        )

    total_tab, industry_tab, region_tab, hs_lookup_tab = st.tabs(["전체 무역", "20대 품목", "9대 지역", "HS 상세조회"])

    with total_tab:
        st.subheader("전체 무역")
        if monthly.empty:
            st.warning("전체무역 최근 5년 자료가 없습니다. GitHub Actions에서 최초 구축을 실행해 주세요.")
        else:
            latest_total = max(monthly["period"])
            st.caption(f"최신 기준: {_period_label(latest_total)}")
            latest_metrics(monthly, latest_total)
            selection = st.radio("월별 조회기간", ["최근 12개월", "최근 5년"], horizontal=True, key="total_period")
            months = 12 if selection == "최근 12개월" else 60
            selected = recent_months(monthly, months)
            trade_charts(selected, f"{selection} 월별 수출입")
            st.download_button(
                "전체 무역 CSV 다운로드",
                csv_bytes(selected),
                f"trade_total_{months}months.csv",
                "text/csv",
            )

    with industry_tab:
        st.subheader("20대 주요 품목")
        st.caption("2026년 개편 MTI 기준입니다. 공식 개편의 소급 비교 가능 기간은 2022년 이후입니다.")
        category_tab(industry, "industry")

    with region_tab:
        st.subheader("9대 주요 수출지역")
        st.caption("미국·중국·아세안·EU(27)·일본·중남미·인도·중동·CIS를 국가별 관세청 자료로 집계합니다.")
        category_tab(region, "region")

    with hs_lookup_tab:
        hs_tab(latest)

    st.divider()
    now_kst = datetime.now(ZoneInfo("Asia/Seoul"))
    st.caption(
        f"화면 생성 시각(KST): {now_kst.strftime('%Y-%m-%d %H:%M')} · 인증키와 인증키가 포함된 요청 주소는 화면과 로그에 표시하지 않습니다."
    )


if __name__ == "__main__":
    main()
