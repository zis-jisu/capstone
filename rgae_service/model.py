from __future__ import annotations

import random
from collections import defaultdict
from typing import Any, Callable

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch_geometric.nn import RGCNConv


# Integer 100-point distribution validated on masked-edge reconstruction.
# OTHER_RELATION_WEIGHT keeps non-role edges near the original neutral 1.0 ratio.
ROLE_EDGE_WEIGHTS = {
    "APPROVES": 31,
    "APPROVER": 31,
    "RESPONSIBLE_FOR": 27,
    "OWNER": 27,
    "REVIEWS": 21,
    "REVIEWER": 21,
    "CONTRIBUTES_TO": 17,
    "COLLABORATOR": 17,
    "RELATED": 4,
}
OTHER_RELATION_WEIGHT = 15


def set_seed(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def resolve_device(name: str) -> torch.device:
    if name == "cpu":
        return torch.device("cpu")
    if name == "cuda":
        if not torch.cuda.is_available():
            raise RuntimeError("CUDA was requested but is unavailable")
        return torch.device("cuda")
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


def prepare_graph(graph: dict[str, Any], seed: int) -> dict[str, Any]:
    nodes, edges = graph["nodes"], graph["edges"]
    node_to_idx = {node["id"]: index for index, node in enumerate(nodes)}
    relation_names = sorted({edge["relation"] for edge in edges})
    if not relation_names:
        raise ValueError("the graph has no relations")
    relation_to_idx = {name: index for index, name in enumerate(relation_names)}
    edge_index = torch.tensor(
        [
            [node_to_idx[edge["source"]] for edge in edges],
            [node_to_idx[edge["target"]] for edge in edges],
        ],
        dtype=torch.long,
    )
    edge_type = torch.tensor(
        [relation_to_idx[edge["relation"]] for edge in edges], dtype=torch.long
    )
    relation_weight_vector = torch.tensor(
        [ROLE_EDGE_WEIGHTS.get(name, OTHER_RELATION_WEIGHT) for name in relation_names],
        dtype=torch.float32,
    )

    node_types = sorted({node["type"] for node in nodes})
    node_type_to_idx = {name: index for index, name in enumerate(node_types)}
    task_statuses = sorted(
        {str(node.get("status", "none")) for node in nodes if node["type"] == "Task"}
    )
    status_to_idx = {name: index for index, name in enumerate(task_statuses)}
    type_features = torch.zeros((len(nodes), len(node_types)))
    status_features = torch.zeros((len(nodes), len(task_statuses)))
    for index, node in enumerate(nodes):
        type_features[index, node_type_to_idx[node["type"]]] = 1.0
        if node["type"] == "Task":
            status_features[index, status_to_idx[str(node.get("status", "none"))]] = 1.0
    generator = torch.Generator().manual_seed(seed)
    random_features = torch.randn((len(nodes), 16), generator=generator) * 0.1
    features = torch.cat([type_features, status_features, random_features], dim=1)

    node_type_by_idx = [node["type"] for node in nodes]
    nodes_by_type: dict[str, list[int]] = defaultdict(list)
    for index, node_type in enumerate(node_type_by_idx):
        nodes_by_type[node_type].append(index)
    known_triples = {
        (
            node_to_idx[edge["source"]],
            node_to_idx[edge["target"]],
            relation_to_idx[edge["relation"]],
        )
        for edge in edges
    }
    negative_candidate_pools: list[list[int]] = []
    for source, target, relation in zip(
        edge_index[0].tolist(), edge_index[1].tolist(), edge_type.tolist()
    ):
        candidates = nodes_by_type[node_type_by_idx[target]]
        valid = [
            candidate
            for candidate in candidates
            if candidate != target
            and (source, candidate, relation) not in known_triples
        ]
        if not valid:
            raise RuntimeError(
                f"negative sampling has no candidate for {(source, target, relation)}"
            )
        negative_candidate_pools.append(valid)
    return {
        "nodes": nodes,
        "node_to_idx": node_to_idx,
        "relation_names": relation_names,
        "edge_index": edge_index,
        "edge_type": edge_type,
        "edge_weight": relation_weight_vector[edge_type],
        "relation_weight_vector": relation_weight_vector,
        "x": features,
        "node_type_by_idx": node_type_by_idx,
        "nodes_by_type": nodes_by_type,
        "known_triples": known_triples,
        "negative_candidate_pools": negative_candidate_pools,
    }


def sample_negative_edges(prepared: dict[str, Any], seed: int) -> tuple[torch.Tensor, torch.Tensor]:
    rng = random.Random(seed)
    negative_source: list[int] = []
    negative_target: list[int] = []
    negative_relation: list[int] = []
    edge_index, edge_type = prepared["edge_index"], prepared["edge_type"]
    for position, (source, relation) in enumerate(
        zip(edge_index[0].tolist(), edge_type.tolist())
    ):
        valid = prepared["negative_candidate_pools"][position]
        negative_source.append(source)
        negative_target.append(rng.choice(valid))
        negative_relation.append(relation)
    return (
        torch.tensor([negative_source, negative_target], dtype=torch.long),
        torch.tensor(negative_relation, dtype=torch.long),
    )


class RelationalGraphAutoencoder(nn.Module):
    def __init__(self, input_dim: int, hidden_dim: int, latent_dim: int, num_relations: int):
        super().__init__()
        bases = min(8, num_relations)
        self.conv1 = RGCNConv(input_dim, hidden_dim, num_relations, num_bases=bases)
        self.conv2 = RGCNConv(hidden_dim, latent_dim, num_relations, num_bases=bases)
        self.relation_embedding = nn.Embedding(num_relations, 16)
        self.decoder = nn.Sequential(
            nn.Linear(latent_dim * 2 + 16, hidden_dim),
            nn.ReLU(),
            nn.Dropout(0.1),
            nn.Linear(hidden_dim, 1),
        )

    def encode(self, x: torch.Tensor, edge_index: torch.Tensor, edge_type: torch.Tensor) -> torch.Tensor:
        return self.conv2(F.relu(self.conv1(x, edge_index, edge_type)), edge_index, edge_type)

    def decode(self, z: torch.Tensor, edge_index: torch.Tensor, edge_type: torch.Tensor) -> torch.Tensor:
        features = torch.cat(
            [z[edge_index[0]], z[edge_index[1]], self.relation_embedding(edge_type)], dim=1
        )
        return self.decoder(features).squeeze(-1)


def build_model(prepared: dict[str, Any], hidden_dim: int = 64, latent_dim: int = 32) -> RelationalGraphAutoencoder:
    return RelationalGraphAutoencoder(
        prepared["x"].shape[1], hidden_dim, latent_dim, len(prepared["relation_names"])
    )


def train_model(
    model: RelationalGraphAutoencoder,
    prepared: dict[str, Any],
    device: torch.device,
    epochs: int,
    seed: int,
    progress: Callable[[int, int, float], None] | None = None,
) -> float:
    x = prepared["x"].to(device)
    edge_index = prepared["edge_index"].to(device)
    edge_type = prepared["edge_type"].to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=0.01, weight_decay=1e-4)
    final_loss = 0.0
    model.train()
    for epoch in range(1, epochs + 1):
        optimizer.zero_grad()
        z = model.encode(x, edge_index, edge_type)
        negative_index, negative_type = sample_negative_edges(prepared, seed + epoch)
        negative_index, negative_type = negative_index.to(device), negative_type.to(device)
        positive_logits = model.decode(z, edge_index, edge_type)
        negative_logits = model.decode(z, negative_index, negative_type)
        logits = torch.cat([positive_logits, negative_logits])
        labels = torch.cat([torch.ones_like(positive_logits), torch.zeros_like(negative_logits)])
        losses = F.binary_cross_entropy_with_logits(logits, labels, reduction="none")
        sample_weights = torch.cat(
            [
                prepared["edge_weight"],
                prepared["relation_weight_vector"][negative_type.cpu()],
            ]
        ).to(device)
        sample_weights = sample_weights / sample_weights.mean().clamp_min(1e-8)
        loss = (losses * sample_weights).mean()
        loss.backward()
        optimizer.step()
        final_loss = float(loss.item())
        # Keep the coordinator's state current on every epoch. The API decides
        # how often to emit progress over the streaming response.
        if progress is not None:
            progress(epoch, epochs, final_loss)
        if epoch == 1 or epoch % 10 == 0 or epoch == epochs:
            print(f"epoch={epoch:04d} loss={final_loss:.6f}", flush=True)
    return final_loss


