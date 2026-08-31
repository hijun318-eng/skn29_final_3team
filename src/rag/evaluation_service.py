"""RAG 검색 결과의 recall·인용·점수 품질을 질문 suite로 평가한다."""

from __future__ import annotations

import math
from typing import Any

from .access_policy import SearchAccessPolicy
from .qwen_embedding import QwenEmbeddingProvider
from .retrieval_service import VectorRetrievalService
from .vector_models import has_complete_locator


class QualityEvaluator:
    """접근 정책을 적용한 검색 결과를 기대 문서와 비교해 품질 지표를 계산한다."""

    def __init__(
        self,
        policy: SearchAccessPolicy,
        retrieval: VectorRetrievalService,
        embedding: QwenEmbeddingProvider,
    ) -> None:
        self._policy = policy
        self._retrieval = retrieval
        self._embedding = embedding

    def evaluate(
        self,
        queries: list[dict[str, object]],
        status: str,
        schema_version: str,
        seed: int | None = None,
    ) -> dict[str, object]:
        """질문별 retrieval을 실행하고 hit·citation completeness를 집계한다."""

        decision = self._policy.decide("MANAGER", 10)
        vectors = self._embedding.embed_queries([str(item["query"]) for item in queries])
        details: list[dict[str, object]] = []
        top1_hits = top3_hits = top5_hits = 0
        negative_hits = positive_count = negative_count = 0
        ndcg10_total = 0.0
        citation_complete = citation_count = 0
        type_metrics: dict[str, dict[str, Any]] = {}
        for item, vector in zip(queries, vectors, strict=True):
            results = self._retrieval.retrieve(str(item["query"]), vector, decision)
            retrieved = [result.manual_id for result in results]
            for result in results:
                citation_count += 1
                citation_complete += int(
                    result.manual_id in result.citation
                    and f"v{result.version}" in result.citation
                    and has_complete_locator(result)
                )
            expected = item["expected_manual_id"]
            if expected is None:
                negative_count += 1
                negative_hits += int(not retrieved)
            else:
                top1_hit = int(bool(retrieved and retrieved[0] == expected))
                top3_hit = int(expected in retrieved[:3])
                top5_hit = int(expected in retrieved[:5])
                rank = retrieved.index(expected) + 1 if expected in retrieved[:10] else None
                ndcg10 = 1 / math.log2(rank + 1) if rank else 0.0
                positive_count += 1
                top1_hits += top1_hit
                top3_hits += top3_hit
                top5_hits += top5_hit
                ndcg10_total += ndcg10
                self._add_type_metric(
                    type_metrics,
                    str(item["query_type"]),
                    top1_hit,
                    top3_hit,
                    top5_hit,
                    ndcg10,
                )
            details.append(
                {
                    "query_id": item["query_id"], "query_type": item["query_type"],
                    "expected_manual_id": expected,
                    "retrieved_manual_ids": retrieved,
                    "expected_rank": rank if expected is not None else None,
                }
            )
        return self._report(
            status, schema_version, seed, positive_count, negative_count,
            top1_hits, top3_hits, top5_hits, negative_hits, ndcg10_total,
            citation_complete, citation_count, type_metrics, details,
            decision.minimum_score,
        )

    @staticmethod
    def _add_type_metric(
        metrics: dict[str, dict[str, Any]], query_type: str,
        top1: int, top3: int, top5: int, ndcg10: float,
    ) -> None:
        bucket = metrics.setdefault(
            query_type,
            {"count": 0, "top1_hits": 0, "top3_hits": 0, "top5_hits": 0, "ndcg10": 0.0},
        )
        bucket["count"] += 1
        bucket["top1_hits"] += top1
        bucket["top3_hits"] += top3
        bucket["top5_hits"] += top5
        bucket["ndcg10"] += ndcg10

    @staticmethod
    def _report(
        status: str, schema_version: str, seed: int | None,
        positive_count: int, negative_count: int, top1_hits: int, top3_hits: int,
        top5_hits: int, negative_hits: int, ndcg10_total: float,
        citation_complete: int, citation_count: int,
        type_metrics: dict[str, dict[str, Any]],
        details: list[dict[str, object]], minimum_score: float,
    ) -> dict[str, Any]:
        recall1 = round(top1_hits / positive_count, 4) if positive_count else None
        recall3 = round(top3_hits / positive_count, 4) if positive_count else None
        recall5 = round(top5_hits / positive_count, 4) if positive_count else None
        ndcg10 = round(ndcg10_total / positive_count, 4) if positive_count else None
        citation_completeness = (
            round(citation_complete / citation_count, 4) if citation_count else None
        )
        negative_accuracy = round(negative_hits / negative_count, 4) if negative_count else None
        by_type = {
            name: {
                "count": value["count"],
                "recall_at_1": round(value["top1_hits"] / value["count"], 4),
                "recall_at_3": round(value["top3_hits"] / value["count"], 4),
                "recall_at_5": round(value["top5_hits"] / value["count"], 4),
                "ndcg_at_10": round(value["ndcg10"] / value["count"], 4),
            }
            for name, value in type_metrics.items()
        }
        gate_passed = bool(
            recall5 is not None and recall5 >= 0.8
            and ndcg10 is not None and ndcg10 >= 0.75
            and citation_completeness == 1.0
            and (negative_accuracy is None or negative_accuracy == 1.0)
        )
        return {
            "status": "SUCCESS",
            "synthetic_technical_gate": "PASSED" if gate_passed else "NOT_PASSED",
            "production_readiness_gate": "NOT_RUN_HUMAN_APPROVAL_REQUIRED",
            "quality_gate_thresholds": {
                "recall_at_5": 0.8,
                "ndcg_at_10": 0.75,
                "citation_metadata_completeness": 1.0,
                "negative_accuracy": 1.0,
            },
            "evaluation_set_status": status, "schema_version": schema_version, "seed": seed,
            "positive_query_count": positive_count, "negative_query_count": negative_count,
            "recall_at_1": recall1,
            "recall_at_3": recall3,
            "recall_at_5": recall5,
            "ndcg_at_10": ndcg10,
            "citation_metadata_completeness": citation_completeness,
            "citation_location_accuracy": "NOT_MEASURABLE_MISSING_GOLD_PAGE",
            "negative_no_evidence_accuracy": negative_accuracy,
            "metrics_by_query_type": by_type, "minimum_score": minimum_score,
            "document_level_deduplication": True, "details": details,
        }
