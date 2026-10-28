# AI Capstone - Slack 업무 추출 파이프라인

Slack -> Event -> Task -> Work 추출과 현재 Supabase DB 연결 코드입니다.

## 구조

- `src/slack/collector.py`: Slack 데이터를 초기 수집/복구용으로 수집
- `src/luna_api.py`: GPT-5.6 Luna Responses API 공통 호출부
- `prompts/event_extraction.md`: Slack Message -> Event
- `prompts/event_to_task.md`: Event -> Task
- `prompts/task_to_work.md`: Task -> Work
- `docs/pipeline-contract.md`: 최신 데이터/ID/업데이트 규칙
- `evaluation/evaluate_grouping.py`: Gold 대비 Task/Work grouping Precision, Recall, F1

## 핵심 원칙

1. 최종 목표는 실시간 동기화다. 메시지 처리 진입점을 제공하며 웹훅/worker 연결은 별도 구현한다.
2. 모델 입력에는 Gold Task/Work 이름, Gold ID, 정답 관계를 넣지 않는다.
3. 원문에 Task/Work 이름이 명시되면 우선 사용하고, 없으면 맥락에서 생성한다.
4. 같은 논리적 Task/Work는 이후 실행에서도 기존 ID를 유지한다.
5. Slack 메시지 수정은 기존 Event 업데이트로 처리한다.
6. Task 상태 변경은 같은 task_id를 유지하고 status_history에 기록한다.
7. 사람은 slack_id + name을 함께 저장하고 동일인 판정은 slack_id 기준으로 한다.
8. deadline은 원문 표현과 한국 시간 ISO 8601 날짜·시간을 보존한다. 시간이 없으면 임의 생성하지 않는다.

과거 실험 예시, 수동 Luna 결과, 가상환경, pycache, 특정 case 전용 생성 스크립트는 백업 브랜치
`backup/pre-cleanup-event-extraction-20260926`에 보존되어 있습니다.

## Supabase 연결

[DB 통합 실행 가이드](docs/db-integration.md)를 참고하세요.

```bash
python scripts/sync_slack.py --input messages.json --out handover_runs/run.json
python scripts/sync_slack.py --apply-plan handover_runs/run.json
python -m unittest discover -s tests -v
```

저장 계획을 만들고, 동일 계획을 적용해 저장 후 검증·DB 기반 graph.json 생성까지 수행합니다.
현재 DB의 가상 Person ID와 실제 Slack ID가 충돌하면 적용을 멈춥니다.
