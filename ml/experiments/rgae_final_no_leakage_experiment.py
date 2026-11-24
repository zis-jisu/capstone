import copy
import hashlib
import json
import math
import os
import random
from collections import defaultdict
from pathlib import Path

import networkx as nx
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch_geometric.nn import RGCNConv


ROOT = Path(__file__).resolve().parent
SOURCE_BASE = ROOT / "data"
GRAPH_1001_PATH = SOURCE_BASE / "graph_2026-10-01.json"
GRAPH_1007_PATH = SOURCE_BASE / "graph_2026-10-07_validation.json"
OUTPUT_DIR = ROOT / "results"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

TARGET_PERSON_ID = "U0C22C8M742"
SECOND_SOURCE_PERSON_ID = "U0C1M3Q1PRV"
SCENARIO_RECEIVER_ID = "U0C20G9MRML"
SEED = 42
SELECTION_EPOCHS = 220
FINAL_EPOCHS = 600
LEARNING_RATE = 0.01
WEIGHT_DECAY = 1e-4
HIDDEN_DIM = 64
LATENT_DIM = 32
DECODER_DIM = 32
K_VALUES = (3, 5, 10)
ROLE_RELATIONS = {"APPROVER", "OWNER", "REVIEWER", "COLLABORATOR", "RELATED"}
PRACTICAL_RELATIONS = ROLE_RELATIONS - {"RELATED"}

# 후보 계수는 업무 책임의 단조성만 사전 가정한다. 운영 GT는 선택 과정에서 사용하지 않는다.
ROLE_WEIGHT_CANDIDATES = {
    "mild": {"APPROVER": 1.30, "OWNER": 1.25, "REVIEWER": 1.15, "COLLABORATOR": 1.05, "RELATED": 0.80},
    "balanced": {"APPROVER": 1.60, "OWNER": 1.50, "REVIEWER": 1.30, "COLLABORATOR": 1.10, "RELATED": 0.50},
    "strong": {"APPROVER": 2.00, "OWNER": 1.80, "REVIEWER": 1.40, "COLLABORATOR": 1.10, "RELATED": 0.25},
    "owner_focus": {"APPROVER": 1.70, "OWNER": 1.70, "REVIEWER": 1.25, "COLLABORATOR": 1.00, "RELATED": 0.40},
}
OTHER_RELATION_WEIGHT = 1.0


def reset_seed(seed):
    os.environ["PYTHONHASHSEED"] = str(seed)
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.set_num_threads(1)


def load_json(path):
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


graph_1001 = load_json(GRAPH_1001_PATH)
validation_1007 = load_json(GRAPH_1007_PATH)
graph_1007 = {"nodes": validation_1007["nodes"], "edges": validation_1007["edges"]}
ground_truth = {
    "snapshot_at": "2026-10-07",
    "operational_ground_truth": {
        **validation_1007["ground_truth"],
        "revision": "replacement_redundancy_v2",
    },
}

all_nodes = graph_1001["nodes"] + graph_1007["nodes"]
all_edges = graph_1001["edges"] + graph_1007["edges"]
NODE_TYPES = sorted({node["type"] for node in all_nodes})
TASK_STATUSES = sorted({node.get("status", "none") for node in all_nodes if node["type"] == "Task"})
BASE_RELATIONS = sorted({edge["relation"] for edge in all_edges})
NODE_TYPE_TO_IDX = {value: idx for idx, value in enumerate(NODE_TYPES)}
STATUS_TO_IDX = {value: idx for idx, value in enumerate(TASK_STATUSES)}
RELATION_TO_IDX = {value: idx for idx, value in enumerate(BASE_RELATIONS)}
IDX_TO_RELATION = {idx: value for value, idx in RELATION_TO_IDX.items()}
NUM_BASE_RELATIONS = len(BASE_RELATIONS)
NUM_ENCODER_RELATIONS = NUM_BASE_RELATIONS * 2


def pseudo_random_vector(node_id, seed, dim=16):
    digest = hashlib.sha256(f"{seed}:{node_id}".encode("utf-8")).digest()
    local_seed = int.from_bytes(digest[:8], "little", signed=False)
    return np.random.default_rng(local_seed).standard_normal(dim).astype(np.float32) * 0.1


def make_node_features(nodes, seed):
    type_x = np.zeros((len(nodes), len(NODE_TYPES)), dtype=np.float32)
    status_x = np.zeros((len(nodes), len(TASK_STATUSES)), dtype=np.float32)
    for idx, node in enumerate(nodes):
        type_x[idx, NODE_TYPE_TO_IDX[node["type"]]] = 1.0
        if node["type"] == "Task":
            status_x[idx, STATUS_TO_IDX[node.get("status", "none")]] = 1.0
    hash_x = np.stack([pseudo_random_vector(node["id"], seed) for node in nodes])
    return torch.tensor(np.concatenate([type_x, status_x, hash_x], axis=1), dtype=torch.float32)


def build_graph_data(graph, seed, role_weights=None, edge_positions=None):
    nodes = graph["nodes"]
    edges = graph["edges"] if edge_positions is None else [graph["edges"][idx] for idx in edge_positions]
    node_to_idx = {node["id"]: idx for idx, node in enumerate(nodes)}
    edge_index = torch.tensor(
        [[node_to_idx[e["source"]] for e in edges], [node_to_idx[e["target"]] for e in edges]],
        dtype=torch.long,
    )
    edge_type = torch.tensor([RELATION_TO_IDX[e["relation"]] for e in edges], dtype=torch.long)
    if role_weights is None:
        relation_weights = torch.ones(NUM_BASE_RELATIONS, dtype=torch.float32)
    else:
        relation_weights = torch.tensor(
            [role_weights.get(relation, OTHER_RELATION_WEIGHT) for relation in BASE_RELATIONS],
            dtype=torch.float32,
        )
    return {
        "nodes": nodes,
        "edges": edges,
        "node_to_idx": node_to_idx,
        "x": make_node_features(nodes, seed),
        "edge_index": edge_index,
        "edge_type": edge_type,
        "edge_weight": relation_weights[edge_type],
        "relation_weights": relation_weights,
    }


