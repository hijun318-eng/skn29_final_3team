"""detection.py 단위 테스트.

결정론성 검증: 동일 입력 N회 호출 → 동일 출력.
이상 감지 규칙별 테스트.
"""

from __future__ import annotations

from src.analysis.detection import (
    AnomalyDetection,
    NEGATIVE_RATE_ANOMALY_THRESHOLD,
    WAIT_P90_ANOMALY_MINUTES,
    detect_anomalies,
)


# ---------------------------------------------------------------------------
# 결정론성 테스트
# ---------------------------------------------------------------------------


class TestDeterminism:
    """동일 입력 N회 호출 → 동일 출력 검증."""

    def test_detect_anomalies_deterministic(self) -> None:
        kpis = {"negative_rate": 0.5}
        results = [detect_anomalies(kpis) for _ in range(3)]
        first = results[0]
        for r in results[1:]:
            assert len(r) == len(first)
            for a1, a2 in zip(r, first):
                assert a1.rule_id == a2.rule_id
                assert a1.severity == a2.severity
                assert a1.message == a2.message


# ---------------------------------------------------------------------------
# NEGATIVE 비율 이상 감지
# ---------------------------------------------------------------------------


class TestNegativeRateAnomaly:
    """NEGATIVE 감성 비율 기반 이상 감지."""

    def test_high_negative_rate_detected(self) -> None:
        """NEGATIVE 비율 > 30% → HIGH 심각도."""
        kpis = {"negative_rate": 0.5}
        anomalies = detect_anomalies(kpis)
        assert len(anomalies) == 1
        assert anomalies[0].rule_id == "R-NEGATIVE-RATE"
        assert anomalies[0].severity == "HIGH"

    def test_borderline_not_detected(self) -> None:
        """NEGATIVE 비율 == 30% → 임계값 초과가 아니므로 미감지."""
        kpis = {"negative_rate": 0.3}
        anomalies = detect_anomalies(kpis)
        negative_anomalies = [a for a in anomalies if a.rule_id == "R-NEGATIVE-RATE"]
        assert len(negative_anomalies) == 0

    def test_low_negative_rate_not_detected(self) -> None:
        """NEGATIVE 비율 < 30% → 정상."""
        kpis = {"negative_rate": 0.1}
        anomalies = detect_anomalies(kpis)
        negative_anomalies = [a for a in anomalies if a.rule_id == "R-NEGATIVE-RATE"]
        assert len(negative_anomalies) == 0

    def test_zero_negative_rate(self) -> None:
        kpis = {"negative_rate": 0.0}
        anomalies = detect_anomalies(kpis)
        negative_anomalies = [a for a in anomalies if a.rule_id == "R-NEGATIVE-RATE"]
        assert len(negative_anomalies) == 0


# ---------------------------------------------------------------------------
# 구역별 VOC 급증 감지
# ---------------------------------------------------------------------------


class TestZoneSpikeDetection:
    """구역별 VOC 급증 기반 이상 감지."""

    def test_spike_detected(self) -> None:
        """구역 VOC가 기준 대비 2배 초과 → MEDIUM."""
        kpis = {"negative_rate": 0.1}
        zone_counts = {"zone-A": 20, "zone-B": 3}
        anomalies = detect_anomalies(
            kpis, zone_voc_counts=zone_counts, baseline_zone_avg=5.0
        )
        spike_anomalies = [a for a in anomalies if a.rule_id == "R-ZONE-SPIKE"]
        assert len(spike_anomalies) == 1
        assert spike_anomalies[0].severity == "MEDIUM"
        assert "zone-A" in spike_anomalies[0].message

    def test_no_spike_when_below_threshold(self) -> None:
        """구역 VOC가 기준 미만 → 이상 없음."""
        kpis = {"negative_rate": 0.1}
        zone_counts = {"zone-A": 4, "zone-B": 3}
        anomalies = detect_anomalies(
            kpis, zone_voc_counts=zone_counts, baseline_zone_avg=5.0
        )
        spike_anomalies = [a for a in anomalies if a.rule_id == "R-ZONE-SPIKE"]
        assert len(spike_anomalies) == 0

    def test_baseline_zero_no_spike(self) -> None:
        """기준 평균이 0이면 급증 감지 안 함."""
        kpis = {"negative_rate": 0.1}
        zone_counts = {"zone-A": 100}
        anomalies = detect_anomalies(
            kpis, zone_voc_counts=zone_counts, baseline_zone_avg=0.0
        )
        spike_anomalies = [a for a in anomalies if a.rule_id == "R-ZONE-SPIKE"]
        assert len(spike_anomalies) == 0


