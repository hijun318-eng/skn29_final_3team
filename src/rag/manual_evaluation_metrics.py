"""매뉴얼 검색 평가 상세 결과에서 재현율·순위·인용 위치 지표를 집계한다."""

from __future__ import annotations

import math


class ManualEvaluationMetrics:
    """질문별 검색 순위와 인용 완결성 값을 재현 가능한 요약 지표로 계산한다."""

    @staticmethod
    def retrieval(items: list[dict[str, object]]) -> dict[str, float | int | None]:
        """긍정 질문의 primary·허용 정답 순위로 Recall@K와 nDCG@10을 계산한다.

        입력이 비어 있으면 표본 수는 0, 비율 지표는 ``None``으로 반환한다.
        """

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
        """지정 필드의 값별로 질문을 나눠 동일한 검색 순위 지표를 집계한다."""

        values = sorted({str(item[field]) for item in items})
        return {
            value: cls.retrieval([item for item in items if item[field] == value])
            for value in values
        }

    @classmethod
    def negative_by_type(
        cls, items: list[dict[str, object]],
    ) -> dict[str, dict[str, float | int | None]]:
        """부정 질문을 유형별로 묶어 근거가 반환되지 않은 정확도를 계산한다."""

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
        """검색 결과가 비어 있는 부정 질문 비율을 계산하고 표본이 없으면 ``None``을 준다."""

        if not items:
            return None
        return round(sum(not item["retrieved_manual_ids"] for item in items) / len(items), 4)

    @staticmethod
    def gold_page_accuracy(items: list[dict[str, object]]) -> float | str:
        """gold 페이지가 있는 질문만 대상으로 검색 위치가 겹친 비율을 계산한다."""

        measured = [item["gold_page_hit"] for item in items if item["gold_page_hit"] is not None]
        if not measured:
            return "NOT_MEASURABLE_MISSING_GOLD_PAGE"
        return round(sum(bool(value) for value in measured) / len(measured), 4)

    @staticmethod
    def citation_completeness(items: list[dict[str, object]]) -> float | None:
        """전체 인용 수 중 문서·버전·위치 메타데이터가 완전한 인용 비율을 반환한다."""

        total = sum(int(item["citation_count"]) for item in items)
        complete = sum(int(item["complete_citation_count"]) for item in items)
        return round(complete / total, 4) if total else None

    @staticmethod
    def percentile(values: list[float], fraction: float) -> float:
        """정렬 표본에서 nearest-rank 방식의 분위값을 구하고 빈 표본은 0으로 처리한다."""

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
