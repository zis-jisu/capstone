# 업무 Agent 1단계: 프론트 업무 데이터 기반 답변

## 적용 범위

- `frontend/index.html`: `sendAgentQuestion()`이 선택된 실제 Task ID와 업무명, 상태, 마감일, ML 우선순위 점수/순위, 담당자, 다음 행동 및 화면에 로드된 업무 문맥을 `POST /api/chat`으로 전달한다.
- `src/agent_chat.py`: 전달받은 업무 문맥만 근거로 답하며, Slack 원문이나 서버 DB를 조회했다고 표현하지 않는다.
- `src/frontend_api.py`: Agent 라우터를 기존 FastAPI 앱에 등록한다.
- `src/luna_api.py`: 기존 `OPENAI_API_KEY`와 공통 모델 `gpt-6-luna`를 사용하는 텍스트 응답 호출을 제공한다.

## 실행과 인증

기존 백엔드 환경변수 `OPENAI_API_KEY`를 사용한다. API 키는 브라우저로 전달하지 않는다.

`/api/chat`은 다음 기존 인증 중 설정된 방식을 허용한다.

- `Authorization: Bearer <API_ACCESS_TOKEN>`
- Railway 데모의 `DEMO_USERNAME` / `DEMO_PASSWORD` HTTP Basic 인증

프론트와 API는 같은 오리진으로 제공하거나 `/api/chat` 프록시를 구성해야 한다.

## 현재 제한

- 브라우저가 전달하는 Task 문맥은 서버가 검증한 DB 사실이 아니다.
- `src/agent_retrieval.py`의 Task → Event → Slack 원문 검색은 읽기 전용으로 유지하지만 `/api/chat`에는 아직 연결하지 않는다.
- RAG를 연결하기 전 서버 측 사용자 인증과 Task 접근 권한 검사가 필요하다.