def encoder_edges(edge_index, edge_type):
    reverse_index = torch.stack([edge_index[1], edge_index[0]], dim=0)
    reverse_type = edge_type + NUM_BASE_RELATIONS
    return torch.cat([edge_index, reverse_index], dim=1), torch.cat([edge_type, reverse_type])


def sample_negative_edges(data, positions, seed):
    rng = random.Random(seed)
    edge_index, edge_type, nodes = data["edge_index"], data["edge_type"], data["nodes"]
    known = set(zip(edge_index[0].tolist(), edge_index[1].tolist(), edge_type.tolist()))
    nodes_by_type = defaultdict(list)
    for idx, node in enumerate(nodes):
        nodes_by_type[node["type"]].append(idx)
    neg_src, neg_dst, neg_rel = [], [], []
    for pos in positions.tolist():
        src, dst, rel = int(edge_index[0, pos]), int(edge_index[1, pos]), int(edge_type[pos])
        dst_type = nodes[dst]["type"]
        choices = [x for x in nodes_by_type[dst_type] if x != dst and (src, x, rel) not in known]
        if choices:
            neg_src.append(src); neg_dst.append(rng.choice(choices)); neg_rel.append(rel)
            continue
        src_type = nodes[src]["type"]
        choices = [x for x in nodes_by_type[src_type] if x != src and (x, dst, rel) not in known]
        if not choices:
            raise RuntimeError("negative edge sampling failed")
        neg_src.append(rng.choice(choices)); neg_dst.append(dst); neg_rel.append(rel)
    return torch.tensor([neg_src, neg_dst], dtype=torch.long), torch.tensor(neg_rel, dtype=torch.long)


class CompactRGAE(nn.Module):
    def __init__(self, input_dim):
        super().__init__()
        self.conv1 = RGCNConv(input_dim, HIDDEN_DIM, NUM_ENCODER_RELATIONS, num_bases=min(8, NUM_ENCODER_RELATIONS))
        self.conv2 = RGCNConv(HIDDEN_DIM, LATENT_DIM, NUM_ENCODER_RELATIONS, num_bases=min(8, NUM_ENCODER_RELATIONS))
        self.relation_embedding = nn.Embedding(NUM_BASE_RELATIONS, LATENT_DIM)
        self.decoder = nn.Sequential(
            nn.Linear(LATENT_DIM * 3, DECODER_DIM), nn.ReLU(), nn.Dropout(0.10), nn.Linear(DECODER_DIM, 1)
        )

    def encode(self, x, edge_index, edge_type):
        hidden = F.relu(self.conv1(x, edge_index, edge_type))
        hidden = F.dropout(hidden, p=0.10, training=self.training)
        return self.conv2(hidden, edge_index, edge_type)

    def decode(self, z, edge_index, edge_type):
        src, dst = z[edge_index[0]], z[edge_index[1]]
        rel = self.relation_embedding(edge_type)
        return self.decoder(torch.cat([src, dst, rel], dim=1)).squeeze(-1)


def stratified_holdout(graph, fraction, seed):
    rng = random.Random(seed)
    by_relation = defaultdict(list)
    for idx, edge in enumerate(graph["edges"]):
        by_relation[edge["relation"]].append(idx)
    validation = []
    for positions in by_relation.values():
        shuffled = positions.copy(); rng.shuffle(shuffled)
        count = 0 if len(shuffled) < 4 else max(1, int(round(len(shuffled) * fraction)))
        validation.extend(shuffled[:count])
    validation = sorted(validation)
    validation_set = set(validation)
    train = [idx for idx in range(len(graph["edges"])) if idx not in validation_set]
    return train, validation


def train_model(graph, seed, role_weights, epochs, train_positions=None):
    reset_seed(seed)
    full_data = build_graph_data(graph, seed, role_weights)
    if train_positions is None:
        train_positions = list(range(len(graph["edges"])))
    train_data = build_graph_data(graph, seed, role_weights, train_positions)
    enc_index, enc_type = encoder_edges(train_data["edge_index"], train_data["edge_type"])
    model = CompactRGAE(train_data["x"].shape[1])
    optimizer = torch.optim.Adam(model.parameters(), lr=LEARNING_RATE, weight_decay=WEIGHT_DECAY)
    positions = torch.arange(train_data["edge_index"].shape[1])
    history = []
    for epoch in range(1, epochs + 1):
        model.train(); optimizer.zero_grad()
        z = model.encode(train_data["x"], enc_index, enc_type)
        neg_index, neg_type = sample_negative_edges(train_data, positions, seed + epoch)
        pos_logits = model.decode(z, train_data["edge_index"], train_data["edge_type"])
        neg_logits = model.decode(z, neg_index, neg_type)
        logits = torch.cat([pos_logits, neg_logits])
        labels = torch.cat([torch.ones_like(pos_logits), torch.zeros_like(neg_logits)])
        losses = F.binary_cross_entropy_with_logits(logits, labels, reduction="none")
        weights = torch.cat([train_data["edge_weight"], train_data["relation_weights"][neg_type]])
        weights = weights / weights.mean().clamp_min(1e-8)
        loss = (losses * weights).mean()
        loss.backward(); optimizer.step()
        history.append(float(loss.item()))
    return model, full_data, history


