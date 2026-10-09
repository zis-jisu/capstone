import json
import os
from collections import Counter

from dotenv import load_dotenv
from supabase import create_client


# ============================================================
# 1. 설정
# ============================================================

SOURCE_JSON_FILE = "synthetic_graph.json"
OUTPUT_FILE = "graph.json"

NODE_TYPE_TO_IDX = {
    "Person": 0,
    "Task": 1,
    "Work": 2,
    "Event": 3,
}

RELATION_TO_IDX = {
    "HAS_TASK": 0,
    "HAS_EVENT": 1,
    "OWNER": 2,
    "APPROVER": 3,
    "REVIEWER": 4,
    "COLLABORATOR": 5,
    "RELATED": 6,
    "ACTOR": 7,
    "REQUESTER": 8,
    "DEPENDS_ON": 9,
}

ALLOWED_RELATIONS = {
    "HAS_TASK": {("Work", "Task")},
    "HAS_EVENT": {("Task", "Event")},
    "OWNER": {("Person", "Task")},
    "APPROVER": {("Person", "Task")},
    "REVIEWER": {("Person", "Task")},
    "COLLABORATOR": {("Person", "Task")},
    "RELATED": {
        ("Person", "Task"),
        ("Person", "Event"),
    },
    "ACTOR": {("Person", "Event")},
    "REQUESTER": {("Person", "Event")},
    "DEPENDS_ON": {("Event", "Event")},
}

EXPECTED_NODE_COUNT = 492
EXPECTED_EDGE_COUNT = 1766

EXPECTED_RELATION_COUNTS = {
    "HAS_TASK": 104,
    "HAS_EVENT": 312,
    "OWNER": 104,
    "APPROVER": 12,
    "REVIEWER": 104,
    "COLLABORATOR": 182,
    "RELATED": 480,
    "ACTOR": 312,
    "REQUESTER": 0,
    "DEPENDS_ON": 156,
}


# ============================================================
# 2. Supabase 연결
# ============================================================

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL:
    raise ValueError("SUPABASE_URL이 .env에 없습니다.")

if not SUPABASE_KEY:
    raise ValueError("SUPABASE_KEY가 .env에 없습니다.")

print("1. Supabase 연결 중...")

supabase = create_client(
    SUPABASE_URL,
    SUPABASE_KEY
)

print("   연결 객체 생성 완료")


# ============================================================
# 3. 전체 행 조회
# ============================================================

def fetch_all_rows(table_name, page_size=500):
    all_rows = []
    start = 0

    while True:
        end = start + page_size - 1

        result = (
            supabase
            .table(table_name)
            .select("*")
            .range(start, end)
            .execute()
        )

        batch = result.data or []

        if not batch:
            break

        all_rows.extend(batch)

        print(
            f"   {table_name}: "
            f"{len(all_rows)}개 조회"
        )

        if len(batch) < page_size:
            break

        start += page_size

    return all_rows


# ============================================================
# 4. 원본 Synthetic JSON 읽기
# ============================================================

print("\n2. 원본 Synthetic Graph 읽는 중...")

with open(
    SOURCE_JSON_FILE,
    "r",
    encoding="utf-8"
) as f:
    source_graph = json.load(f)

source_nodes = source_graph.get("nodes", [])
source_edges = source_graph.get("edges", [])

print(f"   원본 Node : {len(source_nodes)}개")
print(f"   원본 Edge : {len(source_edges)}개")


# ============================================================
# 5. ML 전달용 Node 생성
#
# ML 담당자가 원하는 형식대로 원본 Node의 속성을 보존한다.
# Team / Organization / CustomerTeam은 제외한다.
# ============================================================

print("\n3. ML 전달용 Node 생성 중...")

nodes = [
    dict(node)
    for node in source_nodes
    if node.get("type") in NODE_TYPE_TO_IDX
]

node_id_to_node = {
    node["id"]: node
    for node in nodes
}

if len(node_id_to_node) != len(nodes):
    raise ValueError("중복 Node ID가 있습니다.")

node_id_to_type = {
    node_id: node["type"]
    for node_id, node in node_id_to_node.items()
}

node_id_to_idx = {
    node["id"]: idx
    for idx, node in enumerate(nodes)
}

node_type = [
    NODE_TYPE_TO_IDX[node["type"]]
    for node in nodes
]

node_type_count = Counter(
    node["type"]
    for node in nodes
)

