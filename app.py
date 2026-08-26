from pathlib import Path
from urllib.parse import unquote
from datetime import date
import json, xml.etree.ElementTree as ET

import altair as alt
import pandas as pd
import requests
import streamlit as st

st.set_page_config(page_title="한국무역 한눈에 보기",page_icon="🇰🇷",layout="wide",initial_sidebar_state="collapsed")

ROOT=Path(__file__).resolve().parent
DATA=ROOT/"data"
ITEM_URL="https://apis.data.go.kr/1220000/Itemtrade/getItemtradeList"

INDUSTRY_ORDER=["반도체","자동차","석유제품","석유화학","일반기계","철강","선박","자동차부품",
"무선통신기기","디스플레이","섬유","가전","컴퓨터","바이오헬스","이차전지","전기기기","비철금속",
"농수산식품","화장품","생활용품"]
REGION_ORDER=["중국","미국","아세안","EU","일본","중남미","인도","중동","CIS"]

@st.cache_data(ttl=300,show_spinner=False)
def load_snapshots():
    m=pd.read_csv(DATA/"trade_monthly.csv",encoding="utf-8-sig")
    i=pd.read_csv(DATA/"trade_industry.csv",encoding="utf-8-sig")
    r=pd.read_csv(DATA/"trade_region.csv",encoding="utf-8-sig")
    try:
        status=json.loads((DATA/"customs_update_status.json").read_text(encoding="utf-8"))
    except Exception:
        status={}
    return m,i,r,status

def get_key():
    try:return unquote(str(st.secrets["DATA_GO_KR_SERVICE_KEY"]).strip())
    except:return None

def to_num(v):
    try:return float(str(v).replace(",",""))
    except:return 0.0

def recent_window():
    now=pd.Period(date.today().strftime("%Y-%m"),freq="M")
    end=now-1; start=end-11
    return start.strftime("%Y%m"),end.strftime("%Y%m")

@st.cache_data(ttl=3600,show_spinner=False)
def customs_item(key,hs):
    s,e=recent_window()
    rr=requests.get(ITEM_URL,params={"serviceKey":key,"strtYymm":s,"endYymm":e,"hsSgn":hs},timeout=45)
    rr.raise_for_status()
    root=ET.fromstring(rr.content)
    code=root.findtext(".//resultCode"); msg=root.findtext(".//resultMsg") or ""
    if code not in (None,"00"):raise RuntimeError(f"{code}: {msg}")
    out=[]
    for x in root.findall(".//item"):
        d={c.tag:c.text for c in x}
        p=d.get("year")
        if not p or "총계" in p:continue
        out.append({"period":p,"export":to_num(d.get("expDlr")),"import":to_num(d.get("impDlr"))})
    z=pd.DataFrame(out)
    if not z.empty:z=z.groupby("period",as_index=False)[["export","import"]].sum().sort_values("period")
    return z

def render_trade_table(df,name_col):
    rows=['<div class="trade-table"><div class="trade-row header"><div class="trade-cell">구분</div><div class="trade-cell num">수출액(억 달러)</div><div class="trade-cell num">전년동월 대비</div></div>']
    for _,rr in df.iterrows():
        yoy=float(rr["yoy"]);cls="positive" if yoy>=0 else "negative"
        rows.append(f'<div class="trade-row"><div class="trade-cell name">{rr[name_col]}</div><div class="trade-cell num">{float(rr["export_usd_100m"]):,.1f}</div><div class="trade-cell num {cls}">{yoy:+.1f}%</div></div>')
    rows.append("</div>");st.markdown("".join(rows),unsafe_allow_html=True)

def render_horizontal_bar(df,cat):
    d=df[[cat,"export_usd_100m"]].copy()
    maxv=max(float(d["export_usd_100m"].max()),1)
    ch=(alt.Chart(d).mark_bar(cornerRadiusEnd=4,color="#2563EB").encode(
        y=alt.Y(f"{cat}:N",sort=alt.SortField(field="export_usd_100m",order="descending"),title=None),
        x=alt.X("export_usd_100m:Q",title="수출액(억 달러)",scale=alt.Scale(domain=[0,maxv*1.08],nice=False)),
        tooltip=[alt.Tooltip(f"{cat}:N",title="구분"),alt.Tooltip("export_usd_100m:Q",title="억 달러",format=",.1f")]
    ).properties(height=max(260,len(d)*29)).configure_view(strokeWidth=0,fill="#fff").configure(background="#fff"))
    st.altair_chart(ch,use_container_width=True)