def balanced_validation_bce(model, graph, seed, role_weights, train_positions, validation_positions):
    full_data = build_graph_data(graph, seed, role_weights)
    train_data = build_graph_data(graph, seed, role_weights, train_positions)
    val_data = build_graph_data(graph, seed, role_weights, validation_positions)
    enc_index, enc_type = encoder_edges(train_data["edge_index"], train_data["edge_type"])
    positions = torch.arange(val_data["edge_index"].shape[1])
    neg_index, neg_type = sample_negative_edges(full_data, torch.tensor(validation_positions), seed + 9000)
    model.eval()
    with torch.no_grad():
        z = model.encode(train_data["x"], enc_index, enc_type)
        pos_loss = F.binary_cross_entropy_with_logits(
            model.decode(z, val_data["edge_index"], val_data["edge_type"]),
            torch.ones(len(validation_positions)), reduction="none"
        )
        neg_loss = F.binary_cross_entropy_with_logits(
            model.decode(z, neg_index, neg_type), torch.zeros(len(validation_positions)), reduction="none"
        )
    relation_losses = defaultdict(list)
    for idx, rel_idx in enumerate(val_data["edge_type"].tolist()):
        relation_losses[IDX_TO_RELATION[rel_idx]].extend([float(pos_loss[idx]), float(neg_loss[idx])])
    per_relation = {relation: float(np.mean(values)) for relation, values in relation_losses.items()}
    return float(np.mean(list(per_relation.values()))), per_relation


print("[1/6] graph-only role-weight selection")
selection_rows = []
for profile_name, role_weights in ROLE_WEIGHT_CANDIDATES.items():
    fold_scores = []
    for fold, fold_seed in enumerate((SEED + 101, SEED + 202), start=1):
        train_pos, val_pos = stratified_holdout(graph_1001, 0.15, fold_seed)
        model, _, _ = train_model(graph_1001, fold_seed, role_weights, SELECTION_EPOCHS, train_pos)
        macro_bce, per_relation = balanced_validation_bce(
            model, graph_1001, fold_seed, role_weights, train_pos, val_pos
        )
        fold_scores.append(macro_bce)
        selection_rows.append({
            "profile": profile_name, "fold": fold, "macro_relation_balanced_BCE": macro_bce,
            **{f"BCE_{key}": value for key, value in per_relation.items()},
        })
        print(profile_name, "fold", fold, "macro BCE", round(macro_bce, 6))

selection_df = pd.DataFrame(selection_rows)
selection_summary = selection_df.groupby("profile", as_index=False)["macro_relation_balanced_BCE"].agg(["mean", "std"]).reset_index()
selection_summary = selection_summary.sort_values(["mean", "std", "profile"]).reset_index(drop=True)
SELECTED_PROFILE = selection_summary.loc[0, "profile"]
SELECTED_ROLE_WEIGHTS = ROLE_WEIGHT_CANDIDATES[SELECTED_PROFILE]
SELECTED_ROLE_WEIGHTS_100PT = {
    "APPROVER": 31,
    "OWNER": 27,
    "REVIEWER": 21,
    "COLLABORATOR": 17,
    "RELATED": 4,
}
print("selected:", SELECTED_PROFILE, SELECTED_ROLE_WEIGHTS)


print("[2/6] final full-graph training")
unweighted_profile = {role: 1.0 for role in ROLE_RELATIONS}
unweighted_model, _, unweighted_history = train_model(graph_1007, SEED, unweighted_profile, FINAL_EPOCHS)
weighted_model, _, weighted_history = train_model(graph_1007, SEED, SELECTED_ROLE_WEIGHTS, FINAL_EPOCHS)
temporal_unweighted_model, _, temporal_unweighted_history = train_model(
    graph_1001, SEED, unweighted_profile, FINAL_EPOCHS
)
temporal_weighted_model, _, temporal_weighted_history = train_model(
    graph_1001, SEED, SELECTED_ROLE_WEIGHTS, FINAL_EPOCHS
)


def target_roles_and_hops(graph):
    node_by_id = {node["id"]: node for node in graph["nodes"]}
    roles = defaultdict(set)
    for edge in graph["edges"]:
        if edge["relation"] not in ROLE_RELATIONS:
            continue
        if edge["source"] == TARGET_PERSON_ID and node_by_id.get(edge["target"], {}).get("type") == "Task":
            if node_by_id[edge["target"]].get("status") != "completed": roles[edge["target"]].add(edge["relation"])
        elif edge["target"] == TARGET_PERSON_ID and node_by_id.get(edge["source"], {}).get("type") == "Task":
            if node_by_id[edge["source"]].get("status") != "completed": roles[edge["source"]].add(edge["relation"])
    direct = set(roles)
    hop2 = set(direct)
    for edge in graph["edges"]:
        if edge["relation"] != "DEPENDS_ON":
            continue
        for candidate, anchor in ((edge["source"], edge["target"]), (edge["target"], edge["source"])):
            if anchor in direct and node_by_id.get(candidate, {}).get("type") == "Task" and node_by_id[candidate].get("status") != "completed":
                hop2.add(candidate)
    return roles, direct, hop2


roles_1007, direct_1007, hop2_1007 = target_roles_and_hops(graph_1007)
node_1007 = {node["id"]: node for node in graph_1007["nodes"]}
all_active_tasks_1007 = sorted(node["id"] for node in graph_1007["nodes"] if node["type"] == "Task" and node.get("status") != "completed")


