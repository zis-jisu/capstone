# Railway 배포 가이드

LINK-ing 웹과 R-GAE ML API는 같은 GitHub `main` 브랜치를 사용하지만 Railway에서는 서로 다른 서비스로 실행합니다. 각 서비스의 Root Directory로 빌드 범위를 구분합니다. 기존 `slack`·`ml` 분리 브랜치는 이전 배포 구성입니다.

## 서비스 설정

| 서비스 | GitHub 소스 | Root Directory | 시작·헬스체크 |
| --- | --- | --- | --- |
| `linking-web` | `zis-jisu/capstone`의 `main` | 저장소 루트 | `uvicorn src.demo_frontend:app --host 0.0.0.0 --port $PORT` · `/api/health` |
| `capstone` (ML) | `zis-jisu/capstone`의 `main` | `/ml` | `ml/Dockerfile` 기본 명령 · `/health` |

웹의 Healthcheck Path는 `/api/health`, ML은 `/health`입니다. ML의 Root Directory를 `/ml`로 설정해야 Dockerfile의 `COPY requirements.txt`와 `COPY rgae_service`가 ML 코드에 맞게 동작합니다. Railway의 [모노레포 배포 문서](https://docs.railway.com/deployments/monorepo#deploying-an-isolated-monorepo)도 같은 저장소에서 서비스별 Root Directory를 설정하는 방식을 설명합니다.

## 환경변수

각 서비스의 기존 비밀값은 Railway Variables에 둡니다. 값 자체는 GitHub에 넣지 않습니다.

| 웹 (`linking-web`) | ML (`capstone`) |
| --- | --- |
| `SUPABASE_URL`, `SUPABASE_KEY` | `SUPABASE_URL`, `SUPABASE_SECRET_KEY` |
| `DEMO_USERNAME`, `DEMO_PASSWORD`, `ADMIN_PASSWORD` | `MODEL_BUCKET`, `MODEL_OBJECT_PATH` |
| `SLACK_TOKEN`, `OPENAI_API_KEY` | `MODEL_API_KEY`, `GRAPH_RPC` |
| `MODEL_API_URL`, `MODEL_API_KEY` | `RGAE_EPOCHS`, `RGAE_SEED`, `RGAE_DEVICE` |

웹의 `MODEL_API_URL`은 ML 서비스의 HTTPS 주소 또는 Railway 내부 주소를 가리켜야 합니다. 두 서비스의 `MODEL_API_KEY`는 같은 값을 사용합니다. 전체 예시는 웹 [`.env.example`](../.env.example)과 ML [`ml/.env.example`](../ml/.env.example)을 참고하세요.

## 배포 확인

1. Railway에서 두 서비스가 의도한 브랜치와 Root Directory를 바라보는지 확인합니다.
2. 각 서비스의 최신 배포 상태가 성공인지 확인합니다.
3. 웹 도메인의 `/api/health`, ML 도메인의 `/health`가 정상 응답하는지 확인합니다.
4. 웹에서 ML 학습 상태를 조회해 `MODEL_API_URL`·`MODEL_API_KEY` 연결을 확인합니다.

GitHub 브랜치 연결이나 Root Directory 변경은 배포 대상 코드를 바꾸므로, 적용 후 두 서비스의 빌드 로그와 헬스체크를 다시 확인합니다.
