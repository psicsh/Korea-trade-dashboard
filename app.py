from pathlib import Path
import json
import streamlit as st
import pandas as pd
import requests, xml.etree.ElementTree as ET
from urllib.parse import unquote
from datetime import date

st.set_page_config(
    page_title="한국무역 한눈에 보기",
    page_icon="🇰🇷",
    layout="wide",
    initial_sidebar_state="collapsed",
)

ROOT=Path(__file__).resolve().parent
DATA=ROOT/"data"

TOTAL_URL="https://apis.data.go.kr/1220000/Newtrade/getNewtradeList"
ITEM_URL="https://apis.data.go.kr/1220000/Itemtrade/getItemtradeList"

GROUPS={
"IT·디지털":["반도체","디스플레이","무선통신기기","컴퓨터"],
"모빌리티":["자동차","자동차부품","선박"],
"에너지·화학":["석유제품","석유화학"],
"소재·기계":["일반기계","철강","전기기기","비철금속"],
"바이오·배터리":["바이오헬스","이차전지"],
"소비재":["섬유","가전","농수산식품","화장품","생활용품"],
}
CLASS_INFO={
"반도체":["메모리반도체","D램 / 낸드 등","시스템반도체","기타 반도체"],
"자동차":["차종(승용·화물·승합 등)","파워트레인","신차 / 중고차"],
"바이오헬스":["의약품","의료기기"],
"이차전지":["리튬이온배터리","배터리 소재(양극재·전해액·분리막 등)"],
"일반기계":["제조장비","산업기계","에너지기계","기계부품"],
}

@st.cache_data(ttl=300)
def load_data():
    m=pd.read_csv(DATA/"motir_monthly.csv",encoding="utf-8-sig")
    i=pd.read_csv(DATA/"motir_industry.csv",encoding="utf-8-sig")
    r=pd.read_csv(DATA/"motir_region.csv",encoding="utf-8-sig")
    status={}
    p=DATA/"update_status.json"
    if p.exists():
        status=json.loads(p.read_text(encoding="utf-8"))
    return m,i,r,status

def get_key():
    try:
        return unquote(str(st.secrets["DATA_GO_KR_SERVICE_KEY"]).strip())
    except:
        return None

def to_num(v):
    try:return float(str(v).replace(",",""))
    except:return 0.0

@st.cache_data(ttl=3600,show_spinner=False)
def api_get(url,key,params_tuple):
    params=dict(params_tuple); params["serviceKey"]=key
    rr=requests.get(url,params=params,timeout=30); rr.raise_for_status()
    root=ET.fromstring(rr.content)
    code=root.findtext(".//resultCode"); msg=root.findtext(".//resultMsg") or ""
    if code not in (None,"00"): raise RuntimeError(f"{code}: {msg}")
    return [{c.tag:c.text for c in x} for x in root.findall(".//item")]

def recent_window():
    now=pd.Period(date.today().strftime("%Y-%m"),freq="M")
    return (now-11).strftime("%Y%m"),now.strftime("%Y%m")

def customs_total(key):
    s,e=recent_window()
    rows=api_get(TOTAL_URL,key,tuple(sorted({"strtYymm":s,"endYymm":e}.items())))
    out=[]
    for x in rows:
        p=x.get("year")
        if not p or "총계" in p:continue
        out.append({"기간":p,"수출":to_num(x.get("expDlr")),"수입":to_num(x.get("impDlr"))})
    d=pd.DataFrame(out)
    return d.sort_values("기간") if not d.empty else d

def customs_item(key,hs):
    s,e=recent_window()
    rows=api_get(ITEM_URL,key,tuple(sorted({"strtYymm":s,"endYymm":e,"hsSgn":hs}.items())))
    out=[]
    for x in rows:
        p=x.get("year")
        if not p or "총계" in p:continue
        out.append({"기간":p,"수출":to_num(x.get("expDlr")),"수입":to_num(x.get("impDlr"))})
    d=pd.DataFrame(out)
    if not d.empty:d=d.groupby("기간",as_index=False)[["수출","수입"]].sum().sort_values("기간")
    return d

st.markdown("""
<style>
[data-testid="stAppViewContainer"]{background:#f5f7fb}
.block-container{max-width:1200px;padding-top:1.1rem;padding-bottom:3rem}
.hero{background:#0f2747;color:#fff;border-radius:18px;padding:22px 24px;margin-bottom:14px}
.hero-title{font-size:30px;font-weight:850}.hero-sub{color:#dbe7f5;font-size:14px;margin-top:4px}
.info-card{background:#fff;border:1px solid #dfe5ee;border-radius:16px;padding:17px 18px;box-shadow:0 4px 14px rgba(16,24,40,.04)}
.lab{color:#667085;font-size:13px;font-weight:700}.val{font-size:27px;font-weight:850;margin-top:7px}
.note{background:#fff7ed;border:1px solid #fed7aa;color:#9a3412;border-radius:12px;padding:11px 13px;font-size:13px;line-height:1.5}
.ok{background:#ecfdf3;border:1px solid #a6f4c5;color:#027a48;border-radius:12px;padding:11px 13px;font-size:13px;line-height:1.5}
.source{background:#f8fafc;border:1px solid #e2e8f0;color:#475467;border-radius:12px;padding:11px 13px;font-size:12px;line-height:1.5}
</style>
""",unsafe_allow_html=True)

