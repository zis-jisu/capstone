# R-GAE 모델 API 배포

Supabase mock 테이블을 `get_graph_snapshot()` RPC로 읽어 R-GAE를 학습하고, 프론트에서 받은 `person_id`의 2-hop 미완료 Task 전체 순위를 반환합니다.

## API

| Method | Path | 역할 |
|---|---|---|
| `POST` | `/v1/training` | 최신 Supabase 그래프를 받아 백그라운드 학습 시작 |
| `GET` | `/v1/training` | 학습 상태와 최신 성공 학습일 조회 |
| `POST` | `/v1/priorities` | `person_id`의 미완료 Task 순위 반환 |
| `GET` | `/health` | Railway health check |

### 학습 시작

```bash
curl -X POST "$MODEL_API_URL/v1/training" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $MODEL_API_KEY" \
  -d '{"trigger":"manual"}'
```

응답은 즉시 `202 Accepted`이며, 프론트는 `GET /v1/training`을 polling합니다.

### 우선순위 요청

```bash
curl -X POST "$MODEL_API_URL/v1/priorities" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $MODEL_API_KEY" \
  -d '{"person_id":"U0C22C8M742"}'
```

완료 상태 Task는 최신 Supabase 값으로 제외됩니다. 학습 후 새로 생긴 Node와 Edge는 다음 학습부터 모델에 포함됩니다.

## Supabase 준비

1. `sql/get_graph_snapshot.sql`의 `get_graph_snapshot()`을 SQL Editor에서 실행합니다.
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

1. GitHub `zis-jisu/capstone` 저장소의 `ml` 브랜치로 push합니다.
2. Railway에서 **Deploy from GitHub repo**를 선택하고 branch를 `ml`로 지정합니다.
3. Variables에 `.env.example` 항목을 등록합니다.
4. Networking에서 API용 public domain을 생성합니다.

Railway는 루트의 `Dockerfile`을 자동으로 사용합니다.

API 서비스의 Start Command는 Dockerfile 기본값을 사용하고, Healthcheck Path는 `/health`로 설정합니다.

### 매주 일요일 자동학습

동일 GitHub 저장소로 Railway Cron 서비스를 하나 더 생성합니다.

- Start Command: `python -m rgae_service.training`
- Cron Schedule: `0 12 * * 0`
- 의미: 매주 일요일 21:00 KST
- Public domain: 불필요

API와 Cron 양쪽에 같은 Supabase 관련 Variables를 등록합니다. Railway Shared Variables로 만들면 중복 입력을 피할 수 있습니다.

Cron 작업은 학습을 마치고 자동 종료됩니다.

## 프론트 연결

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

