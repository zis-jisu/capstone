import json

import os

from collections import Counter



from dotenv import load_dotenv

from supabase import create_client





# =========================================================
# 1. 환경변수 로드
# =========================================================
load_dotenv()



SUPABASE_URL = os.getenv("SUPABASE_URL")

SUPABASE_KEY = os.getenv("SUPABASE_KEY")



if not SUPABASE_URL:

    raise ValueError("SUPABASE_URL이 .env에 없습니다.")



if not SUPABASE_KEY:

    raise ValueError("SUPABASE_KEY가 .env에 없습니다.")





# =========================================================
# 2. 설정
# =========================================================
JSON_FILE = "synthetic_graph.json"



VALID_NODE_TYPES = {

    "Person",

    "Task",

    "Work",

    "Event",

}





ROLE_TO_RELATION = {

    # Person -> Task
    "owner": "OWNER",

    "approver": "APPROVER",

    "reviewer": "REVIEWER",

    "collaborator": "COLLABORATOR",

    "related": "RELATED",



    # Person -> Event roles are handled by normalized event relations.
    # NOTE: current PARTICIPATES_IN requester/recipient edges are Person -> Task,
    # so they are intentionally excluded under the final ML schema.

}





VALID_RELATIONS = {

    # Work -> Task
    "HAS_TASK",



    # Task -> Event
    "HAS_EVENT",



    # Person -> Task
    "OWNER",

    "APPROVER",

    "REVIEWER",

    "COLLABORATOR",

    "RELATED",



    # Person -> Event
    "ACTOR",

    "REQUESTER",



    # Event -> Event
    "DEPENDS_ON",

}





ALLOWED_RELATION_TYPES = {

    # Work -> Task
    "HAS_TASK": {

        ("Work", "Task"),

    },



    # Task -> Event
    "HAS_EVENT": {

        ("Task", "Event"),

    },



    # Person -> Task
    "OWNER": {

        ("Person", "Task"),

    },



    "APPROVER": {

        ("Person", "Task"),

    },



    "REVIEWER": {

        ("Person", "Task"),

    },



    "COLLABORATOR": {

        ("Person", "Task"),

    },



    # Person -> Task / Person -> Event
    "RELATED": {

        ("Person", "Task"),

        ("Person", "Event"),

    },



    # Person -> Event
    "ACTOR": {

        ("Person", "Event"),

    },



    "REQUESTER": {

        ("Person", "Event"),

    },



    # Event -> Event
    "DEPENDS_ON": {

        ("Event", "Event"),

    },

}



EXPECTED_NODE_COUNT = 492

# Current synthetic_graph.json after conversion to the final ML schema.
EXPECTED_EDGE_COUNT = 1766

EXPECTED_RELATION_COUNTS = {
    "OWNER": 104,
    "APPROVER": 12,
    "REVIEWER": 104,
    "COLLABORATOR": 182,
    "RELATED": 480,      # Person->Task 26 + Person->Event 454
    "ACTOR": 312,
    "REQUESTER": 0,     # no valid Person->Event requester edge in current synthetic data
    "HAS_EVENT": 312,
    "DEPENDS_ON": 156,  # Event->Event only
    "HAS_TASK": 104,
}


BATCH_SIZE = 500





# =========================================================
# 3. Supabase 연결
# =========================================================
print("1. Supabase 연결 중...")



supabase = create_client(

    SUPABASE_URL,

    SUPABASE_KEY

)



print("   연결 객체 생성 완료")





# =========================================================
# 4. Synthetic Graph JSON 읽기
# =========================================================
print("\n2. Synthetic Graph JSON 읽는 중...")



if not os.path.exists(JSON_FILE):

    raise FileNotFoundError(

        f"{JSON_FILE} 파일을 찾을 수 없습니다.\n"

        f"현재 실행 폴더: {os.getcwd()}"

    )



with open(JSON_FILE, "r", encoding="utf-8") as f:

    graph = json.load(f)



nodes = graph.get("nodes", [])

edges = graph.get("edges", [])



print(f"   원본 Node : {len(nodes)}개")

print(f"   원본 Edge : {len(edges)}개")





# =========================================================
# 5. Node Type Map 생성
# =========================================================
node_type_map = {}



for node in nodes:



    node_id = node.get("id")

    node_type = node.get("type")



    if not node_id:

        raise ValueError(

            f"ID가 없는 Node 발견: {node}"

        )



    if node_id in node_type_map:

        raise ValueError(

            f"중복 Node ID 발견: {node_id}"

        )



    node_type_map[node_id] = node_type