m,i,r,status=load_data()
latest_period=str(m["period"].max())
latest=m[m["period"]==latest_period].iloc[-1]
latest_i=i[i["period"].astype(str)==latest_period].copy()
latest_r=r[r["period"].astype(str)==latest_period].copy()

st.markdown(f"""
<div class="hero">
 <div class="hero-title">🇰🇷 한국무역 한눈에 보기</div>
 <div class="hero-sub">산업통상부 MTI 20대 품목 + 9대 지역 · 관세청 상세통계</div>
</div>
""",unsafe_allow_html=True)

tab_all,tab_ind,tab_reg,tab_mti,tab_customs,tab_class=st.tabs([
    "🇰🇷 전체 무역","🏭 산업부 20대 품목","🌏 산업부 9대 지역",
    "🧩 MTI 분류","🔎 관세청 상세조회","🎓 강의실"
])

with tab_all:
    st.subheader(f"대한민국 무역 Dashboard · {latest_period}")
    c1,c2,c3,c4=st.columns(4)
    vals=[
        ("수출",f"{latest['export_usd_100m']:,.1f}억 달러",f"{latest['export_yoy']:+.1f}%"),
        ("수입",f"{latest['import_usd_100m']:,.1f}억 달러",f"{latest['import_yoy']:+.1f}%"),
        ("무역수지",f"{latest['balance_usd_100m']:+,.1f}억 달러",str(latest["status"])),
        ("일평균 수출",f"{latest['daily_export_usd_100m']:,.1f}억 달러","산업부 잠정치"),
    ]
    for col,(lab,val,sub) in zip([c1,c2,c3,c4],vals):
        with col:
            st.markdown(f'<div class="info-card"><div class="lab">{lab}</div><div class="val">{val}</div><div class="lab">{sub}</div></div>',unsafe_allow_html=True)
    st.write("")
    st.markdown("### 이번 달 주요 특징")
    inc_count = int((latest_i["yoy"] > 0).sum())
    top_growth = latest_i.sort_values("yoy", ascending=False).iloc[0]
    top_export = latest_i.sort_values("export_usd_100m", ascending=False).iloc[0]
    reg_growth = latest_r[latest_r["yoy"] > 0]["region"].tolist()
    reg_down = latest_r[latest_r["yoy"] <= 0]["region"].tolist()

    h1,h2,h3,h4 = st.columns(4)
    h1.metric("20대 품목 증가", f"{inc_count}개 / 20개")
    h2.metric("최대 수출 품목", str(top_export["industry"]), f"{top_export['export_usd_100m']:.1f}억 달러")
    h3.metric("증가율 1위", str(top_growth["industry"]), f"{top_growth['yoy']:+.1f}%")
    if reg_down:
        h4.metric("감소 지역", " · ".join(reg_down), f"나머지 {len(reg_growth)}개 지역 증가")
    else:
        h4.metric("9대 지역", "모두 증가", "")

    st.caption("※ 산업부 최신 월간 수출입동향의 잠정치를 바탕으로 자동 요약합니다.")
    st.write("")

    if len(m)>1:
        ch=m.set_index("period")[["export_usd_100m","import_usd_100m"]]
        ch.columns=["수출(억 달러)","수입(억 달러)"]
        st.line_chart(ch,height=330)
    else:
        st.info("자동 갱신이 누적되면 이곳에 산업부 월별 시계열 그래프가 쌓입니다.")

    key=get_key()
    if key:
        try:
            cd=customs_total(key)
            if not cd.empty:
                st.markdown("### 관세청 최근 12개월 통관 시계열")
                cc=cd.set_index("기간")[["수출","수입"]]/1e8
                cc.columns=["관세청 수출(억 달러)","관세청 수입(억 달러)"]
                st.line_chart(cc,height=300)
        except Exception as e:
            st.caption(f"관세청 API 시계열 표시 실패: {e}")

