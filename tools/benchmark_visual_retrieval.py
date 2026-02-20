#!/usr/bin/env python3
"""Mini-Benchmark für Visual-Document-Retrieval-Modelle in Docaro.

Eingabeformat (JSONL):
{"query": "...", "document": "...", "label": 1}

- `label` ist optional. Wenn nicht gesetzt, wird jedes Paar als positiv gewertet.
- Dieses Script benchmarkt Text-zu-Text als schnellen Integrationscheck.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.vector_service import VectorService


def _load_pairs(path: Path, max_samples: int) -> List[Dict]:
    pairs: List[Dict] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)
            if "query" not in item or "document" not in item:
                raise ValueError("Jede JSONL-Zeile braucht 'query' und 'document'.")
            if "label" not in item:
                item["label"] = 1
            pairs.append(item)
            if max_samples and len(pairs) >= max_samples:
                break

    if not pairs:
        raise ValueError(f"Keine Daten in {path}")

    return pairs


def _normalize_rows(x: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(x, axis=1, keepdims=True)
    norms = np.where(norms == 0.0, 1.0, norms)
    return x / norms


def _prepare_query_doc_space(pairs: List[Dict]) -> Tuple[List[str], List[str], List[List[int]]]:
    query_to_pos_docs: Dict[str, set[str]] = {}
    all_docs: set[str] = set()
    for p in pairs:
        q = p["query"]
        d = p["document"]
        all_docs.add(d)
        if int(p.get("label", 1)) == 1:
            query_to_pos_docs.setdefault(q, set()).add(d)

    queries = sorted(query_to_pos_docs.keys())
    documents = sorted(all_docs)
    doc_to_idx = {d: i for i, d in enumerate(documents)}
    positives: List[List[int]] = []
    for q in queries:
        pos = sorted(doc_to_idx[d] for d in query_to_pos_docs[q] if d in doc_to_idx)
        positives.append(pos)
    return queries, documents, positives


def _ranking_metrics(scores: np.ndarray, positives: List[List[int]], ks: List[int]) -> Dict[str, float]:
    if scores.size == 0 or not positives:
        return {}

    mrr_total = 0.0
    recall_hits = {k: 0 for k in ks}
    valid_queries = 0

    for qi, pos_idx in enumerate(positives):
        if not pos_idx:
            continue
        valid_queries += 1
        ranking = np.argsort(-scores[qi])
        rank_map = {doc_idx: r + 1 for r, doc_idx in enumerate(ranking)}
        best_rank = min(rank_map[p] for p in pos_idx if p in rank_map)
        mrr_total += 1.0 / float(best_rank)
        pos_set = set(pos_idx)
        for k in ks:
            topk = set(ranking[:k].tolist())
            if pos_set.intersection(topk):
                recall_hits[k] += 1

    if valid_queries == 0:
        return {}

    out: Dict[str, float] = {"mrr": float(mrr_total / valid_queries)}
    for k in ks:
        out[f"recall@{k}"] = float(recall_hits[k] / valid_queries)
    return out


def _evaluate_dense_profile(profile: str, pairs: List[Dict]) -> Dict[str, float]:
    service = VectorService(backend="chroma", embedding_profile=profile)

    queries, docs, positives = _prepare_query_doc_space(pairs)

    q_emb = _normalize_rows(service._encode_texts(queries))
    d_emb = _normalize_rows(service._encode_texts(docs))

    sim = q_emb @ d_emb.T

    out: Dict[str, float] = {
        "pairs": float(len(pairs)),
        "queries": float(len(queries)),
        "documents": float(len(docs)),
        "score_mean": float(sim.mean()),
        "score_std": float(sim.std()),
    }
    out.update(_ranking_metrics(sim, positives, ks=[1, 3, 5, 10]))
    return out


def _evaluate_colqwen2(pairs: List[Dict], model_name: str) -> Dict[str, float]:
    import torch
    from transformers import ColQwen2ForRetrieval, ColQwen2Processor
    from transformers.utils.import_utils import is_flash_attn_2_available

    model = ColQwen2ForRetrieval.from_pretrained(
        model_name,
        torch_dtype=torch.bfloat16,
        device_map="auto",
        attn_implementation="flash_attention_2" if is_flash_attn_2_available() else "sdpa",
    )
    processor = ColQwen2Processor.from_pretrained(model_name)

    queries, docs, positives = _prepare_query_doc_space(pairs)

    inputs_q = processor(text=queries).to(model.device)
    inputs_d = processor(text=docs).to(model.device)

    with torch.no_grad():
        q_emb = model(**inputs_q).embeddings
        d_emb = model(**inputs_d).embeddings

    scores = processor.score_retrieval(q_emb, d_emb).detach().float().cpu().numpy()
    out: Dict[str, float] = {
        "pairs": float(len(pairs)),
        "queries": float(len(queries)),
        "documents": float(len(docs)),
        "score_mean": float(scores.mean()),
        "score_std": float(scores.std()),
    }
    out.update(_ranking_metrics(scores, positives, ks=[1, 3, 5, 10]))
    return out


def _evaluate_colnomic(pairs: List[Dict], model_name: str) -> Dict[str, float]:
    import torch
    from colpali_engine.models import ColQwen2_5, ColQwen2_5_Processor
    from transformers.utils.import_utils import is_flash_attn_2_available

    device = "cuda:0" if torch.cuda.is_available() else "cpu"
    model = ColQwen2_5.from_pretrained(
        model_name,
        torch_dtype=torch.bfloat16 if torch.cuda.is_available() else torch.float32,
        device_map=device,
        attn_implementation="flash_attention_2" if is_flash_attn_2_available() else None,
    ).eval()
    processor = ColQwen2_5_Processor.from_pretrained(model_name)

    queries, docs, positives = _prepare_query_doc_space(pairs)

    batch_q = processor.process_queries(queries).to(model.device)
    batch_d = processor.process_queries(docs).to(model.device)

    with torch.no_grad():
        q_emb = model(**batch_q)
        d_emb = model(**batch_d)

    scores = processor.score_multi_vector(q_emb, d_emb).detach().float().cpu().numpy()
    out: Dict[str, float] = {
        "pairs": float(len(pairs)),
        "queries": float(len(queries)),
        "documents": float(len(docs)),
        "score_mean": float(scores.mean()),
        "score_std": float(scores.std()),
    }
    out.update(_ranking_metrics(scores, positives, ks=[1, 3, 5, 10]))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark für VDR-Modelle in Docaro")
    parser.add_argument("--input", required=True, type=Path, help="JSONL-Datei mit query/document-Paaren")
    parser.add_argument("--max-samples", type=int, default=0, help="Optionales Limit für Samples")
    parser.add_argument(
        "--profiles",
        nargs="+",
        default=["sentence-transformers", "bimodernvbert", "colnomic-7b", "colqwen2-v1"],
        help="Zu benchmarkende Profile",
    )
    args = parser.parse_args()

    pairs = _load_pairs(args.input, args.max_samples)

    results: Dict[str, Dict[str, float]] = {}
    for profile in args.profiles:
        try:
            if profile == "colqwen2-v1":
                results[profile] = _evaluate_colqwen2(pairs, "vidore/colqwen2-v1.0-hf")
            elif profile == "colnomic-7b":
                results[profile] = _evaluate_colnomic(pairs, "nomic-ai/colnomic-embed-multimodal-7b")
            else:
                results[profile] = _evaluate_dense_profile(profile, pairs)
        except Exception as exc:
            results[profile] = {"error": str(exc)}

    print(json.dumps(results, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