# =========================================================
# 6. Node 분류 및 Supabase 형식으로 변환
# =========================================================
print("\n3. ML 입력용 Node 분류 중...")



persons = []

tasks = []

works = []

events = []



excluded_nodes = []





for node in nodes:



    node_type = node.get("type")

    node_id = node.get("id")



    # -----------------------------------------------------
    # 이번 ML 그래프에서 사용하지 않는 Node 제외
    # Team / CustomerTeam / Organization
    # -----------------------------------------------------
    if node_type not in VALID_NODE_TYPES:



        excluded_nodes.append(node)

        continue



    # -----------------------------------------------------
    # Person
    # -----------------------------------------------------
    if node_type == "Person":



        persons.append({

            "person_id": node_id,

            "name": node.get("name"),

            "aliases": node.get("aliases", [])

        })



    # -----------------------------------------------------
    # Task
    #
    # Synthetic Graph:
    # name
    #
    # Supabase:
    # title
    # -----------------------------------------------------
    elif node_type == "Task":



        tasks.append({

            "task_id": node_id,



            "title": (

                node.get("title")

                or node.get("name")

            ),



            "subject": node.get("subject"),



            "status": node.get("status"),



            "deadline_text": (

                node.get("deadline_text")

            ),



            "deadline_at": (

                node.get("deadline_at")

                or node.get("due_at")

            ),



            "next_action": (

                node.get("next_action")

            ),



            "certainty": (

                node.get("certainty")

            )

        })



    # -----------------------------------------------------
    # Work
    #
    # Synthetic Graph:
    # name
    #
    # Supabase:
    # title
    # -----------------------------------------------------
    elif node_type == "Work":



        works.append({

            "work_id": node_id,



            "title": (

                node.get("title")

                or node.get("name")

            ),



            "certainty": (

                node.get("certainty")

            )

        })



    # -----------------------------------------------------
    # Event
    # -----------------------------------------------------
    elif node_type == "Event":

        # Synthetic Graph의 evidence_message_ids 첫 값을
        # 기존 Supabase source_id와 호환되도록 사용한다.
        evidence_message_ids = node.get(
            "evidence_message_ids",
            []
        )

        source_id = node.get("source_id")

        if not source_id and evidence_message_ids:
            source_id = evidence_message_ids[0]

        events.append({
            "event_id": node_id,

            "source_id": source_id,

            "speaker": node.get("speaker"),

            "speaker_id": node.get("speaker_id"),

            "slack_ts": node.get("slack_ts"),

            "subject": node.get("subject"),

            "actor": node.get("actor"),

            "actor_id": node.get("actor_id"),

            "related_people": node.get(
                "related_people",
                []
            ),

            "action": node.get("action"),

            "recipient": node.get("recipient"),

            "recipient_id": node.get("recipient_id"),

            "event_type": node.get("event_type"),

            "status": node.get("status"),

            "time_scope": node.get("time_scope"),

            "deadline_text": node.get("deadline_text"),

            # 새 Event 스키마
            "due_at": (
                node.get("due_at")
                or node.get("deadline_at")
            ),

            # prerequisite는 Event 컬럼으로 저장하지 않는다.
            # Event -> Event DEPENDS_ON Edge로 표현한다.

            # 기존 synthetic_graph.json의 constraint와
            # 이전 constraint_text 모두 새 memo 필드로 호환한다.
            "memo": (
                node.get("memo")
                or node.get("constraint_text")
                or node.get("constraint")
            ),

            "certainty": node.get("certainty"),

            "evidence": node.get("evidence"),

            # 기존 reference_url도 새 reference 필드로 호환한다.
            "reference": (
                node.get("reference")
                or node.get("reference_url")
            ),

            "rule_corrections": node.get(
                "rule_corrections",
                []
            ),

            "validation_errors": node.get(
                "validation_errors",
                []
            )
        })


# =========================================================
# 7. Node 개수 출력
# =========================================================
print(f"   Person : {len(persons)}개")

print(f"   Task   : {len(tasks)}개")

print(f"   Work   : {len(works)}개")

print(f"   Event  : {len(events)}개")



valid_node_count = (

    len(persons)

    + len(tasks)

    + len(works)

    + len(events)

)



print("   --------------------")

print(

    f"   ML Node 총합 : "

    f"{valid_node_count}개"

)





# =========================================================
# 8. Node 필수 필드 검증
# =========================================================
print("\n4. Node 필수 필드 검증 중...")



node_errors = []





# ---------------------------------------------------------
# Person 검증
# ---------------------------------------------------------
for person in persons:



    if not person.get("person_id"):



        node_errors.append(

            "Person ID 없음"

        )



    if not person.get("name"):



        node_errors.append(

            f"{person.get('person_id')}: "

            f"Person name 없음"

        )





