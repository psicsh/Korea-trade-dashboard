from pathlib import Path
from datetime import date
from urllib.parse import unquote
import re
import xml.etree.ElementTree as ET

import altair as alt
import pandas as pd
import requests
import streamlit as st

st.set_page_config(
    page_title="한국무역 한눈에 보기",
    page_icon="🇰🇷",
    layout="wide",
    initial_sidebar_state="collapsed",
)

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"

TOTAL_URL  = "https://apis.data.go.kr/1220000/Newtrade/getNewtradeList"
ITEM_URL   = "https://apis.data.go.kr/1220000/Itemtrade/getItemtradeList"
NATION_URL = "https://apis.data.go.kr/1220000/nationtrade/getNationtradeList"

INDUSTRY_ORDER = [
    "반도체","자동차","석유제품","석유화학","일반기계","철강","선박","자동차부품",
    "무선통신기기","디스플레이","섬유","가전","컴퓨터","바이오헬스","이차전지",
    "전기기기","비철금속","농수산식품","화장품","생활용품"
]

REGION_CODES = {
    "중국": {"CN"},
    "미국": {"US"},
    "아세안": {"BN","KH","ID","LA","MY","MM","PH","SG","TH","VN","TL"},
    "EU": {"AT","BE","BG","HR","CY","CZ","DK","EE","FI","FR","DE","GR","HU","IE","IT",
           "LV","LT","LU","MT","NL","PL","PT","RO","SK","SI","ES","SE"},
    "일본": {"JP"},
    "중남미": {"AR","BO","BR","CL","CO","CR","CU","DO","EC","SV","GT","HT","HN","JM","MX",
               "NI","PA","PY","PE","TT","UY","VE","BZ","GY","SR","BS","BB","GD","LC","VC",
               "AG","DM","KN"},
    "인도": {"IN"},
    "중동": {"BH","IR","IQ","IL","JO","KW","LB","OM","QA","SA","SY","AE","YE","TR"},
    "CIS": {"RU","KZ","UZ","KG","TJ","TM","AZ","AM","BY","MD","UA","GE"},
}
REGION_ORDER = ["중국","미국","아세안","EU","일본","중남미","인도","중동","CIS"]

GROUPS = {
    "IT·디지털": ["반도체","디스플레이","무선통신기기","컴퓨터"],
    "모빌리티": ["자동차","자동차부품","선박"],
    "에너지·화학": ["석유제품","석유화학"],
    "소재·기계": ["일반기계","철강","전기기기","비철금속"],
    "바이오·배터리": ["바이오헬스","이차전지"],
    "소비재": ["섬유","가전","농수산식품","화장품","생활용품"],
}

# ── 공통 ─────────────────────────────────────────────────────────────────────
def get_key():
    try:
        return unquote(str(st.secrets["DATA_GO_KR_SERVICE_KEY"]).strip())
    except Exception:
        return None

def to_num(v):
    try:
        return float(str(v).replace(",", "").strip())
    except Exception:
        return 0.0

def norm_period(v):
    s = str(v or "").strip().replace(".", "").replace("-", "")
    return s[:6] if len(s) >= 6 and s[:6].isdigit() else None

def period_label(p):
    return f"{p[:4]}-{p[4:6]}"

def previous_year_period(p):
    return f"{int(p[:4])-1:04d}{p[4:6]}"

def confirmed_period():
    now = pd.Period(date.today().strftime("%Y-%m"), freq="M")
    end = now - (1 if date.today().day >= 16 else 2)
    return end.strftime("%Y%m")

def twelve_month_window(end_yyyymm):
    end = pd.Period(end_yyyymm, freq="M")
    return (end-11).strftime("%Y%m"), end.strftime("%Y%m")

@st.cache_data(ttl=21600, show_spinner=False)
def api_get(url, key, params_tuple, timeout=60):
    params = dict(params_tuple)
    params["serviceKey"] = key
    rr = requests.get(url, params=params, timeout=timeout)
    rr.raise_for_status()
    root = ET.fromstring(rr.content)
    code = root.findtext(".//resultCode")
    msg = root.findtext(".//resultMsg") or ""
    if code not in (None, "00"):
        raise RuntimeError(f"{code}: {msg}")
    return [{c.tag: c.text for c in item} for item in root.findall(".//item")]

def api_rows(url, key, timeout=60, **params):
    return api_get(url, key, tuple(sorted(params.items())), timeout)

