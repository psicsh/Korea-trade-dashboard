from pathlib import Path
from datetime import date
from urllib.parse import unquote
import json, re
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

# ─────────────────────────────────────────────────────────────────────────────
# 관세청 공공데이터 API
# ─────────────────────────────────────────────────────────────────────────────
TOTAL_URL  = "https://apis.data.go.kr/1220000/Newtrade/getNewtradeList"
ITEM_URL   = "https://apis.data.go.kr/1220000/Itemtrade/getItemtradeList"
NATION_URL = "https://apis.data.go.kr/1220000/nationtrade/getNationtradeList"

# 2026년 산업통상부 개편 기준 20대 주력품목 MTI 상위코드
# HSK→MTI 연계표의 MTI 6단위 코드가 아래 prefix로 시작하면 해당 주력품목으로 집계.
MTI_MAJOR = {
    "반도체":       ["831"],
    "자동차":       ["741"],
    "석유제품":     ["133"],
    "석유화학":     ["21"],
    "일반기계":     ["71", "72", "75", "76"],
    "철강":         ["61"],
    "선박":         ["746"],
    "자동차부품":   ["742"],
    "무선통신기기": ["812"],
    "디스플레이":   ["8371"],
    "섬유":         ["4"],
    "가전":         ["82"],
    "컴퓨터":       ["813"],
    "바이오헬스":   ["93"],
    "이차전지":     ["8361"],
    "전기기기":     ["84"],
    "비철금속":     ["62"],
    "농수산식품":   ["0"],
    "화장품":       ["2273"],
    "생활용품":     ["51"],
}
INDUSTRY_ORDER = list(MTI_MAJOR.keys())

