# Handover R-GAE API

Supabase 최신 mock 테이블을 그래프로 변환해 R-GAE 모델을 학습하고, 인수인계자의 `person_id`를 기준으로 2-hop 범위의 미완료 Task 우선순위를 반환하는 FastAPI 서비스입니다.

## 동작 흐름

```text
Supabase mock tables
  -> get_graph_snapshot() REST RPC
  -> Railway Cron: 매주 모델 학습
  -> Supabase Storage: models/latest.pt 저장
  -> Railway FastAPI
  -> 프론트가 person_id 전달
  -> task_id별 우선순위 반환
```

별도 JSON 스냅샷 테이블은 만들지 않습니다. 학습할 때마다 RPC가 최신 테이블을 JSON 그래프로 구성하며, 학습 당시 그래프와 학습일은 모델 파일에 포함됩니다.

## 주요 파일

| 경로 | 용도 |
|---|---|
| `rgae_service/api.py` | FastAPI 엔드포인트 |
| `rgae_service/training.py` | 수동·주간 모델 학습 실행기 |
| `rgae_service/repository.py` | Supabase RPC 및 Storage 연동 |
| `rgae_service/model.py` | R-GAE 학습과 counterfactual 계산 |
| `rgae_service/priority.py` | 최종 Task 우선순위 계산 |
| `sql/get_graph_snapshot.sql` | Supabase RPC 백업·재설치·버전관리용 SQL |
| `Dockerfile` | Railway 컨테이너 빌드 |
| `.env.example` | 필요한 환경변수 목록 |

`sql/get_graph_snapshot.sql`은 Railway가 실행하거나 읽는 파일이 아닙니다. Supabase SQL Editor에 RPC를 최초 설치하거나 복구할 때만 사용합니다. 운영 중에는 Python 서버가 이미 등록된 RPC를 API로 호출합니다.

## API

### 우선순위 산출

```http
POST /v1/priorities
Content-Type: application/json
X-API-Key: <MODEL_API_KEY>

{"person_id":"U0C22C8M742"}
```

응답의 `rankings`는 `task_id`별 객체입니다. 완료된 Task는 제외되며 후보가 없으면 빈 객체를 반환합니다.

```json
{
  "person_id": "U0C22C8M742",
  "person_name": "김지수",
  "model_trained_at": "2026-10-11T12:00:00+00:00",
  "rankings": {
    "TASK-001": {
      "task_id": "TASK-001",
      "task_name": "캠페인 검토",
      "task_status": "in_progress",
      "final_priority_rank": 1,
      "final_priority_score": 87.4,
      "deadline_score": 95.0,
      "model_score": 82.0,
      "relation_score": 100.0,
      "workflow_score": 60.0
    }
  }
}
```

### 학습

| Method | Path | 용도 |
|---|---|---|
| `POST` | `/v1/training` | 최신 그래프로 수동 학습 시작 |
| `GET` | `/v1/training` | 학습 상태와 최신 성공 학습일 조회 |
| `GET` | `/health` | Railway 상태 확인 |

## 환경변수

`.env`와 실제 Secret Key는 GitHub에 올리지 않습니다. Railway의 Shared Variables에 다음 값을 설정해 API와 Cron 서비스가 함께 사용하게 합니다.

```env
SUPABASE_URL=https://PROJECT_ID.supabase.co
SUPABASE_SECRET_KEY=sb_secret_xxx
GRAPH_RPC=get_graph_snapshot
MODEL_BUCKET=rgae-models
MODEL_OBJECT_PATH=models/latest.pt
MODEL_REFRESH_SECONDS=60
MODEL_API_KEY=long-random-secret
ALLOWED_ORIGINS=https://YOUR_FRONTEND_DOMAIN
RGAE_EPOCHS=600
RGAE_SEED=42
RGAE_DEVICE=cpu
```

## Railway 배포

GitHub `zis-jisu/capstone` 저장소의 `ml` 브랜치를 소스로 사용합니다.

1. API 서비스
   - Start Command: Dockerfile 기본 명령
   - Healthcheck: `/health`
   - Public Domain: 생성
2. 주간 학습 Cron 서비스
   - 같은 저장소와 `ml` 브랜치 사용
   - Start Command: `python -m rgae_service.training`
   - Cron Schedule: `0 12 * * 0` (매주 일요일 21:00 KST)
   - Public Domain: 불필요

Cron이 새 모델을 Supabase Storage에 저장하면 API는 `MODEL_REFRESH_SECONDS` 간격으로 이를 감지해 재시작 없이 최신 모델과 학습일을 반영합니다.

자세한 배포 및 프론트 프록시 예시는 `README-deploy.md`를 참고하세요.
