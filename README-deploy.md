# R-GAE 모델 API 배포

Supabase mock 테이블을 `get_graph_snapshot()` RPC로 읽어 역할 edge 가중 R-GAE를 학습하고, 프론트에서 받은 한 명 또는 여러 명의 `person_id`에 대한 직접 1-hop Task 통합 순위를 반환합니다.

## API

| Method | Path | 역할 |
|---|---|---|
| `POST` | `/v1/training` | 최신 Supabase 그래프로 학습하며 NDJSON 진행 로그 전송 |
| `GET` | `/v1/training` | 학습 상태와 최신 성공 학습일 조회 |
| `POST` | `/v1/priorities` | 단일 또는 다중 인계 대상자의 1-hop Task 통합 순위 반환 |
| `GET` | `/health` | Railway health check |

### 학습 시작

```bash
curl -X POST "$MODEL_API_URL/v1/training" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $MODEL_API_KEY" \
  -d '{"trigger":"manual"}'
```

응답은 `202 Accepted`이며 연결을 유지한 채 NDJSON 진행 로그가 전송됩니다. 마지막 `completed` 또는 `failed` 줄까지 연결을 유지해야 합니다. 별도 화면의 상태 표시는 동시에 `GET /v1/training`을 polling할 수 있습니다.

### 우선순위 요청

```bash
curl -X POST "$MODEL_API_URL/v1/priorities" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $MODEL_API_KEY" \
  -d '{"person_id":"U0C22C8M742"}'
```

다중 인수인계 요청:

```bash
curl -X POST "$MODEL_API_URL/v1/priorities" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $MODEL_API_KEY" \
  -d '{"person_ids":["U0C22C8M742","U0C1M3Q1PRV"],"receiver_person_id":"U0C20G9MRML"}'
```

역할 edge 계수는 `APPROVER 31 / OWNER 27 / REVIEWER 21 / COLLABORATOR 17 / RELATED 4`, 기타 관계는 15입니다. 최종 점수는 `구조 55 + 유효 마감 30 + 연속성 15 - RELATED-only 10`입니다.

완료 상태 Task는 최신 Supabase 값으로 제외됩니다. 학습 후 새로 생긴 Node와 Edge는 다음 학습부터 모델에 포함됩니다.

`rankings`는 배열이 아니라 `task_id`를 key로 하는 객체입니다. 각 Task 값에는 `final_priority_rank`, `final_priority_score`와 세부 점수가 들어갑니다.

```json
{
  "person_id": "U0C22C8M742",
  "person_name": "김지수",
  "model_trained_at": "2026-10-11T12:00:00+00:00",
  "rankings": {
    "TASK-001": {
      "task_id": "TASK-001",
      "final_priority_rank": 1,
      "final_priority_score": 87.4
    }
  }
}
```

## Supabase 준비

1. 최초 설치 또는 RPC 복구가 필요할 때만 `sql/get_graph_snapshot.sql`을 Supabase SQL Editor에서 실행합니다. Railway는 이 파일을 실행하지 않습니다.
2. mock 테이블에 데이터를 넣습니다. 빈 그래프는 학습하지 않습니다.
3. 비공개 Storage bucket `rgae-models`를 만듭니다.
4. Secret Key는 Railway 변수에만 저장하고 브라우저에 노출하지 않습니다.

스냅샷 테이블은 필요하지 않습니다. 모델 파일 `models/latest.pt` 안에 학습 당시 그래프와 `trained_at`이 함께 저장됩니다.
API 서버는 `MODEL_REFRESH_SECONDS` 간격으로 Storage를 확인하므로, 별도 Cron 서비스가 새 모델을 올려도 재시작 없이 최신 모델과 학습일을 반영합니다.

## 로컬 실행

```bash
python -m venv .venv
pip install -r requirements.txt
uvicorn rgae_service.api:app --host 0.0.0.0 --port 8000
```

`.env.example`의 값을 로컬 환경변수 또는 Railway Variables에 등록합니다.

## Railway 배포

1. GitHub `zis-jisu/capstone` 저장소의 `slack` 브랜치로 push합니다.
2. Railway에서 **Deploy from GitHub repo**를 선택하고 branch를 `slack`으로 지정합니다.
3. Variables에 `.env.example` 항목을 등록합니다.
4. Networking에서 API용 public domain을 생성합니다.

Railway는 루트의 `Dockerfile`을 자동으로 사용합니다.

API 서비스의 Start Command는 Dockerfile 기본값을 사용하고, Healthcheck Path는 `/health`로 설정합니다.

API 서비스는 Serverless를 켭니다. 학습 스트림이 20초마다 데이터를 보내 학습 중 컨테이너를 유지하고, 학습 완료 후 유휴 상태가 되면 Railway가 자동으로 다시 휴면시킵니다.

### 선택 사항: 매주 일요일 자동학습

현재 데모 배포에서는 Cron 서비스를 만들지 않습니다. 최초 학습은 Postman의 `POST /v1/training` 호출로 한 번만 확인합니다.

실제 운영에서 자동학습이 필요해질 때만 아래 구성을 추가합니다.

동일 GitHub 저장소로 Railway Cron 서비스를 하나 더 생성합니다.

- Start Command: `python -m rgae_service.training`
- Cron Schedule: `0 12 * * 0`
- 의미: 매주 일요일 21:00 KST
- Public domain: 불필요

API와 Cron 양쪽에 같은 Supabase 관련 Variables를 등록합니다. Railway Shared Variables로 만들면 중복 입력을 피할 수 있습니다.

Cron 작업은 학습을 마치고 자동 종료됩니다.

## Postman 테스트

현재 검증은 프론트 대신 Postman을 사용합니다. 요청 URL, Header, Body는 `POSTMAN.md`에 정리되어 있습니다.

## 선택 사항: 프론트 연결

브라우저에서 Railway API를 직접 호출하면 `MODEL_API_KEY`가 노출됩니다. Next.js 서버 Route Handler에서 Railway API를 호출하고, 브라우저는 Next.js의 `/api/...`만 호출하도록 구성합니다.

```ts
const response = await fetch(`${process.env.MODEL_API_URL}/v1/priorities`, {
  method: "POST",
  headers: {
    "Content-Type": "application/json",
    "X-API-Key": process.env.MODEL_API_KEY!,
  },
  body: JSON.stringify({ person_id }),
});
```