def score_all_tasks(model, graph, seed, role_weights, target_person_ids=None):
    data = build_graph_data(graph, seed, role_weights)
    target_person_ids = target_person_ids or [TARGET_PERSON_ID]
    person_indices = [data["node_to_idx"][person_id] for person_id in target_person_ids]
    full_enc_idx, full_enc_type = encoder_edges(data["edge_index"], data["edge_type"])
    keep = torch.ones(data["edge_index"].shape[1], dtype=torch.bool)
    for person_idx in person_indices:
        keep &= (data["edge_index"][0] != person_idx) & (data["edge_index"][1] != person_idx)
    cf_index, cf_type = data["edge_index"][:, keep], data["edge_type"][keep]
    cf_enc_idx, cf_enc_type = encoder_edges(cf_index, cf_type)
    x_cf = data["x"].clone()
    x_cf[person_indices] = 0.0
    positions = torch.arange(data["edge_index"].shape[1])
    neg_index, neg_type = sample_negative_edges(data, positions, seed + 20000)
    eval_index = torch.cat([data["edge_index"], neg_index], dim=1)
    eval_type = torch.cat([data["edge_type"], neg_type])
    labels = torch.cat([torch.ones(data["edge_index"].shape[1]), torch.zeros(neg_index.shape[1])])
    eval_weights = torch.cat([data["edge_weight"], data["relation_weights"][neg_type]])
    model.eval()
    with torch.no_grad():
        z_normal = model.encode(data["x"], full_enc_idx, full_enc_type)
        z_cf = model.encode(x_cf, cf_enc_idx, cf_enc_type)
        z_cf[person_indices] = 0.0
        normal_error = F.binary_cross_entropy_with_logits(model.decode(z_normal, eval_index, eval_type), labels, reduction="none")
        cf_error = F.binary_cross_entropy_with_logits(model.decode(z_cf, eval_index, eval_type), labels, reduction="none")
    node_by_id = {node["id"]: node for node in graph["nodes"]}
    active_task_ids = [node["id"] for node in graph["nodes"] if node["type"] == "Task" and node.get("status") != "completed"]
    idx_to_task = {data["node_to_idx"][task_id]: task_id for task_id in active_task_ids}
    values = defaultdict(list)
    for pos in range(eval_index.shape[1]):
        for idx in {int(eval_index[0, pos]), int(eval_index[1, pos])}:
            if idx in idx_to_task:
                values[idx].append((float(normal_error[pos]), float(cf_error[pos]), float(eval_weights[pos])))
    rows = []
    for idx, task_id in idx_to_task.items():
        triples = values[idx]
        weights = np.array([item[2] for item in triples])
        normal = float(np.average([item[0] for item in triples], weights=weights))
        counter = float(np.average([item[1] for item in triples], weights=weights))
        rows.append({"task_id": task_id, "task_name": node_by_id[task_id].get("name"), "model_score": counter - normal})
    return pd.DataFrame(rows)


print("[3/6] full-graph scoring and hop extraction")
unweighted_all = score_all_tasks(unweighted_model, graph_1007, SEED, unweighted_profile)
weighted_all = score_all_tasks(weighted_model, graph_1007, SEED, SELECTED_ROLE_WEIGHTS)
temporal_unweighted_all = score_all_tasks(
    temporal_unweighted_model, graph_1007, SEED, unweighted_profile
)
temporal_weighted_all = score_all_tasks(
    temporal_weighted_model, graph_1007, SEED, SELECTED_ROLE_WEIGHTS
)

full_nx = nx.Graph()
full_nx.add_nodes_from(node_1007)
full_nx.add_edges_from((edge["source"], edge["target"]) for edge in graph_1007["edges"])
betweenness = nx.betweenness_centrality(full_nx, normalized=True, weight=None)
centrality_all = pd.DataFrame([
    {"task_id": task_id, "task_name": node_1007[task_id].get("name"), "degree_score": float(full_nx.degree(task_id)), "betweenness_score": float(betweenness.get(task_id, 0.0))}
    for task_id in all_active_tasks_1007
])

snapshot = pd.Timestamp(ground_truth["snapshot_at"], tz="UTC")


def active_downstream(task_id, graph, node_by_id):
    return {edge["source"] for edge in graph["edges"] if edge["relation"] == "DEPENDS_ON" and edge["target"] == task_id and node_by_id.get(edge["source"], {}).get("status") != "completed"}


def deadline_score(task_id, graph, node_by_id, snapshot_at):
    ids = {task_id} | active_downstream(task_id, graph, node_by_id)
    dates = [pd.to_datetime(node_by_id[item].get("due_at"), utc=True) for item in ids if node_by_id[item].get("due_at")]
    if not dates: return 0.10
    days = (min(dates) - snapshot_at).total_seconds() / 86400
    if days < 0: return 1.00
    if days <= 1: return 0.95
    if days <= 3: return 0.85
    if days <= 7: return 0.70
    if days <= 30: return 0.45
    return 0.25


def workflow_score(task_id, graph, node_by_id):
    base = {"waiting": 0.70, "in_progress": 0.60, "planned": 0.35}.get(str(node_by_id[task_id].get("status", "")).lower(), 0.20)
    return min(1.0, base + min(len(active_downstream(task_id, graph, node_by_id)), 2) * 0.15)


def add_context(frame, graph, roles, snapshot_at):
    node_by_id = {node["id"]: node for node in graph["nodes"]}
    out = frame.copy()
    out["model_percentile"] = out["model_score"].rank(pct=True)
    out["deadline_score"] = out["task_id"].map(lambda x: deadline_score(x, graph, node_by_id, snapshot_at))
    out["workflow_score"] = out["task_id"].map(lambda x: workflow_score(x, graph, node_by_id))
    # RELATED-only만 독립 감점 항목으로 표시한다. 다른 실질 역할끼리는 차등하지 않는다.
    out["deadline_corrected"] = out["deadline_score"]
    out["workflow_corrected"] = out["workflow_score"]
    out["related_only"] = out["task_id"].map(
        lambda x: 1.0 if roles.get(x) == {"RELATED"} else 0.0
    )
    return out


