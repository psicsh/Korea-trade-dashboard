import streamlit as st
import pandas as pd
import requests
import xml.etree.ElementTree as ET
from urllib.parse import unquote
from datetime import date

st.set_page_config(page_title="한국무역 한눈에 보기", page_icon="🇰🇷", layout="wide")

TOTAL_URL = "https://apis.data.go.kr/1220000/Newtrade/getNewtradeList"
ITEM_URL = "https://apis.data.go.kr/1220000/Itemtrade/getItemtradeList"
NATION_URL = "https://apis.data.go.kr/1220000/nationtrade/getNationtradeList"

INDUSTRIES = {
    "반도체": ("8542", "HS 8542 전자집적회로 기준"),
    "자동차": ("8703", "HS 8703 승용자동차 기준"),
    "선박": ("89", "HS 89류 선박·수상구조물 기준"),
    "석유제품": ("2710", "HS 2710 석유제품 기준"),
    "이차전지": ("8507", "HS 8507 축전지 기준"),
    "바이오": ("3002", "HS 3002 면역물품 등 기준 예시"),
    "디스플레이": ("8524", "HS 8524 평판디스플레이 모듈 기준"),
    "컴퓨터": ("8471", "HS 8471 자동자료처리기계 기준"),
}

COUNTRIES = {
    "미국": "US", "중국": "CN", "일본": "JP", "베트남": "VN",
    "대만": "TW", "독일": "DE", "싱가포르": "SG",
}

def get_service_key():
    try:
        raw = st.secrets["DATA_GO_KR_SERVICE_KEY"]
    except Exception:
        return None
    return unquote(str(raw).strip())

def to_num(v):
    try:
        return float(str(v).replace(",", ""))
    except Exception:
        return None

def fmt_usd(v):
    return "-" if v is None else f"{v / 1e8:,.1f}억 달러"

def parse_xml(content):
    root = ET.fromstring(content)
    code = root.findtext(".//resultCode")
    msg = root.findtext(".//resultMsg") or ""
    if code not in ("00", None):
        raise RuntimeError(f"{code}: {msg}")
    return [{c.tag: c.text for c in item} for item in root.findall(".//item")]

@st.cache_data(ttl=3600, show_spinner=False)
def api_get(url, key, params_tuple):
    params = dict(params_tuple)
    params["serviceKey"] = key
    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    return parse_xml(r.content)

def month_window():
    now = pd.Period(date.today().strftime("%Y-%m"), freq="M")
    start = now - 11
    return start.strftime("%Y%m"), now.strftime("%Y%m")

def prior_year_month(period_text):
    s = str(period_text).replace(".", "")
    if len(s) < 6:
        return None
    return f"{int(s[:4])-1}{s[4:6]}"

def total_df(key, start_ym, end_ym):
    rows = api_get(TOTAL_URL, key, tuple(sorted({"strtYymm": start_ym, "endYymm": end_ym}.items())))
    out = []
    for x in rows:
        period = x.get("year")
        if not period or "총계" in period:
            continue
        out.append({
            "기간": period,
            "수출": to_num(x.get("expDlr")),
            "수입": to_num(x.get("impDlr")),
            "무역수지": to_num(x.get("balPayments")),
        })
    df = pd.DataFrame(out)
    return df.sort_values("기간") if not df.empty else df

def item_df(key, start_ym, end_ym, hs):
    rows = api_get(ITEM_URL, key, tuple(sorted({"strtYymm": start_ym, "endYymm": end_ym, "hsSgn": hs}.items())))
    out = []
    for x in rows:
        period = x.get("year")
        if not period or "총계" in period:
            continue
        out.append({
            "기간": period,
            "HS": x.get("hsCode", ""),
            "품목": x.get("statKor", ""),
            "수출": to_num(x.get("expDlr")) or 0,
            "수입": to_num(x.get("impDlr")) or 0,
            "무역수지": to_num(x.get("balPayments")) or 0,
        })
    return pd.DataFrame(out)

def nation_df(key, start_ym, end_ym, code):
    rows = api_get(NATION_URL, key, tuple(sorted({"strtYymm": start_ym, "endYymm": end_ym, "cntyCd": code}.items())))
    out = []
    for x in rows:
        period = x.get("year")
        if not period or "총계" in period:
            continue
        out.append({
            "기간": period,
            "국가": x.get("statCdCntnKor1", ""),
            "수출": to_num(x.get("expDlr")) or 0,
            "수입": to_num(x.get("impDlr")) or 0,
            "무역수지": to_num(x.get("balPayments")) or 0,
        })
    df = pd.DataFrame(out)
    return df.sort_values("기간") if not df.empty else df

def calc_yoy_latest(key, latest_period, latest_export):
    prev = prior_year_month(latest_period)
    if not prev or latest_export in (None, 0):
        return None
    try:
        p = total_df(key, prev, prev)
        if p.empty or p.iloc[-1]["수출"] in (None, 0):
            return None
        return (latest_export / p.iloc[-1]["수출"] - 1) * 100
    except Exception:
        return None

st.markdown("""
<style>
.block-container { padding-top: 1.4rem; padding-bottom: 3rem; }
.small-note { color:#667085; font-size:0.88rem; }
.notice { background:#fff7ed; border:1px solid #fed7aa; color:#9a3412; border-radius:10px; padding:10px 12px; font-size:0.88rem; }
.source { background:#f8fafc; border:1px solid #e2e8f0; color:#475467; border-radius:10px; padding:10px 12px; font-size:0.84rem; }
</style>
""", unsafe_allow_html=True)