def task_impact_scores(
    model: RelationalGraphAutoencoder,
    prepared: dict[str, Any],
    person_ids: str | list[str],
    device: torch.device,
    seed: int,
) -> tuple[dict[str, dict[str, float]], int]:
    if isinstance(person_ids, str):
        person_ids = [person_ids]
    if not person_ids:
        raise ValueError("at least one source person_id is required")
    person_indices = [prepared["node_to_idx"][person_id] for person_id in person_ids]
    edge_index, edge_type, x = prepared["edge_index"], prepared["edge_type"], prepared["x"]
    keep = torch.ones(edge_index.shape[1], dtype=torch.bool)
    for person_idx in person_indices:
        keep &= (edge_index[0] != person_idx) & (edge_index[1] != person_idx)
    counterfactual_index, counterfactual_type = edge_index[:, keep], edge_type[keep]
    x_counterfactual = x.clone()
    x_counterfactual[person_indices] = 0.0
    negative_index, negative_type = sample_negative_edges(prepared, seed + 1000)

    model.eval()
    with torch.inference_mode():
        normal_z = model.encode(x.to(device), edge_index.to(device), edge_type.to(device))
        counterfactual_z = model.encode(
            x_counterfactual.to(device),
            counterfactual_index.to(device),
            counterfactual_type.to(device),
        )
        counterfactual_z[person_indices] = 0.0
        evaluation_index = torch.cat([edge_index, negative_index], dim=1).to(device)
        evaluation_type = torch.cat([edge_type, negative_type]).to(device)
        labels = torch.cat(
            [torch.ones(edge_index.shape[1]), torch.zeros(negative_index.shape[1])]
        ).to(device)
        normal_error = F.binary_cross_entropy_with_logits(
            model.decode(normal_z, evaluation_index, evaluation_type), labels, reduction="none"
        ).cpu()
        counterfactual_error = F.binary_cross_entropy_with_logits(
            model.decode(counterfactual_z, evaluation_index, evaluation_type), labels, reduction="none"
        ).cpu()
    evaluation_weights = torch.cat(
        [
            prepared["edge_weight"],
            prepared["relation_weight_vector"][negative_type],
        ]
    )

    task_indices = {
        index for index, node in enumerate(prepared["nodes"]) if node["type"] == "Task"
    }
    values_by_task: dict[int, list[tuple[float, float, float]]] = defaultdict(list)
    evaluation_index = evaluation_index.cpu()
    for position in range(evaluation_index.shape[1]):
        for node_idx in {int(evaluation_index[0, position]), int(evaluation_index[1, position])}:
            if node_idx in task_indices:
                values_by_task[node_idx].append(
                    (
                        float(normal_error[position]),
                        float(counterfactual_error[position]),
                        float(evaluation_weights[position]),
                    )
                )

    result: dict[str, dict[str, float]] = {}
    for task_idx in task_indices:
        values = values_by_task[task_idx]
        if not values:
            continue
        weights = np.asarray([value[2] for value in values], dtype=float)
        normal = float(np.average([value[0] for value in values], weights=weights))
        counterfactual = float(np.average([value[1] for value in values], weights=weights))
        result[prepared["nodes"][task_idx]["id"]] = {
            "normal_error": normal,
            "counterfactual_error": counterfactual,
            "delta_error": counterfactual - normal,
        }
    return result, int((~keep).sum())