for node_type_name in NODE_TYPE_TO_IDX:
    print(
        f"   {node_type_name:<6}: "
        f"{node_type_count.get(node_type_name, 0)}개"
    )

print(f"   전체 Node: {len(nodes)}개")

if len(nodes) != EXPECTED_NODE_COUNT:
    raise ValueError(
        f"Node 수가 {EXPECTED_NODE_COUNT}이 아닙니다. "
        f"실제={len(nodes)}"
    )


# ============================================================
# 6. Supabase 최종 Edge 조회
# ============================================================

print("\n4. Supabase 최종 Edge 조회 중...")

db_edges = fetch_all_rows("edges")

print(f"   조회 Edge: {len(db_edges)}개")

if len(db_edges) != EXPECTED_EDGE_COUNT:
    raise ValueError(
        f"Supabase Edge 수가 {EXPECTED_EDGE_COUNT}이 아닙니다. "
        f"실제={len(db_edges)}"
    )


# ============================================================
# 7. 원본 Edge -> 최종 Relation 변환
#
# 목적:
# Supabase에는 edge_id가 없으므로 원본 synthetic_graph.json의
# Edge와 최종 DB Edge를 연결하여 가능한 경우 원래 EDGE-xxxxx ID와
# evidence/dependency_scope/certainty 같은 속성을 복원한다.
# ============================================================

ROLE_TO_RELATION = {
    "owner": "OWNER",
    "approver": "APPROVER",
    "reviewer": "REVIEWER",
    "collaborator": "COLLABORATOR",
    "related": "RELATED",
}


def normalize_source_edge(edge):
    source = edge.get("source")
    target = edge.get("target")
    relation = edge.get("relation")

    source_type = node_id_to_type.get(source)
    target_type = node_id_to_type.get(target)

    if relation == "PARTICIPATES_IN":
        role = str(edge.get("role") or "").lower()

        # requester/recipient Person->Task는 최종 스키마에서 제외
        if (
            source_type == "Person"
            and target_type == "Task"
            and role in ROLE_TO_RELATION
        ):
            return (
                source,
                ROLE_TO_RELATION[role],
                target
            )

        return None

    if relation == "ACTOR_OF":
        if (
            source_type == "Person"
            and target_type == "Event"
        ):
            return (source, "ACTOR", target)

        return None

    if relation == "RELATED_TO_EVENT":
        if (
            source_type == "Person"
            and target_type == "Event"
        ):
            return (source, "RELATED", target)

        return None

    if relation == "DEPENDS_ON":
        # 최종 스키마는 Event -> Event만 사용
        if (
            source_type == "Event"
            and target_type == "Event"
        ):
            return (source, "DEPENDS_ON", target)

        return None

    if relation == "HAS_TASK":
        if (
            source_type == "Work"
            and target_type == "Task"
        ):
            return (source, "HAS_TASK", target)

        return None

    if relation == "HAS_EVENT":
        if (
            source_type == "Task"
            and target_type == "Event"
        ):
            return (source, "HAS_EVENT", target)

        return None

    return None


source_edge_lookup = {}

for edge in source_edges:
    key = normalize_source_edge(edge)

    if key is None:
        continue

    # 동일 최종 관계가 여러 번 존재할 경우 첫 원본 Edge를 대표로 사용
    if key not in source_edge_lookup:
        source_edge_lookup[key] = edge


# ============================================================
# 8. ML 전달용 Edge 생성
# ============================================================

print("\n5. ML 전달용 Edge 생성 중...")

edges = []
invalid_edges = []
relation_count = Counter()

edge_sources = []
edge_targets = []
edge_types = []

used_edge_ids = set()
generated_edge_number = 1

