# v9.0 배포 순서

1. 기존 GitHub 저장소의 파일을 v9.0 파일로 교체
2. `.github/workflows/update_trade.yml`은 삭제하거나 비활성화
3. 공식 `2026 MTI-HSK 코드표_vFF_260507.xlsx`를 다운로드
4. 파일명을 `mti_hsk_mapping.xlsx`로 바꿔 `data/` 폴더에 업로드
5. 기존 Streamlit Secrets의 DATA_GO_KR_SERVICE_KEY는 그대로 유지
6. Streamlit이 자동 재배포되면 확인

체크:
- 전체 무역 숫자 표시
- 20대 품목 탭에서 'HSK-MTI ...개 코드 인식' 성공 메시지
- 9대 지역 표
- HS 8542 상세조회
