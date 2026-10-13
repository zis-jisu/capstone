# Postman 검증 가이드

프론트엔드 없이 Railway FastAPI를 직접 검증하는 순서입니다.

## 공통 설정

Postman Environment에 다음 값을 등록합니다.

```text
MODEL_API_URL=https://capstone-production-0d32.up.railway.app
MODEL_API_KEY=Railway의 MODEL_API_KEY 값
```

보호된 API 요청에는 다음 Header를 사용합니다.

```text
Content-Type: application/json
X-API-Key: {{MODEL_API_KEY}}
```

## 1. 서버 상태 확인

```http
GET {{MODEL_API_URL}}/health
```

`200 OK`가 나오면 서버가 실행 중입니다. 아직 학습 전이면 모델 대기 상태가 표시될 수 있습니다.

## 2. 최초 학습 1회 실행

```http
POST {{MODEL_API_URL}}/v1/training
Content-Type: application/json
X-API-Key: {{MODEL_API_KEY}}

{
  "trigger": "manual"
}
```

정상 응답은 `202 Accepted`이며 여러 줄의 NDJSON이 순서대로 표시됩니다. 학습 중에는 진행 상태 또는 heartbeat가 나오고 마지막 줄은 `completed` 또는 `failed`입니다. **마지막 줄이 나오기 전에 Postman 요청을 중단하지 마세요.** 이 열린 연결이 Railway 컨테이너를 학습 중에 유지합니다.

```json
{"accepted":true,"status":"running","trigger":"manual"}
{"status":"running","current_epoch":1,"total_epochs":600,"progress_percent":0.2,"loss":0.69}
{"status":"running","heartbeat":true}
{"status":"completed","trained_at":"..."}
```

## 3. 학습 완료 확인

```http
GET {{MODEL_API_URL}}/v1/training
X-API-Key: {{MODEL_API_KEY}}
```

완료 후 상태와 최신 학습 날짜를 확인합니다. 모델은 Supabase Storage의 `rgae-models/models/latest.pt`에 저장됩니다.

## 4. person_id 우선순위 확인

```http
POST {{MODEL_API_URL}}/v1/priorities
Content-Type: application/json
X-API-Key: {{MODEL_API_KEY}}

{
  "person_id": "U0C22C8M742"
}
```

응답의 `rankings`는 배열이 아니라 `task_id`를 key로 하는 객체입니다. 완료된 Task는 제외되며 대상 Task가 없으면 `{}`를 반환합니다.

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

## 주의

- Supabase mock 테이블이 비어 있으면 학습이 실패합니다.
- `MODEL_API_KEY`와 `SUPABASE_SECRET_KEY`는 GitHub에 올리지 않습니다.
- Postman에서 최초 학습을 실행하기 전까지 `/v1/priorities`는 학습된 모델이 없다는 응답을 반환할 수 있습니다.
- Railway Serverless는 켜 둡니다. 학습 요청의 스트림이 컨테이너를 유지하고, 완료 후에는 자동으로 다시 휴면합니다.
