from __future__ import annotations

import gc
import hashlib
import json
import math
import os
import random
import statistics
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

import torch
from huggingface_hub import HfApi
from transformers import AutoModelForSequenceClassification, AutoTokenizer


CANDIDATES = Path(os.getenv("RAG_RERANK_CANDIDATES", "RAG_reranker_후보군_20260829.json"))
MAX_LENGTH = 512
BATCH_SIZE = 16
SEED = 20260829
BOOTSTRAP_SAMPLES = 10_000
MODELS = (
    {
        "name": "BGE_RERANKER_V2_M3",
        "model_id": "BAAI/bge-reranker-v2-m3",
        "license": "Apache-2.0",
        "trust_remote_code": False,
    },
    {
        "name": "GTE_MULTILINGUAL_RERANKER_BASE",
        "model_id": "Alibaba-NLP/gte-multilingual-reranker-base",
        "license": "Apache-2.0",
        "trust_remote_code": True,
    },
)
SELECTION_RULE = {
    "primary_metric": "ndcg_at_5",
    "minimum_ndcg_at_5_delta": 0.02,
    "bootstrap_95_ci_lower_must_exceed": 0.0,
    "maximum_recall_at_5_regression": 0.01,
    "maximum_gpu_p95_ms": 300.0,
    "maximum_error_count": 0,
}


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * fraction)))
    return round(ordered[index], 4)


def document_ranking(candidates: list[dict], score_key: str | None = None) -> list[str]:
    ordered = candidates if score_key is None else sorted(
        candidates,
        key=lambda item: (-float(item[score_key]), int(item["rank"])),
    )
    return list(dict.fromkeys(str(item["manual_id"]) for item in ordered))


def query_metrics(ranking: list[str], expected: set[str]) -> dict[str, float]:
    result: dict[str, float] = {}
    for k in (1, 3, 5, 10):
        top = ranking[:k]
        result[f"recall_at_{k}"] = len(expected.intersection(top)) / len(expected)
        result[f"hit_at_{k}"] = float(bool(expected.intersection(top)))
        dcg = sum(
            1.0 / math.log2(rank + 1)
            for rank, manual_id in enumerate(top, start=1)
            if manual_id in expected
        )
        ideal = sum(1.0 / math.log2(rank + 1) for rank in range(1, min(len(expected), k) + 1))
        result[f"ndcg_at_{k}"] = dcg / ideal if ideal else 0.0
    first = next((rank for rank, manual_id in enumerate(ranking, start=1) if manual_id in expected), None)
    result["mrr_at_10"] = 1.0 / first if first and first <= 10 else 0.0
    hits = 0
    precision_sum = 0.0
    for rank, manual_id in enumerate(ranking[:10], start=1):
        if manual_id in expected:
            hits += 1
            precision_sum += hits / rank
    result["map_at_10"] = precision_sum / min(len(expected), 10)
    return result


def aggregate(records: list[dict], ranking_key: str) -> dict[str, float]:
    rows = [row[ranking_key] for row in records]
    keys = rows[0].keys()
    return {key: round(statistics.mean(row[key] for row in rows), 6) for key in keys}


def subset(records: list[dict], ranking_key: str, predicate) -> dict[str, float]:
    selected = [row for row in records if predicate(row)]
    return aggregate(selected, ranking_key) if selected else {}


def bootstrap_delta(baseline: list[float], candidate: list[float]) -> dict[str, float]:
    rng = random.Random(SEED)
    count = len(baseline)
    deltas = []
    for _ in range(BOOTSTRAP_SAMPLES):
        indexes = [rng.randrange(count) for _ in range(count)]
        deltas.append(statistics.mean(candidate[index] - baseline[index] for index in indexes))
    return {
        "mean": round(statistics.mean(candidate) - statistics.mean(baseline), 6),
        "ci95_lower": percentile(deltas, 0.025),
        "ci95_upper": percentile(deltas, 0.975),
        "samples": BOOTSTRAP_SAMPLES,
        "seed": SEED,
    }