def render_lines(df):
    d=df[["period","export_usd_100m","import_usd_100m"]].rename(columns={"export_usd_100m":"수출","import_usd_100m":"수입"})
    long=d.melt(id_vars=["period"],var_name="구분",value_name="값")
    ymin=float(long["값"].min());ymax=float(long["값"].max());pad=max((ymax-ymin)*.12,1)
    base=alt.Chart(long).encode(
        x=alt.X("period:N",title=None,axis=alt.Axis(labelAngle=-45)),
        y=alt.Y("값:Q",title="억 달러",scale=alt.Scale(domain=[max(0,ymin-pad),ymax+pad],nice=False)),
        color=alt.Color("구분:N",title=None,scale=alt.Scale(domain=["수출","수입"],range=["#2563EB","#F59E0B"])),
        strokeDash=alt.StrokeDash("구분:N",scale=alt.Scale(domain=["수출","수입"],range=[[1,0],[7,4]]),legend=None),
        tooltip=["period:N","구분:N",alt.Tooltip("값:Q",format=",.1f")]
    )
    ch=(base.mark_line(strokeWidth=3)+base.mark_point(filled=True,size=55)).properties(height=320).configure_view(strokeWidth=0,fill="#fff").configure(background="#fff")
    st.altair_chart(ch,use_container_width=True)

st.markdown("""
<style>
html,body,[data-testid="stAppViewContainer"],[data-testid="stApp"]{background:#f4f7fb!important;color:#18202a!important;color-scheme:light!important}
[data-testid="stHeader"]{background:rgba(244,247,251,.96)!important}.block-container{max-width:1200px;padding-top:1.1rem;padding-bottom:3rem}
.hero{background:#0f2747;color:#fff;border-radius:18px;padding:22px 24px;margin-bottom:12px}.hero-title{font-size:30px;font-weight:850}.hero-sub{color:#dbe7f5;font-size:14px;margin-top:4px}
.info-card{background:#fff;border:1px solid #dfe5ee;border-radius:16px;padding:16px}.lab{font-size:12px;color:#667085;font-weight:700}.val{font-size:23px;font-weight:850;margin:7px 0}
.trade-table{width:100%;border:1px solid #dfe5ee;border-radius:14px;overflow:hidden;background:#fff}.trade-row{display:grid;grid-template-columns:minmax(120px,1.2fr) 1fr 1fr;align-items:center;border-bottom:1px solid #e5eaf1;background:#fff}.trade-row:last-child{border-bottom:0}.trade-row.header{background:#eaf0f7;font-size:12px;font-weight:800;color:#475467}.trade-cell{padding:11px 13px;font-size:14px}.trade-cell.name{font-weight:800}.trade-cell.num{text-align:right}.positive{color:#067647;font-weight:800}.negative{color:#b42318;font-weight:800}
.source{background:#f8fafc;border:1px solid #e2e8f0;color:#475467;border-radius:12px;padding:11px 13px;font-size:12px}
@media(max-width:760px){.trade-row{grid-template-columns:minmax(100px,1.2fr) .9fr .9fr}.trade-cell{padding:10px 8px;font-size:12px}}
</style>""",unsafe_allow_html=True)

st.markdown('<div class="hero"><div class="hero-title">🇰🇷 한국무역 한눈에 보기</div><div class="hero-sub">관세청 확정 통계 · 2026 MTI 20대 품목 · 9대 주요 수출지역</div></div>',unsafe_allow_html=True)

MENU=["🇰🇷 전체 무역","🏭 20대 품목","🌏 9대 지역","🧩 MTI 분류","🔎 관세청 상세조회","🎓 강의실"]
page=st.segmented_control("메뉴",MENU,default=MENU[0],selection_mode="single",label_visibility="collapsed") or MENU[0]

m,i,r,status=load_snapshots()
latest=str(m["period"].max())
source_ok=status.get("source")=="customs" and not status.get("errors")

