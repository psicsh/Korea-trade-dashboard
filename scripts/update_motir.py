#!/usr/bin/env python3
"""
산업통상부 월간 '수출입 동향' 자동 업데이트.

동작:
1) 산업통상부 보도자료 목록 최근 페이지에서 최신 'YYYY년 M월 ... 수출입 동향' 검색\n   - javascript:article.view('글번호') 링크를 실제 상세 URL로 자동 변환
2) 상세 HTML + 첨부 PDF 텍스트를 결합
3) 총괄, 20대 주력품목, 9대 주요지역 숫자 추출
4) 20/20 + 9/9 검증을 통과할 때만 CSV 갱신
5) 기존 기간이면 정정치로 덮어쓰고, 새 기간이면 추가

PDF가 필요한 이유:
보도자료 본문에는 대표 품목만 서술되고, 나머지 20대 품목은 참고표에만 있는 달이 있습니다.
PDF는 OCR이 아니라 텍스트 레이어를 pypdf로 읽습니다.
"""
from pathlib import Path
from urllib.parse import urljoin
from io import BytesIO
import argparse, datetime as dt, json, re, sys
import requests
import pandas as pd
from bs4 import BeautifulSoup
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
LIST_URL = "https://www.motir.go.kr/kor/article/ATCL3f49a5a8c"

INDUSTRIES = [
    "반도체","자동차","자동차부품","석유제품","석유화학","일반기계","철강","선박",
    "무선통신기기","디스플레이","섬유","가전","컴퓨터","바이오헬스","이차전지",
    "전기기기","농수산식품","화장품","생활용품","비철금속"
]
REGIONS = ["중국","아세안","미국","EU","일본","중남미","인도","중동","CIS"]

ALIASES = {
    "무선통신기기": ["무선통신기기","무선 통신기기"],
    "철강": ["철강","철강제품"],
    "가전": ["가전","가전제품"],
    "컴퓨터": ["컴퓨터","컴퓨터(eSSD)","컴퓨터·주변기기"],
}
REGION_ALIASES = {
    "중국":["대중국","대(對)중국","중국"],
    "아세안":["대아세안","아세안"],
    "미국":["대미국","미국"],
    "EU":["대EU","EU","유럽연합"],
    "일본":["대일본","일본"],
    "중남미":["대중남미","중남미"],
    "인도":["대인도","인도"],
    "중동":["대중동","중동"],
    "CIS":["대CIS","CIS"],
}

session = requests.Session()
session.headers.update({
    "User-Agent":"Mozilla/5.0 (compatible; KoreaTradeLectureBot/1.0; educational use)"
})

def clean_text(s):
    s = s.replace("\u00a0"," ").replace("△","-").replace("▲","+").replace("▼","-")
    s = s.replace("−","-").replace("–","-")
    s = re.sub(r"[ \t]+"," ",s)
    return s

def period_from_title(title):
    # 2026년 6월 및 상반기 수출입 동향 / 2026년 7월 수출입 동향
    m = re.search(r"(20\d{2})년\s*(\d{1,2})월(?:\s*및\s*상반기)?\s*수출입\s*동향", title)
    if not m:
        return None
    return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}"

def normalize_article_url(anchor, base_url):
    """
    산업통상부 목록은 상세글 링크를 일반 URL이 아니라
    javascript:article.view('172077'); 형식으로 제공하는 경우가 있다.
    이 경우 글 번호를 추출해 실제 상세 URL로 변환한다.
    """
    raw = (anchor.get("href") or "").strip()
    onclick = (anchor.get("onclick") or "").strip()
    probe = raw + " " + onclick

    # javascript:article.view('172077'); 또는 onclick="article.view('172077')"
    m = re.search(r"article\.view\(\s*['\"]?(\d+)['\"]?\s*\)", probe, re.I)
    if m:
        article_id = m.group(1)
        return f"{LIST_URL}/{article_id}/view"

    # 이미 정상적인 상세 URL인 경우
    if raw and not raw.lower().startswith("javascript:") and raw != "#":
        return urljoin(base_url, raw)

    return None


def discover_latest():
    found = []
    # 한 달치 보도자료가 뒤로 밀릴 수 있어 최근 10페이지 탐색
    for page in range(1, 11):
        r = session.get(LIST_URL, params={"pageIndex":page}, timeout=30)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")

        # href뿐 아니라 onclick에 article.view가 들어간 경우도 잡기 위해 모든 a 태그 확인
        for a in soup.find_all("a"):
            title = " ".join(a.get_text(" ", strip=True).split())
            period = period_from_title(title)
            if not period:
                continue

            # ICT/자동차산업 등 별도 동향은 제외
            if "정보통신" in title or "ICT" in title or "자동차산업" in title:
                continue

            href = normalize_article_url(a, r.url)
            if not href:
                print(f"[WARN] 상세 URL 해석 실패: {title} / href={a.get('href')}", file=sys.stderr)
                continue

            found.append((period, title, href))

    if not found:
        raise RuntimeError("산업통상부 목록에서 월간 '수출입 동향'을 찾지 못했습니다.")

    # 같은 글이 중복 수집되면 URL 기준 중복 제거
    uniq = {}
    for p, t, u in found:
        uniq[u] = (p, t, u)

    latest = max(uniq.values(), key=lambda x: x[0])

    # javascript: URL이 남아 있으면 여기서 즉시 중단하여 원인을 명확히 표시
    if latest[2].lower().startswith("javascript:"):
        raise RuntimeError(f"상세 URL 변환 실패: {latest[2]}")

    return latest

