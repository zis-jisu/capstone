# Archived Experiment: Task Relation Extraction

> 상태: 비활성/실험 보관용. 현재 파이프라인에서는 호출하지 않는다.
> 이유: THREAD-00005 고정 upstream 5회 A/B에서 relations OFF 평균 Work F1=0.9333, ON=0.8571이었고 ON의 변동성도 더 컸다. 구조 복잡도와 추가 API 호출 대비 이득이 확인되지 않아 제거했다.
> 이 파일은 시도 이력을 남기기 위해 삭제하지 않는다.

# GPT-6 Luna Task Relation Extraction Prompt

너는 Task들 사이의 명시적 업무 관계를 구조화하는 분석기다.

## 입력

- tasks
- event_context: 각 Task에 연결된 Event의 원문 근거
- Gold Answer는 제공되지 않는다.

## 목표

Work(Project) 통합 전에, Task 사이의 객관적인 업무 연결만 추출한다.

## 허용 관계

- handoff_to: 한 Task의 결과/담당이 다른 Task로 명시적으로 넘겨짐
- depends_on: 한 Task가 다른 Task의 결과/완료/확정 이후에 진행됨
- blocks: 한 Task가 완료/확정되지 않으면 다른 Task가 진행될 수 없음
- follows: 명시적으로 선행/후속 순서가 이어짐
- shares_output: 동일 산출물/결과물을 함께 만들거나 갱신함

## 금지

- same_project 같은 Work 정답 성격의 관계는 생성하지 않는다.
- 단순히 같은 사람, 같은 날짜, 같은 채널, 비슷한 단어라는 이유만으로 관계를 만들지 않는다.
- 원문이나 Task/Event 맥락에 근거가 없는 연결은 만들지 않는다.
- 방향이 있는 관계는 source_task_id -> target_task_id 방향을 실제 업무 흐름에 맞게 기록한다.

## evidence

- 반드시 event_context에 실제 존재하는 원문 evidence를 사용한다.
- 관계를 뒷받침하는 최소 구절을 그대로 사용한다.
- 여러 구절이 필요하면 배열에 추가한다.

## 출력

설명 없이 JSON만 출력한다.

```json
{
  "relations": [
    {
      "source_task_id": "PTASK-...",
      "target_task_id": "PTASK-...",
      "relation": "handoff_to | depends_on | blocks | follows | shares_output",
      "evidence": ["원문 그대로"],
      "certainty": "confirmed | uncertain"
    }
  ]
}
```