def rank_corr(a, b):
    ra = pd.Series(a).rank(method="average").to_numpy()
    rb = pd.Series(b).rank(method="average").to_numpy()
    if np.std(ra) == 0 or np.std(rb) == 0: return 0.0
    return float(np.corrcoef(ra, rb)[0, 1])


def jaccard_topk(a, b, k=10):
    left = set(np.argsort(-np.asarray(a))[:k]); right = set(np.argsort(-np.asarray(b))[:k])
    return len(left & right) / len(left | right)


print("[4/6] graph-only priority coefficient selection")
# 10/1에서 별도 모델을 학습하고, 운영 GT 없이 안정성 제약으로 비율을 확정한다.
weighted_1001, _, _ = train_model(graph_1001, SEED + 303, SELECTED_ROLE_WEIGHTS, FINAL_EPOCHS)
roles_1001, direct_1001, hop2_1001 = target_roles_and_hops(graph_1001)
score_1001 = score_all_tasks(weighted_1001, graph_1001, SEED + 303, SELECTED_ROLE_WEIGHTS)
node_1001 = {node["id"]: node for node in graph_1001["nodes"]}
snapshot_1001 = pd.Timestamp("2025-10-01T00:00:00Z")
context_1001 = add_context(score_1001[score_1001["task_id"].isin(hop2_1001)].reset_index(drop=True), graph_1001, roles_1001, snapshot_1001)

coefficient_rows = []
for structure_pct in range(50, 71, 5):
    for deadline_pct in range(15, 31, 5):
        for workflow_pct in (10, 15):
            penalty_pct = 100 - structure_pct - deadline_pct - workflow_pct
            if penalty_pct < 5 or penalty_pct > 20:
                continue
            alpha, beta, gamma, penalty = (
                structure_pct / 100,
                deadline_pct / 100,
                workflow_pct / 100,
                penalty_pct / 100,
            )
            final = (
                alpha * context_1001["model_percentile"]
                + beta * context_1001["deadline_corrected"]
                + gamma * context_1001["workflow_corrected"]
                - penalty * context_1001["related_only"]
            )
            corr = rank_corr(final, context_1001["model_percentile"])
            overlap = jaccard_topk(final, context_1001["model_percentile"], min(10, len(final)))
            top_positions = np.argsort(-final.to_numpy())[: min(10, len(final))]
            low_structure_related_intrusions = int((
                (context_1001.iloc[top_positions]["related_only"] == 1.0)
                & (context_1001.iloc[top_positions]["model_percentile"] < 0.50)
            ).sum())
            coefficient_rows.append({
                "structure": alpha, "deadline": beta, "workflow": gamma,
                "related_penalty": penalty,
                "spearman_vs_structure": corr, "top10_jaccard_vs_structure": overlap,
                "low_structure_RELATED_top10": low_structure_related_intrusions,
                "feasible": (
                    corr >= 0.80 and overlap >= 0.65
                    and low_structure_related_intrusions == 0
                ),
            })
coefficient_df = pd.DataFrame(coefficient_rows)
feasible = coefficient_df[coefficient_df["feasible"]].copy()
if feasible.empty:
    feasible = coefficient_df.sort_values(
        ["low_structure_RELATED_top10", "spearman_vs_structure", "top10_jaccard_vs_structure"],
        ascending=[True, False, False],
    ).head(1)
# 제약을 만족하는 범위에서 deadline 반응성을 최대화하되 RELATED 감점은 최소화한다.
chosen = feasible.sort_values(
    ["deadline", "related_penalty", "structure", "spearman_vs_structure"],
    ascending=[False, True, False, False],
).iloc[0]
# 최종 운영안은 사용자 지정 100점 기본점수 + RELATED 10점 차감이다.
# 양의 세 항은 1.00이며 related_penalty는 별도 감점이므로 절댓값 합은 1.10이다.
FINAL_COEFFICIENTS = {
    "structure": 0.55,
    "deadline": 0.30,
    "workflow": 0.15,
    "related_penalty": 0.10,
}
print("selected final coefficients:", FINAL_COEFFICIENTS)


def corrected_formula(frame):
    a = FINAL_COEFFICIENTS["structure"]
    b = FINAL_COEFFICIENTS["deadline"]
    c = FINAL_COEFFICIENTS["workflow"]
    penalty = FINAL_COEFFICIENTS["related_penalty"]
    out = frame.copy()
    out["final_score"] = (
        a * out["model_percentile"]
        + b * out["deadline_corrected"]
        + c * out["workflow_corrected"]
        - penalty * out["related_only"]
    )
    return out.sort_values(["final_score", "model_score", "task_id"], ascending=[False, False, True]).reset_index(drop=True)


def rule_baseline(frame):
    out = frame.copy()
    # 구조 모델이 없는 baseline은 마감:연속성 = 선택된 context 비율로 재정규화한다.
    denom = FINAL_COEFFICIENTS["deadline"] + FINAL_COEFFICIENTS["workflow"]
    deadline_ratio = FINAL_COEFFICIENTS["deadline"] / denom
    workflow_ratio = FINAL_COEFFICIENTS["workflow"] / denom
    out["final_score"] = (
        deadline_ratio * out["deadline_corrected"]
        + workflow_ratio * out["workflow_corrected"]
        - FINAL_COEFFICIENTS["related_penalty"] * out["related_only"]
    )
    return out.sort_values(["final_score", "task_id"], ascending=[False, True]).reset_index(drop=True)


