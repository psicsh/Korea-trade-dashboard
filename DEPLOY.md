# v8 배포/업데이트 방법

## 1. 기존 GitHub 저장소에 v8 파일 올리기
기존 저장소의 파일을 v8 파일로 교체합니다. 특히 아래 폴더까지 올라가야 합니다.

- `app.py`
- `requirements.txt`
- `data/`
- `scripts/`
- `.github/workflows/update_trade.yml`

`.github` 폴더가 안 보이면 Windows 탐색기에서 숨김 파일 표시를 켜거나,
GitHub 웹의 Upload files에서 폴더째 드래그하면 됩니다.

## 2. Streamlit Secrets
기존과 동일합니다.

```toml
DATA_GO_KR_SERVICE_KEY = "공공데이터포털 인증키"
```

## 3. GitHub Actions 확인
GitHub 저장소 상단의 **Actions** 탭을 누르면
`Update MOTIR trade data`가 보입니다.

처음에는:
- Actions → Update MOTIR trade data → Run workflow
- force는 `true`로 한 번 시험할 수 있습니다.

정상이라면 매일 한국시간 12:30에 자동 점검합니다.

## 4. GitHub 권한
워크플로 파일에 `permissions: contents: write`를 넣어두었습니다.
조직/저장소 정책에서 Actions의 쓰기 권한을 막아둔 경우에는
Settings → Actions → General → Workflow permissions에서
**Read and write permissions**를 선택해야 할 수 있습니다.

## 5. 새 달 동작
예: 9월 1일에 「2026년 8월 수출입 동향」 게시
→ 12:30 자동 점검
→ HTML/PDF 파싱
→ 20대 + 9대 + 총괄 검증
→ CSV에 2026-08 추가
→ GitHub 자동 commit
→ Streamlit 앱 자동 재배포/갱신

## 6. 실패 시
산업부 표 형식이 바뀌면 Action이 실패(빨간색)할 수 있습니다.
기존 정상 데이터는 절대로 덮어쓰지 않습니다.
그때 `scripts/update_motir.py`의 정규식만 수정하면 됩니다.

## 7. MTI-HSK 공식 연계표
Action이 KITA 공식 보도자료에서 `2026 MTI-HSK 코드표`를 자동으로 내려받으려고 시도합니다.
사이트 첨부 구조 때문에 실패하면 공식 파일을 한 번 내려받아
`data/mti_hsk_mapping.xlsx` 이름으로 올리면 됩니다.
