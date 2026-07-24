"""quality.py 단위 테스트.

결정론성 검증: 동일 입력 N회 호출 → 동일 출력.
DSG §11 기반 품질 게이트 각 검사 항목별 테스트.
"""

from __future__ import annotations

from src.analysis.quality import (
    QualityCheck,
    QualityGateResult,
    VOC_COMPLETENESS_MIN,
    SENTIMENT_COVERAGE_MIN,
    run_quality_gate,
)


# ---------------------------------------------------------------------------
# 테스트 픽스처
# ---------------------------------------------------------------------------

_VALID_VOC_ITEMS: list[dict[str, object]] = [
    {"voc_id": f"voc-{i:03d}", "sentiment_label": label, "topic_code": "객실"}
    for i, label in enumerate(
        ["NEGATIVE", "NEUTRAL", "POSITIVE", "NEGATIVE", "NEUTRAL"]
    )
]

_EMPTY_VOC_ITEMS: list[dict[str, object]] = []

_INCOMPLETE_VOC_ITEMS: list[dict[str, object]] = [
    {"voc_id": "voc-001", "sentiment_label": "NEGATIVE"},
    {"voc_id": "voc-002", "sentiment_label": None},
    {"voc_id": "voc-003", "sentiment_label": "POSITIVE"},
    {"voc_id": "voc-004", "sentiment_label": None},
    {"voc_id": "voc-005", "sentiment_label": "NEUTRAL"},
]


# ---------------------------------------------------------------------------
# 결정론성 테스트
# ---------------------------------------------------------------------------


class TestDeterminism:
    """동일 입력 N회 호출 → 동일 출력 검증."""

    def test_quality_gate_deterministic(self) -> None:
        """run_quality_gate는 동일 입력에 대해 동일 결과를 반환해야 한다."""
        results = [run_quality_gate(_VALID_VOC_ITEMS) for _ in range(3)]
        first = results[0]
        for r in results[1:]:
            assert r.passed == first.passed
            assert r.summary == first.summary
            assert len(r.checks) == len(first.checks)
            for c1, c2 in zip(r.checks, first.checks):
                assert c1.gate == c2.gate
                assert c1.passed == c2.passed


# ---------------------------------------------------------------------------
# PK 중복 검사
# ---------------------------------------------------------------------------


class TestPkDuplicateCheck:
    """§11.1: PK 중복 0건 검사."""

    def test_no_duplicates_passes(self) -> None:
        result = run_quality_gate(_VALID_VOC_ITEMS)
        pk_check = next(c for c in result.checks if c.gate == "pk_duplicate")
        assert pk_check.passed is True
        assert "PK 중복 없음" in pk_check.message

    def test_duplicates_fail(self) -> None:
        items = [
            {"voc_id": "voc-001", "sentiment_label": "NEGATIVE"},
            {"voc_id": "voc-001", "sentiment_label": "POSITIVE"},
        ]
        result = run_quality_gate(items)
        pk_check = next(c for c in result.checks if c.gate == "pk_duplicate")
        assert pk_check.passed is False
        assert "1건 발견" in pk_check.message


# ---------------------------------------------------------------------------
# VOC 완전성 검사
# ---------------------------------------------------------------------------


class TestVocCompleteness:
    """VOC 데이터 완전성 검사."""

    def test_complete_data_passes(self) -> None:
        result = run_quality_gate(_VALID_VOC_ITEMS)
        check = next(c for c in result.checks if c.gate == "voc_completeness")
        assert check.passed is True

    def test_incomplete_data_fails(self) -> None:
        """sentiment_label이 null인 비율이 임계값 미만이면 실패."""
        result = run_quality_gate(_INCOMPLETE_VOC_ITEMS)
        check = next(c for c in result.checks if c.gate == "voc_completeness")
        # 3/5 = 60% → 95% 미만
        assert check.passed is False

    def test_empty_data_fails(self) -> None:
        result = run_quality_gate(_EMPTY_VOC_ITEMS)
        check = next(c for c in result.checks if c.gate == "voc_completeness")
        assert check.passed is False


# ---------------------------------------------------------------------------
# 감성 커버리지 검사
# ---------------------------------------------------------------------------


