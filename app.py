
import streamlit as st
import pandas as pd
import requests
import xml.etree.ElementTree as ET
from urllib.parse import unquote
from datetime import date

st.set_page_config(
    page_title="한국무역 한눈에 보기",
    page_icon="🇰🇷",
    layout="wide",
    initial_sidebar_state="collapsed",
)

TOTAL_URL = "https://apis.data.go.kr/1220000/Newtrade/getNewtradeList"
ITEM_URL = "https://apis.data.go.kr/1220000/Itemtrade/getItemtradeList"
NATION_URL = "https://apis.data.go.kr/1220000/nationtrade/getNationtradeList"

INDUSTRIES = {
    "반도체": {"emoji":"💾","hs":"8542","note":"HS 8542 전자집적회로 기준"},
    "자동차": {"emoji":"🚗","hs":"8703","note":"HS 8703 승용자동차 기준"},
    "선박": {"emoji":"🚢","hs":"89","note":"HS 89류 선박·수상구조물 기준"},
    "석유제품": {"emoji":"🛢️","hs":"2710","note":"HS 2710 석유제품 기준"},
    "이차전지": {"emoji":"🔋","hs":"8507","note":"HS 8507 축전지 기준"},
    "바이오": {"emoji":"🧬","hs":"3002","note":"HS 3002 면역물품 등 기준 예시"},
    "디스플레이": {"emoji":"🖥️","hs":"8524","note":"HS 8524 평판디스플레이 모듈 기준"},
    "컴퓨터": {"emoji":"💻","hs":"8471","note":"HS 8471 자동자료처리기계 기준"},
}

COUNTRIES = {
    "미국":"US","중국":"CN","일본":"JP","베트남":"VN",
    "대만":"TW","독일":"DE","싱가포르":"SG"
}

def get_key():
    try:
        raw = st.secrets["DATA_GO_KR_SERVICE_KEY"]
        return unquote(str(raw).strip())
    except Exception:
        return None

def to_num(v):
    try:
        return float(str(v).replace(",", ""))
    except:
        return None

def fmt_usd(v):
    if v is None:
        return "-"
    return f"{v/1e8:,.1f}억 달러"

@st.cache_data(ttl=3600, show_spinner=False)
def api_get(url, key, params_tuple):
    params = dict(params_tuple)
    params["serviceKey"] = key
    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    root = ET.fromstring(r.content)
    code = root.findtext(".//resultCode")
    msg = root.findtext(".//resultMsg") or ""
    if code not in (None, "00"):
        raise RuntimeError(f"{code}: {msg}")
    return [{c.tag:c.text for c in item} for item in root.findall(".//item")]

def month_window():
    now = pd.Period(date.today().strftime("%Y-%m"), freq="M")
    return (now-11).strftime("%Y%m"), now.strftime("%Y%m")

def total_df(key, start_ym, end_ym):
    rows = api_get(
        TOTAL_URL, key,
        tuple(sorted({"strtYymm":start_ym, "endYymm":end_ym}.items()))
    )
    out=[]
    for x in rows:
        p=x.get("year")
        if not p or "총계" in p:
            continue
        out.append({
            "기간":p,
            "수출":to_num(x.get("expDlr")),
            "수입":to_num(x.get("impDlr")),
            "무역수지":to_num(x.get("balPayments"))
        })
    df=pd.DataFrame(out)
    if not df.empty:
        df=df.sort_values("기간")
    return df

def item_df(key, start_ym, end_ym, hs):
    rows = api_get(
        ITEM_URL, key,
        tuple(sorted({"strtYymm":start_ym,"endYymm":end_ym,"hsSgn":hs}.items()))
    )
    out=[]
    for x in rows:
        p=x.get("year")
        if not p or "총계" in p:
            continue
        out.append({
            "기간":p,
            "품목":x.get("statKor",""),
            "수출":to_num(x.get("expDlr")) or 0,
            "수입":to_num(x.get("impDlr")) or 0,
            "무역수지":to_num(x.get("balPayments")) or 0
        })
    df=pd.DataFrame(out)
    if not df.empty:
        df=df.groupby("기간",as_index=False)[["수출","수입","무역수지"]].sum().sort_values("기간")
    return df