def score_pairs(model, tokenizer, query: str, passages: list[str], device: str) -> list[float]:
    scores = []
    for start in range(0, len(passages), BATCH_SIZE):
        batch = passages[start:start + BATCH_SIZE]
        encoded = tokenizer(
            [query] * len(batch),
            batch,
            padding=True,
            truncation=True,
            max_length=MAX_LENGTH,
            return_tensors="pt",
        ).to(device)
        with torch.inference_mode():
            logits = model(**encoded).logits.float().reshape(-1)
        scores.extend(float(value) for value in logits.cpu())
    return scores


def evaluate_model(spec: dict, source: dict, baseline_rows: list[dict]) -> dict:
    device = "cuda" if torch.cuda.is_available() else "cpu"
    revision = HfApi().model_info(spec["model_id"]).sha
    if device == "cuda":
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats()
    loaded_at = time.perf_counter()
    tokenizer = AutoTokenizer.from_pretrained(spec["model_id"], revision=revision)
    model = AutoModelForSequenceClassification.from_pretrained(
        spec["model_id"],
        revision=revision,
        trust_remote_code=spec["trust_remote_code"],
        torch_dtype=torch.float16 if device == "cuda" else torch.float32,
    ).to(device).eval()
    load_seconds = time.perf_counter() - loaded_at

    warmup = source["records"][0]
    score_pairs(model, tokenizer, warmup["query"], [item["passage"] for item in warmup["candidates"][:4]], device)
    if device == "cuda":
        torch.cuda.synchronize()

    rows = []
    latencies = []
    pairs = 0
    for source_row, baseline_row in zip(source["records"], baseline_rows, strict=True):
        candidates = [dict(item) for item in source_row["candidates"]]
        started = time.perf_counter()
        scores = score_pairs(model, tokenizer, source_row["query"], [item["passage"] for item in candidates], device)
        if device == "cuda":
            torch.cuda.synchronize()
        elapsed = (time.perf_counter() - started) * 1000
        latencies.append(elapsed)
        pairs += len(candidates)
        for item, score in zip(candidates, scores, strict=True):
            item["reranker_score"] = score
        ranking = document_ranking(candidates, "reranker_score")
        expected = set(source_row["expected_manual_ids"])
        rows.append({
            "id": source_row["id"],
            "difficulty": source_row["difficulty"],
            "domain": source_row["domain"],
            "ranking": ranking,
            "metrics": query_metrics(ranking, expected),
            "baseline_metrics": baseline_row["metrics"],
        })

    metrics = aggregate(rows, "metrics")
    baseline_metrics = aggregate(rows, "baseline_metrics")
    ndcg_baseline = [row["baseline_metrics"]["ndcg_at_5"] for row in rows]
    ndcg_candidate = [row["metrics"]["ndcg_at_5"] for row in rows]
    mrr_baseline = [row["baseline_metrics"]["mrr_at_10"] for row in rows]
    mrr_candidate = [row["metrics"]["mrr_at_10"] for row in rows]
    wins = sum(candidate > baseline + 1e-12 for baseline, candidate in zip(mrr_baseline, mrr_candidate))
    losses = sum(candidate + 1e-12 < baseline for baseline, candidate in zip(mrr_baseline, mrr_candidate))
    ties = len(rows) - wins - losses
    peak_vram = torch.cuda.max_memory_allocated() / 1024**3 if device == "cuda" else 0.0
    runtime = {
        "device": device,
        "load_seconds": round(load_seconds, 3),
        "average_ms": round(statistics.mean(latencies), 3),
        "p50_ms": percentile(latencies, 0.50),
        "p95_ms": percentile(latencies, 0.95),
        "maximum_ms": round(max(latencies), 3),
        "pairs_per_second": round(pairs / (sum(latencies) / 1000), 2),
        "peak_vram_gb": round(peak_vram, 3),
    }
    delta = {key: round(metrics[key] - baseline_metrics[key], 6) for key in metrics}
    ndcg_ci = bootstrap_delta(ndcg_baseline, ndcg_candidate)
    mrr_ci = bootstrap_delta(mrr_baseline, mrr_candidate)
    eligible = (
        delta["ndcg_at_5"] >= SELECTION_RULE["minimum_ndcg_at_5_delta"]
        and ndcg_ci["ci95_lower"] > SELECTION_RULE["bootstrap_95_ci_lower_must_exceed"]
        and delta["recall_at_5"] >= -SELECTION_RULE["maximum_recall_at_5_regression"]
        and runtime["p95_ms"] <= SELECTION_RULE["maximum_gpu_p95_ms"]
    )
    result = {
        **spec,
        "revision": revision,
        "max_length": MAX_LENGTH,
        "batch_size": BATCH_SIZE,
        "metrics": metrics,
        "delta_vs_hybrid": delta,
        "hard_metrics": subset(rows, "metrics", lambda row: row["difficulty"] == "HARD"),
        "cross_domain_metrics": subset(rows, "metrics", lambda row: row["domain"] == "CROSS_DOMAIN"),
        "bootstrap_delta_ndcg_at_5": ndcg_ci,
        "bootstrap_delta_mrr_at_10": mrr_ci,
        "paired_win_tie_loss_by_mrr": {"win": wins, "tie": ties, "loss": losses},
        "runtime": runtime,
        "eligible": eligible,
        "error_count": 0,
        "records": rows,
    }
    del model, tokenizer
    gc.collect()
    if device == "cuda":
        torch.cuda.empty_cache()
    return result


