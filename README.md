# 한국무역 한눈에 보기 1.0.0

관세청 공공데이터를 이용해 한국의 전체 무역, 20대 주요 품목, 9대 주요 수출지역, HS 2·4·6자리 상세 실적을 보여 주는 Streamlit 앱입니다.

## 핵심 기능

- 전체 무역: 최신 월 지표, 최근 12개월·5년 월별 그래프, CSV 다운로드
- 20대 품목: 2026년 개편 MTI 기준 최신 월 비교, 품목별 12개월·5년 그래프, CSV 다운로드
- 9대 지역: 미국·중국·아세안·EU(27)·일본·중남미·인도·중동·CIS 비교 및 시계열
- HS 상세조회: 숫자 2·4·6자리만 허용, 선택한 한 달만 호출, 공식 명칭·관련 MTI·CSV 제공
- 안전장치: HS 결과 6시간 캐시, 세션당 10분 10회/최소 2초 간격, API 오류 구분, 인증키·요청 URL 비공개
- 데이터 갱신: 매월 15~22일 자동 재시도, 최근 3개월 재검증, 원자적 교체와 최근 3개 백업

## 인증키 설정

인증키 이름은 모든 환경에서 아래 이름만 사용합니다.

```text
DATA_GO_KR_SERVICE_KEY
```

인증키 값은 GitHub 파일에 넣지 않습니다.

### Streamlit Cloud

앱의 `Settings → Secrets`에 다음과 같이 입력합니다.

```toml
DATA_GO_KR_SERVICE_KEY = "발급받은_일반인증키"
```

### GitHub Actions

저장소의 `Settings → Secrets and variables → Actions → New repository secret`에서 같은 이름으로 등록합니다. 워크플로는 이 값을 실행 환경변수로만 전달합니다.

## 최초 배포 순서

1. 이 저장소 전체를 GitHub 새 저장소의 루트에 올립니다.
2. 공공데이터포털에서 다음 API의 활용신청을 완료합니다.
   - [관세청 수출입총괄](https://www.data.go.kr/data/15102108/openapi.do)
   - [관세청 품목별 수출입실적](https://www.data.go.kr/data/15101609/openapi.do)
   - [관세청 국가별 수출입실적](https://www.data.go.kr/data/15101612/openapi.do)
3. GitHub Actions Secret `DATA_GO_KR_SERVICE_KEY`를 등록합니다.
4. `data/mti_hsk_mapping.xlsx`를 한국무역협회가 공개한 **공식 2026 HSK–MTI 연계표**로 교체합니다.
5. GitHub의 `Actions → 관세청 무역자료 갱신 → Run workflow`에서 `mode=bootstrap`을 한 번 실행합니다. 최근 60개월만 구축됩니다.
6. Streamlit Community Cloud에서 저장소의 `app.py`를 지정하고, Streamlit Secrets에 같은 인증키를 등록합니다.

### MTI 연계표에 관한 중요 안내

배포본의 `data/mti_hsk_mapping.xlsx`는 열 구조만 가진 자리표시자입니다. 공식 연계표 원본은 이 저장소 생성 시 제공되지 않았으므로 임의의 매핑을 넣지 않았습니다. 앱과 스크립트는 다음과 같은 열 이름을 자동 인식합니다.

- HSK: `HSK`, `HSK10`, `HS코드`, `HS부호`, `세번`, `세번부호`
- MTI: `MTI`, `MTI6`, `MTI코드`

공식 파일을 넣기 전에도 전체 무역·9대 지역·HS 상세조회는 작동합니다. 20대 품목의 최초 구축과 관련 MTI 표시는 공식 연계표를 넣은 뒤 활성화됩니다.

산업통상부는 2026 MTI 개편 자료를 2022년 이후로 소급 정비한다고 밝혔으므로, 품목 시계열의 기본 시작월은 2022년 1월입니다. 앱의 “최근 5년”은 이 경우 **최근 5년 범위 안의 공식 가용기간**을 표시합니다.

## 데이터 구축 방식

관세청 공식 명세에서 `hsSgn`과 `cntyCd`는 선택 항목입니다. 모든 저장 CSV는 최근 60개월만 유지하며 다음 방식으로 호출량을 줄입니다.

- 전체 무역: 최근 60개월을 12개월 단위로 나누어 수집
- 9대 지역: 국가별 전체 자료를 최대 12개월 단위로 한 번씩 받고 지역 정의에 따라 합산
- 20대 품목: 한 달의 전체 HSK를 한 번만 받은 뒤 공식 2026 HSK–MTI 연계표로 집계
- 월별 갱신: 전체·지역은 새 달과 직전 2개월을 검증하고, 대용량 HSK는 새 달만 수집
- HS 상세조회: 사용자가 입력한 코드와 선택한 한 달만 실시간 조회하며 저장하지 않음

최초 품목 구축은 최대 60회의 월별 HSK 호출이 필요해 시간이 걸릴 수 있지만, 이후에는 새 달만 한 번 처리합니다.

## 로컬 검사

인증키 없이 코드와 테스트만 확인할 수 있습니다.

```bash
python -m venv .venv
source .venv/bin/activate  # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
pytest -q
streamlit run app.py
```

API 연결 확인은 인증키를 셸 환경변수로 일시 주입한 로컬 개발 환경이나 GitHub Actions에서 실행합니다. 키 값이나 요청 주소는 출력하지 않습니다.

```bash
python scripts/check_public_data.py --period 2026-07 --hs 8542
```

## CSV 구조

- `trade_monthly.csv`: `period`, 수출·수입·수지, 수출입 건수, 출처
- `trade_industry.csv`: `period`, 20대 품목 코드·명칭, 수출·수입·수지, 출처
- `trade_region.csv`: `period`, 9대 지역 코드·명칭, 수출·수입·수지, 출처

금액은 모두 미화 달러입니다. 화면에서만 억 달러로 바꾸어 표시합니다.

## API 기준

공식 명세상 요청변수는 `strtYymm`, `endYymm`, 품목의 `hsSgn`, 국가의 `cntyCd`입니다. 명세에 없는 `numOfRows`는 사용하지 않습니다. 관세청은 매월 15일경 전월까지의 정정·취하 내역을 반영하며, 개발계정 기본 호출량은 일반적으로 일 10,000건입니다.