for db_edge in db_edges:
    source = db_edge["source_id"]
    target = db_edge["target_id"]
    relation = db_edge["relation"]

    source_type = db_edge["source_type"]
    target_type = db_edge["target_type"]

    # Relation 검사
    if relation not in RELATION_TO_IDX:
        invalid_edges.append({
            "edge": db_edge,
            "reason": "UNKNOWN_RELATION",
        })
        continue

    # Node 존재 검사
    if source not in node_id_to_idx:
        invalid_edges.append({
            "edge": db_edge,
            "reason": "SOURCE_NODE_NOT_FOUND",
        })
        continue

    if target not in node_id_to_idx:
        invalid_edges.append({
            "edge": db_edge,
            "reason": "TARGET_NODE_NOT_FOUND",
        })
        continue

    # DB type과 실제 Node type 일치 검사
    if node_id_to_type[source] != source_type:
        invalid_edges.append({
            "edge": db_edge,
            "reason": "SOURCE_TYPE_MISMATCH",
        })
        continue

    if node_id_to_type[target] != target_type:
        invalid_edges.append({
            "edge": db_edge,
            "reason": "TARGET_TYPE_MISMATCH",
        })
        continue

    actual_type_pair = (
        source_type,
        target_type
    )

    if (
        actual_type_pair
        not in ALLOWED_RELATIONS[relation]
    ):
        invalid_edges.append({
            "edge": db_edge,
            "reason": "INVALID_RELATION_TYPE_PAIR",
            "actual_type_pair": actual_type_pair,
        })
        continue

    key = (
        source,
        relation,
        target
    )

    original_edge = source_edge_lookup.get(key)

    # --------------------------------------------------------
    # Edge ID
    # --------------------------------------------------------
    if original_edge:
        edge_id = original_edge.get("id")

        if not edge_id:
            edge_id = (
                f"EDGE-ML-{generated_edge_number:05d}"
            )
            generated_edge_number += 1
    else:
        edge_id = (
            f"EDGE-ML-{generated_edge_number:05d}"
        )
        generated_edge_number += 1

    # 혹시 원본 데이터에 중복 ID가 있다면 안전하게 새 ID 부여
    if edge_id in used_edge_ids:
        edge_id = (
            f"EDGE-ML-{generated_edge_number:05d}"
        )
        generated_edge_number += 1

    used_edge_ids.add(edge_id)

    # --------------------------------------------------------
    # ML 담당자용 Edge
    # 기본 형식: id / source / target / relation
    # 원본에 존재했던 의미 속성은 함께 보존
    # --------------------------------------------------------
    export_edge = {
        "id": edge_id,
        "source": source,
        "target": target,
        "relation": relation,
    }

    if original_edge:
        # graph 연결에 불필요한 내부 필드는 제외하고
        # evidence/확신도/dependency scope 등은 보존한다.
        for key_name, value in original_edge.items():
            if key_name in {
                "id",
                "source",
                "target",
                "relation",
                "role",
            }:
                continue

            if value is not None:
                export_edge[key_name] = value

    # DEPENDS_ON은 Event dependency임을 명시
    if (
        relation == "DEPENDS_ON"
        and "dependency_scope" not in export_edge
    ):
        export_edge["dependency_scope"] = "event"

    edges.append(export_edge)

    relation_count[relation] += 1

    edge_sources.append(
        node_id_to_idx[source]
    )

    edge_targets.append(
        node_id_to_idx[target]
    )

    edge_types.append(
        RELATION_TO_IDX[relation]
    )


# ============================================================
# 9. Edge 검증
# ============================================================

print(f"   정상 Edge: {len(edges)}개")
print(f"   오류 Edge: {len(invalid_edges)}개")

if invalid_edges:
    print("\n[중단] 잘못된 Edge가 있습니다.")

    for item in invalid_edges[:20]:
        print(
            f"   - {item['reason']}: "
            f"{item['edge']}"
        )

    raise SystemExit(1)

if len(edges) != EXPECTED_EDGE_COUNT:
    raise ValueError(
        f"최종 Edge 수가 {EXPECTED_EDGE_COUNT}이 아닙니다. "
        f"실제={len(edges)}"
    )

if len(used_edge_ids) != len(edges):
    raise ValueError("중복 Edge ID가 있습니다.")


# ============================================================
# 10. Relation별 개수 검증
# ============================================================

print("\n6. Relation별 Edge 수")

relation_errors = []

for relation in RELATION_TO_IDX:
    actual = relation_count.get(
        relation,
        0
    )

    expected = EXPECTED_RELATION_COUNTS[
        relation
    ]

    print(
        f"   {relation:<14}: "
        f"{actual}개"
    )

    if actual != expected:
        relation_errors.append(
            f"{relation}: "
            f"예상 {expected}, 실제 {actual}"
        )

if relation_errors:
    print(
        "\n[중단] Relation 개수가 "
        "예상값과 다릅니다."
    )

    for error in relation_errors:
        print(f"   - {error}")

    raise SystemExit(1)


# ============================================================
# 11. R-GCN Tensor 검증
# ============================================================