# ── 전체무역 ─────────────────────────────────────────────────────────────────
@st.cache_data(ttl=21600, show_spinner=False)
def customs_total_12m(key, end_period):
    start,end = twelve_month_window(end_period)
    rows = api_rows(TOTAL_URL,key,strtYymm=start,endYymm=end)
    out=[]
    for x in rows:
        p=norm_period(x.get("year"))
        if not p: continue
        out.append({"period":p,"export":to_num(x.get("expDlr")),
                    "import":to_num(x.get("impDlr")),
                    "balance":to_num(x.get("balPayments"))})
    d=pd.DataFrame(out)
    if d.empty: return d
    return d.groupby("period",as_index=False)[["export","import","balance"]].sum().sort_values("period")

@st.cache_data(ttl=21600, show_spinner=False)
def customs_total_one(key, p):
    rows=api_rows(TOTAL_URL,key,strtYymm=p,endYymm=p)
    exp=imp=bal=0.0
    for x in rows:
        if norm_period(x.get("year")):
            exp+=to_num(x.get("expDlr")); imp+=to_num(x.get("impDlr")); bal+=to_num(x.get("balPayments"))
    return {"export":exp,"import":imp,"balance":bal}

# ── 국가/지역 ─────────────────────────────────────────────────────────────────
@st.cache_data(ttl=21600, show_spinner=False)
def customs_nations_one(key,p):
    rows=api_rows(NATION_URL,key,strtYymm=p,endYymm=p,timeout=75)
    out=[]
    for x in rows:
        pp=norm_period(x.get("year"))
        if not pp: continue
        code=(x.get("statCd") or x.get("cntyCd") or "").strip().upper()
        if not code or code=="-": continue
        out.append({"period":pp,"country_code":code,
                    "export":to_num(x.get("expDlr")),"import":to_num(x.get("impDlr"))})
    return pd.DataFrame(out)

def aggregate_regions(cur,prv):
    rows=[]
    for region in REGION_ORDER:
        codes=REGION_CODES[region]
        c=cur[cur["country_code"].isin(codes)]["export"].sum() if not cur.empty else 0
        p=prv[prv["country_code"].isin(codes)]["export"].sum() if not prv.empty else 0
        rows.append({"region":region,"export_usd_100m":c/1e8,
                     "yoy":((c/p)-1)*100 if p else 0.0})
    return pd.DataFrame(rows)

# ── HSK-MTI 공식 연계표 ───────────────────────────────────────────────────────
def _norm_hsk(v):
    s=re.sub(r"\D","",str(v or "").split(".0")[0])
    return s.zfill(10) if s else None

def _norm_mti(v):
    s=re.sub(r"\D","",str(v or "").split(".0")[0])
    return s.zfill(6) if s else None

@st.cache_data(ttl=86400, show_spinner=False)
def load_mti_mapping(path_str, file_mtime):
    """
    공식 파일 구조를 직접 사용:
    sheet='HSK-MTI 연계표', columns='HSK','MTI','구분'
    file_mtime을 캐시 키에 넣어 파일이 바뀌면 자동 재읽기.
    """
    path=Path(path_str)
    d=pd.read_excel(path, sheet_name="HSK-MTI 연계표", dtype=str)
    required={"HSK","MTI","구분"}
    missing=required-set(d.columns)
    if missing:
        raise RuntimeError(f"연계표 필수 열 없음: {', '.join(sorted(missing))}")

    d=d[["HSK","MTI","구분"]].copy()
    d["hsk"]=d["HSK"].map(_norm_hsk)
    d["mti"]=d["MTI"].map(_norm_mti)
    d["industry"]=d["구분"].astype(str).str.strip()
    d=d[d["hsk"].str.fullmatch(r"\d{10}",na=False)]
    d=d[d["mti"].str.fullmatch(r"\d{6}",na=False)]
    d=d[d["industry"].isin(INDUSTRY_ORDER)]
    d=d[["hsk","mti","industry"]].drop_duplicates("hsk")

    if len(d)<1000:
        raise RuntimeError(f"유효 HSK-MTI 매핑이 너무 적음: {len(d):,}개")
    return d

def get_mapping():
    p=DATA/"mti_hsk_mapping.xlsx"
    if not p.exists():
        return None
    return load_mti_mapping(str(p), p.stat().st_mtime_ns)

