# Handover R-GAE API

Supabase 최신 mock 테이블을 그래프로 변환해 역할 edge 가중 R-GAE를 학습하고, 한 명 또는 여러 인계 대상자의 직접 1-hop Task를 통합 우선순위로 반환하는 FastAPI 서비스입니다.

## 동작 흐름

```text
Supabase mock tables
  -> get_graph_snapshot() REST RPC
  -> POST /v1/training: 필요할 때 1회 학습
  -> Supabase Storage: models/latest.pt 저장
  -> Railway FastAPI
  -> Postman 또는 클라이언트가 person_id 또는 person_ids 전달
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

여러 사람의 업무를 한 수신자가 함께 인수하는 요청도 지원합니다.

```json
{
  "person_ids": ["U0C22C8M742", "U0C1M3Q1PRV"],
  "receiver_person_id": "U0C20G9MRML"
}
```

`receiver_person_id`는 응답 메타데이터에만 사용합니다. 인수 전 위험을 계산할 때 수신자 edge를 미리 추가하지 않습니다.

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
      "structure_score": 82.0,
      "workflow_score": 60.0,
      "related_only": false,
      "related_penalty": 0.0,
      "source_person_ids": ["U0C22C8M742"]
    }
  }
}
```

학습 edge 계수는 `APPROVER 31 / OWNER 27 / REVIEWER 21 / COLLABORATOR 17 / RELATED 4`이며 기타 관계는 중립 계수 15를 사용합니다. 최종 점수는 `구조 55 + 유효 마감 30 + 연속성 15 - RELATED-only 10`입니다.

### 학습

| Method | Path | 용도 |
|---|---|---|
| `POST` | `/v1/training` | 최신 그래프로 학습하고 진행 상황을 NDJSON으로 스트리밍 |
| `GET` | `/v1/training` | 학습 상태와 최신 성공 학습일 조회 |
| `GET` | `/health` | Railway 상태 확인 |

## 환경변수

`.env`와 실제 Secret Key는 GitHub에 올리지 않습니다. Railway API 서비스의 Variables에 다음 값을 설정합니다.

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

GitHub `zis-jisu/capstone` 저장소의 `slack` 브랜치를 소스로 사용합니다.

1. API 서비스
   - Start Command: Dockerfile 기본 명령
   - Healthcheck: `/health`
   - Public Domain: 생성

API 서비스는 Railway Serverless를 켜 둡니다. `POST /v1/training`이 20초마다 진행 상태 또는 heartbeat를 전송하므로 학습 중에는 컨테이너가 유지되고, 완료 후 요청이 없으면 자동으로 다시 휴면합니다. Postman에서 이 요청을 닫지 말고 마지막 `completed` 또는 `failed` 줄까지 확인합니다. 학습 완료 모델은 Supabase Storage에 저장됩니다.

실제 주간 자동화가 필요해질 때는 동일 저장소로 별도 Railway Cron 서비스를 만들고 Start Command를 `python -m rgae_service.training`으로 지정합니다. Cron 프로세스는 학습 완료 후 자동 종료됩니다.

Postman에서 `postman_collection.json`을 Import하면 네 요청을 바로 테스트할 수 있습니다. 상세 순서는 `POSTMAN.md`, 자세한 배포 설명은 `README-deploy.md`를 참고하세요.