def extract_pdf_text(soup, detail_url):
    texts = []
    candidates = []
    for a in soup.find_all("a", href=True):
        label = " ".join(a.get_text(" ", strip=True).split())
        href = urljoin(detail_url, a["href"])
        probe = (label + " " + href).lower()
        if ".pdf" in probe or "pdf" in label.lower():
            candidates.append(href)
    # 같은 링크 중복 제거
    for href in dict.fromkeys(candidates):
        try:
            rr = session.get(href, timeout=45)
            rr.raise_for_status()
            content = rr.content
            # HTML 미리보기 링크면 건너뜀
            if not content.startswith(b"%PDF"):
                continue
            reader = PdfReader(BytesIO(content))
            txt = "\n".join((p.extract_text() or "") for p in reader.pages)
            if len(txt) > 1000:
                texts.append(txt)
        except Exception as e:
            print(f"[WARN] PDF 추출 실패: {href} / {e}", file=sys.stderr)
    return "\n".join(texts)

def get_detail(url):
    r = session.get(url, timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    html_text = soup.get_text("\n", strip=True)
    pdf_text = extract_pdf_text(soup, r.url)
    return clean_text(html_text + "\n" + pdf_text), soup

def num(s):
    return float(str(s).replace(",","").replace("+","").strip())

def signed_num(s):
    s = str(s).strip().replace("△","-").replace("▲","+").replace("▼","-")
    s = s.replace("−","-")
    return float(s.replace(",","").replace("+",""))

def metric_patterns(label):
    labels = ALIASES.get(label, [label])
    alts = "|".join(re.escape(x) for x in sorted(labels,key=len,reverse=True))
    # 자동차가 자동차부품을 먹지 않도록
    if label == "자동차":
        alts = r"자동차(?!부품)"
    return [
        # 서술형: 반도체 수출(410.1억 달러, +178.8%)
        re.compile(rf"(?:{alts})(?:\s*수출)?\s*[\(（]\s*([0-9,.]+)\s*억\s*달러\s*[,，]\s*([+\-]?\s*[0-9,.]+)\s*%", re.S),
        # 표 추출형: 반도체 410.1 ... 178.8
        re.compile(rf"(?:{alts})\s+([0-9,.]+)\s*(?:억\s*달러|억불|억\$)?\s+(?:[^\n]{{0,55}}?\s)?([+\-]?\s*[0-9,.]+)\s*%", re.S),
    ]

def find_metric(text, label):
    for pat in metric_patterns(label):
        m = pat.search(text)
        if m:
            return num(m.group(1)), signed_num(m.group(2))
    return None

def find_region(text, label):
    aliases = REGION_ALIASES[label]
    alts = "|".join(re.escape(x) for x in sorted(aliases,key=len,reverse=True))
    pats = [
        re.compile(rf"(?:{alts})\s*수출\s*[\(（]\s*([0-9,.]+)\s*억\s*달러\s*[,，]\s*([+\-]?\s*[0-9,.]+)\s*%", re.S),
        re.compile(rf"(?:{alts})\s+([0-9,.]+)\s*(?:억\s*달러|억불|억\$)?\s+(?:[^\n]{{0,55}}?\s)?([+\-]?\s*[0-9,.]+)\s*%", re.S),
    ]
    for pat in pats:
        m=pat.search(text)
        if m:
            return num(m.group(1)), signed_num(m.group(2))
    return None

def parse_overall(text):
    # 총괄 문단 우선
    chunk = text
    idx = text.find("총괄")
    if idx >= 0:
        chunk = text[idx:idx+3500]
    exp = re.search(r"수출은\s*(?:전년\s*동월\s*대비\s*)?([0-9,.]+)\s*%\s*증가한\s*([0-9,.]+)\s*억\s*달러", chunk)
    imp = re.search(r"수입은\s*([0-9,.]+)\s*%\s*증가한\s*([0-9,.]+)\s*억\s*달러", chunk)
    bal = re.search(r"무역수지(?:는)?\s*([0-9,.]+)\s*억\s*달러\s*흑자", chunk)
    daily = re.search(r"일평균\s*수출(?:은|액은)?[^0-9]{0,60}([0-9,.]+)\s*억\s*달러", text)
    if not (exp and imp and bal):
        # * 7월 수출 988.9억 달러(+62.8%), 수입 ...
        alt = re.search(
            r"수출\s*([0-9,.]+)\s*억\s*달러\s*[\(（]\s*\+?([0-9,.]+)%[\)）]"
            r".{0,100}?수입\s*([0-9,.]+)\s*억\s*달러\s*[\(（]\s*\+?([0-9,.]+)%[\)）]"
            r".{0,100}?(?:수지|무역수지)\s*([0-9,.]+)\s*억\s*달러",
            text, re.S)
        if alt:
            return {
                "export_usd_100m":num(alt.group(1)),
                "export_yoy":num(alt.group(2)),
                "import_usd_100m":num(alt.group(3)),
                "import_yoy":num(alt.group(4)),
                "balance_usd_100m":num(alt.group(5)),
                "daily_export_usd_100m":num(daily.group(1)) if daily else None,
            }
        raise RuntimeError("총괄 수출·수입·수지 추출 실패")
    return {
        "export_usd_100m":num(exp.group(2)),
        "export_yoy":num(exp.group(1)),
        "import_usd_100m":num(imp.group(2)),
        "import_yoy":num(imp.group(1)),
        "balance_usd_100m":num(bal.group(1)),
        "daily_export_usd_100m":num(daily.group(1)) if daily else None,
    }

def validate(period, overall, industries, regions):
    errors=[]
    if len(industries)!=20:
        errors.append(f"20대 품목 {len(industries)}/20")
    if len(regions)!=9:
        errors.append(f"9대 지역 {len(regions)}/9")
    e=overall["export_usd_100m"]; i=overall["import_usd_100m"]; b=overall["balance_usd_100m"]
    if not (300 <= e <= 1500): errors.append(f"수출총액 비정상 {e}")
    if not (200 <= i <= 1300): errors.append(f"수입총액 비정상 {i}")
    if abs((e-i)-b) > max(3.0, e*0.01):
        errors.append(f"무역수지 검증 실패: 수출-수입={e-i:.1f}, 발표={b:.1f}")
    for n,(v,y) in industries.items():
        if not (0 < v < e): errors.append(f"{n} 수출액 비정상 {v}")
        if not (-100 <= y <= 1000): errors.append(f"{n} 증감률 비정상 {y}")
    for n,(v,y) in regions.items():
        if not (0 < v < e): errors.append(f"{n} 수출액 비정상 {v}")
        if not (-100 <= y <= 1000): errors.append(f"{n} 증감률 비정상 {y}")
    if errors:
        raise RuntimeError("자동검증 실패: " + " / ".join(errors))

def upsert_csv(path, key_cols, rows):
    if path.exists():
        df=pd.read_csv(path, encoding="utf-8-sig")
    else:
        df=pd.DataFrame()
    new=pd.DataFrame(rows)
    if not df.empty:
        # 새 rows와 같은 키의 기존행 삭제
        keys=set(tuple(x) for x in new[key_cols].astype(str).itertuples(index=False,name=None))
        mask=df[key_cols].astype(str).apply(tuple,axis=1).isin(keys)
        df=df[~mask]
    out=pd.concat([df,new],ignore_index=True)
    out=out.sort_values(key_cols)
    out.to_csv(path,index=False,encoding="utf-8-sig")

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="같은 월도 다시 파싱해 정정치 반영")
    args=ap.parse_args()

    period,title,url=discover_latest()
    existing=pd.read_csv(DATA/"motir_monthly.csv",encoding="utf-8-sig")
    latest_existing=str(existing["period"].max())

    print(f"[INFO] 발견: {period} / {title} / {url}")
    if period < latest_existing:
        print("[INFO] 저장 데이터보다 오래된 자료라 종료")
        return
    if period == latest_existing and not args.force:
        print("[INFO] 이미 반영된 월. --force가 아니므로 종료")
        return

    text,_=get_detail(url)
    overall=parse_overall(text)
    inds={}
    for n in INDUSTRIES:
        m=find_metric(text,n)
        if m: inds[n]=m
        else: print(f"[MISS] industry: {n}",file=sys.stderr)
    regs={}
    for n in REGIONS:
        m=find_region(text,n)
        if m: regs[n]=m
        else: print(f"[MISS] region: {n}",file=sys.stderr)

    validate(period,overall,inds,regs)

    monthrow={
        "period":period,
        **overall,
        "source_title":title,
        "source_url":url,
        "status":"잠정치",
    }
    upsert_csv(DATA/"motir_monthly.csv",["period"],[monthrow])
    upsert_csv(DATA/"motir_industry.csv",["period","industry"],[
        {"period":period,"industry":n,"export_usd_100m":v,"yoy":y}
        for n,(v,y) in inds.items()
    ])
    upsert_csv(DATA/"motir_region.csv",["period","region"],[
        {"period":period,"region":n,"export_usd_100m":v,"yoy":y}
        for n,(v,y) in regs.items()
    ])
    status={
        "period":period,
        "last_success":dt.datetime.now(dt.timezone.utc).isoformat(),
        "source_title":title,
        "source_url":url,
        "industries":len(inds),
        "regions":len(regs),
        "message":"20대 품목·9대 지역 자동검증 통과 후 반영"
    }
    (DATA/"update_status.json").write_text(json.dumps(status,ensure_ascii=False,indent=2),encoding="utf-8")
    print(f"[OK] {period} 자동 업데이트 완료")

if __name__=="__main__":
    main()
