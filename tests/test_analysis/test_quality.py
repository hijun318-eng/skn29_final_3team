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
        """기본 호출 시 6개 검사 (pk, fk_orphan, 완전성, 커버리지, occurred_at, pii)."""
        result = run_quality_gate(_VALID_VOC_ITEMS)
        assert len(result.checks) == 6

    def test_with_all_options(self) -> None:
        """numeric_items, bucket, room, 15m/daily까지 포함하면 9개 검사."""
        items = [{"avg_wait_min": 5.0}]
        room = [
            {
                "service_date": "2026-07-20",
                "room_inventory": 100,
                "rooms_out_of_order": 5,
                "rooms_available": 95,
                "rooms_sold": 80,
            }
        ]
        result = run_quality_gate(
            _VALID_VOC_ITEMS,
            numeric_items=items,
            expected_buckets=10,
            actual_buckets=10,
            valid_area_ids={"GW_BREAKFAST_DEMO"},
            room_items=room,
            bucket_15m_totals={"GW_BREAKFAST_DEMO": 42.0},
            daily_arrivals={"GW_BREAKFAST_DEMO": 42.0},
        )
        assert len(result.checks) == 10

    def test_result_is_frozen_dataclass(self) -> None:
        """QualityGateResult는 frozen dataclass여야 한다."""
        result = run_quality_gate(_VALID_VOC_ITEMS)
        assert isinstance(result, QualityGateResult)
        assert isinstance(result.checks[0], QualityCheck)


# ---------------------------------------------------------------------------
# FK 고아 검사
# ---------------------------------------------------------------------------


class TestFkOrphanCheck:
    """§11.1: FK 고아 0건 검사."""

    def test_no_orphans_passes(self) -> None:
        items = [
            {"voc_id": "voc-001", "service_area_id": "GW_BREAKFAST_DEMO"},
        ]
        result = run_quality_gate(
            items, valid_area_ids={"GW_BREAKFAST_DEMO"}
        )
        check = next(c for c in result.checks if c.gate == "fk_orphan")
        assert check.passed is True

    def test_orphan_detected(self) -> None:
        items = [
            {"voc_id": "voc-001", "service_area_id": "UNKNOWN_AREA"},
        ]
        result = run_quality_gate(
            items, valid_area_ids={"GW_BREAKFAST_DEMO"}
        )
        check = next(c for c in result.checks if c.gate == "fk_orphan")
        assert check.passed is False
        assert "1건 발견" in check.message

    def test_skipped_when_no_valid_ids(self) -> None:
        items = [
            {"voc_id": "voc-001", "service_area_id": "ANY"},
        ]
        result = run_quality_gate(items)
        check = next(c for c in result.checks if c.gate == "fk_orphan")
        assert check.passed is True
        assert check.details["skipped"] is True


# ---------------------------------------------------------------------------
# 객실 재고 산식 검사
# ---------------------------------------------------------------------------


class TestRoomInventoryFormula:
    """§11.2: 객실 재고 산식 검사."""

    def test_valid_formula_passes(self) -> None:
        room = [
            {
                "service_date": "2026-07-20",
                "room_inventory": 100,
                "rooms_out_of_order": 5,
                "rooms_available": 95,
                "rooms_sold": 80,
            }
        ]
        result = run_quality_gate(_VALID_VOC_ITEMS, room_items=room)
        check = next(c for c in result.checks if c.gate == "room_inventory_formula")
        assert check.passed is True

    def test_invalid_formula_fails(self) -> None:
        """rooms_available != room_inventory - rooms_out_of_order."""
        room = [
            {
                "service_date": "2026-07-20",
                "room_inventory": 100,
                "rooms_out_of_order": 5,
                "rooms_available": 90,  # 95여야 함
                "rooms_sold": 80,
            }
        ]
        result = run_quality_gate(_VALID_VOC_ITEMS, room_items=room)
        check = next(c for c in result.checks if c.gate == "room_inventory_formula")
        assert check.passed is False

    def test_sold_exceeds_available_fails(self) -> None:
        """rooms_sold > rooms_available."""
        room = [
            {
                "service_date": "2026-07-20",
                "room_inventory": 100,
                "rooms_out_of_order": 5,
                "rooms_available": 95,
                "rooms_sold": 100,  # 95 이하여야 함
            }
        ]
        result = run_quality_gate(_VALID_VOC_ITEMS, room_items=room)
        check = next(c for c in result.checks if c.gate == "room_inventory_formula")
        assert check.passed is False

    def test_skipped_when_none(self) -> None:
        result = run_quality_gate(_VALID_VOC_ITEMS)
        gates = [c.gate for c in result.checks]
        assert "room_inventory_formula" not in gates


# ---------------------------------------------------------------------------
# 15분/daily 합계 일치 검사
# ---------------------------------------------------------------------------


class Test15mDailyAggregation:
    """§11.5: 15분 가산 합계와 daily 합계 일치 검사."""

    def test_matching_sums_passes(self) -> None:
        result = run_quality_gate(
            _VALID_VOC_ITEMS,
            bucket_15m_totals={"GW_BREAKFAST_DEMO": 42.0},
            daily_arrivals={"GW_BREAKFAST_DEMO": 42.0},
        )
        check = next(c for c in result.checks if c.gate == "15m_daily_aggregation")
        assert check.passed is True

    def test_mismatched_sums_fails(self) -> None:
        result = run_quality_gate(
            _VALID_VOC_ITEMS,
            bucket_15m_totals={"GW_BREAKFAST_DEMO": 42.0},
            daily_arrivals={"GW_BREAKFAST_DEMO": 40.0},
        )
        check = next(c for c in result.checks if c.gate == "15m_daily_aggregation")
        assert check.passed is False
        assert len(check.details["violations"]) == 1

    def test_skipped_when_none(self) -> None:
        result = run_quality_gate(_VALID_VOC_ITEMS)
        gates = [c.gate for c in result.checks]
        assert "15m_daily_aggregation" not in gates


# ---------------------------------------------------------------------------
# PII 패턴 검사
# ---------------------------------------------------------------------------


class TestPiiPattern:
    """§11.9: 금지 PII pattern 0건 검사."""

    def test_clean_text_passes(self) -> None:
        items = [
            {"voc_id": "voc-001", "review_text": "조식 대기가 너무 길었습니다"},
        ]
        result = run_quality_gate(items)
        check = next(c for c in result.checks if c.gate == "pii_pattern")
        assert check.passed is True

    def test_email_detected(self) -> None:
        items = [
            {"voc_id": "voc-001", "review_text": "contact me at test@example.com"},
        ]
        result = run_quality_gate(items)
        check = next(c for c in result.checks if c.gate == "pii_pattern")
        assert check.passed is False
        assert check.details["count"] >= 1

    def test_phone_detected(self) -> None:
        items = [
            {"voc_id": "voc-001", "review_text": "전화 010-1234-5678로 연락주세요"},
        ]
        result = run_quality_gate(items)
        check = next(c for c in result.checks if c.gate == "pii_pattern")
        assert check.passed is False

    def test_skipped_when_no_text_fields(self) -> None:
        items = [
            {"voc_id": "voc-001", "sentiment_label": "NEGATIVE"},
        ]
        result = run_quality_gate(items)
        check = next(c for c in result.checks if c.gate == "pii_pattern")
        assert check.passed is True
