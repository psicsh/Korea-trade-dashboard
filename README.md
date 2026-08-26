# 한국무역 한눈에 보기 v8.6

v8.5 화면 기능은 그대로 두고 산업통상부 자동 업데이트 링크 해석 오류를 수정했습니다.

## 수정 사항
산업통상부 보도자료 목록의 링크가
`javascript:article.view('172077');`
형식이어도 글 번호를 추출하여
`https://www.motir.go.kr/kor/article/ATCL3f49a5a8c/172077/view`
형식의 실제 상세 URL로 변환합니다.

화면/App 코드는 v8.5와 동일합니다.
GitHub에서는 `scripts/update_motir.py`만 교체해도 됩니다.
