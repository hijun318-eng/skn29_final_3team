from __future__ import annotations

import hashlib
import json
import math
import os
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean


ROOT = Path(__file__).resolve().parent
SOURCE = Path(os.environ.get("RAG_RERANK_CANDIDATES", ROOT / "reranker_candidates.json"))
OUTPUT = Path(os.environ.get("RAG_BM25_OUTPUT", ROOT / "bm25_ablation_result.json"))
SEED = 20260829
BOOTSTRAP_SAMPLES = 10_000


class AblationEvaluator:
    KS = (1, 3, 5, 10)

    def __init__(self, source: dict) -> None:
        self.source = source
        self.records = source["records"]

    @staticmethod
    def _score(value: object) -> float:
        return float(value) if value is not None else -1.0

    @staticmethod
    def _unique_documents(candidates: list[dict]) -> list[str]:
        seen: set[str] = set()
        ranked: list[str] = []
        for item in candidates:
            manual_id = str(item["manual_id"])
            if manual_id not in seen:
                seen.add(manual_id)
                ranked.append(manual_id)
        return ranked

    def _ranking(self, record: dict, system: str) -> list[str]:
        candidates = list(record["candidates"])
        if system == "dense_only":
            candidates.sort(
                key=lambda item: (-self._score(item.get("vector_score")), int(item["rank"]))
            )
        elif system == "bm25_only":
            candidates.sort(
                key=lambda item: (-self._score(item.get("lexical_score")), int(item["rank"]))
            )
        elif system != "hybrid_65_35":
            raise ValueError(f"unknown system: {system}")
        return self._unique_documents(candidates)

    def _query_metrics(self, expected: set[str], ranked: list[str]) -> dict[str, float]:
        result: dict[str, float] = {}
        for k in self.KS:
            top = ranked[:k]
            hits = [1 if item in expected else 0 for item in top]
            relevant = sum(hits)
            ideal_count = min(len(expected), k)
            dcg = sum(hit / math.log2(index + 2) for index, hit in enumerate(hits))
            idcg = sum(1 / math.log2(index + 2) for index in range(ideal_count))
            result[f"recall_at_{k}"] = relevant / len(expected)
            result[f"hit_at_{k}"] = 1.0 if relevant else 0.0
            result[f"ndcg_at_{k}"] = dcg / idcg if idcg else 0.0

        reciprocal_rank = 0.0
        precision_sum = 0.0
        relevant_seen = 0
        for index, item in enumerate(ranked[:10], start=1):
            if item in expected:
                relevant_seen += 1
                precision_sum += relevant_seen / index
                if reciprocal_rank == 0.0:
                    reciprocal_rank = 1.0 / index
        result["mrr_at_10"] = reciprocal_rank
        result["map_at_10"] = precision_sum / min(len(expected), 10)
        return result

    @staticmethod
    def _aggregate(rows: list[dict[str, float]]) -> dict[str, float]:
        if not rows:
            return {}
        return {
            key: round(mean(row[key] for row in rows), 6)
            for key in rows[0]
        }

    @staticmethod
    def _percentile(values: list[float], probability: float) -> float:
        ordered = sorted(values)
        index = min(len(ordered) - 1, max(0, math.ceil(probability * len(ordered)) - 1))
        return ordered[index]

    def _bootstrap(self, target: list[float], control: list[float]) -> dict[str, float | int]:
        rng = random.Random(SEED)
        size = len(target)
        deltas = []
        for _ in range(BOOTSTRAP_SAMPLES):
            indexes = [rng.randrange(size) for _ in range(size)]
            deltas.append(mean(target[i] - control[i] for i in indexes))
        return {
            "mean": round(mean(target[i] - control[i] for i in range(size)), 6),
            "ci95_lower": round(self._percentile(deltas, 0.025), 4),
            "ci95_upper": round(self._percentile(deltas, 0.975), 4),
            "samples": BOOTSTRAP_SAMPLES,
            "seed": SEED,
        }

    def evaluate(self) -> dict:
        systems = ("dense_only", "bm25_only", "hybrid_65_35")
        per_system: dict[str, list[dict[str, float]]] = {name: [] for name in systems}
        per_query: list[dict] = []

        for record in self.records:
            expected = set(record["expected_manual_ids"])
            query_result = {"id": record["id"], "difficulty": record["difficulty"], "systems": {}}
            for system in systems:
                metrics = self._query_metrics(expected, self._ranking(record, system))
                per_system[system].append(metrics)
                query_result["systems"][system] = metrics
            per_query.append(query_result)

        system_results = {}
        for system in systems:
            rows = per_system[system]
            hard_indexes = [
                i for i, record in enumerate(self.records)
                if str(record["difficulty"]).upper() == "HARD"
            ]
            cross_indexes = [
                i for i, record in enumerate(self.records)
                if str(record["domain"]).upper() == "CROSS_DOMAIN"
            ]
            system_results[system] = {
                "metrics": self._aggregate(rows),
                "hard_metrics": self._aggregate([rows[i] for i in hard_indexes]),
                "cross_domain_metrics": self._aggregate([rows[i] for i in cross_indexes]),
            }

        hybrid = per_system["hybrid_65_35"]
        comparisons = {}
        for control_name in ("dense_only", "bm25_only"):
            control = per_system[control_name]
            comparisons[f"hybrid_vs_{control_name}"] = {
                "ndcg_at_5": self._bootstrap(
                    [row["ndcg_at_5"] for row in hybrid],
                    [row["ndcg_at_5"] for row in control],
                ),
                "mrr_at_10": self._bootstrap(
                    [row["mrr_at_10"] for row in hybrid],
                    [row["mrr_at_10"] for row in control],
                ),
            }

        return {
            "schema_version": "1.0",
            "measured_at": datetime.now(timezone(timedelta(hours=9))).isoformat(),
            "source_sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
            "evaluation_status": "FIXED_CANDIDATE_COMPONENT_ABLATION_NOT_END_TO_END",
            "protocol": {
                "query_count": len(self.records),
                "candidate_pool": "same hybrid top-20 chunks",
                "forced_positive_injection": False,
                "ranking_unit": "document-deduplicated",
                "relevance": "binary document-level",
                "primary_metric": "nDCG@5",
                "statistics": "paired bootstrap 10000 samples",
                "limitation": "dense-only and BM25-only candidates outside hybrid top-20 are not observed",
            },
            "systems": system_results,
            "comparisons": comparisons,
            "records": per_query,
        }


def main() -> None:
    source = json.loads(SOURCE.read_text(encoding="utf-8-sig"))
    result = AblationEvaluator(source).evaluate()
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(OUTPUT)


if __name__ == "__main__":
    main()
