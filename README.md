# LINK-ing capstone

Slack 대화를 Event → Task → Work로 구조화하고, Supabase에 저장한 업무를 인수인계 화면에서 보여주는 프로젝트입니다. 별도 R-GAE 서비스가 인수 대상자의 Task 우선순위를 계산합니다.

## 저장소 구성

| 경로 | 역할 |
| --- | --- |
| `src/`, `frontend/`, `prompts/` | Slack 수집·구조화, API, 인수인계 화면 |
| `ml/` | R-GAE 학습·우선순위 API와 독립 Docker 배포 설정 |
| `supabase/migrations/` | 앱 데이터베이스 마이그레이션 |
| `tests/`, `ml/tests/` | 앱 및 ML 서비스 검증 |
| `docs/` | API와 인증 흐름 문서 |

## 로컬 실행

Python 3.11 이상이 필요합니다. 앱과 ML 서비스의 의존성은 별도로 설치합니다.

```bash
python -m venv .venv
pip install -r requirements.txt
uvicorn src.demo_frontend:app --reload
```

ML 서비스는 `ml/`을 작업 디렉터리로 실행합니다.

```bash
cd ml
pip install -r requirements.txt
uvicorn rgae_service.api:app --reload
```

각 서비스의 환경변수와 배포 절차는 [앱 API 문서](docs/frontend-api.md), [ML 서비스 문서](ml/README.md), [ML 배포 문서](ml/README-deploy.md)를 참고하세요. 실제 비밀값은 환경변수로 주입합니다.

## 검증

```bash
python -m unittest discover -s tests -v
cd ml
python -m unittest discover -s tests -v
```

앱은 저장소 루트를 Railway 서비스의 Root Directory로 사용하고 `railway.json`으로 실행합니다. ML 서비스는 `ml`을 Root Directory로 지정해 `ml/Dockerfile`로 별도 배포합니다.