def main() -> None:
    raw = CANDIDATES.read_bytes()
    source = json.loads(raw)
    baseline_rows = []
    for row in source["records"]:
        ranking = document_ranking(row["candidates"])
        expected = set(row["expected_manual_ids"])
        baseline_rows.append({
            "id": row["id"],
            "difficulty": row["difficulty"],
            "domain": row["domain"],
            "ranking": ranking,
            "metrics": query_metrics(ranking, expected),
        })
    baseline = {
        "name": "OPENAI_LARGE_1024_HYBRID_65_35",
        "metrics": aggregate(baseline_rows, "metrics"),
        "hard_metrics": subset(baseline_rows, "metrics", lambda row: row["difficulty"] == "HARD"),
        "cross_domain_metrics": subset(baseline_rows, "metrics", lambda row: row["domain"] == "CROSS_DOMAIN"),
        "candidate_recall": round(statistics.mean(
            len(set(row["expected_manual_ids"]).intersection(document_ranking(row["candidates"]))) / len(row["expected_manual_ids"])
            for row in source["records"]
        ), 6),
        "retrieval_runtime": source["retrieval"],
        "records": baseline_rows,
    }
    results = []
    for spec in MODELS:
        try:
            results.append(evaluate_model(spec, source, baseline_rows))
        except Exception as error:
            results.append({
                **spec,
                "eligible": False,
                "error_count": 1,
                "error": f"{type(error).__name__}: {error}",
                "traceback": traceback.format_exc(),
            })
    output = {
        "schema_version": "1.0",
        "measured_at": datetime.now(timezone.utc).astimezone().isoformat(),
        "candidate_file_sha256": hashlib.sha256(raw).hexdigest(),
        "evaluation_status": "ENGINEERING_REVIEW_CANDIDATE_NOT_BUSINESS_GOLD",
        "selection_rule_frozen_before_inference": SELECTION_RULE,
        "protocol": {
            "candidate_pool": "same hybrid top-20 chunks for every reranker",
            "forced_positive_injection": False,
            "relevance": "binary document-level",
            "primary_metric": "nDCG@5",
            "secondary_metrics": ["Recall@1/3/5/10", "MRR@10", "MAP@10"],
            "statistics": "paired bootstrap 10000 samples",
        },
        "environment": {
            "torch": torch.__version__,
            "transformers": __import__("transformers").__version__,
            "cuda_available": torch.cuda.is_available(),
            "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
        },
        "baseline": baseline,
        "rerankers": results,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