# ── 품목별 API ────────────────────────────────────────────────────────────────
@st.cache_data(ttl=43200, show_spinner=False)
def customs_items_one(key,p):
    # 한 달 전체 HSK 10단위. 한 달 약 1만 행 수준이라 첫 조회만 시간이 걸릴 수 있음.
    rows=api_rows(ITEM_URL,key,strtYymm=p,endYymm=p,timeout=120)
    out=[]
    for x in rows:
        pp=norm_period(x.get("year"))
        if not pp: continue
        hsk=_norm_hsk(x.get("hsCode") or x.get("hsCd"))
        if not hsk: continue
        out.append({"period":pp,"hsk":hsk,
                    "export":to_num(x.get("expDlr")),"import":to_num(x.get("impDlr"))})
    d=pd.DataFrame(out)
    if d.empty: return d
    return d.groupby(["period","hsk"],as_index=False)[["export","import"]].sum()

def aggregate_industries(cur,prv,mapping):
    def agg(items):
        if items.empty: return pd.Series(dtype=float)
        x=items.merge(mapping[["hsk","industry"]],on="hsk",how="inner")
        return x.groupby("industry")["export"].sum()
    c=agg(cur); p=agg(prv)
    rows=[]
    for name in INDUSTRY_ORDER:
        cv=float(c.get(name,0)); pv=float(p.get(name,0))
        rows.append({"industry":name,"export_usd_100m":cv/1e8,
                     "yoy":((cv/pv)-1)*100 if pv else 0.0})
    return pd.DataFrame(rows)

@st.cache_data(ttl=21600, show_spinner=False)
def customs_item_12m(key,hs,end_period):
    start,end=twelve_month_window(end_period)
    rows=api_rows(ITEM_URL,key,strtYymm=start,endYymm=end,hsSgn=hs,timeout=75)
    out=[]
    for x in rows:
        p=norm_period(x.get("year"))
        if p:
            out.append({"period":p,"export":to_num(x.get("expDlr")),"import":to_num(x.get("impDlr"))})
    d=pd.DataFrame(out)
    if d.empty:return d
    return d.groupby("period",as_index=False)[["export","import"]].sum().sort_values("period")

# ── 시각화 ────────────────────────────────────────────────────────────────────
def render_trade_table(df,name_col):
    rows=['<div class="trade-table">',
          '<div class="trade-row header"><div class="trade-cell">구분</div><div class="trade-cell num">수출액(억 달러)</div><div class="trade-cell num">전년동월 대비</div></div>']
    for _,rr in df.iterrows():
        yoy=float(rr["yoy"]); cls="positive" if yoy>=0 else "negative"
        rows.append(f'<div class="trade-row"><div class="trade-cell name">{rr[name_col]}</div>'
                    f'<div class="trade-cell num">{float(rr["export_usd_100m"]):,.1f}</div>'
                    f'<div class="trade-cell num {cls}">{yoy:+.1f}%</div></div>')
    rows.append("</div>")
    st.markdown("".join(rows),unsafe_allow_html=True)

def render_horizontal_bar(df,category_col,value_col="export_usd_100m",height_per_row=31):
    d=df[[category_col,value_col]].copy()
    d[value_col]=pd.to_numeric(d[value_col],errors="coerce").fillna(0)
    max_v=max(float(d[value_col].max()),1.0)
    chart=(alt.Chart(d).mark_bar(cornerRadiusEnd=4,color="#2563EB").encode(
        y=alt.Y(f"{category_col}:N",sort=alt.SortField(field=value_col,order="descending"),
                title=None,axis=alt.Axis(labelLimit=125,labelFontSize=12)),
        x=alt.X(f"{value_col}:Q",title="수출액(억 달러)",
                scale=alt.Scale(domain=[0,max_v*1.08],nice=False,zero=True),
                axis=alt.Axis(format=",.0f",tickCount=5)),
        tooltip=[alt.Tooltip(f"{category_col}:N",title="구분"),
                 alt.Tooltip(f"{value_col}:Q",title="수출액(억 달러)",format=",.1f")]
    ).properties(height=max(250,int(len(d)*height_per_row)))
    .configure_view(strokeWidth=0,fill="#fff").configure(background="#fff")
    .configure_axis(labelColor="#344054",titleColor="#344054",gridColor="#e5e7eb",
                    domainColor="#98a2b3",tickColor="#98a2b3"))
    st.altair_chart(chart,use_container_width=True)

