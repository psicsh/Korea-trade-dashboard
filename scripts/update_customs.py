#!/usr/bin/env python3
from pathlib import Path
from urllib.parse import unquote
from datetime import datetime, timezone
import os, re, json, time
import xml.etree.ElementTree as ET

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
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
    "중국":{"CN"},"미국":{"US"},
    "아세안":{"BN","KH","ID","LA","MY","MM","PH","SG","TH","VN","TL"},
    "EU":{"AT","BE","BG","HR","CY","CZ","DK","EE","FI","FR","DE","GR","HU","IE","IT",
          "LV","LT","LU","MT","NL","PL","PT","RO","SK","SI","ES","SE"},
    "일본":{"JP"},
    "중남미":{"AR","BO","BR","CL","CO","CR","CU","DO","EC","SV","GT","HT","HN","JM","MX",
              "NI","PA","PY","PE","TT","UY","VE","BZ","GY","SR","BS","BB","GD","LC","VC",
              "AG","DM","KN"},
    "인도":{"IN"},
    "중동":{"BH","IR","IQ","IL","JO","KW","LB","OM","QA","SA","SY","AE","YE","TR"},
    "CIS":{"RU","KZ","UZ","KG","TJ","TM","AZ","AM","BY","MD","UA","GE"},
}
REGION_ORDER = ["중국","미국","아세안","EU","일본","중남미","인도","중동","CIS"]

def num(v):
    try:
        return float(str(v).replace(",","").strip())
    except Exception:
        return 0.0

def norm_period(v):
    s=str(v or "").replace(".","").replace("-","").strip()
    return s[:6] if len(s)>=6 and s[:6].isdigit() else None

def norm_hsk(v):
    s=re.sub(r"\D","",str(v or "").split(".0")[0])
    return s.zfill(10) if s else None

def api_get(url, key, params, attempts=4, timeout=120):
    last=None
    for n in range(attempts):
        try:
            q=dict(params)
            q["serviceKey"]=key
            rr=requests.get(url, params=q, timeout=timeout)
            rr.raise_for_status()
            root=ET.fromstring(rr.content)
            code=root.findtext(".//resultCode")
            msg=root.findtext(".//resultMsg") or ""
            if code not in (None,"00"):
                raise RuntimeError(f"{code}: {msg}")
            return [{c.tag:c.text for c in item} for item in root.findall(".//item")]
        except Exception as e:
            last=e
            if n < attempts-1:
                wait=3*(2**n)
                print(f"[WARN] API 재시도 {n+1}/{attempts}: {e} / {wait}s")
                time.sleep(wait)
    raise last

def previous_month():
    now=pd.Period(pd.Timestamp.utcnow().strftime("%Y-%m"), freq="M")
    return (now-1).strftime("%Y%m")

def prior_year(p):
    return f"{int(p[:4])-1:04d}{p[4:]}"

def period_range(start,end):
    s=pd.Period(start,freq="M"); e=pd.Period(end,freq="M")
    return [(s+n).strftime("%Y%m") for n in range((e-s).n+1)]

def fetch_total_one(key,p):
    rows=api_get(TOTAL_URL,key,{"strtYymm":p,"endYymm":p},timeout=60)
    exp=imp=bal=0.0
    for x in rows:
        if not norm_period(x.get("year")): continue
        exp+=num(x.get("expDlr")); imp+=num(x.get("impDlr")); bal+=num(x.get("balPayments"))
    return exp,imp,bal

def detect_latest_period(key):
    # 먼저 전월을 확인하고, 아직 현행화되지 않았으면 전전월로 fallback.
    p1=previous_month()
    p2=(pd.Period(p1,freq="M")-1).strftime("%Y%m")
    for p in (p1,p2):
        exp,imp,bal=fetch_total_one(key,p)
        if exp>1e9 and imp>1e9:
            return p
    raise RuntimeError("최근 확정월을 찾지 못했습니다.")

def update_monthly(key, latest):
    end=pd.Period(latest,freq="M")
    start=(end-23).strftime("%Y%m")
    rows=api_get(TOTAL_URL,key,{"strtYymm":start,"endYymm":latest},timeout=75)
    vals={}
    for x in rows:
        p=norm_period(x.get("year"))
        if not p: continue
        d=vals.setdefault(p,{"export":0.0,"import":0.0,"balance":0.0})
        d["export"]+=num(x.get("expDlr"))
        d["import"]+=num(x.get("impDlr"))
        d["balance"]+=num(x.get("balPayments"))

    out=[]
    for p in sorted(vals):
        d=vals[p]
        py=prior_year(p)
        prev=vals.get(py)
        ey=((d["export"]/prev["export"])-1)*100 if prev and prev["export"] else None
        iy=((d["import"]/prev["import"])-1)*100 if prev and prev["import"] else None
        out.append({
            "period":f"{p[:4]}-{p[4:]}",
            "export_usd_100m":d["export"]/1e8,
            "import_usd_100m":d["import"]/1e8,
            "balance_usd_100m":d["balance"]/1e8,
            "export_yoy":ey,
            "import_yoy":iy,
        })

    df=pd.DataFrame(out)
    if df.empty or len(df)<12:
        raise RuntimeError(f"총괄 월별 자료가 부족함: {len(df)}개")
    df.to_csv(DATA/"trade_monthly.csv",index=False,encoding="utf-8-sig")
    return len(df)