with tab_ind:
    st.subheader("산업통상부 20대 주력 수출품목")
    st.caption(f"현행 MTI 기준 · 최신 {latest_period}")
    left,right=st.columns([1.25,1])
    with left:
        show=latest_i[["industry","export_usd_100m","yoy"]].copy()
        show.columns=["품목","수출액(억 달러)","전년동월비(%)"]
        st.dataframe(show.sort_values("수출액(억 달러)",ascending=False),use_container_width=True,hide_index=True,height=530)
    with right:
        st.bar_chart(latest_i.set_index("industry")["export_usd_100m"].sort_values(ascending=False),height=480)

    st.markdown("### 품목별 월별 추이")
    selected=st.selectbox("품목",latest_i["industry"].tolist())
    hist=i[i["industry"]==selected].sort_values("period")
    c1,c2=st.columns(2)
    lr=hist.iloc[-1]
    c1.metric("최신 수출액",f"{lr['export_usd_100m']:.1f}억 달러")
    c2.metric("전년동월비",f"{lr['yoy']:+.1f}%")
    if len(hist)>1:
        st.line_chart(hist.set_index("period")[["export_usd_100m"]],height=280)
    else:
        st.caption("다음 달부터 자동으로 시계열이 누적됩니다.")

with tab_reg:
    st.subheader("산업통상부 9대 주요 수출지역")
    show=latest_r[["region","export_usd_100m","yoy"]].copy()
    show.columns=["지역","수출액(억 달러)","전년동월비(%)"]
    c1,c2=st.columns([1,1])
    c1.dataframe(show,use_container_width=True,hide_index=True,height=390)
    with c2:
        st.bar_chart(latest_r.set_index("region")["export_usd_100m"].sort_values(ascending=False),height=360)
    selected=st.selectbox("지역",latest_r["region"].tolist(),key="region_select")
    hist=r[r["region"]==selected].sort_values("period")
    if len(hist)>1:
        st.line_chart(hist.set_index("period")[["export_usd_100m"]],height=280)

with tab_mti:
    st.subheader("MTI 산업분류 탐색")
    st.caption("20대 주력품목 전체를 먼저 익히고, 주요 개편품목은 하위분류 구조를 확인합니다.")
    for g,items in GROUPS.items():
        st.markdown(f"**{g}** · " + " / ".join(items))
    st.divider()
    chosen=st.selectbox("하위분류 예시",list(CLASS_INFO.keys()))
    st.markdown(f"### {chosen}")
    for x in CLASS_INFO[chosen]:
        st.write("↳",x)
    mapping=DATA/"mti_hsk_mapping.xlsx"
    if mapping.exists():
        st.success("공식 HSK–MTI 연계표 파일이 저장되어 있습니다.")
        try:
            xls=pd.ExcelFile(mapping)
            st.caption("시트: "+", ".join(xls.sheet_names[:8]))
        except:
            st.caption("연계표 파일은 있으나 미리보기에 실패했습니다.")
    else:
        st.info("GitHub Action이 한국무역협회 공식 HSK–MTI 연계표 자동 다운로드를 시도합니다. 실패 시 공식 파일을 data/mti_hsk_mapping.xlsx로 한 번만 넣으면 됩니다.")

with tab_customs:
    st.subheader("관세청 HS 상세조회")
    key=get_key()
    if not key:
        st.warning("Streamlit Secrets에 DATA_GO_KR_SERVICE_KEY를 설정하면 작동합니다.")
    else:
        hs=st.text_input("HS 코드",value="8542",help="예: 8542 전자집적회로, 8703 승용자동차")
        if st.button("조회"):
            try:
                d=customs_item(key,hs.strip())
                if d.empty:st.info("조회 결과 없음")
                else:
                    cc=d.set_index("기간")[["수출","수입"]]/1e8
                    cc.columns=["수출(억 달러)","수입(억 달러)"]
                    st.line_chart(cc,height=340)
                    st.dataframe(d,use_container_width=True,hide_index=True)
            except Exception as e:
                st.error(str(e))

with tab_class:
    st.subheader("강의실")
    st.markdown("""
### 오늘의 질문
**“산업부의 잠정치와 관세청 확정·현행화 통계가 왜 조금 다를까요?”**

- 산업부 월간 「수출입 동향」은 해당 월 말일까지의 통관자료를 기초로 한 잠정 분석입니다.
- 관세청 월간통계는 정정·취하 등을 반영해 현행화됩니다.
- MTI는 HS 코드를 한국의 산업·무역 분석 목적에 맞게 다시 묶은 분류입니다.

### 자동화가 수업에 주는 장점
월이 바뀌면 새 산업부 발표가 자동으로 추가되므로, 학생은 같은 URL에서 최신 자료를 계속 볼 수 있습니다.
""")

st.write("")
st.markdown(
    f'<div class="source"><b>자료:</b> 산업통상부 「{latest["source_title"]}」, 관세청 수출입무역통계. '
    f'산업부 자료는 월간 잠정치이며 이후 정정될 수 있습니다.</div>',
    unsafe_allow_html=True
)