def render_time_lines(df,period_col,series_cols,height=320):
    d=df[[period_col]+series_cols].copy()
    for c in series_cols:d[c]=pd.to_numeric(d[c],errors="coerce")
    long=d.melt(id_vars=[period_col],value_vars=series_cols,var_name="구분",value_name="값").dropna()
    if long.empty:return
    ymin,ymax=float(long["값"].min()),float(long["값"].max())
    pad=(ymax-ymin)*.12 if ymax>ymin else 1
    low=max(0,ymin-pad); high=ymax+pad
    palette=["#2563EB","#F59E0B"][:len(series_cols)]
    dashes=[[1,0],[7,4]][:len(series_cols)]
    base=alt.Chart(long).encode(
        x=alt.X(f"{period_col}:N",title=None,axis=alt.Axis(labelAngle=-45,labelFontSize=11)),
        y=alt.Y("값:Q",title="억 달러",scale=alt.Scale(domain=[low,high],nice=False)),
        color=alt.Color("구분:N",title=None,scale=alt.Scale(domain=series_cols,range=palette),
                        legend=alt.Legend(orient="bottom",direction="horizontal",labelFontSize=12)),
        strokeDash=alt.StrokeDash("구분:N",title=None,scale=alt.Scale(domain=series_cols,range=dashes),legend=None),
        tooltip=[alt.Tooltip(f"{period_col}:N",title="기간"),alt.Tooltip("구분:N",title="구분"),
                 alt.Tooltip("값:Q",title="억 달러",format=",.1f")]
    )
    chart=((base.mark_line(strokeWidth=3)+base.mark_point(filled=True,size=58))
           .properties(height=height).configure_view(strokeWidth=0,fill="#fff")
           .configure(background="#fff").configure_axis(labelColor="#344054",
           titleColor="#344054",gridColor="#e5e7eb",domainColor="#98a2b3",tickColor="#98a2b3"))
    st.altair_chart(chart,use_container_width=True)