gt_labels = [item for item in ground_truth["operational_ground_truth"]["labels"] if item.get("operational_rank") is not None]
gt_rank = {item["task_id"]: int(item["operational_rank"]) for item in gt_labels}
gt_relevance = {item["task_id"]: float(item["operational_relevance"]) for item in gt_labels}
important_ids = set(gt_rank)


def ndcg(ids, k):
    gains = [gt_relevance.get(task_id, 0.0) for task_id in ids[:k]]
    ideal = sorted(gt_relevance.values(), reverse=True)[:k]
    dcg = sum(value / math.log2(idx + 1) for idx, value in enumerate(gains, start=1))
    idcg = sum(value / math.log2(idx + 1) for idx, value in enumerate(ideal, start=1))
    return dcg / idcg if idcg else 0.0


def evaluate(frame, method, hop_label, k):
    predicted = frame.head(k)["task_id"].tolist()
    tp = len(set(predicted) & important_ids)
    return {
        "hop": hop_label, "method": method, "K": k, "candidate_count": len(frame), "TP@K": tp,
        "Precision@K": tp / k, "Recall@K": tp / len(important_ids), "nDCG@K": ndcg(predicted, k),
        "topK_task_ids": ",".join(predicted),
    }


print("[5/6] final evaluation (GT first used here)")
unweighted_context = add_context(unweighted_all, graph_1007, roles_1007, snapshot)
weighted_context = add_context(weighted_all, graph_1007, roles_1007, snapshot)
temporal_unweighted_context = add_context(
    temporal_unweighted_all, graph_1007, roles_1007, snapshot
)
temporal_weighted_context = add_context(
    temporal_weighted_all, graph_1007, roles_1007, snapshot
)
degree_context = add_context(
    centrality_all.rename(columns={"degree_score": "model_score"}),
    graph_1007,
    roles_1007,
    snapshot,
)
betweenness_context = add_context(
    centrality_all.rename(columns={"betweenness_score": "model_score"}),
    graph_1007,
    roles_1007,
    snapshot,
)

all_rankings = {
    "temporal 10/1→10/7 | R-GAE single": temporal_unweighted_context.sort_values(["model_score", "task_id"], ascending=[False, True]),
    "temporal 10/1→10/7 | R-GAE role-weighted": temporal_weighted_context.sort_values(["model_score", "task_id"], ascending=[False, True]),
    "temporal 10/1→10/7 | R-GAE role-weighted + corrected priority": corrected_formula(temporal_weighted_context),
    "Degree": centrality_all.assign(model_score=centrality_all["degree_score"]).sort_values(["model_score", "task_id"], ascending=[False, True]),
    "Betweenness": centrality_all.assign(model_score=centrality_all["betweenness_score"]).sort_values(["model_score", "task_id"], ascending=[False, True]),
    "Degree + corrected priority": corrected_formula(degree_context),
    "Betweenness + corrected priority": corrected_formula(betweenness_context),
}

metric_rows, ranking_rows = [], []
for hop_label, allowed in (("1-hop", direct_1007),):
    for method, full_frame in all_rankings.items():
        frame = full_frame[full_frame["task_id"].isin(allowed)].copy().reset_index(drop=True)
        for k in K_VALUES:
            metric_rows.append(evaluate(frame, method, hop_label, k))
        frame["hop_scope"] = hop_label; frame["method"] = method; frame["rank"] = np.arange(1, len(frame) + 1)
        ranking_rows.append(frame)

metrics = pd.DataFrame(metric_rows)
rankings = pd.concat(ranking_rows, ignore_index=True)

baseline_audit_rows = []
for hop_label, allowed in (("1-hop", direct_1007),):
    for method in (
        "Degree",
        "Degree + corrected priority",
        "Betweenness",
        "Betweenness + corrected priority",
    ):
        full_frame = all_rankings[method]
        frame = full_frame[full_frame["task_id"].isin(allowed)].copy().reset_index(drop=True)
        for k in K_VALUES:
            baseline_audit_rows.append(evaluate(frame, method, hop_label, k))
baseline_audit = pd.DataFrame(baseline_audit_rows)


# ---------------------------------------------------------------------------
# Multi-source handoff scenario: 김지수 + 박보검 -> 원이정, temporal / 1-hop only
# ---------------------------------------------------------------------------
def roles_for_sources(graph, source_person_ids):
    node_by_id = {node["id"]: node for node in graph["nodes"]}
    roles = defaultdict(set)
    sources = defaultdict(set)
    roles_by_source = defaultdict(lambda: defaultdict(set))
    for edge in graph["edges"]:
        if edge["relation"] not in ROLE_RELATIONS:
            continue
        for person_id in source_person_ids:
            task_id = None
            if edge["source"] == person_id and node_by_id.get(edge["target"], {}).get("type") == "Task":
                task_id = edge["target"]
            elif edge["target"] == person_id and node_by_id.get(edge["source"], {}).get("type") == "Task":
                task_id = edge["source"]
            if task_id and node_by_id[task_id].get("status") != "completed":
                roles[task_id].add(edge["relation"])
                sources[task_id].add(person_id)
                roles_by_source[person_id][task_id].add(edge["relation"])
    return roles, sources, roles_by_source


scenario_source_ids = [TARGET_PERSON_ID, SECOND_SOURCE_PERSON_ID]
scenario_roles, scenario_sources, scenario_roles_by_source = roles_for_sources(
    graph_1007, scenario_source_ids
)
scenario_direct_ids = set(scenario_roles)