# ---------------------------------------------------------
# Task 검증
# ---------------------------------------------------------
for task in tasks:



    if not task.get("task_id"):



        node_errors.append(

            "Task ID 없음"

        )



    if not task.get("title"):



        node_errors.append(

            f"{task.get('task_id')}: "

            f"Task title 없음"

        )





# ---------------------------------------------------------
# Work 검증
# ---------------------------------------------------------
for work in works:



    if not work.get("work_id"):



        node_errors.append(

            "Work ID 없음"

        )



    if not work.get("title"):



        node_errors.append(

            f"{work.get('work_id')}: "

            f"Work title 없음"

        )





# ---------------------------------------------------------
# Event 검증
# ---------------------------------------------------------
for event in events:



    if not event.get("event_id"):



        node_errors.append(

            "Event ID 없음"

        )



    if not event.get("source_id"):



        node_errors.append(

            f"{event.get('event_id')}: "

            f"Event source_id 없음"

        )





# ---------------------------------------------------------
# 오류가 있으면 DB 저장 전에 중단
# ---------------------------------------------------------
if node_errors:



    print(

        f"   Node 필수 필드 오류: "

        f"{len(node_errors)}개"

    )



    for error in node_errors[:20]:

        print(f"   - {error}")



    raise SystemExit(1)





print("   Person name 검증 통과")

print("   Task title 검증 통과")

print("   Work title 검증 통과")

print("   Event source_id 검증 통과")





# =========================================================
# 9. 제외 Node 확인
# =========================================================
excluded_node_type_count = Counter(

    node.get("type", "UNKNOWN")

    for node in excluded_nodes

)



print(

    "\n5. ML 입력에서 제외되는 Node"

)



if excluded_node_type_count:



    for (

        node_type,

        count

    ) in excluded_node_type_count.items():



        print(

            f"   {node_type:<20}: "

            f"{count}개"

        )



else:



    print("   없음")





# =========================================================
# 10. Edge 변환
# =========================================================
print(

    "\n6. ML 입력용 Edge 변환 중..."

)



db_edges = []



excluded_edges = []

invalid_edges = []



relation_count = Counter()





for edge in edges:



    source_id = (

        edge.get("source_id")

        or edge.get("source")

    )



    target_id = (

        edge.get("target_id")

        or edge.get("target")

    )



    original_relation = (

        edge.get("relation")

    )



    # -----------------------------------------------------
    # 기본 필드 확인
    # -----------------------------------------------------
    if (

        not source_id

        or not target_id

        or not original_relation

    ):



        invalid_edges.append({

            "reason": "MISSING_FIELD",

            "edge": edge

        })



        continue



    # -----------------------------------------------------
    # Source Node 확인
    # -----------------------------------------------------
    if source_id not in node_type_map:



        invalid_edges.append({

            "reason":

                "SOURCE_NODE_NOT_FOUND",

            "edge": edge

        })



        continue



    # -----------------------------------------------------
    # Target Node 확인
    # -----------------------------------------------------
    if target_id not in node_type_map:



        invalid_edges.append({

            "reason":

                "TARGET_NODE_NOT_FOUND",

            "edge": edge

        })



        continue



    source_type = (

        node_type_map[source_id]

    )



    target_type = (

        node_type_map[target_id]

    )



    # =====================================================
    # A. PARTICIPATES_IN
    #
    # role 값을 실제 Relation으로 변환
    # =====================================================
    if (

        original_relation

        == "PARTICIPATES_IN"

    ):



        role = edge.get("role")



        if not role:



            invalid_edges.append({

                "reason":

                    "PARTICIPATES_IN_ROLE_MISSING",

                "edge": edge

            })



            continue



        role = role.lower()



        if role not in ROLE_TO_RELATION:

            excluded_edges.append({
                "reason": f"ROLE_NOT_USED_FOR_ML:{role}",
                "edge": edge
            })

            continue



        relation = (

            ROLE_TO_RELATION[role]

        )



    # =====================================================
    # B. HAS_EVENT
    # =====================================================
    elif (

        original_relation

        == "HAS_EVENT"

    ):



        relation = "HAS_EVENT"



    # =====================================================
    # C. Event participant relations
    #
    # Synthetic source names -> final ML relation names
    # ACTOR_OF         : Person -> Event => ACTOR
    # RELATED_TO_EVENT : Person -> Event => RELATED
    # Direct normalized ACTOR / REQUESTER / RELATED edges are also accepted.
    # RECIPIENT_OF is intentionally excluded because RECIPIENT is not
    # part of the final ML relation schema.
    # =====================================================
    elif original_relation == "ACTOR_OF":
        relation = "ACTOR"

    elif original_relation == "RELATED_TO_EVENT":
        relation = "RELATED"

    elif original_relation in {"ACTOR", "REQUESTER", "RELATED"}:
        relation = original_relation


    # =====================================================
    # D. DEPENDS_ON
    #
    # 새 ML 그래프에서는 Event -> Event만 사용
    # Task -> Task DEPENDS_ON은 제외
    # =====================================================

    elif original_relation == "DEPENDS_ON":

        if (
            source_type == "Event"
            and target_type == "Event"
        ):
            relation = "DEPENDS_ON"

        else:
            excluded_edges.append({
                "reason": "NON_EVENT_DEPENDS_ON",
                "edge": edge
            })
            continue


    # =====================================================
    # E. HAS_TASK
    # =====================================================
    elif (

        original_relation

        == "HAS_TASK"

    ):



        relation = "HAS_TASK"



    # =====================================================
    # F. 그 외 Relation은 ML 입력에서 제외
    # =====================================================
    else:



        excluded_edges.append({

            "reason":

                f"NOT_USED_FOR_ML:"

                f"{original_relation}",

            "edge": edge

        })



        continue



    # =====================================================
    # 최종 Relation 검증
    # =====================================================
    if relation not in VALID_RELATIONS:



        invalid_edges.append({

            "reason":

                f"UNKNOWN_FINAL_RELATION:"

                f"{relation}",

            "edge": edge

        })



        continue



    actual_type_pair = (
        source_type,
        target_type
    )

    allowed_type_pairs = ALLOWED_RELATION_TYPES[relation]

    if actual_type_pair not in allowed_type_pairs:

        invalid_edges.append({
            "reason": (
                f"TYPE_MISMATCH:"
                f"{source_type}"
                f"-[{relation}]->"
                f"{target_type}"
            ),
            "edge": edge
        })

        continue


    # =====================================================
    # 정상 Edge
    # =====================================================
    db_edges.append({

        "source_id": source_id,

        "source_type": source_type,

        "relation": relation,

        "target_id": target_id,

        "target_type": target_type

    })



    relation_count[relation] += 1





