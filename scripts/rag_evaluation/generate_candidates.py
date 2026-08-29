from __future__ import annotations

import hashlib
import json
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path

from src.rag.vector_application import VectorRagApplication


DATASET = Path("/tmp/reranker_dataset.json")
TOP_K = 20


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * fraction)))
    return round(ordered[index], 2)


def main() -> None:
    raw = DATASET.read_bytes()
    dataset = json.loads(raw)
    app = VectorRagApplication(Path("/workspace"))
    decision = app._policy.decide("MANAGER", 10)
    records = []
    latencies = []

    for item in dataset["queries"]:
        started = time.perf_counter()
        vector = app._get_embedding().embed_query(item["query"])
        candidates = app._repository.search(
            vector,
            item["query"],
            decision.role,
            TOP_K,
            0.0,
            decision.allow_unresolved_validity,
            (),
            retrieval_mode="HYBRID",
            maximum_chunks_per_document=2,
        )
        latency = (time.perf_counter() - started) * 1000
        latencies.append(latency)
        records.append({
            **item,
            "retrieval_ms": round(latency, 2),
            "candidates": [
                {
                    "rank": rank,
                    "manual_id": candidate.manual_id,
                    "title": candidate.title,
                    "section_title": candidate.section_title,
                    "page_start": candidate.page_start,
                    "score": candidate.score,
                    "vector_score": candidate.vector_score,
                    "lexical_score": candidate.lexical_score,
                    "evidence_id": candidate.evidence_id,
                    "passage": (
                        f"문서명: {candidate.title}\n"
                        f"영역: {candidate.section_title}\n"
                        f"본문: {candidate.content}"
                    ),
                }
                for rank, candidate in enumerate(candidates, start=1)
            ],
        })

    output = {
        "schema_version": "1.0",
        "created_at": datetime.now(timezone.utc).astimezone().isoformat(),
        "dataset_sha256": hashlib.sha256(raw).hexdigest(),
        "retrieval": {
            "embedding_model": app.status()["model_id"],
            "embedding_dimension": app.status()["expected_dimension"],
            "mode": "HYBRID",
            "dense_weight": 0.65,
            "bm25_weight": 0.35,
            "candidate_top_k": TOP_K,
            "minimum_score": 0.0,
            "maximum_chunks_per_document": 2,
            "query_count": len(records),
            "average_ms": round(statistics.mean(latencies), 2),
            "p50_ms": percentile(latencies, 0.50),
            "p95_ms": percentile(latencies, 0.95),
        },
        "records": records,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
