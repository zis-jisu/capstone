# 업무 Agent 1단계: 프론트 업무 데이터 기반 답변

## 적용 파일
- `frontend/index.html`: 기존 `fakeAsk()`를 `sendAgentQuestion()`로 교체. 현재 `TASKS`에서 업무명, 상태, risk 점수, 마감, 다음 행동, blocker 등을 API에 전달.
- `src/agent_chat.py`: `POST /api/chat`에서 전달받은 데이터만 근거로 LLM 답변 생성.
- `src/frontend_api.py`: API 라우터 등록.

## 실행
기존 백엔드 의존성 설치 후 환경변수 `OPENAI_API_KEY` 설정.
`AGENT_MODEL`은 선택적이며 기본값은 `gpt-6`.
```bash
python -m uvicorn src.frontend_api:app --host 127.0.0.1 --port 8000
```
기존 프론트 정적 파일도 **같은 오리진**으로 제공하거나 /api/chat 프록시를 구성해야 함. 단순히 HTML 파일만 열면 /api/chat 요청은 동작하지 않음.

## 현재 범위 및 제한
- **1단계 데모**: 프론트 업무 데이터만 이용. Slack 원문 검색, 벡터 검색, DB 조회는 **미구현**.
- `TASKS` 기본값은 데모 데이터. 통합 어댑터가 교체한 실제 업무 데이터가 있다면 매핑 확인 필요.
- 브라우저가 보내는 업무 데이터는 변조 가능. 인증된 사용자 기준 DB 조회 및 업무 접근권한 검증이 구현되기 전까지 실제 사내 데이터로 공개 서비스 금지.
- LLM API 키는 서버 환경변수에만 저장.
- 모델 응답과 실제 통합 동작은 아직 실행 검증하지 않음.

## 2단계 예정
- 로그인 사용자 인증 및 인수인계 권한 검사
- Graph Task/Event/Slack 원문 ID 매핑
- Supabase 원문 검색 및 출처 반환
- 근거 부족 시 답변 보류, 우선순위 근거와 메시지 타임스탬프 표시

## 독립 개발: Graph 연계 원문 검색
- `src/agent_retrieval.py`: Task → HAS_EVENT → Event.source_id → slack_messages.message_id 조회; Work는 역방향 HAS_TASK로 조회.
- `tests/test_agent_retrieval.py`: 가짜 저장소 기반 오프라인 단위 테스트(아직 실행 검증 전).
- 검색 함수는 API에 **아직 연결하지 않음**. 호출 전에 서버 측 로그인 사용자와 해당 Task의 접근 권한을 검증해야 함.
- 실제 DB에서 `slack_messages` 테이블과 `source_id` 매핑이 유효한지 조회 테스트 필요.
