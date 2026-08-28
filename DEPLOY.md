# 배포 및 운영 안내

## 1. GitHub 저장소 준비

저장소 루트에 `app.py`, `requirements.txt`, `.github`, `.streamlit`, `data`, `scripts`, `trade_dashboard`가 보이도록 전체 파일을 올립니다.

다음 파일은 절대 커밋하지 않습니다.

- `.streamlit/secrets.toml`
- `.env`, `.env.*`
- 다른 이름의 `secrets.toml`
- 인증키가 포함된 실행 로그나 요청 URL

## 2. GitHub Actions Secret

`Settings → Secrets and variables → Actions`에서 다음 Repository secret을 만듭니다.

```text
Name: DATA_GO_KR_SERVICE_KEY
Value: 공공데이터포털 일반인증키
```

GitHub Actions의 `GITHUB_TOKEN` 권한은 워크플로의 `permissions: contents: write`로 제한되어 있습니다.

## 3. 최초 과거자료 구축

`data/mti_hsk_mapping.xlsx`를 공식 2026 HSK–MTI 연계표로 교체한 뒤:

1. `Actions` 탭에서 `관세청 무역자료 갱신` 선택
2. `Run workflow` 선택
3. `mode`를 `bootstrap`으로 선택
4. 공식 연계표가 아직 없다면 `skip_industries=true`로 먼저 전체·지역만 구축
5. 실행 결과가 성공하면 갱신된 CSV와 상태 JSON이 자동 커밋되었는지 확인

전체 장기 시계열은 기본 1965년 1월부터 조회합니다. 제공기관의 실제 가용 시작월이 더 늦으면 유효한 월만 저장됩니다.

## 4. 월별 자동 갱신

워크플로는 매월 15일부터 22일까지 한국시간 오전 9시 15분에 실행됩니다. 목표 전월이 아직 없으면 `pending` 상태만 기록하고 다음 날 다시 시도합니다.

자료가 제공되면:

- 최근 3개월을 다시 조회
- 데이터 형식, 중복, 음수 금액, 무역수지를 검증
- 정상인 경우에만 기존 CSV 교체
- 기존 CSV는 실행 환경에서 최근 3개까지 백업
- 변경 파일을 GitHub에 자동 커밋

## 5. Streamlit Community Cloud

1. `New app`에서 GitHub 저장소와 브랜치를 선택
2. Main file path에 `app.py` 입력
3. `Advanced settings` 또는 배포 후 `Settings → Secrets`에서 다음을 입력

```toml
DATA_GO_KR_SERVICE_KEY = "공공데이터포털 일반인증키"
```

4. 재부팅 후 HS 상세조회에서 2·4·6자리 코드로 확인

## 6. 장애 확인

- `update_status.json`의 `status`가 `pending`: 관세청의 전월 자료가 아직 현행화되지 않은 상태
- 인증·권한 오류: 세 API 각각의 활용신청 상태와 인증키 유효기간 확인
- 호출 한도 오류: 다음 날 다시 실행하거나 공공데이터포털에서 운영계정 증설 신청
- 20대 품목만 건너뜀: 공식 2026 연계표인지, HSK/MTI 열을 로더가 찾을 수 있는지 확인
- CI 실패: `pytest -q`를 로컬에서 실행하고 CSV 헤더·지역 그룹 중복·비밀파일 포함 여부 확인

오류 메시지에는 인증키나 전체 요청 주소가 들어가지 않도록 구현되어 있습니다.