# 관세청 국가코드(ISO alpha-2) 기반 지역 묶음.
# 중국·미국·일본·인도는 개별국, 나머지는 국가군 합계.
REGION_CODES = {
    "중국": {"CN"},
    "미국": {"US"},
    "아세안": {"BN","KH","ID","LA","MY","MM","PH","SG","TH","VN","TL"},
    "EU": {"AT","BE","BG","HR","CY","CZ","DK","EE","FI","FR","DE","GR","HU","IE","IT",
           "LV","LT","LU","MT","NL","PL","PT","RO","SK","SI","ES","SE"},
    "일본": {"JP"},
    "중남미": {
        "AR","BO","BR","CL","CO","CR","CU","DO","EC","SV","GT","HT","HN","JM","MX",
        "NI","PA","PY","PE","TT","UY","VE","BZ","GY","SR","BS","BB","GD","LC","VC",
        "AG","DM","KN"
    },
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

# ─────────────────────────────────────────────────────────────────────────────
# 공통 도우미
# ─────────────────────────────────────────────────────────────────────────────
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

def period_label(yyyymm):
    return f"{yyyymm[:4]}-{yyyymm[4:6]}"

def previous_year_period(yyyymm):
    return f"{int(yyyymm[:4])-1:04d}{yyyymm[4:6]}"

def confirmed_period():
    """
    관세청이 매월 15일경 전월 자료의 정정·취하를 반영해 현행화한다는 점을 반영.
    16일 이후: 전월 / 1~15일: 전전월을 기본 확정월로 사용.
    """
    now = pd.Period(date.today().strftime("%Y-%m"), freq="M")
    end = now - (1 if date.today().day >= 16 else 2)
    return end.strftime("%Y%m")

def twelve_month_window(end_yyyymm):
    end = pd.Period(end_yyyymm, freq="M")
    start = end - 11
    return start.strftime("%Y%m"), end.strftime("%Y%m")

@st.cache_data(ttl=21600, show_spinner=False)
def api_get(url, key, params_tuple):
    params = dict(params_tuple)
    params["serviceKey"] = key
    rr = requests.get(url, params=params, timeout=45)
    rr.raise_for_status()
    root = ET.fromstring(rr.content)

    code = root.findtext(".//resultCode")
    msg = root.findtext(".//resultMsg") or ""
    if code not in (None, "00"):
        raise RuntimeError(f"{code}: {msg}")

    return [{c.tag: c.text for c in item} for item in root.findall(".//item")]

def api_rows(url, key, **params):
    return api_get(url, key, tuple(sorted(params.items())))

# ─────────────────────────────────────────────────────────────────────────────
# 전체 무역
# ─────────────────────────────────────────────────────────────────────────────
@st.cache_data(ttl=21600, show_spinner=False)
def customs_total_12m(key, end_period):
    start, end = twelve_month_window(end_period)
    rows = api_rows(TOTAL_URL, key, strtYymm=start, endYymm=end)
    out = []
    for x in rows:
        p = norm_period(x.get("year"))
        if not p:
            continue
        out.append({
            "period": p,
            "export": to_num(x.get("expDlr")),
            "import": to_num(x.get("impDlr")),
            "balance": to_num(x.get("balPayments")),
        })
    d = pd.DataFrame(out)
    if d.empty:
        return d
    return d.groupby("period", as_index=False)[["export","import","balance"]].sum().sort_values("period")

@st.cache_data(ttl=21600, show_spinner=False)
def customs_total_one(key, yyyymm):
    rows = api_rows(TOTAL_URL, key, strtYymm=yyyymm, endYymm=yyyymm)
    exp = imp = bal = 0.0
    for x in rows:
        if not norm_period(x.get("year")):
            continue
        exp += to_num(x.get("expDlr"))
        imp += to_num(x.get("impDlr"))
        bal += to_num(x.get("balPayments"))
    return {"export":exp, "import":imp, "balance":bal}

# ─────────────────────────────────────────────────────────────────────────────
# 국가 → 9대 지역
# ─────────────────────────────────────────────────────────────────────────────
@st.cache_data(ttl=21600, show_spinner=False)
def customs_nations_one(key, yyyymm):
    rows = api_rows(NATION_URL, key, strtYymm=yyyymm, endYymm=yyyymm)
    out = []
    for x in rows:
        p = norm_period(x.get("year"))
        if not p:
            continue
        code = (x.get("statCd") or x.get("cntyCd") or x.get("countryCd") or "").strip().upper()
        name = (x.get("statKor") or x.get("countryNm") or x.get("cntyNm") or "").strip()
        if not code or code == "-":
            continue
        out.append({
            "period": p,
            "country_code": code,
            "country_name": name,
            "export": to_num(x.get("expDlr")),
            "import": to_num(x.get("impDlr")),
        })
    return pd.DataFrame(out)

def aggregate_regions(current_df, previous_df):
    rows = []
    for region in REGION_ORDER:
        codes = REGION_CODES[region]
        cur = current_df[current_df["country_code"].isin(codes)]["export"].sum() if not current_df.empty else 0.0
        prv = previous_df[previous_df["country_code"].isin(codes)]["export"].sum() if not previous_df.empty else 0.0
        yoy = ((cur / prv) - 1) * 100 if prv else 0.0
        rows.append({"region": region, "export_usd_100m": cur/1e8, "yoy": yoy})
    return pd.DataFrame(rows)

# ─────────────────────────────────────────────────────────────────────────────
# 공식 HSK-MTI 연계표 읽기
# ─────────────────────────────────────────────────────────────────────────────
def _clean_cell(v):
    if pd.isna(v):
        return ""
    return str(v).strip()

def _norm_hsk(v):
    s = re.sub(r"\D", "", _clean_cell(v).split(".0")[0])
    if not s:
        return None
    if len(s) <= 10:
        return s.zfill(10)
    return s[:10]

def _norm_mti(v):
    raw = _clean_cell(v)
    if not raw:
        return None
    # Excel 숫자형으로 들어오면 .0 제거. MTI 최하위는 6단위이므로 숫자는 6자리 복원.
    if re.fullmatch(r"\d+(?:\.0+)?", raw):
        s = raw.split(".")[0]
        return s.zfill(6) if len(s) < 6 else s[:6]
    s = re.sub(r"[^0-9]", "", raw)
    if not s:
        return None
    return s.zfill(6) if len(s) < 6 else s[:6]

@st.cache_data(ttl=86400, show_spinner=False)
def load_mti_mapping():
    path = DATA / "mti_hsk_mapping.xlsx"
    if not path.exists():
        return None, "공식 연계표 파일이 없음"

    best = None
    best_score = -1
    xls = pd.ExcelFile(path)

    for sheet in xls.sheet_names:
        raw = pd.read_excel(path, sheet_name=sheet, header=None, dtype=str)
        if raw.empty:
            continue

        # 먼저 헤더 후보를 찾고, 실패하면 모든 열 조합을 점수화한다.
        header_candidates = []
        for r in range(min(30, len(raw))):
            vals = [_clean_cell(v).upper() for v in raw.iloc[r].tolist()]
            hs_cols = [i for i,v in enumerate(vals) if ("HSK" in v or re.search(r"(^|[^A-Z])HS([^A-Z]|$)", v)) and "품명" not in v]
            mti_cols = [i for i,v in enumerate(vals) if "MTI" in v and "품명" not in v]
            for hc in hs_cols:
                for mc in mti_cols:
                    if hc != mc:
                        header_candidates.append((r,hc,mc))

        if not header_candidates:
            # 보수적 fallback: 각 열을 HSK/MTI 후보로 점수화
            for hc in range(raw.shape[1]):
                for mc in range(raw.shape[1]):
                    if hc == mc:
                        continue
                    header_candidates.append((-1,hc,mc))

        for header_row, hc, mc in header_candidates[:300]:
            d = raw.iloc[header_row+1 if header_row >= 0 else 0:, [hc,mc]].copy()
            d.columns = ["hsk_raw","mti_raw"]
            d["hsk"] = d["hsk_raw"].map(_norm_hsk)
            d["mti"] = d["mti_raw"].map(_norm_mti)
            valid = d["hsk"].str.fullmatch(r"\d{10}", na=False) & d["mti"].str.fullmatch(r"\d{6}", na=False)
            score = int(valid.sum())
            if score > best_score:
                best_score = score
                best = d.loc[valid, ["hsk","mti"]].drop_duplicates("hsk")

    if best is None or len(best) < 1000:
        return None, f"연계표 구조 자동인식 실패(유효 매핑 {0 if best is None else len(best):,}개)"

    return best, f"HSK-MTI {len(best):,}개 코드 인식"

def classify_mti(mti_code):
    s = str(mti_code or "")
    # 긴 코드부터 비교하면 2273 같은 세부코드가 안전하게 우선된다.
    candidates = sorted(
        [(industry, prefix) for industry, prefs in MTI_MAJOR.items() for prefix in prefs],
        key=lambda x: len(x[1]),
        reverse=True,
    )
    for industry, prefix in candidates:
        if s.startswith(prefix):
            return industry
    return None

@st.cache_data(ttl=21600, show_spinner=False)
def customs_items_one(key, yyyymm):
    # hsSgn을 생략하면 해당 월의 HSK 전체 품목을 한 번에 받아온다.
    rows = api_rows(ITEM_URL, key, strtYymm=yyyymm, endYymm=yyyymm)
    out = []
    for x in rows:
        p = norm_period(x.get("year"))
        if not p:
            continue
        hsk = _norm_hsk(x.get("hsCode") or x.get("hsCd"))
        if not hsk:
            continue
        out.append({
            "period": p,
            "hsk": hsk,
            "export": to_num(x.get("expDlr")),
            "import": to_num(x.get("impDlr")),
        })
    d = pd.DataFrame(out)
    if d.empty:
        return d
    return d.groupby(["period","hsk"], as_index=False)[["export","import"]].sum()

def aggregate_industries(cur_items, prev_items, mapping):
    mp = mapping.copy()
    mp["industry"] = mp["mti"].map(classify_mti)
    mp = mp.dropna(subset=["industry"])

    def agg(items):
        if items.empty:
            return pd.Series(dtype=float)
        x = items.merge(mp[["hsk","industry"]], on="hsk", how="inner")
        return x.groupby("industry")["export"].sum()

    cur = agg(cur_items)
    prv = agg(prev_items)
    rows = []
    for name in INDUSTRY_ORDER:
        c = float(cur.get(name, 0.0))
        p = float(prv.get(name, 0.0))
        rows.append({
            "industry": name,
            "export_usd_100m": c/1e8,
            "yoy": ((c/p)-1)*100 if p else 0.0,
        })
    return pd.DataFrame(rows)

# ─────────────────────────────────────────────────────────────────────────────
# HS 상세조회
# ─────────────────────────────────────────────────────────────────────────────
@st.cache_data(ttl=21600, show_spinner=False)
def customs_item_12m(key, hs, end_period):
    start, end = twelve_month_window(end_period)
    rows = api_rows(ITEM_URL, key, strtYymm=start, endYymm=end, hsSgn=hs)
    out = []
    for x in rows:
        p = norm_period(x.get("year"))
        if not p:
            continue
        out.append({
            "period": p,
            "export": to_num(x.get("expDlr")),
            "import": to_num(x.get("impDlr")),
        })
    d = pd.DataFrame(out)
    if d.empty:
        return d
    return d.groupby("period", as_index=False)[["export","import"]].sum().sort_values("period")

# ─────────────────────────────────────────────────────────────────────────────
# 시각화
# ─────────────────────────────────────────────────────────────────────────────
def render_trade_table(df, name_col):
    rows = ['<div class="trade-table">',
            '<div class="trade-row header"><div class="trade-cell">구분</div><div class="trade-cell num">수출액(억 달러)</div><div class="trade-cell num">전년동월 대비</div></div>']
    for _, rr in df.iterrows():
        yoy = float(rr["yoy"])
        cls = "positive" if yoy >= 0 else "negative"
        rows.append(
            f'<div class="trade-row">'
            f'<div class="trade-cell name">{rr[name_col]}</div>'
            f'<div class="trade-cell num">{float(rr["export_usd_100m"]):,.1f}</div>'
            f'<div class="trade-cell num {cls}">{yoy:+.1f}%</div>'
            f'</div>'
        )
    rows.append("</div>")
    st.markdown("".join(rows), unsafe_allow_html=True)

def render_horizontal_bar(df, category_col, value_col="export_usd_100m", height_per_row=31):
    d = df[[category_col,value_col]].copy()
    d[value_col] = pd.to_numeric(d[value_col], errors="coerce").fillna(0)
    max_v = max(float(d[value_col].max()), 1.0)
    chart = (
        alt.Chart(d)
        .mark_bar(cornerRadiusEnd=4, color="#2563EB")
        .encode(
            y=alt.Y(f"{category_col}:N",
                    sort=alt.SortField(field=value_col, order="descending"),
                    title=None, axis=alt.Axis(labelLimit=120, labelFontSize=12)),
            x=alt.X(f"{value_col}:Q", title="수출액(억 달러)",
                    scale=alt.Scale(domain=[0,max_v*1.08], nice=False, zero=True),
                    axis=alt.Axis(format=",.0f", tickCount=5)),
            tooltip=[
                alt.Tooltip(f"{category_col}:N", title="구분"),
                alt.Tooltip(f"{value_col}:Q", title="수출액(억 달러)", format=",.1f"),
            ],
        )
        .properties(height=max(250,int(len(d)*height_per_row)))
        .configure_view(strokeWidth=0, fill="#ffffff")
        .configure(background="#ffffff")
        .configure_axis(labelColor="#344054", titleColor="#344054",
                        gridColor="#e5e7eb", domainColor="#98a2b3", tickColor="#98a2b3")
    )
    st.altair_chart(chart, use_container_width=True)

def render_time_lines(df, period_col, series_cols, height=320):
    d = df[[period_col]+series_cols].copy()
    for c in series_cols:
        d[c] = pd.to_numeric(d[c], errors="coerce")
    long = d.melt(id_vars=[period_col], value_vars=series_cols,
                  var_name="구분", value_name="값").dropna()
    if long.empty:
        return

    y_min, y_max = float(long["값"].min()), float(long["값"].max())
    if y_max <= y_min:
        low, high = max(0,y_min*.9), y_max*1.1+1
    else:
        pad = (y_max-y_min)*.12
        low, high = max(0,y_min-pad), y_max+pad

    palette = ["#2563EB","#F59E0B","#059669","#7C3AED"][:len(series_cols)]
    dashes = [[1,0],[7,4],[2,3],[10,3,2,3]][:len(series_cols)]
    base = alt.Chart(long).encode(
        x=alt.X(f"{period_col}:N", title=None, axis=alt.Axis(labelAngle=-45,labelFontSize=11)),
        y=alt.Y("값:Q", title="억 달러", scale=alt.Scale(domain=[low,high],nice=False)),
        color=alt.Color("구분:N", title=None,
                        scale=alt.Scale(domain=series_cols, range=palette),
                        legend=alt.Legend(orient="bottom",direction="horizontal",
                                          labelFontSize=12,symbolStrokeWidth=4)),
        strokeDash=alt.StrokeDash("구분:N", title=None,
                                  scale=alt.Scale(domain=series_cols, range=dashes), legend=None),
        tooltip=[
            alt.Tooltip(f"{period_col}:N", title="기간"),
            alt.Tooltip("구분:N", title="구분"),
            alt.Tooltip("값:Q", title="억 달러", format=",.1f"),
        ]
    )
    chart = (
        (base.mark_line(strokeWidth=3)+base.mark_point(filled=True,size=58))
        .properties(height=height)
        .configure_view(strokeWidth=0, fill="#ffffff")
        .configure(background="#ffffff")
        .configure_axis(labelColor="#344054", titleColor="#344054",
                        gridColor="#e5e7eb", domainColor="#98a2b3", tickColor="#98a2b3")
        .configure_legend(labelColor="#344054", titleColor="#344054")
    )
    st.altair_chart(chart, use_container_width=True)

# ─────────────────────────────────────────────────────────────────────────────
# CSS
# ─────────────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
html,body,[data-testid="stAppViewContainer"],[data-testid="stApp"]{
  background:#f4f7fb!important;color:#18202a!important;color-scheme:light!important
}
[data-testid="stHeader"]{background:rgba(244,247,251,.96)!important}
.block-container{max-width:1200px;padding-top:1.1rem;padding-bottom:3rem}
.hero{background:#0f2747;color:#fff;border-radius:18px;padding:22px 24px;margin-bottom:14px}
.hero-title{font-size:30px;font-weight:850}.hero-sub{color:#dbe7f5;font-size:14px;margin-top:4px}
.info-card{background:#fff;border:1px solid #dfe5ee;border-radius:16px;padding:16px;min-height:96px}
.info-card .lab{font-size:12px;color:#667085;font-weight:700}
.info-card .val{font-size:22px;font-weight:850;color:#18202a;margin:7px 0}
.source{background:#f8fafc;border:1px solid #e2e8f0;color:#475467;border-radius:12px;padding:11px 13px;font-size:12px;line-height:1.5}
.summary-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin:8px 0 4px}
.summary-box{background:#fff;border:1px solid #dfe5ee;border-radius:13px;padding:14px}
.slabel{font-size:12px;color:#667085;font-weight:700}.svalue{font-size:24px;font-weight:850;margin-top:6px;color:#18202a}.snote{font-size:12px;color:#475467;margin-top:4px}
.trade-table{width:100%;border:1px solid #dfe5ee;border-radius:14px;overflow:hidden;background:#fff}
.trade-row{display:grid;grid-template-columns:minmax(120px,1.2fr) 1fr 1fr;align-items:center;border-bottom:1px solid #e5eaf1;background:#fff}
.trade-row:last-child{border-bottom:0}.trade-row.header{background:#eaf0f7;font-size:12px;font-weight:800;color:#475467}
.trade-cell{padding:11px 13px;font-size:14px}.trade-cell.name{font-weight:800}.trade-cell.num{text-align:right;font-variant-numeric:tabular-nums}
.positive{color:#067647;font-weight:800}.negative{color:#b42318;font-weight:800}
[data-baseweb="select"]>div,[data-baseweb="input"]>div,input,textarea{background:#fff!important;color:#18202a!important}
.vega-embed,.vega-embed>div,iframe{background:#fff!important}
@media(max-width:760px){
 .summary-grid{grid-template-columns:1fr 1fr}
 .trade-row{grid-template-columns:minmax(100px,1.2fr) .9fr .9fr}
 .trade-cell{padding:10px 8px;font-size:12px}.trade-row.header .trade-cell{font-size:11px}
}
@media(max-width:430px){.summary-box .svalue{font-size:20px}}
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# 앱 시작
# ─────────────────────────────────────────────────────────────────────────────
st.markdown("""
<div class="hero">
 <div class="hero-title">🇰🇷 한국무역 한눈에 보기</div>
 <div class="hero-sub">관세청 확정 통계 · 2026 MTI 20대 품목 · 9대 주요 수출지역</div>
</div>
""", unsafe_allow_html=True)

key = get_key()
end_period = confirmed_period()
prev_period = previous_year_period(end_period)

tab_all, tab_ind, tab_reg, tab_mti, tab_customs, tab_class = st.tabs([
    "🇰🇷 전체 무역","🏭 20대 품목","🌏 9대 지역","🧩 MTI 분류","🔎 관세청 상세조회","🎓 강의실"
])

if not key:
    st.warning("Streamlit Secrets에 DATA_GO_KR_SERVICE_KEY가 필요합니다.")

# 전체 무역 데이터는 한 번만 읽어 여러 탭에서 공유
total12 = pd.DataFrame()
latest_total = prior_total = None
region_df = pd.DataFrame()
mapping, mapping_status = load_mti_mapping()
industry_df = pd.DataFrame()

if key:
    try:
        total12 = customs_total_12m(key, end_period)
        latest_total = customs_total_one(key, end_period)
        prior_total = customs_total_one(key, prev_period)
    except Exception as e:
        st.error(f"관세청 총괄 API 조회 실패: {e}")

    try:
        cur_nations = customs_nations_one(key, end_period)
        prev_nations = customs_nations_one(key, prev_period)
        region_df = aggregate_regions(cur_nations, prev_nations)
    except Exception as e:
        st.error(f"관세청 국가별 API 조회 실패: {e}")

    if mapping is not None:
        try:
            with st.spinner("20대 품목을 관세청 HSK 통계와 MTI 연계표로 계산 중입니다…"):
                cur_items = customs_items_one(key, end_period)
                prev_items = customs_items_one(key, prev_period)
                industry_df = aggregate_industries(cur_items, prev_items, mapping)
        except Exception as e:
            st.error(f"20대 품목 계산 실패: {e}")

with tab_all:
    st.subheader(f"대한민국 무역 Dashboard · {period_label(end_period)}")
    st.caption("관세청 확정·현행화 통계 기준 · 매월 16일 이후 전월, 그 이전에는 전전월을 기본 표시")

    if latest_total and prior_total:
        exp = latest_total["export"]/1e8
        imp = latest_total["import"]/1e8
        bal = latest_total["balance"]/1e8
        exp_yoy = ((latest_total["export"]/prior_total["export"])-1)*100 if prior_total["export"] else 0
        imp_yoy = ((latest_total["import"]/prior_total["import"])-1)*100 if prior_total["import"] else 0

        c1,c2,c3 = st.columns(3)
        vals = [
            ("수출",f"{exp:,.1f}억 달러",f"전년동월 대비 {exp_yoy:+.1f}%"),
            ("수입",f"{imp:,.1f}억 달러",f"전년동월 대비 {imp_yoy:+.1f}%"),
            ("무역수지",f"{bal:+,.1f}억 달러","관세청 확정·현행화"),
        ]
        for col,(lab,val,sub) in zip([c1,c2,c3],vals):
            with col:
                st.markdown(f'<div class="info-card"><div class="lab">{lab}</div><div class="val">{val}</div><div class="lab">{sub}</div></div>', unsafe_allow_html=True)

        if not industry_df.empty and not region_df.empty:
            inc_count = int((industry_df["yoy"]>0).sum())
            top_export = industry_df.sort_values("export_usd_100m",ascending=False).iloc[0]
            top_growth = industry_df.sort_values("yoy",ascending=False).iloc[0]
            reg_down = region_df.sort_values("yoy").iloc[0]

            st.markdown("### 이번 달 주요 특징")
            st.markdown(
                f'<div class="summary-grid">'
                f'<div class="summary-box"><div class="slabel">20대 품목 증가</div><div class="svalue">{inc_count}개 / 20개</div><div class="snote">전년동월 대비</div></div>'
                f'<div class="summary-box"><div class="slabel">최대 수출 품목</div><div class="svalue">{top_export["industry"]}</div><div class="snote">수출액 {top_export["export_usd_100m"]:.1f}억 달러</div></div>'
                f'<div class="summary-box"><div class="slabel">증가율 1위</div><div class="svalue">{top_growth["industry"]}</div><div class="snote">전년동월 대비 {top_growth["yoy"]:+.1f}%</div></div>'
                f'<div class="summary-box"><div class="slabel">지역 증감률 최저</div><div class="svalue">{reg_down["region"]}</div><div class="snote">전년동월 대비 {reg_down["yoy"]:+.1f}%</div></div>'
                f'</div>',
                unsafe_allow_html=True
            )

        if not total12.empty:
            st.markdown("### 관세청 최근 12개월 통관 시계열")
            ch = total12.copy()
            ch["수출"] = ch["export"]/1e8
            ch["수입"] = ch["import"]/1e8
            render_time_lines(ch[["period","수출","수입"]], "period", ["수출","수입"], height=320)

    if mapping is None:
        st.info("20대 품목 자동계산을 위해 공식 `2026 MTI-HSK 코드표`를 data/mti_hsk_mapping.xlsx로 한 번만 추가하면 됩니다.")

with tab_ind:
    st.subheader("2026 MTI 기준 20대 주력 수출품목")
    st.caption(f"관세청 HSK 통관통계 + 공식 HSK-MTI 연계표 재집계 · {period_label(end_period)}")

    if mapping is None:
        st.warning("공식 HSK-MTI 연계표가 아직 저장되어 있지 않아 20대 품목 계산을 시작할 수 없습니다.")
        st.markdown("""
**한 번만 필요한 설정**
1. 한국무역협회에서 `2026 MTI-HSK 코드표_vFF_260507.xlsx` 다운로드  
2. 파일 이름을 `mti_hsk_mapping.xlsx`로 변경  
3. GitHub 저장소의 `data/` 폴더에 업로드  

그 이후부터는 월별 숫자를 손댈 필요가 없습니다.
""")
    elif industry_df.empty:
        st.info("20대 품목 자료를 불러오지 못했습니다.")
    else:
        st.success(mapping_status)
        left,right = st.columns([1.25,1])
        with left:
            render_trade_table(industry_df.sort_values("export_usd_100m",ascending=False), "industry")
        with right:
            render_horizontal_bar(industry_df.sort_values("export_usd_100m",ascending=False), "industry", height_per_row=28)

        selected = st.selectbox("품목 상세", INDUSTRY_ORDER)
        rr = industry_df[industry_df["industry"]==selected].iloc[0]
        c1,c2 = st.columns(2)
        c1.metric("수출액", f"{rr['export_usd_100m']:.1f}억 달러")
        c2.metric("전년동월 대비", f"{rr['yoy']:+.1f}%")
        st.caption("12개월 품목별 시계열은 다음 버전에서 API 부하를 최소화하는 방식으로 추가할 수 있습니다.")

with tab_reg:
    st.subheader("9대 주요 수출지역")
    st.caption(f"관세청 국가별 통계를 국가코드 묶음으로 자동 합산 · {period_label(end_period)}")
    if region_df.empty:
        st.info("지역 자료를 불러오지 못했습니다.")
    else:
        c1,c2 = st.columns([1,1])
        with c1:
            render_trade_table(region_df, "region")
        with c2:
            render_horizontal_bar(region_df.sort_values("export_usd_100m",ascending=False), "region", height_per_row=34)

        selected_region = st.selectbox("지역 선택", REGION_ORDER, key="region_select")
        rr = region_df[region_df["region"]==selected_region].iloc[0]
        cls = "positive" if rr["yoy"] >= 0 else "negative"
        st.markdown(
            f'<div class="summary-grid">'
            f'<div class="summary-box"><div class="slabel">대{selected_region} 수출</div><div class="svalue">{rr["export_usd_100m"]:.1f}억 달러</div><div class="snote">{period_label(end_period)}</div></div>'
            f'<div class="summary-box"><div class="slabel">증감률</div><div class="svalue {cls}">{rr["yoy"]:+.1f}%</div><div class="snote">전년동월 대비</div></div>'
            f'</div>',
            unsafe_allow_html=True
        )
        st.caption("※ 국가군 구성은 앱의 data/region_groups_reference.json에 공개되어 있어 필요 시 조정할 수 있습니다.")

with tab_mti:
    st.subheader("2026 MTI 분류")
    st.caption("산업통상부의 2026년 개편 기준. 20대 품목은 아래 MTI 상위코드로 자동 집계합니다.")
    codes = []
    for name in INDUSTRY_ORDER:
        codes.append({"품목":name, "MTI 코드":", ".join(MTI_MAJOR[name])})
    st.dataframe(pd.DataFrame(codes), use_container_width=True, hide_index=True)

    st.markdown("### 산업군")
    for g, items in GROUPS.items():
        st.markdown(f"**{g}** · " + " / ".join(items))

    if mapping is not None:
        st.success(mapping_status)
    else:
        st.info("공식 HSK-MTI 연계표를 data/mti_hsk_mapping.xlsx로 추가하면 HSK 10단위가 위 20개 MTI 품목으로 자동 연결됩니다.")

with tab_customs:
    st.subheader("관세청 HS 상세조회")
    if not key:
        st.warning("Streamlit Secrets에 DATA_GO_KR_SERVICE_KEY를 설정하면 작동합니다.")
    else:
        hs = st.text_input("HS 코드", value="8542", help="예: 8542 전자집적회로, 8703 승용자동차")
        if st.button("조회"):
            try:
                d = customs_item_12m(key, hs.strip(), end_period)
                if d.empty:
                    st.info("조회 결과 없음")
                else:
                    ch = d.copy()
                    ch["수출"] = ch["export"]/1e8
                    ch["수입"] = ch["import"]/1e8
                    render_time_lines(ch[["period","수출","수입"]], "period", ["수출","수입"], height=340)
                    show = d.copy()
                    show["수출(억 달러)"] = show["export"]/1e8
                    show["수입(억 달러)"] = show["import"]/1e8
                    st.dataframe(show[["period","수출(억 달러)","수입(억 달러)"]], use_container_width=True, hide_index=True)
            except Exception as e:
                st.error(str(e))

with tab_class:
    st.subheader("강의실")
    st.markdown("""
### 오늘의 질문
**“산업부 월초 잠정치와 관세청 확정·현행화 통계가 왜 조금 다를까요?”**

- 이 앱의 기본 숫자는 관세청 통관통계를 사용합니다.
- 관세청은 매월 15일경 정정·취하 등을 반영해 전월 자료를 현행화합니다.
- 따라서 산업부가 월초 발표하는 잠정치보다 표시 시점은 늦지만 수업용 시계열은 더 안정적입니다.
- 20대 품목은 관세청 HSK 10단위 통계를 2026년 HSK-MTI 연계표로 다시 묶어 계산합니다.
- 9대 지역은 관세청 국가별 통계를 지역별 국가코드 묶음으로 합산합니다.

### v9.0의 운영 방식
월이 바뀌어도 CSV나 산업부 보도자료를 손으로 고칠 필요가 없습니다.  
관세청 API가 최신 확정월로 현행화되면 같은 URL에서 자동으로 새 달이 표시됩니다.
""")

st.write("")
st.markdown(
    f'<div class="source"><b>자료:</b> 관세청 수출입무역통계(Open API). '
    f'20대 품목 분류는 산업통상부 2026 MTI 개편 기준 및 한국무역협회 HSK-MTI 연계표를 사용합니다. '
    f'기본 표시월: {period_label(end_period)}.</div>',
    unsafe_allow_html=True
)
