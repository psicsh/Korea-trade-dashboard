# v9.2 배포

1. app.py / requirements.txt / scripts / .github / data의 v9.2 파일을 GitHub에 업로드
2. 기존 data/mti_hsk_mapping.xlsx는 유지
3. GitHub repository secret DATA_GO_KR_SERVICE_KEY 추가
4. Actions → Update Customs trade data → Run workflow 1회 테스트
5. 이후 매월 15~22일 자동 실행
