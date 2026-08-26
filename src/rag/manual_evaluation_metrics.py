from __future__ import annotations

import math


class ManualEvaluationMetrics:
    @staticmethod
    def retrieval(items: list[dict[str, object]]) -> dict[str, float | int | None]:
        count = len(items)
        if not count:
            return {
                "count": 0,
                "recall_at_1": None,
                "recall_at_3": None,
                "recall_at_5": None,
                "allowed_hit_at_1": None,
                "allowed_hit_at_3": None,
                "allowed_hit_at_5": None,
                "ndcg_at_10": None,
            }
        return {
            "count": count,
            "recall_at_1": round(sum(item["primary_rank"] == 1 for item in items) / count, 4),
            "recall_at_3": ManualEvaluationMetrics._hit_rate(items, "primary_rank", 3),
            "recall_at_5": ManualEvaluationMetrics._hit_rate(items, "primary_rank", 5),
            "allowed_hit_at_1": round(sum(item["allowed_rank"] == 1 for item in items) / count, 4),
            "allowed_hit_at_3": ManualEvaluationMetrics._hit_rate(items, "allowed_rank", 3),
            "allowed_hit_at_5": ManualEvaluationMetrics._hit_rate(items, "allowed_rank", 5),
            "ndcg_at_10": round(
                sum(
                    1 / math.log2(int(item["primary_rank"]) + 1)
                    if item["primary_rank"] is not None and int(item["primary_rank"]) <= 10
                    else 0
                    for item in items
                ) / count,
                4,
            ),
        }

    @classmethod
    def grouped_retrieval(
        cls, items: list[dict[str, object]], field: str,
    ) -> dict[str, dict[str, float | int | None]]:
        values = sorted({str(item[field]) for item in items})
        return {
            value: cls.retrieval([item for item in items if item[field] == value])
            for value in values
        }

    @classmethod
    def negative_by_type(
        cls, items: list[dict[str, object]],
    ) -> dict[str, dict[str, float | int | None]]:
        values = sorted({str(item["query_type"]) for item in items})
        return {
            value: {
                "count": len(group),
                "no_evidence_accuracy": cls.no_evidence_accuracy(group),
            }
            for value in values
            if (group := [item for item in items if item["query_type"] == value])
        }

    @staticmethod
    def no_evidence_accuracy(items: list[dict[str, object]]) -> float | None:
        if not items:
            return None
        return round(sum(not item["retrieved_manual_ids"] for item in items) / len(items), 4)

    @staticmethod
    def gold_page_accuracy(items: list[dict[str, object]]) -> float | str:
        measured = [item["gold_page_hit"] for item in items if item["gold_page_hit"] is not None]
        if not measured:
            return "NOT_MEASURABLE_MISSING_GOLD_PAGE"
        return round(sum(bool(value) for value in measured) / len(measured), 4)

    @staticmethod
    def citation_completeness(items: list[dict[str, object]]) -> float | None:
        total = sum(int(item["citation_count"]) for item in items)
        complete = sum(int(item["complete_citation_count"]) for item in items)
        return round(complete / total, 4) if total else None

    @staticmethod
    def percentile(values: list[float], fraction: float) -> float:
        if not values:
            return 0.0
        ordered = sorted(values)
        return ordered[max(0, math.ceil(len(ordered) * fraction) - 1)]

    @staticmethod
    def _hit_rate(items: list[dict[str, object]], field: str, limit: int) -> float:
        return round(
            sum(item[field] is not None and int(item[field]) <= limit for item in items)
            / len(items),
            4,
        )
