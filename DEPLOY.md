# Streamlit 배포

1. GitHub 저장소에서 기존 `app.py`를 이 버전의 `app.py`로 교체합니다.
2. `requirements.txt`도 같이 교체합니다.
3. Streamlit Community Cloud에서 앱을 연결합니다.
4. Settings → Secrets에 아래를 입력합니다.

```toml
DATA_GO_KR_SERVICE_KEY = "공공데이터포털 인증키"
```

Encoding/Decoding 키 모두 사용할 수 있습니다.