if page=="🇰🇷 전체 무역":
    st.subheader(f"대한민국 무역 Dashboard · {latest}")
    latestrow=m[m["period"].astype(str)==latest].iloc[-1]
    c1,c2,c3=st.columns(3)
    vals=[
        ("수출",f"{latestrow['export_usd_100m']:,.1f}억 달러",f"전년동월 대비 {latestrow.get('export_yoy',0):+.1f}%"),
        ("수입",f"{latestrow['import_usd_100m']:,.1f}억 달러",f"전년동월 대비 {latestrow.get('import_yoy',0):+.1f}%"),
        ("무역수지",f"{latestrow['balance_usd_100m']:+,.1f}억 달러","확정·현행화 통계" if source_ok else "최근 저장자료"),
    ]
    for col,(a,b,c) in zip([c1,c2,c3],vals):
        with col:st.markdown(f'<div class="info-card"><div class="lab">{a}</div><div class="val">{b}</div><div class="lab">{c}</div></div>',unsafe_allow_html=True)
    if len(m)>1:
        st.markdown("### 최근 12개월 통관 시계열")
        render_lines(m.sort_values("period").tail(12))

elif page=="🏭 20대 품목":
    st.subheader(f"2026 MTI 기준 20대 주력 수출품목 · {str(i['period'].max())}")
    li=i[i["period"].astype(str)==str(i["period"].max())].copy()
    left,right=st.columns([1.25,1])
    with left:render_trade_table(li.sort_values("export_usd_100m",ascending=False),"industry")
    with right:render_horizontal_bar(li.sort_values("export_usd_100m",ascending=False),"industry")

elif page=="🌏 9대 지역":
    st.subheader(f"9대 주요 수출지역 · {str(r['period'].max())}")
    lr=r[r["period"].astype(str)==str(r["period"].max())].copy()
    c1,c2=st.columns([1,1])
    with c1:render_trade_table(lr,"region")
    with c2:render_horizontal_bar(lr.sort_values("export_usd_100m",ascending=False),"region")
    sel=st.selectbox("지역 선택",REGION_ORDER)
    rr=lr[lr["region"]==sel].iloc[0]
    a,b=st.columns(2);a.metric(f"대{sel} 수출",f"{rr['export_usd_100m']:.1f}억 달러");b.metric("전년동월 대비",f"{rr['yoy']:+.1f}%")

elif page=="🧩 MTI 분류":
    st.subheader("2026 HSK-MTI 연계표")
    p=DATA/"mti_hsk_mapping.xlsx"
    if p.exists():
        try:
            mp=pd.read_excel(p,sheet_name="HSK-MTI 연계표",dtype=str)
            counts=(mp[mp["구분"].isin(INDUSTRY_ORDER)].groupby("구분")["HSK"].nunique().reindex(INDUSTRY_ORDER).fillna(0).astype(int).rename("연결 HSK 수").reset_index())
            st.dataframe(counts,use_container_width=True,hide_index=True)
        except Exception as e:st.error(str(e))

elif page=="🔎 관세청 상세조회":
    st.subheader("관세청 HS 상세조회")
    key=get_key()
    hs=st.text_input("HS 코드",value="8542")
    if st.button("조회",type="primary"):
        if not key:st.warning("Streamlit Secrets에 인증키가 필요합니다.")
        else:
            try:
                with st.spinner("선택한 HS 코드만 조회 중…"):
                    d=customs_item(key,hs.strip())
                if d.empty:st.info("조회 결과 없음")
                else:
                    show=d.copy();show["export_usd_100m"]=show["export"]/1e8;show["import_usd_100m"]=show["import"]/1e8
                    render_lines(show[["period","export_usd_100m","import_usd_100m"]])
            except Exception as e:st.error(str(e))
else:
    st.subheader("강의실")
    st.markdown("월별 기본 화면은 저장된 최신 관세청 확정자료를 즉시 표시합니다. HS 상세조회만 선택한 코드에 대해 실시간 API를 사용합니다.")

caption="관세청 확정 통계 자동저장" if source_ok else "최근 저장자료"
st.markdown(f'<div class="source"><b>자료:</b> {caption} · 한국무역협회 2026 HSK-MTI 연계표 · 학생 화면은 API 대기 없이 즉시 표시됩니다.</div>',unsafe_allow_html=True)