# =========================================================
# 11. Edge 결과 출력
# =========================================================
print(

    f"   ML 사용 Edge : "

    f"{len(db_edges)}개"

)



print(

    f"   의도적 제외 Edge : "

    f"{len(excluded_edges)}개"

)



print(

    f"   실제 오류 Edge : "

    f"{len(invalid_edges)}개"

)





print(

    "\n7. 최종 Relation별 Edge 수"

)



for (

    relation,

    count

) in relation_count.most_common():



    print(

        f"   {relation:<20}: "

        f"{count}개"

    )





# =========================================================
# 12. Import 전 최종 검증
# =========================================================
print(

    "\n8. Import 전 최종 검증 중..."

)





# ---------------------------------------------------------
# 실제 오류 Edge 검증
# ---------------------------------------------------------
if invalid_edges:



    print(

        "\n[중단] 실제 오류 Edge가 "

        "발견되었습니다."

    )



    for item in invalid_edges[:10]:



        print(

            item["reason"],

            "->",

            item["edge"]

        )



    raise SystemExit(1)





# ---------------------------------------------------------
# Node 개수 검증
# ---------------------------------------------------------
if (

    valid_node_count

    != EXPECTED_NODE_COUNT

):



    print(

        f"\n[중단] 예상 Node 수와 "

        f"다릅니다.\n"

        f"예상: {EXPECTED_NODE_COUNT}\n"

        f"실제: {valid_node_count}"

    )



    raise SystemExit(1)





# ---------------------------------------------------------
# Edge 개수 검증
# ---------------------------------------------------------
if (

    len(db_edges)

    != EXPECTED_EDGE_COUNT

):



    print(

        f"\n[중단] 예상 Edge 수와 "

        f"다릅니다.\n"

        f"예상: {EXPECTED_EDGE_COUNT}\n"

        f"실제: {len(db_edges)}"

    )



    raise SystemExit(1)





# ---------------------------------------------------------
# Relation별 개수 검증
# ---------------------------------------------------------
for (

    relation,

    expected_count

) in EXPECTED_RELATION_COUNTS.items():



    actual_count = (

        relation_count.get(

            relation,

            0

        )

    )



    if actual_count != expected_count:



        print(

            f"\n[중단] {relation} 개수가 "

            f"예상과 다릅니다.\n"

            f"예상: {expected_count}\n"

            f"실제: {actual_count}"

        )



        raise SystemExit(1)





