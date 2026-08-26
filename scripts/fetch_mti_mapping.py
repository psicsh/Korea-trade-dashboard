#!/usr/bin/env python3
"""
한국무역협회 보도자료의 '2026 MTI-HSK 코드표' 첨부파일을 찾아 data/에 저장합니다.
사이트 첨부 URL 구조가 바뀌면 실패할 수 있으며, 월간 업데이트 자체에는 영향이 없습니다.
"""
from pathlib import Path
from urllib.parse import urljoin
import re, sys, requests
from bs4 import BeautifulSoup

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"data"/"mti_hsk_mapping.xlsx"
PAGE="https://www.kita.net/board/pressData/pressDataDetail.do?no=12102"

s=requests.Session()
s.headers.update({"User-Agent":"Mozilla/5.0 (compatible; KoreaTradeLectureBot/1.0)"})
r=s.get(PAGE,timeout=30); r.raise_for_status()
soup=BeautifulSoup(r.text,"html.parser")

candidates=[]
for a in soup.find_all("a",href=True):
    label=" ".join(a.get_text(" ",strip=True).split())
    probe=(label+" "+a["href"])
    if "MTI-HSK" in probe and "코드표" in probe and ("xlsx" in probe.lower() or "download" in probe.lower() or "down" in probe.lower()):
        candidates.append(urljoin(r.url,a["href"]))

if not candidates:
    print("[WARN] 자동 다운로드 링크를 찾지 못했습니다. 공식 페이지에서 '2026 MTI-HSK 코드표_vFF_260507.xlsx'를 내려받아 data/mti_hsk_mapping.xlsx로 넣으세요.")
    sys.exit(0)

for u in candidates:
    try:
        rr=s.get(u,timeout=45); rr.raise_for_status()
        if len(rr.content)>5000:
            OUT.write_bytes(rr.content)
            print("[OK] MTI-HSK 연계표 저장:",OUT)
            sys.exit(0)
    except Exception as e:
        print("[WARN]",u,e)

print("[WARN] 링크는 찾았으나 파일 저장에 실패했습니다.")