print("\n7. R-GCN Tensor 검증 중...")

if len(edge_sources) != EXPECTED_EDGE_COUNT:
    raise ValueError("edge_sources 길이 오류")

if len(edge_targets) != EXPECTED_EDGE_COUNT:
    raise ValueError("edge_targets 길이 오류")

if len(edge_types) != EXPECTED_EDGE_COUNT:
    raise ValueError("edge_types 길이 오류")

if len(node_type) != EXPECTED_NODE_COUNT:
    raise ValueError("node_type 길이 오류")

if edge_sources + edge_targets:
    min_node_idx = min(
        edge_sources + edge_targets
    )
    max_node_idx = max(
        edge_sources + edge_targets
    )

    if min_node_idx < 0:
        raise ValueError("음수 Node index가 있습니다.")

    if max_node_idx >= EXPECTED_NODE_COUNT:
        raise ValueError(
            "Node index 범위를 벗어난 Edge가 있습니다."
        )

if edge_types:
    if min(edge_types) < 0:
        raise ValueError(
            "음수 Relation index가 있습니다."
        )

    if max(edge_types) >= len(
        RELATION_TO_IDX
    ):
        raise ValueError(
            "Relation index 범위를 벗어났습니다."
        )

print(
    f"   edge_index : "
    f"[2, {len(edge_sources)}]"
)

print(
    f"   edge_type  : "
    f"{len(edge_types)}"
)

print(
    f"   node_type  : "
    f"{len(node_type)}"
)


# ============================================================
# 12. 고립 Node 확인
# ============================================================

connected_node_indices = set(
    edge_sources
) | set(
    edge_targets
)

isolated_node_indices = [
    idx
    for idx in range(len(nodes))
    if idx not in connected_node_indices
]

isolated_node_ids = [
    nodes[idx]["id"]
    for idx in isolated_node_indices
]

print(
    f"   고립 Node : "
    f"{len(isolated_node_ids)}개"
)


# ============================================================
# 13. 최종 graph.json
#
# nodes / edges:
#   ML 담당자가 직접 읽고 사용할 수 있는 semantic graph
#
# rgcn_tensors:
#   PyTorch Geometric R-GCN 입력 변환에 사용할 index 데이터
# ============================================================

used_relations = [
    relation
    for relation in RELATION_TO_IDX
    if relation_count.get(relation, 0) > 0
]

graph_data = {
    "metadata": {
        "num_nodes": len(nodes),
        "num_edges": len(edges),
        "num_relation_types": len(
            RELATION_TO_IDX
        ),
        "node_type_to_idx":
            NODE_TYPE_TO_IDX,
        "relation_to_idx":
            RELATION_TO_IDX,
        "used_relations":
            used_relations,
        "relation_counts":
            dict(relation_count),
        "num_isolated_nodes":
            len(isolated_node_ids),
    },

    "nodes": nodes,

    "edges": edges,

    "rgcn_tensors": {
        "edge_index": [
            edge_sources,
            edge_targets,
        ],
        "edge_type":
            edge_types,
        "node_type":
            node_type,
        "node_id_to_idx":
            node_id_to_idx,
    },

    "validation": {
        "invalid_edges":
            invalid_edges,
        "isolated_node_ids":
            isolated_node_ids,
    },
}


# ============================================================
# 14. 저장
# ============================================================

with open(
    OUTPUT_FILE,
    "w",
    encoding="utf-8"
) as f:
    json.dump(
        graph_data,
        f,
        ensure_ascii=False,
        indent=2,
        default=str
    )


# ============================================================
# 15. 결과
# ============================================================

print(
    "\n========================================"
)

print(
    "ML 전달용 Graph Export 완료"
)

print(
    "========================================"
)

print(
    f"Node          : {len(nodes)}"
)

print(
    f"Edge          : {len(edges)}"
)

print(
    f"Relation Type : "
    f"{len(RELATION_TO_IDX)}"
)

print(
    f"Invalid Edge  : "
    f"{len(invalid_edges)}"
)

print(
    f"Isolated Node : "
    f"{len(isolated_node_ids)}"
)

print(
    "\n[성공] graph.json 생성 완료"
)

print(
    " - 원본 Node 속성 보존"
)

print(
    " - Edge id/source/target/relation 형식"
)

print(
    " - 정규화 Relation 10종"
)

print(
    " - R-GCN Tensor 포함"
)