# ── CSS ───────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
html,body,[data-testid="stAppViewContainer"],[data-testid="stApp"]{background:#f4f7fb!important;color:#18202a!important;color-scheme:light!important}
[data-testid="stHeader"]{background:rgba(244,247,251,.96)!important}.block-container{max-width:1200px;padding-top:1.1rem;padding-bottom:3rem}
.hero{background:#0f2747;color:#fff;border-radius:18px;padding:22px 24px;margin-bottom:12px}.hero-title{font-size:30px;font-weight:850}.hero-sub{color:#dbe7f5;font-size:14px;margin-top:4px}
.info-card{background:#fff;border:1px solid #dfe5ee;border-radius:16px;padding:16px;min-height:96px}.info-card .lab{font-size:12px;color:#667085;font-weight:700}.info-card .val{font-size:22px;font-weight:850;margin:7px 0}
.summary-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin:8px 0}.summary-box{background:#fff;border:1px solid #dfe5ee;border-radius:13px;padding:14px}.slabel{font-size:12px;color:#667085;font-weight:700}.svalue{font-size:24px;font-weight:850;margin-top:6px}.snote{font-size:12px;color:#475467;margin-top:4px}
.trade-table{width:100%;border:1px solid #dfe5ee;border-radius:14px;overflow:hidden;background:#fff}.trade-row{display:grid;grid-template-columns:minmax(120px,1.2fr) 1fr 1fr;align-items:center;border-bottom:1px solid #e5eaf1;background:#fff}.trade-row:last-child{border-bottom:0}.trade-row.header{background:#eaf0f7;font-size:12px;font-weight:800;color:#475467}.trade-cell{padding:11px 13px;font-size:14px}.trade-cell.name{font-weight:800}.trade-cell.num{text-align:right}.positive{color:#067647;font-weight:800}.negative{color:#b42318;font-weight:800}
div[data-testid="stSegmentedControl"]{margin-bottom:12px}div[data-testid="stSegmentedControl"] button{font-weight:750}
.source{background:#f8fafc;border:1px solid #e2e8f0;color:#475467;border-radius:12px;padding:11px 13px;font-size:12px;line-height:1.5}
[data-baseweb="select"]>div,[data-baseweb="input"]>div,input,textarea{background:#fff!important;color:#18202a!important}
@media(max-width:760px){.summary-grid{grid-template-columns:1fr 1fr}.trade-row{grid-template-columns:minmax(100px,1.2fr) .9fr .9fr}.trade-cell{padding:10px 8px;font-size:12px}}
</style>
""",unsafe_allow_html=True)

st.markdown("""<div class="hero"><div class="hero-title">🇰🇷 한국무역 한눈에 보기</div>
<div class="hero-sub">관세청 확정 통계 · 2026 MTI 20대 품목 · 9대 주요 수출지역</div></div>""",unsafe_allow_html=True)

MENU=["🇰🇷 전체 무역","🏭 20대 품목","🌏 9대 지역","🧩 MTI 분류","🔎 관세청 상세조회","🎓 강의실"]
page=st.segmented_control("메뉴",MENU,default=MENU[0],selection_mode="single",label_visibility="collapsed")
if page is None: page=MENU[0]

key=get_key()
end_period=confirmed_period()
prev_period=previous_year_period(end_period)

# 중요: 선택한 메뉴의 데이터만 조회한다. 첫 화면에서 전체 HSK를 미리 읽지 않는다.
if page=="🇰🇷 전체 무역":
    st.subheader(f"대한민국 무역 Dashboard · {period_label(end_period)}")
    st.caption("관세청 확정·현행화 통계 기준 · 매월 16일 이후 전월, 그 이전에는 전전월을 기본 표시")
    if not key:
        st.warning("Streamlit Secrets에 DATA_GO_KR_SERVICE_KEY가 필요합니다.")
    else:
        try:
            with st.spinner("관세청 최신 무역통계를 불러오는 중…"):
                total12=customs_total_12m(key,end_period)
                prev=customs_total_one(key,prev_period)
            if total12.empty:
                st.info("조회 결과가 없습니다.")
            else:
                rr=total12.iloc[-1]
                exp,imp,bal=rr["export"],rr["import"],rr["balance"]
                ey=((exp/prev["export"])-1)*100 if prev["export"] else 0
                iy=((imp/prev["import"])-1)*100 if prev["import"] else 0
                c1,c2,c3=st.columns(3)
                for col,(lab,val,sub) in zip([c1,c2,c3],[
                    ("수출",f"{exp/1e8:,.1f}억 달러",f"전년동월 대비 {ey:+.1f}%"),
                    ("수입",f"{imp/1e8:,.1f}억 달러",f"전년동월 대비 {iy:+.1f}%"),
                    ("무역수지",f"{bal/1e8:+,.1f}억 달러","관세청 확정·현행화")
                ]):
                    with col:
                        st.markdown(f'<div class="info-card"><div class="lab">{lab}</div><div class="val">{val}</div><div class="lab">{sub}</div></div>',unsafe_allow_html=True)
                st.markdown("### 최근 12개월 통관 시계열")
                ch=total12.copy(); ch["수출"]=ch["export"]/1e8; ch["수입"]=ch["import"]/1e8
                render_time_lines(ch[["period","수출","수입"]],"period",["수출","수입"],320)
        except Exception as e:
            st.error(f"관세청 총괄 API 조회 실패: {e}")

elif page=="🏭 20대 품목":
    st.subheader(f"2026 MTI 기준 20대 주력 수출품목 · {period_label(end_period)}")
    st.caption("관세청 HSK 10단위 통관통계 + 공식 HSK-MTI 연계표 재집계")
    if not key:
        st.warning("Streamlit Secrets에 DATA_GO_KR_SERVICE_KEY가 필요합니다.")
    else:
        try:
            mapping=get_mapping()
            if mapping is None:
                st.warning("data/mti_hsk_mapping.xlsx가 없습니다.")
            else:
                group_count=mapping["industry"].nunique()
                st.success(f"공식 HSK-MTI 연계표 인식 완료 · HSK {len(mapping):,}개 · 20대 구분 {group_count}개")
                with st.spinner("처음 한 번은 HSK 약 2만 행(당월+전년동월)을 읽어 10~30초 정도 걸릴 수 있습니다. 이후에는 캐시되어 빨라집니다."):
                    cur=customs_items_one(key,end_period)
                    prv=customs_items_one(key,prev_period)
                    ind=aggregate_industries(cur,prv,mapping)
                left,right=st.columns([1.25,1])
                with left: render_trade_table(ind.sort_values("export_usd_100m",ascending=False),"industry")
                with right: render_horizontal_bar(ind.sort_values("export_usd_100m",ascending=False),"industry",height_per_row=28)
                selected=st.selectbox("품목 상세",INDUSTRY_ORDER)
                rr=ind[ind["industry"]==selected].iloc[0]
                c1,c2=st.columns(2)
                c1.metric("수출액",f"{rr['export_usd_100m']:.1f}억 달러")
                c2.metric("전년동월 대비",f"{rr['yoy']:+.1f}%")
        except Exception as e:
            st.error(f"20대 품목 계산 실패: {e}")

elif page=="🌏 9대 지역":
    st.subheader(f"9대 주요 수출지역 · {period_label(end_period)}")
    st.caption("관세청 국가별 통계를 지역별 국가코드로 자동 합산")
    if not key:
        st.warning("Streamlit Secrets에 DATA_GO_KR_SERVICE_KEY가 필요합니다.")
    else:
        try:
            with st.spinner("국가별 통계를 불러오는 중…"):
                cur=customs_nations_one(key,end_period); prv=customs_nations_one(key,prev_period)
                reg=aggregate_regions(cur,prv)
            c1,c2=st.columns([1,1])
            with c1: render_trade_table(reg,"region")
            with c2: render_horizontal_bar(reg.sort_values("export_usd_100m",ascending=False),"region",height_per_row=34)
            selected=st.selectbox("지역 선택",REGION_ORDER)
            rr=reg[reg["region"]==selected].iloc[0]
            c1,c2=st.columns(2)
            c1.metric(f"대{selected} 수출",f"{rr['export_usd_100m']:.1f}억 달러")
            c2.metric("전년동월 대비",f"{rr['yoy']:+.1f}%")
        except Exception as e:
            st.error(f"9대 지역 계산 실패: {e}")

elif page=="🧩 MTI 분류":
    st.subheader("2026 MTI 분류")
    try:
        mapping=get_mapping()
        if mapping is None:
            st.warning("연계표가 없습니다.")
        else:
            st.success(f"공식 HSK-MTI 연계표 정상 인식 · HSK {len(mapping):,}개")
            counts=(mapping.groupby("industry")["hsk"].nunique().reindex(INDUSTRY_ORDER).fillna(0).astype(int)
                    .rename("연결 HSK 수").reset_index().rename(columns={"industry":"품목"}))
            st.dataframe(counts,use_container_width=True,hide_index=True)
    except Exception as e:
        st.error(f"연계표 읽기 실패: {e}")
    st.markdown("### 산업군")
    for g,items in GROUPS.items(): st.markdown(f"**{g}** · "+" / ".join(items))

elif page=="🔎 관세청 상세조회":
    st.subheader("관세청 HS 상세조회")
    if not key:
        st.warning("Streamlit Secrets에 DATA_GO_KR_SERVICE_KEY가 필요합니다.")
    else:
        hs=st.text_input("HS 코드",value="8542",help="예: 8542 전자집적회로, 8703 승용자동차")
        if st.button("조회",type="primary"):
            try:
                with st.spinner("관세청 품목별 통계를 조회하는 중…"):
                    d=customs_item_12m(key,hs.strip(),end_period)
                if d.empty: st.info("조회 결과 없음")
                else:
                    ch=d.copy(); ch["수출"]=ch["export"]/1e8; ch["수입"]=ch["import"]/1e8
                    render_time_lines(ch[["period","수출","수입"]],"period",["수출","수입"],340)
                    show=d.copy(); show["수출(억 달러)"]=show["export"]/1e8; show["수입(억 달러)"]=show["import"]/1e8
                    st.dataframe(show[["period","수출(억 달러)","수입(억 달러)"]],use_container_width=True,hide_index=True)
            except Exception as e: st.error(str(e))

else:
    st.subheader("강의실")
    st.markdown("""
### 오늘의 질문
**산업부 월초 잠정치와 관세청 확정·현행화 통계는 왜 조금 다를까요?**

- 이 앱은 관세청 통관통계를 기본으로 사용합니다.
- 20대 품목은 HSK 10단위 통계를 공식 HSK-MTI 연계표의 `구분` 열로 다시 묶습니다.
- 9대 지역은 국가별 통계를 지역 국가군으로 합산합니다.
- 숫자는 산업부 월초 잠정치보다 늦지만 강의용 시계열에는 더 안정적입니다.
""")

st.write("")
st.markdown(f'<div class="source"><b>자료:</b> 관세청 수출입무역통계(Open API) · 한국무역협회 2026 HSK-MTI 공식 연계표 · 기본 표시월 {period_label(end_period)}</div>',unsafe_allow_html=True)