class TestSentimentCoverage:
    """감성 분석 커버리지 검사."""

    def test_full_coverage_passes(self) -> None:
        result = run_quality_gate(_VALID_VOC_ITEMS)
        check = next(c for c in result.checks if c.gate == "sentiment_coverage")
        assert check.passed is True
        # 100% 커버리지
        assert check.details["rate"] == 1.0

    def test_partial_coverage_fails(self) -> None:
        """sentiment_label이 유효하지 않은 값이 있으면 커버리지가 떨어진다."""
        items = [
            {"voc_id": "voc-001", "sentiment_label": "INVALID"},
            {"voc_id": "voc-002", "sentiment_label": None},
            {"voc_id": "voc-003", "sentiment_label": "NEGATIVE"},
            {"voc_id": "voc-004", "sentiment_label": None},
            {"voc_id": "voc-005", "sentiment_label": None},
        ]
        result = run_quality_gate(items)
        check = next(c for c in result.checks if c.gate == "sentiment_coverage")
        # 1/5 = 20% → 90% 미만
        assert check.passed is False


# ---------------------------------------------------------------------------
# 음수 값 검사
# ---------------------------------------------------------------------------


class TestNegativeValues:
    """§11.4: 음수 값 0건 검사."""

    def test_no_negatives_passes(self) -> None:
        items = [
            {"avg_wait_min": 5.0, "p90_wait_min": 10.0, "actual_arrivals": 20},
        ]
        result = run_quality_gate(_VALID_VOC_ITEMS, numeric_items=items)
        check = next(c for c in result.checks if c.gate == "negative_values")
        assert check.passed is True

    def test_negative_value_fails(self) -> None:
        items = [
            {"avg_wait_min": -1.0, "p90_wait_min": 10.0},
        ]
        result = run_quality_gate(_VALID_VOC_ITEMS, numeric_items=items)
        check = next(c for c in result.checks if c.gate == "negative_values")
        assert check.passed is False


# ---------------------------------------------------------------------------
# occurred_at 순서 검사
# ---------------------------------------------------------------------------


class TestOccurredAtOrder:
    """§11.6: occurred_at <= received_at 검사."""

    def test_valid_order_passes(self) -> None:
        items = [
            {
                "voc_id": "voc-001",
                "received_at": "2026-07-20T12:00:00+00:00",
                "occurred_at": "2026-07-20T11:00:00+00:00",
            },
        ]
        result = run_quality_gate(items)
        check = next(c for c in result.checks if c.gate == "occurred_at_order")
        assert check.passed is True

    def test_invalid_order_fails(self) -> None:
        items = [
            {
                "voc_id": "voc-001",
                "received_at": "2026-07-20T11:00:00+00:00",
                "occurred_at": "2026-07-20T12:00:00+00:00",
            },
        ]
        result = run_quality_gate(items)
        check = next(c for c in result.checks if c.gate == "occurred_at_order")
        assert check.passed is False
        assert len(check.details["violations"]) == 1


# ---------------------------------------------------------------------------
# Bucket 완전성 검사
# ---------------------------------------------------------------------------


class TestBucketCompleteness:
    """§11.7: 필수 bucket 누락 검사."""

    def test_complete_buckets_passes(self) -> None:
        result = run_quality_gate(
            _VALID_VOC_ITEMS, expected_buckets=10, actual_buckets=10
        )
        check = next(c for c in result.checks if c.gate == "bucket_completeness")
        assert check.passed is True

    def test_missing_buckets_fails(self) -> None:
        result = run_quality_gate(
            _VALID_VOC_ITEMS, expected_buckets=10, actual_buckets=8
        )
        check = next(c for c in result.checks if c.gate == "bucket_completeness")
        assert check.passed is False
        assert check.details["missing"] == 2


# ---------------------------------------------------------------------------
# 전체 판정
# ---------------------------------------------------------------------------


class TestOverallResult:
    """전체 품질 게이트 판정."""

    def test_all_pass(self) -> None:
        result = run_quality_gate(_VALID_VOC_ITEMS)
        assert result.passed is True
        assert "통과" in result.summary

    def test_any_fail_means_overall_fail(self) -> None:
        result = run_quality_gate(_INCOMPLETE_VOC_ITEMS)
        assert result.passed is False
        assert "실패" in result.summary

    def test_checks_count(self) -> None:
        """기본 호출 시 4개 검사 (pk, 완전성, 커버리지, occurred_at)."""
        result = run_quality_gate(_VALID_VOC_ITEMS)
        assert len(result.checks) == 4

    def test_with_all_options(self) -> None:
        """numeric_items와 bucket까지 포함하면 6개 검사."""
        items = [{"avg_wait_min": 5.0}]
        result = run_quality_gate(
            _VALID_VOC_ITEMS,
            numeric_items=items,
            expected_buckets=10,
            actual_buckets=10,
        )
        assert len(result.checks) == 6

    def test_result_is_frozen_dataclass(self) -> None:
        """QualityGateResult는 frozen dataclass여야 한다."""
        result = run_quality_gate(_VALID_VOC_ITEMS)
        assert isinstance(result, QualityGateResult)
        assert isinstance(result.checks[0], QualityCheck)
