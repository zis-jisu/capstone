import json
import os
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client


# ============================================================
# 1. 기본 설정
# ============================================================

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"

load_dotenv(BASE_DIR / ".env")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError(
        "SUPABASE_URL 또는 SUPABASE_KEY가 .env에 없습니다."
    )

supabase = create_client(
    SUPABASE_URL,
    SUPABASE_KEY
)


# ============================================================
# 2. JSON 읽기
# ============================================================

def load_json(filename):
    path = DATA_DIR / filename

    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


persons_data = load_json("persons.json")
events_data = load_json("events.json")
tasks_data = load_json("tasks.json")
works_data = load_json("works.json")


# ============================================================
# 3. Person 저장
# ============================================================

def save_persons():

    print("\n[Person 저장]")

    for person in persons_data["people"]:

        row = {
            "person_id": person["person_id"],
            "name": person["name"],
            "aliases": person.get("aliases", [])
        }

        supabase.table("persons").upsert(
            row,
            on_conflict="person_id"
        ).execute()

        print(
            f"  {person['person_id']} "
            f"{person['name']}"
        )


# ============================================================
# 4. Event 저장
# ============================================================

def save_events():

    print("\n[Event 저장]")

    for event in events_data["events"]:

        row = {
            "event_id": event["event_id"],
            "source_id": event["source_id"],

            "speaker": event.get("speaker"),
            "speaker_id": event.get("speaker_id"),

            "slack_ts": event.get("slack_ts"),
            "conversation_id": event.get(
                "conversation_id"
            ),
            "conversation_type": event.get(
                "conversation_type"
            ),
            "parent_ts": event.get("parent_ts"),
            "slack_user_id": event.get(
                "slack_user_id"
            ),

            "subject": event.get("subject"),

            "actor": event.get("actor"),
            "actor_id": event.get("actor_id"),

            "related_people": event.get(
                "related_people", []
            ),

            "action": event.get("action"),

            "recipient": event.get("recipient"),
            "recipient_id": event.get(
                "recipient_id"
            ),

            "event_type": event.get("event_type"),
            "status": event.get("status"),
            "time_scope": event.get("time_scope"),

            "deadline_text": event.get(
                "deadline_text"
            ),

            "prerequisite": event.get(
                "prerequisite"
            ),

            "constraint_text": event.get(
                "constraint"
            ),

            "certainty": event.get("certainty"),
            "evidence": event.get("evidence"),

            "rule_corrections": event.get(
                "rule_corrections", []
            ),

            "validation_errors": event.get(
                "validation_errors", []
            )
        }

        supabase.table("events").upsert(
            row,
            on_conflict="event_id"
        ).execute()

        print(
            f"  {event['event_id']} "
            f"{event.get('action')}"
        )


# ============================================================
# 5. Task 저장
# ============================================================

def save_tasks():

    print("\n[Task 저장]")

    for task in tasks_data["tasks"]:

        deadline = task.get("deadline") or {}

        row = {
            "task_id": task["task_id"],
            "title": task["title"],
            "subject": task.get("subject"),
            "status": task.get("status"),

            "deadline_text": deadline.get("text"),
            "deadline_at": deadline.get("at"),

            "next_action": task.get("next_action"),
            "certainty": task.get("certainty")
        }

        supabase.table("tasks").upsert(
            row,
            on_conflict="task_id"
        ).execute()

        print(
            f"  {task['task_id']} "
            f"{task['title']}"
        )


# ============================================================
# 6. Work 저장
# ============================================================

def save_works():

    print("\n[Work 저장]")

    for work in works_data["works"]:

        row = {
            "work_id": work["work_id"],
            "title": work["title"],
            "certainty": work.get("certainty")
        }

        supabase.table("works").upsert(
            row,
            on_conflict="work_id"
        ).execute()

        print(
            f"  {work['work_id']} "
            f"{work['title']}"
        )


# ============================================================
# 7. Edge 저장 함수
# ============================================================

def save_edge(
    source_id,
    source_type,
    relation,
    target_id,
    target_type,
    role=None,
    evidence_event_ids=None
):

    row = {
        "source_id": source_id,
        "source_type": source_type,
        "relation": relation.upper(),
        "target_id": target_id,
        "target_type": target_type,
        "role": role,
        "evidence_event_ids":
            evidence_event_ids or []
    }

    supabase.table("edges").upsert(
        row,
        on_conflict="source_id,relation,target_id"
    ).execute()


# ============================================================
# 8. Task → Graph Edge 변환
# ============================================================

def build_task_edges():

    print("\n[Task Edge 생성]")

    for task in tasks_data["tasks"]:

        task_id = task["task_id"]

        # ------------------------------------
        # Person → Task
        # ------------------------------------

        for participant in task.get(
            "participants", []
        ):

            person_id = participant.get(
                "person_id"
            )

            if not person_id:
                continue

            event_ids = participant.get(
                "event_ids", []
            )

            for role in participant.get(
                "roles", []
            ):

                save_edge(
                    source_id=person_id,
                    source_type="Person",
                    relation=role,
                    target_id=task_id,
                    target_type="Task",
                    role=role,
                    evidence_event_ids=event_ids
                )

                print(
                    f"  {person_id} "
                    f"-[{role.upper()}]-> "
                    f"{task_id}"
                )

        # ------------------------------------
        # Task → Event
        # ------------------------------------

        for event_ref in task.get(
            "events", []
        ):

            event_id = event_ref["event_id"]
            event_role = event_ref.get("role")

            save_edge(
                source_id=task_id,
                source_type="Task",
                relation="HAS_EVENT",
                target_id=event_id,
                target_type="Event",
                role=event_role
            )

            print(
                f"  {task_id} "
                f"-[HAS_EVENT]-> "
                f"{event_id}"
            )

        # ------------------------------------
        # Task → Task
        # ------------------------------------

        for link in task.get(
            "task_links", []
        ):

            target_task_id = link["task_id"]
            relation = link["relation"]

            save_edge(
                source_id=task_id,
                source_type="Task",
                relation=relation,
                target_id=target_task_id,
                target_type="Task"
            )

            print(
                f"  {task_id} "
                f"-[{relation.upper()}]-> "
                f"{target_task_id}"
            )


# ============================================================
# 9. Work → Task Edge
# ============================================================

def build_work_edges():

    print("\n[Work Edge 생성]")

    for work in works_data["works"]:

        work_id = work["work_id"]

        for task_ref in work.get(
            "tasks", []
        ):

            task_id = task_ref["task_id"]
            task_role = task_ref.get("role")

            save_edge(
                source_id=work_id,
                source_type="Work",
                relation="HAS_TASK",
                target_id=task_id,
                target_type="Task",
                role=task_role
            )

            print(
                f"  {work_id} "
                f"-[HAS_TASK]-> "
                f"{task_id}"
            )


# ============================================================
# 10. 실행
# ============================================================

def main():

    print("==============================")
    print(" WorkGap Graph Builder 시작")
    print("==============================")

    save_persons()
    save_events()
    save_tasks()
    save_works()

    build_task_edges()
    build_work_edges()

    print("\n==============================")
    print(" Graph Builder 완료")
    print("==============================")


if __name__ == "__main__":
    main()