st.title("🇰🇷 한국무역 한눈에 보기")
st.markdown('<div class="small-note">강의용 웹앱 · 관세청 수출입무역통계 Open API 자동 연동</div>', unsafe_allow_html=True)

key = get_service_key()
if not key:
    st.error("서버에 공공데이터포털 서비스키가 설정되지 않았습니다.")
    st.markdown('배포 관리자가 Streamlit의 **Settings → Secrets**에 `DATA_GO_KR_SERVICE_KEY = "..."`를 등록하면 자동으로 작동합니다.')
    st.stop()

start_ym, end_ym = month_window()

try:
    df = total_df(key, start_ym, end_ym)
except Exception as e:
    st.error("관세청 API 연결에 실패했습니다.")
    st.code(str(e))
    st.caption("해당 Open API 활용신청이 승인되어 있는지와 서비스키를 확인해 주세요.")
    st.stop()

if df.empty:
    st.warning("조회된 수출입 데이터가 없습니다.")
    st.stop()

latest = df.iloc[-1]
yoy = calc_yoy_latest(key, latest["기간"], latest["수출"])

tab1, tab2, tab3 = st.tabs(["🇰🇷 무역 한눈에 보기", "🏭 산업별 수출", "🌏 국가별 무역"])

with tab1:
    st.subheader(f"{latest['기간']} 대한민국 무역")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("수출", fmt_usd(latest["수출"]), f"{yoy:+.1f}% YoY" if yoy is not None else None)
    c2.metric("수입", fmt_usd(latest["수입"]))
    c3.metric("무역수지", fmt_usd(latest["무역수지"]))
    c4.metric("최근 확정월", str(latest["기간"]))

    st.subheader("최근 12개월 수출입 추이")
    chart = df.set_index("기간")[["수출", "수입"]] / 1e8
    chart.columns = ["수출(억 달러)", "수입(억 달러)"]
    st.line_chart(chart, height=360)

    st.markdown('<div class="source">자료: 관세청 수출입무역통계. 수출은 FOB, 수입은 CIF 기준이며 매월 정정·취하 등을 반영해 전월 자료가 현행화됩니다.</div>', unsafe_allow_html=True)

    with st.expander("월별 원자료"):
        show = df.copy()
        for c in ["수출", "수입", "무역수지"]:
            show[c] = (show[c] / 1e8).round(1)
        st.dataframe(show, use_container_width=True, hide_index=True)

with tab2:
    st.subheader("산업별 수출")
    industry = st.selectbox("산업 선택", list(INDUSTRIES.keys()))
    hs, note = INDUSTRIES[industry]
    st.markdown(f'<div class="notice"><b>분류 주의:</b> {note}. 산업통상자원부의 15대 수출품목(MTI)과 관세청 HS 분류는 정확히 일치하지 않습니다.</div>', unsafe_allow_html=True)
    try:
        raw = item_df(key, start_ym, end_ym, hs)
        if raw.empty:
            st.info("해당 HS 기준으로 조회된 자료가 없습니다.")
        else:
            g = raw.groupby("기간", as_index=False)[["수출", "수입", "무역수지"]].sum().sort_values("기간")
            last = g.iloc[-1]
            c1, c2, c3 = st.columns(3)
            c1.metric(f"{industry} 수출", fmt_usd(last["수출"]))
            c2.metric(f"{industry} 수입", fmt_usd(last["수입"]))
            c3.metric("무역수지", fmt_usd(last["무역수지"]))
            chart = g.set_index("기간")[["수출", "수입"]] / 1e8
            chart.columns = ["수출(억 달러)", "수입(억 달러)"]
            st.line_chart(chart, height=340)
            with st.expander("HS 원자료"):
                show = raw.copy()
                for c in ["수출", "수입", "무역수지"]:
                    show[c] = (show[c] / 1e8).round(2)
                st.dataframe(show, use_container_width=True, hide_index=True)
    except Exception as e:
        st.error("산업별 자료 조회 실패")
        st.code(str(e))
        st.caption("품목별 수출입실적(GW) API 활용신청 여부를 확인해 주세요.")

with tab3:
    st.subheader("국가별 무역")
    country = st.selectbox("국가 선택", list(COUNTRIES.keys()))
    code = COUNTRIES[country]
    try:
        nd = nation_df(key, start_ym, end_ym, code)
        if nd.empty:
            st.info("해당 국가 자료가 없습니다.")
        else:
            last = nd.iloc[-1]
            c1, c2, c3 = st.columns(3)
            c1.metric(f"대{country} 수출", fmt_usd(last["수출"]))
            c2.metric(f"대{country} 수입", fmt_usd(last["수입"]))
            c3.metric("무역수지", fmt_usd(last["무역수지"]))
            chart = nd.set_index("기간")[["수출", "수입"]] / 1e8
            chart.columns = ["수출(억 달러)", "수입(억 달러)"]
            st.line_chart(chart, height=340)
            with st.expander("국가별 원자료"):
                show = nd.copy()
                for c in ["수출", "수입", "무역수지"]:
                    show[c] = (show[c] / 1e8).round(1)
                st.dataframe(show, use_container_width=True, hide_index=True)
    except Exception as e:
        st.error("국가별 자료 조회 실패")
        st.code(str(e))
        st.caption("국가별 수출입실적(GW) API 활용신청 여부를 확인해 주세요.")

st.divider()
st.caption("교육용 프로토타입 v4 · 인증키는 앱 코드에 저장하지 않고 Streamlit Secrets에서 읽습니다.")