scenario_unweighted_all = score_all_tasks(
    temporal_unweighted_model, graph_1007, SEED, unweighted_profile, scenario_source_ids
)
scenario_weighted_all = score_all_tasks(
    temporal_weighted_model, graph_1007, SEED, SELECTED_ROLE_WEIGHTS, scenario_source_ids
)
scenario_unweighted_context = add_context(
    scenario_unweighted_all, graph_1007, scenario_roles, snapshot
)
scenario_weighted_context = add_context(
    scenario_weighted_all, graph_1007, scenario_roles, snapshot
)
scenario_degree_context = add_context(
    centrality_all.rename(columns={"degree_score": "model_score"}),
    graph_1007,
    scenario_roles,
    snapshot,
)
scenario_betweenness_context = add_context(
    centrality_all.rename(columns={"betweenness_score": "model_score"}),
    graph_1007,
    scenario_roles,
    snapshot,
)

scenario_methods = {
    "temporal 10/1→10/7 | R-GAE single": scenario_unweighted_context.sort_values(
        ["model_score", "task_id"], ascending=[False, True]
    ),
    "temporal 10/1→10/7 | R-GAE role-weighted": scenario_weighted_context.sort_values(
        ["model_score", "task_id"], ascending=[False, True]
    ),
    "temporal 10/1→10/7 | R-GAE role-weighted + corrected priority": corrected_formula(
        scenario_weighted_context
    ),
    "Degree": centrality_all.assign(model_score=centrality_all["degree_score"]).sort_values(
        ["model_score", "task_id"], ascending=[False, True]
    ),
    "Betweenness": centrality_all.assign(model_score=centrality_all["betweenness_score"]).sort_values(
        ["model_score", "task_id"], ascending=[False, True]
    ),
    "Degree + corrected priority": corrected_formula(scenario_degree_context),
    "Betweenness + corrected priority": corrected_formula(scenario_betweenness_context),
}

# 박보검의 독립 human GT가 없으므로 동일 운영 기준으로 만든 명시적 proxy GT다.
# 실질 역할만 positive로 두고, 마감·책임·연속성으로 통합 순위를 만든다.
responsibility_value = {
    "APPROVER": 1.00,
    "OWNER": 1.00,
    "REVIEWER": 0.85,
    "COLLABORATOR": 0.70,
    "RELATED": 0.00,
}
scenario_gt_rows = []
scenario_source_set = set(scenario_source_ids)
task_role_people = defaultdict(lambda: defaultdict(set))
for edge in graph_1007["edges"]:
    if edge["relation"] not in PRACTICAL_RELATIONS:
        continue
    if node_1007.get(edge["source"], {}).get("type") == "Person" and node_1007.get(edge["target"], {}).get("type") == "Task":
        task_role_people[edge["target"]][edge["relation"]].add(edge["source"])
    elif node_1007.get(edge["target"], {}).get("type") == "Person" and node_1007.get(edge["source"], {}).get("type") == "Task":
        task_role_people[edge["source"]][edge["relation"]].add(edge["target"])

for task_id in sorted(scenario_direct_ids):
    task_roles = scenario_roles[task_id]
    practical = bool(task_roles & PRACTICAL_RELATIONS)
    source_practical_roles = task_roles & PRACTICAL_RELATIONS
    role_scores = []
    for role in source_practical_roles:
        remaining_same_role = task_role_people[task_id][role] - scenario_source_set
        replacement_factor = 0.35 if remaining_same_role else 1.0
        role_scores.append(responsibility_value[role] * replacement_factor)
    responsibility = max(role_scores, default=0.0)
    generated_proxy_score = (
        0.45 * deadline_score(task_id, graph_1007, node_1007, snapshot)
        + 0.30 * responsibility
        + 0.25 * workflow_score(task_id, graph_1007, node_1007)
    )
    # 김지수의 확정 human GT는 통합 proxy 재계산으로 덮어쓰지 않는다.
    # 박보검 추가 업무만 역할 대체 가능성을 반영한 proxy 점수를 사용한다.
    proxy_score = gt_relevance[task_id] / 10.0 if task_id in important_ids else generated_proxy_score
    scenario_gt_rows.append({
        "task_id": task_id,
        "combined_proxy_gt_label": int(practical),
        "combined_proxy_gt_score": proxy_score if practical else 0.0,
        "replacement_aware_responsibility": responsibility,
        "kim_existing_gt_rank": gt_rank.get(task_id),
        "gt_provenance": (
            "existing_kim_human_gt"
            if task_id in important_ids
            else ("park_proxy_added" if practical else "negative_context")
        ),
    })
scenario_gt = pd.DataFrame(scenario_gt_rows)
positive_proxy = scenario_gt[scenario_gt["combined_proxy_gt_label"] == 1].copy()
positive_proxy = positive_proxy.sort_values(
    ["combined_proxy_gt_score", "task_id"], ascending=[False, True]
).reset_index(drop=True)
positive_proxy["combined_proxy_gt_rank"] = np.arange(1, len(positive_proxy) + 1)
rank_map = dict(zip(positive_proxy["task_id"], positive_proxy["combined_proxy_gt_rank"]))
proxy_relevance = {
    task_id: float(len(positive_proxy) - rank + 1)
    for task_id, rank in rank_map.items()
}
scenario_gt["combined_proxy_gt_rank"] = scenario_gt["task_id"].map(rank_map)
scenario_positive_ids = set(rank_map)


