import json
from collections import Counter, defaultdict

FILE_PATH = "synthetic_graph.json"

with open(FILE_PATH, "r", encoding="utf-8") as f:
    data = json.load(f)

nodes = data.get("nodes", [])
edges = data.get("edges", [])

# Node ID -> Node Type
node_type_map = {
    node["id"]: node.get("type", "UNKNOWN")
    for node in nodes
}

print("=" * 70)
print("1. NODE TYPE 분석")
print("=" * 70)

node_type_count = Counter(
    node.get("type", "UNKNOWN")
    for node in nodes
)

for node_type, count in node_type_count.most_common():
    print(f"{node_type:<20} : {count}")


print("\n" + "=" * 70)
print("2. RELATION 종류 분석")
print("=" * 70)

relation_count = Counter()

for edge in edges:
    relation = (
        edge.get("relation")
        or edge.get("type")
        or edge.get("relation_type")
        or "UNKNOWN"
    )

    relation_count[relation] += 1

for relation, count in relation_count.most_common():
    print(f"{relation:<30} : {count}")


print("\n" + "=" * 70)
print("3. Source Type → Relation → Target Type 분석")
print("=" * 70)

structure_count = Counter()

for edge in edges:

    source = (
        edge.get("source_id")
        or edge.get("source")
        or edge.get("from")
    )

    target = (
        edge.get("target_id")
        or edge.get("target")
        or edge.get("to")
    )

    relation = (
        edge.get("relation")
        or edge.get("type")
        or edge.get("relation_type")
        or "UNKNOWN"
    )

    source_type = node_type_map.get(source, "MISSING")
    target_type = node_type_map.get(target, "MISSING")

    structure_count[
        (source_type, relation, target_type)
    ] += 1


for (source_type, relation, target_type), count in \
        structure_count.most_common():

    print(
        f"{source_type:<12}"
        f" --[{relation}]--> "
        f"{target_type:<12}"
        f" : {count}"
    )


print("\n" + "=" * 70)
print("4. TEAM 관련 Edge")
print("=" * 70)

team_count = 0

for (source_type, relation, target_type), count in \
        structure_count.most_common():

    if source_type == "Team" or target_type == "Team":

        print(
            f"{source_type:<12}"
            f" --[{relation}]--> "
            f"{target_type:<12}"
            f" : {count}"
        )

        team_count += count


print()
print(f"Team 관련 Edge 총합 : {team_count}")
print(f"전체 Edge           : {len(edges)}")

print("\n" + "=" * 70)
print("5. PARTICIPATES_IN 실제 데이터 샘플")
print("=" * 70)

count = 0

for edge in edges:
    relation = (
        edge.get("relation")
        or edge.get("type")
        or edge.get("relation_type")
    )

    if relation == "PARTICIPATES_IN":
        print(edge)
        count += 1

        if count >= 10:
            break


print("\n" + "=" * 70)
print("6. PARTICIPATES_IN ROLE 종류")
print("=" * 70)

role_count = Counter()

for edge in edges:
    relation = (
        edge.get("relation")
        or edge.get("type")
        or edge.get("relation_type")
    )

    if relation == "PARTICIPATES_IN":
        role = edge.get("role", "UNKNOWN")
        role_count[role] += 1

for role, count in role_count.most_common():
    print(f"{role:<20} : {count}")

print(f"\n총합 : {sum(role_count.values())}")

print("\n" + "=" * 70)
print("7. WORK NODE 실제 데이터 샘플")
print("=" * 70)

count = 0

for node in nodes:
    if node.get("type") == "Work":
        print(node)
        count += 1

        if count >= 5:
            break
print("\n" + "=" * 70)
print("8. TASK NODE 실제 데이터 샘플")
print("=" * 70)

count = 0

for node in nodes:
    if node.get("type") == "Task":
        print(node)
        count += 1

        if count >= 3:
            break


print("\n" + "=" * 70)
print("9. EVENT NODE 실제 데이터 샘플")
print("=" * 70)

count = 0

for node in nodes:
    if node.get("type") == "Event":
        print(node)
        count += 1

        if count >= 3:
            break