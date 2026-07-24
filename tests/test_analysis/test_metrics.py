"""metrics.py 단위 테스트.

결정론성 검증: 동일 입력 N회 호출 → 동일 출력.
NEGATIVE 감성 비율 KPI 계산 검증.
"""

from __future__ import annotations

from src.analysis.metrics import KpiResult, VocKpi, calculate_kpis


# ---------------------------------------------------------------------------
# 테스트 픽스처
# ---------------------------------------------------------------------------

_SAMPLE_VOC: list[dict[str, object]] = [
    {"voc_id": "voc-001", "sentiment_label": "NEGATIVE", "topic_code": "객실"},
    {"voc_id": "voc-002", "sentiment_label": "NEUTRAL", "topic_code": "시설"},
    {"voc_id": "voc-003", "sentiment_label": "POSITIVE", "topic_code": "서비스"},
    {"voc_id": "voc-004", "sentiment_label": "NEGATIVE", "topic_code": "식음료"},
    {"voc_id": "voc-005", "sentiment_label": "NEGATIVE", "topic_code": "객실"},
]

_ALL_NEGATIVE: list[dict[str, object]] = [
    {"voc_id": "voc-001", "sentiment_label": "NEGATIVE", "topic_code": "객실"},
    {"voc_id": "voc-002", "sentiment_label": "NEGATIVE", "topic_code": "시설"},
]

_ALL_POSITIVE: list[dict[str, object]] = [
    {"voc_id": "voc-001", "sentiment_label": "POSITIVE", "topic_code": "객실"},
    {"voc_id": "voc-002", "sentiment_label": "POSITIVE", "topic_code": "시설"},
]

_EMPTY_VOC: list[dict[str, object]] = []


# ---------------------------------------------------------------------------
# 결정론성 테스트
# ---------------------------------------------------------------------------


class TestDeterminism:
    """동일 입력 N회 호출 → 동일 출력 검증."""

    def test_calculate_kpis_deterministic(self) -> None:
        """calculate_kpis는 동일 입력에 대해 동일 결과를 반환해야 한다."""
        results = [calculate_kpis(_SAMPLE_VOC) for _ in range(3)]
        first = results[0]
        for r in results[1:]:
            assert r.voc.total_count == first.voc.total_count
            assert r.voc.negative_count == first.voc.negative_count
            assert r.voc.negative_rate == first.voc.negative_rate
            assert r.voc.topic_breakdown == first.voc.topic_breakdown


# ---------------------------------------------------------------------------
# 기본 KPI 계산
# ---------------------------------------------------------------------------


class TestBasicCalculation:
    """기본 KPI 계산 검증."""

    def test_total_count(self) -> None:
        result = calculate_kpis(_SAMPLE_VOC)
        assert result.voc.total_count == 5

    def test_negative_count(self) -> None:
        result = calculate_kpis(_SAMPLE_VOC)
        assert result.voc.negative_count == 3

    def test_neutral_count(self) -> None:
        result = calculate_kpis(_SAMPLE_VOC)
        assert result.voc.neutral_count == 1

    def test_positive_count(self) -> None:
        result = calculate_kpis(_SAMPLE_VOC)
        assert result.voc.positive_count == 1

    def test_negative_rate(self) -> None:
        """3/5 = 0.6"""
        result = calculate_kpis(_SAMPLE_VOC)
        assert result.voc.negative_rate == 0.6


# ---------------------------------------------------------------------------
# 주제별 분해
# ---------------------------------------------------------------------------


class TestTopicBreakdown:
    """주제별 NEGATIVE 건수 분해."""

    def test_breakdown_keys(self) -> None:
        result = calculate_kpis(_SAMPLE_VOC)
        assert "객실" in result.voc.topic_breakdown
        assert "식음료" in result.voc.topic_breakdown

    def test_breakdown_values(self) -> None:
        result = calculate_kpis(_SAMPLE_VOC)
        assert result.voc.topic_breakdown["객실"] == 2
        assert result.voc.topic_breakdown["식음료"] == 1


# ---------------------------------------------------------------------------
# 엣지 케이스
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """엣지 케이스 검증."""

    def test_all_negative(self) -> None:
        result = calculate_kpis(_ALL_NEGATIVE)
        assert result.voc.negative_rate == 1.0
        assert result.voc.negative_count == 2

    def test_all_positive(self) -> None:
        result = calculate_kpis(_ALL_POSITIVE)
        assert result.voc.negative_rate == 0.0
        assert result.voc.negative_count == 0

    def test_empty_voc(self) -> None:
        result = calculate_kpis(_EMPTY_VOC)
        assert result.voc.total_count == 0
        assert result.voc.negative_rate == 0.0

    def test_invalid_sentiment_label_ignored(self) -> None:
        items = [
            {"voc_id": "voc-001", "sentiment_label": "INVALID"},
            {"voc_id": "voc-002", "sentiment_label": "NEGATIVE"},
        ]
        result = calculate_kpis(items)
        assert result.voc.total_count == 2
        assert result.voc.negative_count == 1
        assert result.voc.neutral_count == 0
        assert result.voc.positive_count == 0

    def test_none_sentiment_label_ignored(self) -> None:
        items = [
            {"voc_id": "voc-001", "sentiment_label": None},
            {"voc_id": "voc-002", "sentiment_label": "NEGATIVE"},
        ]
        result = calculate_kpis(items)
        assert result.voc.total_count == 2
        assert result.voc.negative_count == 1


# ---------------------------------------------------------------------------
# KPI 딕셔너리 호환성
# ---------------------------------------------------------------------------


class TestKpiDictionary:
    """전체 KPI 딕셔너리 (호환성용) 검증."""

    def test_kpis_dict_keys(self) -> None:
        result = calculate_kpis(_SAMPLE_VOC)
        expected_keys = {
            "total_voc_count",
            "negative_count",
            "neutral_count",
            "positive_count",
            "negative_rate",
            "negative_topic_breakdown",
        }
        assert set(result.kpis.keys()) == expected_keys

    def test_result_is_frozen_dataclass(self) -> None:
        result = calculate_kpis(_SAMPLE_VOC)
        assert isinstance(result, KpiResult)
        assert isinstance(result.voc, VocKpi)