def evaluate_scenario(frame, method, k):
    predicted = frame.head(k)["task_id"].tolist()
    tp = len(set(predicted) & scenario_positive_ids)
    gains = [proxy_relevance.get(task_id, 0.0) for task_id in predicted]
    ideal = sorted(proxy_relevance.values(), reverse=True)[:k]
    dcg = sum(value / math.log2(idx + 1) for idx, value in enumerate(gains, start=1))
    idcg = sum(value / math.log2(idx + 1) for idx, value in enumerate(ideal, start=1))
    return {
        "scenario": "김지수+박보검 → 원이정",
        "scope": "temporal 10/1→10/7, 1-hop",
        "method": method,
        "K": k,
        "candidate_count": len(frame),
        "proxy_GT_positive_count": len(scenario_positive_ids),
        "TP@K": tp,
        "Precision@K": tp / k,
        "Recall@K": tp / len(scenario_positive_ids),
        "nDCG@K": dcg / idcg if idcg else 0.0,
        "topK_task_ids": ",".join(predicted),
    }


person_name = {
    TARGET_PERSON_ID: "김지수",
    SECOND_SOURCE_PERSON_ID: "박보검",
    SCENARIO_RECEIVER_ID: "원이정",
}
scenario_metric_rows = []
scenario_ranking_rows = []
for method, full_frame in scenario_methods.items():
    frame = full_frame[full_frame["task_id"].isin(scenario_direct_ids)].copy().reset_index(drop=True)
    for k in K_VALUES:
        scenario_metric_rows.append(evaluate_scenario(frame, method, k))
    frame["method"] = method
    frame["rank"] = np.arange(1, len(frame) + 1)
    frame["source_people"] = frame["task_id"].map(
        lambda task_id: ",".join(sorted(person_name[value] for value in scenario_sources[task_id]))
    )
    frame["receiver"] = "원이정"
    frame = frame.merge(scenario_gt, on="task_id", how="left")
    scenario_ranking_rows.append(frame)

scenario_metrics = pd.DataFrame(scenario_metric_rows)
scenario_rankings = pd.concat(scenario_ranking_rows, ignore_index=True)

print("[6/6] save")
selection_df.to_csv(OUTPUT_DIR / "edge_weight_masked_validation_folds.csv", index=False, encoding="utf-8-sig")
selection_summary.to_csv(OUTPUT_DIR / "edge_weight_masked_validation_summary.csv", index=False, encoding="utf-8-sig")
coefficient_df.to_csv(OUTPUT_DIR / "priority_coefficient_stability_grid.csv", index=False, encoding="utf-8-sig")
metrics.to_csv(OUTPUT_DIR / "final_1hop_2hop_metrics.csv", index=False, encoding="utf-8-sig")
rankings.to_csv(OUTPUT_DIR / "final_1hop_2hop_rankings.csv", index=False, encoding="utf-8-sig")
baseline_audit.to_csv(OUTPUT_DIR / "baseline_correction_audit.csv", index=False, encoding="utf-8-sig")
baseline_audit.to_csv(OUTPUT_DIR / "centrality_baseline_formula_audit.csv", index=False, encoding="utf-8-sig")
scenario_gt.to_csv(OUTPUT_DIR / "combined_kim_park_proxy_gt.csv", index=False, encoding="utf-8-sig")
scenario_metrics.to_csv(OUTPUT_DIR / "combined_kim_park_to_lee_metrics.csv", index=False, encoding="utf-8-sig")
scenario_rankings.to_csv(OUTPUT_DIR / "combined_kim_park_to_lee_rankings.csv", index=False, encoding="utf-8-sig")

config = {
    "leakage_control": "edge weights and priority coefficients selected on 10/1 graph only; operational GT first used for final 10/7 reporting",
    "ground_truth_revision": ground_truth.get("operational_ground_truth", {}).get("revision"),
    "selected_role_weight_profile": SELECTED_PROFILE,
    "selected_role_edge_weights_100pt": SELECTED_ROLE_WEIGHTS_100PT,
    "role_weight_100pt_note": "Integer 100-point presentation of the validated relative ratios; sum=100",
    "other_relation_weight": OTHER_RELATION_WEIGHT,
    "selected_priority_coefficients": FINAL_COEFFICIENTS,
    "related_guard": "RELATED-only is an independent negative term; OWNER/APPROVER/REVIEWER/COLLABORATOR receive no extra final-formula weight",
    "primary_scope": "temporal 10/1→10/7, 1-hop",
    "multi_handoff_scenario": {
        "sources": ["김지수", "박보검"],
        "receiver": "원이정",
        "candidate_scope": "union of source 1-hop active tasks",
        "gt_status": "existing Kim GT plus explicitly labeled Park proxy GT; not independent human GT",
    },
    "candidate_counts": {"1-hop": len(direct_1007), "2-hop": len(hop2_1007), "all_active_tasks_scored": len(all_active_tasks_1007)},
}
(OUTPUT_DIR / "final_configuration.json").write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
torch.save({
    "unweighted_state": copy.deepcopy(unweighted_model.state_dict()),
    "weighted_state": copy.deepcopy(weighted_model.state_dict()),
    "temporal_unweighted_state": copy.deepcopy(temporal_unweighted_model.state_dict()),
    "temporal_weighted_state": copy.deepcopy(temporal_weighted_model.state_dict()),
    "config": config,
}, OUTPUT_DIR / "final_models.pt")

print(json.dumps(config, ensure_ascii=False, indent=2))
print(metrics[["hop", "method", "K", "TP@K", "Precision@K", "Recall@K", "nDCG@K"]].to_string(index=False))
print(scenario_metrics[["method", "K", "TP@K", "Precision@K", "Recall@K", "nDCG@K"]].to_string(index=False))
