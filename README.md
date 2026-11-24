# LINK-ing

Slack 대화를 Event → Task → Work로 구조화해 Supabase에 저장하고, 인수인계 화면에서 업무의 맥락과 진행 상태를 보여주는 캡스톤 프로젝트입니다. 별도 R-GAE API가 인수 대상자의 Task 우선순위를 계산합니다.

## 서비스 흐름

```text
Slack 메시지 → Event 추출 → Task/Work 연결 → Supabase
                                         ├─ LINK-ing 웹/API → 인수인계 화면
                                         └─ R-GAE 학습/API → Task 우선순위
```

- **웹/API**: `src/demo_frontend.py`가 `frontend/index.html`을 제공하고, Supabase 조회·Slack 수집·인수인계 요청·ML API 프록시를 처리합니다.
- **ML API**: `ml/rgae_service/`가 Supabase 그래프 스냅샷으로 학습하고, `POST /v1/priorities`에서 Task 순위를 반환합니다. 모델은 Supabase Storage에 저장합니다. [역할 가중 R-GAE 최종 실험](ml/experiments/README.md)은 별도로 보존합니다.
- **그래프 자료**: `graph/`에 합성 데이터와 생성·분석 스크립트를 모았습니다. 운영 웹 서비스의 실행 경로와는 분리돼 있습니다.

최종 오프라인 평가(10/1 학습 → 10/7 평가, 김지수 활성 1-hop Task)에서 역할 가중 R-GAE의 Precision@5는 **1.00**, nDCG@5는 **0.786**이었습니다. 최종 우선순위 산식을 적용한 nDCG@5는 **0.845**입니다. 이는 [저장된 실험 결과](ml/experiments/README.md)이며 Railway 실시간 성능 측정값은 아닙니다.

## 저장소 구성

| 경로 | 내용 |
| --- | --- |
| `src/` | Slack 수집, LLM 추출, Supabase 저장, 웹/API |
| `frontend/` | 인수인계 및 관리자 화면의 HTML·JavaScript |
| `prompts/` | Event·Task·Work 추출 프롬프트 |
| `ml/` | R-GAE API, Dockerfile, SQL, 테스트, [상세 문서](ml/README.md) |
| `ml/experiments/` | 최종 역할 가중 1-hop 노트북, 재현 스크립트, 입력 그래프, 성능 결과 |
| `graph/` | 합성 그래프 예시와 [실험 스크립트](graph/README.md) |
| `supabase/migrations/` | 앱 데이터베이스 변경 파일 |
| `tests/`, `ml/tests/` | 웹/API 및 ML 테스트 |

## 로컬 실행

Python 3.11 또는 3.13을 사용합니다(ML Dockerfile은 3.11, 아래 로컬 검증은 3.13). 아래 명령은 **PowerShell** 기준이며, 저장소 루트에서 실행합니다. 웹과 ML은 의존성이 달라 각각 가상환경을 만듭니다. Python 3.11을 사용한다면 명령의 `-3.13`을 `-3.11`로 바꾸세요.

### 1. 웹/API

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

`.env`의 Supabase 접속값과 데모 계정을 실제 개발용 값으로 바꿉니다. Slack 동기화와 AI 추출을 사용하려면 각각 `SLACK_TOKEN`, `OPENAI_API_KEY`도 설정합니다. `SUPABASE_KEY`는 서버에서만 사용합니다.

```powershell
.\.venv\Scripts\python.exe -m uvicorn src.demo_frontend:app --host 127.0.0.1 --port 8000 --env-file .env
```

- 화면: `http://127.0.0.1:8000/` (HTTP Basic 인증: `DEMO_USERNAME` / `DEMO_PASSWORD`)
- 상태 확인: `http://127.0.0.1:8000/api/health`
- API 문서: `http://127.0.0.1:8000/docs`

### 2. ML API

```powershell
cd ml
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -m uvicorn rgae_service.api:app --host 127.0.0.1 --port 8001 --env-file .env
```

`ml/.env`에는 Supabase URL·비밀키, 모델 Storage 버킷, `MODEL_API_KEY`를 설정합니다. `ml/sql/`의 RPC·스냅샷 테이블도 대상 Supabase 프로젝트에 준비돼 있어야 학습할 수 있습니다. 자세한 요청 예시는 [ML README](ml/README.md)와 [Postman 가이드](ml/POSTMAN.md)를 참고하세요.

웹에서 ML API를 호출할 때는 웹의 `MODEL_API_URL`을 배포된 ML 서비스의 HTTPS 주소 또는 Railway 내부 주소로 설정하고, 두 서비스의 `MODEL_API_KEY`를 같은 값으로 맞춥니다. 현재 웹 코드는 일반 `http://localhost` ML 주소를 허용하지 않습니다.

## 환경변수

실제 비밀값은 GitHub에 올리지 않습니다. 웹의 예시는 [`.env.example`](.env.example), ML의 예시는 [`ml/.env.example`](ml/.env.example)에 있습니다.

| 서비스 | 핵심 변수 | 용도 |
| --- | --- | --- |
| 웹 | `SUPABASE_URL`, `SUPABASE_KEY` | 업무·인수인계 데이터 조회와 저장 |
| 웹 | `DEMO_USERNAME`, `DEMO_PASSWORD`, `ADMIN_PASSWORD` | 데모 화면과 관리자 접근 |
| 웹 | `SLACK_TOKEN`, `OPENAI_API_KEY` | Slack 수집과 AI 추출·질의 |
| 웹 | `MODEL_API_URL`, `MODEL_API_KEY` | ML API 연결 |
| ML | `SUPABASE_URL`, `SUPABASE_SECRET_KEY` | 그래프 스냅샷·Storage 접근 |
| ML | `MODEL_BUCKET`, `MODEL_OBJECT_PATH`, `MODEL_API_KEY` | 모델 저장 위치와 API 인증 |

Slack OAuth 로그인은 `SLACK_CLIENT_ID`, `SLACK_CLIENT_SECRET`, `SLACK_REDIRECT_URI`가 모두 있을 때 활성화됩니다. DB 기반 AI 질의 등 선택 기능은 코드와 [API 문서](docs/frontend-api.md)의 추가 설정을 확인하세요.

## Railway 배포

웹과 ML은 같은 GitHub `main` 브랜치에서 별도 Railway 서비스로 실행합니다. 웹은 저장소 루트, ML은 `/ml`을 Root Directory로 사용합니다. 두 서비스는 각각 빌드·배포되며 환경변수와 헬스체크도 따로 설정합니다.

서비스별 GitHub 브랜치, Root Directory, 시작 명령, 환경변수와 확인 방법은 [Railway 배포 가이드](docs/railway-deploy.md)에 정리했습니다. ML API의 학습·Storage 설정은 [ML 배포 상세 문서](ml/README-deploy.md)를 참고하세요.

## 테스트

저장소 루트에서:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -q
node --test tests/*.cjs tests/*.js
cd ml
.\.venv\Scripts\python.exe -m unittest discover -s tests -q
```

앱의 Python 테스트 124개, 프론트 테스트 6개, ML 테스트 10개를 확인했습니다.