print("   Node 검증 통과")

print("   Edge 검증 통과")

print("   Relation 검증 통과")



print(

    "\n   예상 최종 구조:"

)



print("   Node : 492")

print("   Edge : 1130")





# =========================================================
# 13. Supabase Upsert 함수
# =========================================================
def upsert_rows(

    table_name,

    rows,

    on_conflict

):



    if not rows:



        print(

            f"   {table_name}: "

            f"입력할 데이터 없음"

        )



        return



    print(

        f"   {table_name}: "

        f"{len(rows)}개 Upsert 중..."

    )



    for start in range(

        0,

        len(rows),

        BATCH_SIZE

    ):



        batch = rows[

            start:

            start + BATCH_SIZE

        ]



        supabase.table(

            table_name

        ).upsert(

            batch,

            on_conflict=on_conflict

        ).execute()



    print(

        f"   {table_name}: 완료"

    )





# =========================================================
# 14. Edge Insert 함수
# =========================================================
def insert_edges(rows):

    if not rows:
        print("   edges: 입력할 데이터 없음")
        return

    print(f"   edges: {len(rows)}개 Upsert 중...")

    for start in range(0, len(rows), BATCH_SIZE):
        batch = rows[start:start + BATCH_SIZE]

        supabase.table(
            "edges"
        ).upsert(
            batch,
            on_conflict="source_id,relation,target_id"
        ).execute()

    print("   edges: 완료")


def clear_existing_edges():

    print("\n10. 기존 Edge 초기화 중...")

    # source_id는 NOT NULL이므로 아래 조건은 현재 모든 edge row를 선택한다.
    supabase.table(
        "edges"
    ).delete().neq(
        "source_id",
        "__NEVER_MATCH_GRAPH_ID__"
    ).execute()

    print("   기존 edges 삭제 완료")


# =========================================================
# 15. Supabase Node 저장
# =========================================================
print(

    "\n9. Supabase에 Node 저장 중..."

)



upsert_rows(

    "persons",

    persons,

    "person_id"

)



upsert_rows(

    "works",

    works,

    "work_id"

)



upsert_rows(

    "tasks",

    tasks,

    "task_id"

)



upsert_rows(

    "events",

    events,

    "event_id"

)





# =========================================================
# 16. Edge 저장
# =========================================================
# relation 체계가 변경되었으므로 이전 Edge를 먼저 제거한다.
# 이후 composite PK (source_id, relation, target_id)를 기준으로
# 새 Edge를 Upsert한다.
clear_existing_edges()

print("\n10-1. Supabase에 새 Edge 저장 중...")

insert_edges(db_edges)


# =========================================================
# 17. DB 결과 확인
# =========================================================
print(

    "\n11. Supabase 저장 결과 확인 중..."

)





def get_count(

    table_name,

    column_name

):



    result = (

        supabase

        .table(table_name)

        .select(column_name)

        .execute()

    )



    return len(result.data)





person_count = get_count(

    "persons",

    "person_id"

)



task_count = get_count(

    "tasks",

    "task_id"

)



work_count = get_count(

    "works",

    "work_id"

)



event_count = get_count(

    "events",

    "event_id"

)



edge_count = get_count(

    "edges",

    "source_id"

)





# =========================================================
# 18. 최종 결과 출력
# =========================================================
print(

    "\n========================================"

)



print(

    "Synthetic Data Import 완료"

)



print(

    "========================================"

)



print(

    f"Person : {person_count}"

)



print(

    f"Task   : {task_count}"

)



print(

    f"Work   : {work_count}"

)



print(

    f"Event  : {event_count}"

)



print(

    "----------------------------------------"

)



print(

    f"Node   : "

    f"{person_count + task_count + work_count + event_count}"

)



print(

    f"Edge   : {edge_count}"

)





# =========================================================
# 19. 최종 성공 여부 확인
# =========================================================
if (

    person_count == 50

    and task_count == 104

    and work_count == 26

    and event_count == 312

    and edge_count == EXPECTED_EDGE_COUNT

):



    print(

        "\n[성공] 예상한 Synthetic Graph가 "

        "Supabase에 저장되었습니다."

    )



else:



    print(

        "\n[주의] 예상 개수와 "

        "DB 저장 결과가 다릅니다."

    )



    print(

        "기존 데이터가 남아 있거나 "

        "일부 저장이 실패했을 수 있습니다."

    )





# =========================================================
# 20. 다음 단계
# =========================================================
print(

    "\n다음 단계:"

)



print(

    "python export_graph.py"

)