def nation_df(key, start_ym, end_ym, code):
    rows = api_get(
        NATION_URL, key,
        tuple(sorted({"strtYymm":start_ym,"endYymm":end_ym,"cntyCd":code}.items()))
    )
    out=[]
    for x in rows:
        p=x.get("year")
        if not p or "총계" in p:
            continue
        out.append({
            "기간":p,
            "수출":to_num(x.get("expDlr")) or 0,
            "수입":to_num(x.get("impDlr")) or 0,
            "무역수지":to_num(x.get("balPayments")) or 0
        })
    df=pd.DataFrame(out)
    if not df.empty:
        df=df.groupby("기간",as_index=False)[["수출","수입","무역수지"]].sum().sort_values("기간")
    return df

def yoy(series):
    if len(series) < 13:
        return None
    latest = series.iloc[-1]
    prev = series.iloc[-13]
    if prev in (None,0):
        return None
    return (latest/prev-1)*100

# ---------- style ----------
st.markdown("""
<style>
[data-testid="stAppViewContainer"] { background:#f5f7fb; }
.block-container { max-width:1180px; padding-top:1.2rem; padding-bottom:3rem; }
h1,h2,h3 { letter-spacing:-0.5px; }
.hero {
  background:#0f2747; color:white; border-radius:18px; padding:22px 24px;
  margin-bottom:18px;
}
.hero-title { font-size:30px; font-weight:850; margin-bottom:4px; }
.hero-sub { color:#dbe7f5; font-size:14px; }
.card {
  background:white; border:1px solid #dfe5ee; border-radius:16px;
  padding:17px 18px; box-shadow:0 4px 14px rgba(16,24,40,.04); min-height:110px;
}
.card-label { color:#667085; font-size:13px; font-weight:700; }
.card-value { font-size:27px; font-weight:850; margin:8px 0 3px; }
.card-delta { color:#059669; font-size:13px; font-weight:750; }
.panel {
  background:white; border:1px solid #dfe5ee; border-radius:16px;
  padding:18px; box-shadow:0 4px 14px rgba(16,24,40,.04);
}
.note {
  background:#fff7ed; border:1px solid #fed7aa; color:#9a3412;
  border-radius:12px; padding:11px 13px; font-size:13px; line-height:1.5;
}
.source {
  background:#f8fafc; border:1px solid #e2e8f0; color:#475467;
  border-radius:12px; padding:11px 13px; font-size:12px; line-height:1.5;
}
div.stButton > button {
  width:100%; border-radius:12px; min-height:48px; font-weight:750;
  border:1px solid #dfe5ee; background:white;
}
div.stButton > button:hover {
  border-color:#93b4ff; background:#eff6ff; color:#1d4ed8;
}
</style>
""", unsafe_allow_html=True)

# ---------- state ----------
if "view" not in st.session_state:
    st.session_state.view="home"
if "industry" not in st.session_state:
    st.session_state.industry="반도체"

key=get_key()
start_ym,end_ym=month_window()

st.markdown("""
<div class="hero">
  <div class="hero-title">🇰🇷 한국무역 한눈에 보기</div>
  <div class="hero-sub">강의용 웹앱 · 관세청 수출입무역통계 Open API 자동 연동</div>
</div>
""", unsafe_allow_html=True)

if not key:
    st.error("Streamlit Secrets에 공공데이터포털 인증키가 아직 설정되지 않았습니다.")
    st.code('DATA_GO_KR_SERVICE_KEY = "인증키"', language="toml")
    st.stop()

try:
    total=total_df(key,start_ym,end_ym)
except Exception as e:
    st.error("관세청 수출입총괄 API 연결에 실패했습니다.")
    st.code(str(e))
    st.caption("공공데이터포털에서 해당 API의 활용신청 승인 여부를 확인해 주세요.")
    st.stop()

