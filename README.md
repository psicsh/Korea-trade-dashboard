# 한국무역 한눈에 보기 v9.2

## 핵심
학생 화면에서 관세청 API를 직접 기다리지 않습니다.

- 전체무역: `data/trade_monthly.csv` 즉시 로드
- 20대 품목: `data/trade_industry.csv` 즉시 로드
- 9대 지역: `data/trade_region.csv` 즉시 로드
- GitHub Actions: 매월 15~22일 관세청 API를 백그라운드에서 호출해 위 CSV 자동 갱신
- HS 상세조회만 사용자가 버튼을 눌렀을 때 실시간 API 호출
- API 한 구성요소가 실패해도 기존 정상 CSV를 그대로 유지

## 한 번만 필요한 설정
GitHub 저장소에도 공공데이터포털 인증키를 Secret으로 등록해야 합니다.

Settings → Secrets and variables → Actions → New repository secret

Name:
`DATA_GO_KR_SERVICE_KEY`

Value:
Streamlit Secrets에 넣었던 것과 같은 공공데이터포털 인증키

그 뒤 Actions → `Update Customs trade data` → Run workflow로 첫 실행을 한 번 확인합니다.
정상 확인 후에는 매월 자동 실행됩니다.