# ---------------------------------------------------------------------------
# 대기 시간 p90 이상 감지
# ---------------------------------------------------------------------------


class TestWaitAnomalyDetection:
    """대기 시간 p90 기반 이상 감지."""

    def test_high_wait_detected(self) -> None:
        """p90 대기 > 15분 → HIGH."""
        kpis = {"negative_rate": 0.1}
        breakfast_items = [
            {"service_area_id": "zone-A", "p90_wait_min": 20.0},
            {"service_area_id": "zone-B", "p90_wait_min": 5.0},
        ]
        anomalies = detect_anomalies(kpis, breakfast_15m_items=breakfast_items)
        wait_anomalies = [a for a in anomalies if a.rule_id == "R-WAIT-P90"]
        assert len(wait_anomalies) == 1
        assert wait_anomalies[0].severity == "HIGH"
        assert "zone-A" in wait_anomalies[0].message

    def test_normal_wait_not_detected(self) -> None:
        """p90 대기 <= 15분 → 정상."""
        kpis = {"negative_rate": 0.1}
        breakfast_items = [
            {"service_area_id": "zone-A", "p90_wait_min": 10.0},
        ]
        anomalies = detect_anomalies(kpis, breakfast_15m_items=breakfast_items)
        wait_anomalies = [a for a in anomalies if a.rule_id == "R-WAIT-P90"]
        assert len(wait_anomalies) == 0

    def test_borderline_wait(self) -> None:
        """p90 대기 == 15분 → 임계값 미초과 (>)."""
        kpis = {"negative_rate": 0.1}
        breakfast_items = [
            {"service_area_id": "zone-A", "p90_wait_min": 15.0},
        ]
        anomalies = detect_anomalies(kpis, breakfast_15m_items=breakfast_items)
        wait_anomalies = [a for a in anomalies if a.rule_id == "R-WAIT-P90"]
        assert len(wait_anomalies) == 0


# ---------------------------------------------------------------------------
# 복합 시나리오
# ---------------------------------------------------------------------------


class TestCompositeScenarios:
    """복합 이상 감지 시나리오."""

    def test_multiple_anomalies(self) -> None:
        """여러 이상이 동시에 감지되는 경우."""
        kpis = {"negative_rate": 0.4}
        zone_counts = {"zone-A": 30}
        breakfast_items = [
            {"service_area_id": "zone-A", "p90_wait_min": 25.0},
        ]
        anomalies = detect_anomalies(
            kpis,
            zone_voc_counts=zone_counts,
            baseline_zone_avg=5.0,
            breakfast_15m_items=breakfast_items,
        )
        rule_ids = {a.rule_id for a in anomalies}
        assert "R-NEGATIVE-RATE" in rule_ids
        assert "R-ZONE-SPIKE" in rule_ids
        assert "R-WAIT-P90" in rule_ids
        assert len(anomalies) == 3

    def test_no_anomalies_normal(self) -> None:
        """정상 데이터 → 이상 없음."""
        kpis = {"negative_rate": 0.1}
        zone_counts = {"zone-A": 5}
        breakfast_items = [
            {"service_area_id": "zone-A", "p90_wait_min": 8.0},
        ]
        anomalies = detect_anomalies(
            kpis,
            zone_voc_counts=zone_counts,
            baseline_zone_avg=5.0,
            breakfast_15m_items=breakfast_items,
        )
        assert len(anomalies) == 0

    def test_empty_optional_fields(self) -> None:
        """선택 필드 없이 호출 시 정상 동작."""
        kpis = {"negative_rate": 0.1}
        anomalies = detect_anomalies(kpis)
        assert len(anomalies) == 0


# ---------------------------------------------------------------------------
# 결과 모델
# ---------------------------------------------------------------------------


class TestResultModel:
    """결과 모델 검증."""

    def test_anomaly_is_frozen_dataclass(self) -> None:
        kpis = {"negative_rate": 0.5}
        anomalies = detect_anomalies(kpis)
        assert isinstance(anomalies[0], AnomalyDetection)
        assert anomalies[0].details  # details가 비어있지 않은지