def fetch_nations(key,p):
    rows=api_get(NATION_URL,key,{"strtYymm":p,"endYymm":p},timeout=90)
    out=[]
    for x in rows:
        if not norm_period(x.get("year")): continue
        code=(x.get("statCd") or x.get("cntySgn") or x.get("cntyCd") or x.get("countryCd") or "").strip().upper()
        if len(code)!=2: continue
        out.append({"code":code,"export":num(x.get("expDlr"))})
    return pd.DataFrame(out)

def update_regions(key,latest):
    cur=fetch_nations(key,latest)
    prv=fetch_nations(key,prior_year(latest))
    if len(cur)<100:
        raise RuntimeError(f"국가별 현재월 행 수 부족: {len(cur)}")

    rows=[]
    for region in REGION_ORDER:
        codes=REGION_CODES[region]
        c=cur[cur["code"].isin(codes)]["export"].sum()
        p=prv[prv["code"].isin(codes)]["export"].sum()
        rows.append({
            "period":f"{latest[:4]}-{latest[4:]}",
            "region":region,
            "export_usd_100m":c/1e8,
            "yoy":((c/p)-1)*100 if p else 0.0,
        })
    df=pd.DataFrame(rows)
    if len(df)!=9 or df["export_usd_100m"].sum()<=0:
        raise RuntimeError("9대 지역 검증 실패")
    df.to_csv(DATA/"trade_region.csv",index=False,encoding="utf-8-sig")
    return len(df)

def load_mapping():
    p=DATA/"mti_hsk_mapping.xlsx"
    if not p.exists():
        raise RuntimeError("mti_hsk_mapping.xlsx 없음")
    d=pd.read_excel(p,sheet_name="HSK-MTI 연계표",dtype=str)
    req={"HSK","MTI","구분"}
    if not req.issubset(d.columns):
        raise RuntimeError("HSK-MTI 연계표의 HSK/MTI/구분 열을 찾지 못함")
    d=d[["HSK","MTI","구분"]].copy()
    d["hsk"]=d["HSK"].map(norm_hsk)
    d["industry"]=d["구분"].astype(str).str.strip()
    d=d[d["hsk"].str.fullmatch(r"\d{10}",na=False)]
    d=d[d["industry"].isin(INDUSTRY_ORDER)]
    d=d[["hsk","industry"]].drop_duplicates("hsk")
    if len(d)<1000:
        raise RuntimeError(f"유효 매핑 부족: {len(d)}")
    return d

def fetch_items(key,p):
    # 공식 API는 전체 HSK 조회가 무거우므로 GitHub Actions에서만 수행.
    rows=api_get(ITEM_URL,key,{"strtYymm":p,"endYymm":p},timeout=180)
    out=[]
    for x in rows:
        if not norm_period(x.get("year")): continue
        h=norm_hsk(x.get("hsCode") or x.get("hsSgn") or x.get("hsCd"))
        if not h: continue
        out.append({"hsk":h,"export":num(x.get("expDlr"))})
    d=pd.DataFrame(out)
    if d.empty:
        raise RuntimeError("품목별 API 결과 없음")
    return d.groupby("hsk",as_index=False)["export"].sum()

def update_industries(key,latest):
    mp=load_mapping()
    cur=fetch_items(key,latest)
    prv=fetch_items(key,prior_year(latest))

    def agg(d):
        x=d.merge(mp,on="hsk",how="inner")
        return x.groupby("industry")["export"].sum()

    c=agg(cur); p=agg(prv)
    rows=[]
    for name in INDUSTRY_ORDER:
        cv=float(c.get(name,0)); pv=float(p.get(name,0))
        rows.append({
            "period":f"{latest[:4]}-{latest[4:]}",
            "industry":name,
            "export_usd_100m":cv/1e8,
            "yoy":((cv/pv)-1)*100 if pv else 0.0,
        })

    df=pd.DataFrame(rows)
    nonzero=int((df["export_usd_100m"]>0).sum())
    if len(df)!=20 or nonzero<18:
        raise RuntimeError(f"20대 품목 검증 실패: nonzero={nonzero}/20")
    df.to_csv(DATA/"trade_industry.csv",index=False,encoding="utf-8-sig")
    return len(df)

def main():
    raw=os.environ.get("DATA_GO_KR_SERVICE_KEY","").strip()
    if not raw:
        raise SystemExit("GitHub Actions secret DATA_GO_KR_SERVICE_KEY가 없습니다.")
    key=unquote(raw)

    status_path=DATA/"customs_update_status.json"
    try:
        status=json.loads(status_path.read_text(encoding="utf-8"))
    except Exception:
        status={}

    latest=detect_latest_period(key)
    print("[INFO] 최신 확정월:",latest)

    components={}
    errors={}

    for name,fn in [
        ("monthly",update_monthly),
        ("region",update_regions),
        ("industry",update_industries),
    ]:
        try:
            n=fn(key,latest)
            components[name]=f"ok:{n}"
            print(f"[OK] {name}: {n}")
        except Exception as e:
            components[name]="failed"
            errors[name]=f"{type(e).__name__}: {e}"
            print(f"[WARN] {name} 업데이트 실패 — 기존 정상 파일 유지: {errors[name]}")

    new_status={
        "source":"customs",
        "period":f"{latest[:4]}-{latest[4:]}",
        "updated_at":datetime.now(timezone.utc).isoformat(),
        "components":components,
        "errors":errors,
    }
    status_path.write_text(json.dumps(new_status,ensure_ascii=False,indent=2),encoding="utf-8")

    # 한 구성요소가 실패해도 workflow는 성공 처리.
    # 기존 정상 CSV를 보존해 학생 화면이 깨지는 것을 방지한다.
    print("[DONE]",json.dumps(new_status,ensure_ascii=False))

if __name__=="__main__":
    main()
