"""evidence.py 단위 테스트.

결정론성 검증: 동일 입력 N회 호출 → 동일 출력.
근거 수집/포맷 검증.
"""

from __future__ import annotations

from src.analysis.evidence import (
    EvidenceBundle,
    EvidenceRecord,
    build_evidence,
)


# ---------------------------------------------------------------------------
# 테스트 픽스처
# ---------------------------------------------------------------------------

_SAMPLE_ANOMALIES: list[dict[str, object]] = [
    {
        "rule_id": "R-WAIT-P90",
        "severity": "HIGH",
        "message": "p90 대기 초과",
        "details": {
            "zone": "zone-A",
            "p90_wait_min": 20.0,
            "threshold_minutes": 15.0,
        },
    },
    {
        "rule_id": "R-NEGATIVE-RATE",
        "severity": "HIGH",
        "message": "NEGATIVE 비율 초과",
        "details": {
            "negative_rate": 0.5,
            "threshold": 0.3,
        },
    },
]

_SINGLE_ANOMALY: list[dict[str, object]] = [
    {
        "rule_id": "R-ZONE-SPIKE",
        "severity": "MEDIUM",
        "message": "구역 VOC 급증",
        "details": {
            "zone": "zone-B",
            "count": 20,
            "baseline_avg": 5.0,
            "ratio": 4.0,
            "threshold": 10.0,
        },
    },
]


# ---------------------------------------------------------------------------
# 결정론성 테스트
# ---------------------------------------------------------------------------


class TestDeterminism:
    """동일 입력 N회 호출 → 동일 출력 검증."""

    def test_build_evidence_deterministic(self) -> None:
        """build_evidence는 동일 입력에 대해 동일 결과를 반환해야 한다."""
        results = [
            build_evidence("run-001", _SAMPLE_ANOMALIES) for _ in range(3)
        ]
        first = results[0]
        for r in results[1:]:
            assert r.analysis_run_id == first.analysis_run_id
            assert r.evidence_ids == first.evidence_ids
            assert len(r.records) == len(first.records)
            for rec1, rec2 in zip(r.records, first.records):
                assert rec1.evidence_id == rec2.evidence_id
                assert rec1.value == rec2.value


# ---------------------------------------------------------------------------
# 근거 생성
# ---------------------------------------------------------------------------


class TestEvidenceGeneration:
    """근거 레코드 생성 검증."""

    def test_records_count_matches_anomalies(self) -> None:
        result = build_evidence("run-001", _SAMPLE_ANOMALIES)
        assert len(result.records) == 2

    def test_evidence_ids_match_records(self) -> None:
        result = build_evidence("run-001", _SAMPLE_ANOMALIES)
        assert len(result.evidence_ids) == len(result.records)
        for eid in result.evidence_ids:
            assert eid.startswith("EV-")

    def test_wait_evidence_fields(self) -> None:
        result = build_evidence("run-001", _SAMPLE_ANOMALIES)
        wait_record = next(
            r for r in result.records if r.metric_code == "wait_p90_min"
        )
        assert wait_record.source_table == "analytics.v_breakfast_15m"
        assert wait_record.unit == "min"
        assert wait_record.value == 20.0
        assert wait_record.is_counter_evidence is False

    def test_sentiment_evidence_fields(self) -> None:
        result = build_evidence("run-001", _SAMPLE_ANOMALIES)
        sentiment_record = next(
            r for r in result.records if r.metric_code == "negative_wait_voc_rate"
        )
        assert sentiment_record.source_table == "analytics.v_voc_summary"
        assert sentiment_record.unit == "ratio"
        assert sentiment_record.value == 0.5

    def test_zone_spike_evidence_fields(self) -> None:
        result = build_evidence("run-001", _SINGLE_ANOMALY)
        ops_record = next(
            r for r in result.records if r.metric_code == "voc_count"
        )
        assert ops_record.source_table == "analytics.v_voc_summary"
        assert ops_record.unit == "count"
        assert ops_record.value == 20

    def test_unknown_rule_id_skipped(self) -> None:
        """알 수 없는 rule_id는 건너뛴다."""
        unknown_anomalies = [
            {
                "rule_id": "R-UNKNOWN",
                "severity": "LOW",
                "message": "test",
                "details": {},
            },
        ]
        result = build_evidence("run-001", unknown_anomalies)
        assert len(result.records) == 0


# ---------------------------------------------------------------------------
# 엣지 케이스
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """엣지 케이스 검증."""

    def test_empty_anomalies(self) -> None:
        result = build_evidence("run-001", [])
        assert len(result.records) == 0
        assert result.evidence_ids == ()
        assert "없음" in result.summary

    def test_analysis_run_id_preserved(self) -> None:
        result = build_evidence("run-xyz-123", _SINGLE_ANOMALY)
        assert result.analysis_run_id == "run-xyz-123"

    def test_multiple_same_rule_different_ids(self) -> None:
        """같은 규칙이 여러 번 감지되면 다른 evidence_id가 부여된다."""
        anomalies = [
            {
                "rule_id": "R-WAIT-P90",
                "severity": "HIGH",
                "message": "test1",
                "details": {
                    "zone": "zone-A",
                    "p90_wait_min": 20.0,
                    "threshold_minutes": 15.0,
                },
            },
            {
                "rule_id": "R-WAIT-P90",
                "severity": "HIGH",
                "message": "test2",
                "details": {
                    "zone": "zone-B",
                    "p90_wait_min": 25.0,
                    "threshold_minutes": 15.0,
                },
            },
        ]
        result = build_evidence("run-001", anomalies)
        assert len(result.records) == 2
        ids = [r.evidence_id for r in result.records]
        assert ids[0] != ids[1]


# ---------------------------------------------------------------------------
# 결과 모델
# ---------------------------------------------------------------------------


class TestResultModel:
    """결과 모델 검증."""

    def test_result_is_frozen_dataclass(self) -> None:
        result = build_evidence("run-001", _SAMPLE_ANOMALIES)
        assert isinstance(result, EvidenceBundle)

    def test_record_is_frozen_dataclass(self) -> None:
        result = build_evidence("run-001", _SAMPLE_ANOMALIES)
        assert isinstance(result.records[0], EvidenceRecord)

    def test_summary_message(self) -> None:
        result = build_evidence("run-001", _SAMPLE_ANOMALIES)
        assert "2건" in result.summary