if total.empty:
    st.warning("최근 수출입 자료를 불러오지 못했습니다.")
    st.stop()

latest=total.iloc[-1]

# ---------- home ----------
if st.session_state.view=="home":
    st.subheader(f"대한민국 무역 Dashboard · {latest['기간']}")

    c1,c2,c3,c4=st.columns(4)
    with c1:
        st.markdown(f'<div class="card"><div class="card-label">수출</div><div class="card-value">{fmt_usd(latest["수출"])}</div></div>', unsafe_allow_html=True)
    with c2:
        st.markdown(f'<div class="card"><div class="card-label">수입</div><div class="card-value">{fmt_usd(latest["수입"])}</div></div>', unsafe_allow_html=True)
    with c3:
        st.markdown(f'<div class="card"><div class="card-label">무역수지</div><div class="card-value">{fmt_usd(latest["무역수지"])}</div></div>', unsafe_allow_html=True)
    with c4:
        st.markdown(f'<div class="card"><div class="card-label">최근 확정월</div><div class="card-value">{latest["기간"]}</div></div>', unsafe_allow_html=True)

    st.write("")
    left,right=st.columns([2,1])

    with left:
        st.markdown('<div class="panel">', unsafe_allow_html=True)
        st.markdown("### 월별 수출입 추이")
        chart=total.set_index("기간")[["수출","수입"]]/1e8
        chart.columns=["수출(억 달러)","수입(억 달러)"]
        st.line_chart(chart,height=330)
        st.markdown('</div>', unsafe_allow_html=True)

    with right:
        st.markdown('<div class="panel">', unsafe_allow_html=True)
        st.markdown("### 산업별 바로 보기")
        names=list(INDUSTRIES.keys())
        for i in range(0,len(names),2):
            a,b=st.columns(2)
            n1=names[i]
            if a.button(f"{INDUSTRIES[n1]['emoji']} {n1}", key=f"btn_{n1}"):
                st.session_state.industry=n1
                st.session_state.view="industry"
                st.rerun()
            if i+1<len(names):
                n2=names[i+1]
                if b.button(f"{INDUSTRIES[n2]['emoji']} {n2}", key=f"btn_{n2}"):
                    st.session_state.industry=n2
                    st.session_state.view="industry"
                    st.rerun()
        st.markdown("""
        <div class="note" style="margin-top:10px">
        산업을 누르면 최근 수출액·수입액·무역수지와 최근 12개월 추이를 보여줍니다.
        </div>""", unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)

    st.write("")
    c1,c2=st.columns(2)
    with c1:
        st.markdown('<div class="panel">', unsafe_allow_html=True)
        st.markdown("### 국가별 무역")
        country=st.selectbox("국가 선택",list(COUNTRIES.keys()),label_visibility="collapsed")
        try:
            ndf=nation_df(key,start_ym,end_ym,COUNTRIES[country])
            if not ndf.empty:
                last=ndf.iloc[-1]
                st.write(f"**대{country} 수출:** {fmt_usd(last['수출'])}")
                st.write(f"**대{country} 수입:** {fmt_usd(last['수입'])}")
                st.write(f"**무역수지:** {fmt_usd(last['무역수지'])}")
            else:
                st.info("조회 자료가 없습니다.")
        except:
            st.info("국가별 API가 아직 승인되지 않았거나 조회에 실패했습니다.")
        st.markdown('</div>', unsafe_allow_html=True)

    with c2:
        st.markdown('<div class="panel">', unsafe_allow_html=True)
        st.markdown("### 오늘의 강의 질문")
        st.markdown("""
        **“수출이 늘었는데도 체감경기가 나쁠 수 있는 이유는 무엇일까요?”**

        산업별 수출 편중, 내수, 고용, 수입물가와 연결해 토론할 수 있습니다.
        """)
        st.markdown('</div>', unsafe_allow_html=True)

    st.write("")
    st.markdown("""
    <div class="source">
    자료: 관세청 수출입무역통계 Open API. 수출은 FOB, 수입은 CIF 기준.
    산업별 화면은 현재 HS 기준 교육용 근사치이며 산업통상자원부의 MTI 15대 수출품목과 정확히 일치하지 않습니다.
    </div>
    """, unsafe_allow_html=True)

