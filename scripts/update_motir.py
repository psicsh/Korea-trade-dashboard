#!/usr/bin/env python3
"""
산업통상부 월간 '수출입 동향' 자동 업데이트.

동작:
1) 산업통상부 보도자료에서 최신 월간 수출입 동향 검색\n   - 산업통상부 접속 장애 시 한국무역협회 FTA 통합플랫폼 재게시 자료로 자동 전환
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
KITA_LIST_URL = "https://okfta.kita.net/nttCntnt/list?mnSn=38"

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

BUILD_ID = "v8.8.1-final-20260826"

def normalize_download_url(raw_href, base_url):
    """
    산업통상부 첨부파일 링크가
    javascript:location.href='/attach/down/...'
    형태여도 실제 다운로드 URL로 변환한다.
    """
    raw = (raw_href or "").strip()
    if not raw:
        return None

    # 일반 URL
    if not raw.lower().startswith("javascript:"):
        return urljoin(base_url, raw)

    # javascript:location.href='/attach/down/...'
    m = re.search(
        r"""location\.href\s*=\s*['"]([^'"]+)['"]""",
        raw,
        re.I,
    )
    if m:
        return urljoin(base_url, m.group(1))

    # 혹시 window.location / location.assign 형태도 대비
    m = re.search(
        r"""(?:window\.)?location(?:\.assign)?\s*\(\s*['"]([^'"]+)['"]\s*\)""",
        raw,
        re.I,
    )
    if m:
        return urljoin(base_url, m.group(1))

    return None



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


def discover_latest_motir():
    """산업통상부 원문을 우선 탐색. 접속 장애가 나면 호출자가 KITA로 전환한다."""
    found = []
    # 최신 월간자료는 보통 앞쪽에 있으므로 3페이지만 확인해
    # GitHub Actions에서 외부사이트 지연이 길어지는 것을 막는다.
    for page in range(1, 4):
        r = session.get(LIST_URL, params={"pageIndex": page}, timeout=(10, 20))
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")

        for a in soup.find_all("a"):
            title = " ".join(a.get_text(" ", strip=True).split())
            period = period_from_title(title)
            if not period:
                continue
            if "정보통신" in title or "ICT" in title or "자동차산업" in title:
                continue

            href = normalize_article_url(a, r.url)
            if not href:
                continue
            found.append((period, title, href))

    if not found:
        raise RuntimeError("산업통상부 목록에서 월간 수출입 동향을 찾지 못했습니다.")

    uniq = {u: (p, t, u) for p, t, u in found}
    return max(uniq.values(), key=lambda x: x[0])


def normalize_kita_url(anchor, base_url):
    """KITA 목록의 일반 링크 또는 자바스크립트 링크를 상세 URL로 변환."""
    raw = (anchor.get("href") or "").strip()
    onclick = (anchor.get("onclick") or "").strip()
    probe = raw + " " + onclick

    if raw and not raw.lower().startswith("javascript:") and raw != "#":
        return urljoin(base_url, raw)

    # 예: javascript:...('10184') / fnView(10184) 등
    m = re.search(r"(?:view|fnView|nttCntnt)[^0-9]{0,30}(\d{4,})", probe, re.I)
    if m:
        return f"https://okfta.kita.net/nttCntnt/view/{m.group(1)}?mnSn=38"

    return None


def discover_latest_kita():
    """
    한국무역협회 FTA 통합플랫폼의 '시장정보'는 산업통상부 월간
    수출입 동향 원문과 첨부 PDF를 재게시한다. MOTIR 접속 실패 시 사용.
    """
    r = session.get(KITA_LIST_URL, timeout=(10, 25))
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    found = []

    for a in soup.find_all("a"):
        title = " ".join(a.get_text(" ", strip=True).split())
        period = period_from_title(title)
        if not period:
            continue
        if "정보통신" in title or "ICT" in title or "자동차산업" in title:
            continue

        href = normalize_kita_url(a, r.url)
        if href:
            found.append((period, title, href))

    if not found:
        # 일부 사이트 개편 시 제목이 링크 바깥에 있을 수 있으므로
        # HTML 전체에서 상세글 번호가 붙은 주변 텍스트를 한 번 더 탐색한다.
        html = r.text
        for m in re.finditer(r"(20\d{2}년\s*\d{1,2}월(?:\s*및\s*상반기)?\s*수출입\s*동향)", html):
            title = re.sub(r"<[^>]+>", " ", m.group(1))
            title = " ".join(title.split())
            period = period_from_title(title)
            if not period:
                continue
            around = html[max(0, m.start()-500):m.end()+500]
            idm = re.search(r"/nttCntnt/view/(\d+)", around)
            if idm:
                found.append(
                    (period, title,
                     f"https://okfta.kita.net/nttCntnt/view/{idm.group(1)}?mnSn=38")
                )

    if not found:
        raise RuntimeError("KITA FTA 통합플랫폼에서도 월간 수출입 동향을 찾지 못했습니다.")

    uniq = {u: (p, t, u) for p, t, u in found}
    return max(uniq.values(), key=lambda x: x[0])


def discover_latest():
    """산업통상부 원문 우선, 장애 시 KITA 공식 재게시 자료로 자동 전환."""
    try:
        latest = discover_latest_motir()
        print("[INFO] 자료원: 산업통상부 원문")
        return latest
    except Exception as e:
        print(f"[WARN] 산업통상부 직접 접속 실패 → KITA로 전환: {type(e).__name__}: {e}",
              file=sys.stderr)

    latest = discover_latest_kita()
    print("[INFO] 자료원: 한국무역협회 FTA 통합플랫폼(산업통상부 자료 재게시)")
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
            rr = session.get(href, timeout=(10, 35))
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
    r = session.get(url, timeout=(10, 30))
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    page_text = soup.get_text("\n", strip=True)

    pdf_texts = []
    for a in soup.find_all("a"):
        href_raw = a.get("href") or ""
        label = " ".join(a.get_text(" ", strip=True).split())
        probe = f"{href_raw} {label}".lower()

        # PDF 첨부 또는 /attach/down/ 형태의 다운로드 링크만 시도
        if ".pdf" not in probe and "/attach/down/" not in probe:
            continue

        href = normalize_download_url(href_raw, r.url)
        if not href:
            print(f"[WARN] PDF 링크 해석 실패: {href_raw}", file=sys.stderr)
            continue

        try:
            rr = session.get(href, timeout=(10, 35))
            rr.raise_for_status()
            ctype = (rr.headers.get("content-type") or "").lower()

            # 확장자가 없어도 실제 PDF 응답이면 처리
            if "pdf" in ctype or rr.content[:4] == b"%PDF":
                with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tf:
                    tf.write(rr.content)
                    tmp = tf.name
                try:
                    reader = PdfReader(tmp)
                    txt = "\n".join((p.extract_text() or "") for p in reader.pages)
                    if txt.strip():
                        pdf_texts.append(txt)
                finally:
                    try:
                        os.unlink(tmp)
                    except OSError:
                        pass
        except Exception as e:
            print(f"[WARN] PDF 추출 실패: {href_raw} / {e}", file=sys.stderr)

    # HTML 본문 + PDF 추출문을 함께 파싱 대상으로 사용
    combined = page_text
    if pdf_texts:
        combined += "\n\n" + "\n\n".join(pdf_texts)

    return combined

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
