"""KPI 계산 모듈.

DSG v2.0 기반으로 NEGATIVE 감성 비율만 KPI로 사용한다.
POSITIVE/NEUTRAL은 저장만 하고 KPI로 사용하지 않는다 (D11 결정).

모든 함수는 순수 함수로 DB/IO/네트워크 접근이 없다.

References:
    - docs/markdown/ai_docs/02_data_standard_guide.md (DSG v2.0)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from common.enums import SentimentLabel

# ---------------------------------------------------------------------------
# KPI 임계값 상수
# ---------------------------------------------------------------------------

#: NEGATIVE 감성 비율이 이 값 이상이면 위험으로 판정
NEGATIVE_RATE_CRITICAL: float = 0.30

#: NEGATIVE 감성 비율이 이 값 이상이면 경고
NEGATIVE_RATE_WARNING: float = 0.20


# ---------------------------------------------------------------------------
# 결과 모델
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class VocKpi:
    """VOC 관련 KPI 결과.

    Attributes:
        total_count: 전체 VOC 건수
        negative_count: NEGATIVE 감성 건수
        neutral_count: NEUTRAL 감성 건수
        positive_count: POSITIVE 감성 건수
        negative_rate: NEGATIVE 감성 비율 (0~1)
        topic_breakdown: 주제별 NEGATIVE 건수
    """

    total_count: int
    negative_count: int
    neutral_count: int
    positive_count: int
    negative_rate: float
    topic_breakdown: dict[str, int]


@dataclass(frozen=True, slots=True)
class KpiResult:
    """전체 KPI 계산 결과.

    Attributes:
        voc: VOC 관련 KPI
        kpis: 전체 KPI 딕셔너리 (호환성용)
    """

    voc: VocKpi
    kpis: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# KPI 계산 함수 (순수 함수)
# ---------------------------------------------------------------------------


def _count_by_sentiment(
    voc_items: list[dict[str, Any]],
) -> dict[str, int]:
    """감성 레이블별 건수를 센다.

    Args:
        voc_items: VOC 레코드 리스트 (sentiment_label 필드 필수)

    Returns:
        감성 레이블별 건수 딕셔너리
    """
    counts: dict[str, int] = {
        SentimentLabel.NEGATIVE.value: 0,
        SentimentLabel.NEUTRAL.value: 0,
        SentimentLabel.POSITIVE.value: 0,
    }
    for item in voc_items:
        label = item.get("sentiment_label")
        if isinstance(label, str) and label in counts:
            counts[label] += 1
    return counts


def _count_negative_by_topic(
    voc_items: list[dict[str, Any]],
) -> dict[str, int]:
    """주제별 NEGATIVE 건수를 센다.

    Args:
        voc_items: VOC 레코드 리스트

    Returns:
        주제별 NEGATIVE 건수 딕셔너리
    """
    breakdown: dict[str, int] = {}
    for item in voc_items:
        if item.get("sentiment_label") == SentimentLabel.NEGATIVE.value:
            topic = str(item.get("topic_code", "unknown"))
            breakdown[topic] = breakdown.get(topic, 0) + 1
    return breakdown


def _safe_divide(numerator: int, denominator: int) -> float:
    """0 나눗셈을 방지하는 안전한 나눗셈.

    Args:
        numerator: 분자
        denominator: 분모

    Returns:
        나눗셈 결과. 분모가 0이면 0.0
    """
    if denominator == 0:
        return 0.0
    return numerator / denominator


def calculate_kpis(
    voc_items: list[dict[str, Any]],
) -> KpiResult:
    """VOC 리스트에서 KPI를 계산한다.

    NEGATIVE 감성 비율만 KPI로 사용한다.
    POSITIVE/NEUTRAL은 저장만 하고 KPI 집계에서 제외하지는 않되
    최종 KPI 키로는 negative_rate만 사용한다.

    결정론적: 동일 입력 → 동일 출력.

    Args:
        voc_items: fact_voc 기반 VOC 레코드 리스트

    Returns:
        KpiResult: 계산된 KPI 결과
    """
    counts = _count_by_sentiment(voc_items)
    total = len(voc_items)
    negative = counts[SentimentLabel.NEGATIVE.value]
    neutral = counts[SentimentLabel.NEUTRAL.value]
    positive = counts[SentimentLabel.POSITIVE.value]
    negative_rate = _safe_divide(negative, total)
    topic_breakdown = _count_negative_by_topic(voc_items)

    voc_kpi = VocKpi(
        total_count=total,
        negative_count=negative,
        neutral_count=neutral,
        positive_count=positive,
        negative_rate=negative_rate,
        topic_breakdown=topic_breakdown,
    )

    # 전체 KPI 딕셔너리 (호환성 및 확장용)
    kpis: dict[str, Any] = {
        "total_voc_count": total,
        "negative_count": negative,
        "neutral_count": neutral,
        "positive_count": positive,
        "negative_rate": negative_rate,
        "negative_topic_breakdown": topic_breakdown,
    }

    return KpiResult(voc=voc_kpi, kpis=kpis)