# ---------- industry detail ----------
else:
    name=st.session_state.industry
    info=INDUSTRIES[name]

    if st.button("← 전체 무역으로 돌아가기"):
        st.session_state.view="home"
        st.rerun()

    st.subheader(f"{info['emoji']} {name} 수출")

    st.markdown(
        f'<div class="note"><b>분류 기준:</b> {info["note"]}. '
        '산업통상자원부의 MTI 품목분류와 범위가 다를 수 있습니다.</div>',
        unsafe_allow_html=True
    )

    try:
        idf=item_df(key,start_ym,end_ym,info["hs"])
    except Exception as e:
        st.error("산업별 API 호출에 실패했습니다.")
        st.code(str(e))
        st.stop()

    if idf.empty:
        st.info("이 산업에 대한 조회 자료가 없습니다.")
    else:
        last=idf.iloc[-1]
        c1,c2,c3=st.columns(3)
        with c1:
            st.markdown(f'<div class="card"><div class="card-label">최근월 수출액</div><div class="card-value">{fmt_usd(last["수출"])}</div></div>', unsafe_allow_html=True)
        with c2:
            st.markdown(f'<div class="card"><div class="card-label">최근월 수입액</div><div class="card-value">{fmt_usd(last["수입"])}</div></div>', unsafe_allow_html=True)
        with c3:
            st.markdown(f'<div class="card"><div class="card-label">무역수지</div><div class="card-value">{fmt_usd(last["무역수지"])}</div></div>', unsafe_allow_html=True)

        st.write("")
        left,right=st.columns([2,1])
        with left:
            st.markdown('<div class="panel">', unsafe_allow_html=True)
            st.markdown(f"### {name} 최근 12개월 추이")
            chart=idf.set_index("기간")[["수출","수입"]]/1e8
            chart.columns=["수출(억 달러)","수입(억 달러)"]
            st.line_chart(chart,height=340)
            st.markdown('</div>', unsafe_allow_html=True)

        with right:
            st.markdown('<div class="panel">', unsafe_allow_html=True)
            st.markdown("### 🎓 강의 포인트")
            if name=="반도체":
                st.write("반도체는 한국 전체 수출 변동을 좌우하는 핵심 품목입니다. 메모리 가격과 글로벌 IT 경기의 영향을 함께 봅니다.")
            elif name=="자동차":
                st.write("자동차는 미국 시장 비중과 환율, 현지 생산, 관세 변화의 영향을 함께 살펴볼 필요가 있습니다.")
            elif name=="선박":
                st.write("선박은 수주 시점과 실제 수출 인식 시점 사이에 시차가 크므로 월별 수치만으로 판단하면 안 됩니다.")
            elif name=="석유제품":
                st.write("석유제품은 물량뿐 아니라 국제유가 변화가 수출액에 크게 영향을 미칩니다.")
            elif name=="이차전지":
                st.write("해외 현지생산 확대 때문에 국내 수출 감소가 반드시 기업 경쟁력 약화를 뜻하지는 않습니다.")
            elif name=="바이오":
                st.write("대형 계약과 승인 일정 때문에 월별 변동성이 클 수 있습니다.")
            elif name=="디스플레이":
                st.write("해외 생산기지 때문에 최종 소비시장과 직접 수출국이 다를 수 있습니다.")
            else:
                st.write("SSD·서버 수요와 AI 데이터센터 투자를 함께 보면 최근 흐름을 이해하기 쉽습니다.")
            st.markdown('</div>', unsafe_allow_html=True)

        with st.expander("원자료 보기"):
            show=idf.copy()
            for c in ["수출","수입","무역수지"]:
                show[c]=(show[c]/1e8).round(2)
            st.dataframe(show,use_container_width=True,hide_index=True)
