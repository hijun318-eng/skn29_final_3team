"""이상 감지 결정론적 규칙 모듈.

KPI와 메트릭을 기반으로 임계값 초과를 검사하여 이상을 감지한다.
모든 함수는 순수 함수로 DB/IO/네트워크 접근이 없다.

References:
    - docs/markdown/ai_docs/02_data_standard_guide.md (DSG v2.0)
    - docs/markdown/ai_docs/02_data_standard_guide.md §12 (필수 scenario)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# 감지 임계값 상수
# ---------------------------------------------------------------------------

#: NEGATIVE 감성 비율 이상 임계값
NEGATIVE_RATE_ANOMALY_THRESHOLD: float = 0.30

#: 구역별 VOC 급증: 기준 대비 이 배수 이상이면 이상
ZONE_SPIKE_MULTIPLIER: float = 2.0

#: 대기 시간 p90 이상 임계값 (분)
WAIT_P90_ANOMALY_MINUTES: float = 15.0


# ---------------------------------------------------------------------------
# 결과 모델
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class AnomalyDetection:
    """단일 이상 감지 결과.

    Attributes:
        rule_id: 규칙 식별자
        severity: 심각도 ("HIGH", "MEDIUM", "LOW")
        message: 이상 설명
        details: 추가 상세 정보
    """

    rule_id: str
    severity: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# 감지 함수 (순수 함수)
# ---------------------------------------------------------------------------


def _detect_negative_rate_anomaly(
    negative_rate: float,
    threshold: float = NEGATIVE_RATE_ANOMALY_THRESHOLD,
) -> AnomalyDetection | None:
    """NEGATIVE 감성 비율 기반 이상 감지.

    Args:
        negative_rate: 현재 NEGATIVE 비율 (0~1)
        threshold: 이상 판정 임계값

    Returns:
        이상 감지 결과 또는 None
    """
    if negative_rate > threshold:
        return AnomalyDetection(
            rule_id="R-NEGATIVE-RATE",
            severity="HIGH",
            message=f"NEGATIVE 감성 비율 {negative_rate:.1%}가 임계값 {threshold:.0%} 초과",
            details={
                "negative_rate": negative_rate,
                "threshold": threshold,
            },
        )
    return None


def _detect_zone_spike(
    zone_voc_counts: dict[str, int],
    baseline_avg: float,
    multiplier: float = ZONE_SPIKE_MULTIPLIER,
) -> list[AnomalyDetection]:
    """구역별 VOC 급증 감지.

    특정 구역의 VOC 건수가 기준 평균의 multiplier배를 초과하면 이상으로 판정한다.

    Args:
        zone_voc_counts: 구역별 VOC 건수 딕셔너리
        baseline_avg: 기준 평균 VOC 건수
        multiplier: 이상 판정 배수

    Returns:
        이상 감지 결과 리스트
    """
    if baseline_avg <= 0:
        return []

    threshold = baseline_avg * multiplier
    anomalies: list[AnomalyDetection] = []
    for zone, count in zone_voc_counts.items():
        if count > threshold:
            anomalies.append(
                AnomalyDetection(
                    rule_id="R-ZONE-SPIKE",
                    severity="MEDIUM",
                    message=f"구역 '{zone}' VOC {count}건, 기준 {baseline_avg:.0f}건 대비 {count / baseline_avg:.1f}배 급증",
                    details={
                        "zone": zone,
                        "count": count,
                        "baseline_avg": baseline_avg,
                        "ratio": count / baseline_avg,
                        "threshold": threshold,
                    },
                )
            )
    return anomalies


def _detect_wait_anomaly(
    items_with_wait: list[dict[str, Any]],
    threshold_minutes: float = WAIT_P90_ANOMALY_MINUTES,
) -> list[AnomalyDetection]:
    """대기 시간 p90 이상 감지.

    Args:
        items_with_wait: 대기 시간 레코드 리스트 (p90_wait_min 필드)
        threshold_minutes: 이상 판정 대기 시간(분)

    Returns:
        이상 감지 결과 리스트
    """
    anomalies: list[AnomalyDetection] = []
    for item in items_with_wait:
        p90 = item.get("p90_wait_min")
        zone = item.get("service_area_id", "unknown")
        if p90 is not None and isinstance(p90, (int, float)):
            if p90 > threshold_minutes:
                anomalies.append(
                    AnomalyDetection(
                        rule_id="R-WAIT-P90",
                        severity="HIGH",
                        message=f"구역 '{zone}' p90 대기 {p90:.1f}분, 임계값 {threshold_minutes:.0f}분 초과",
                        details={
                            "zone": zone,
                            "p90_wait_min": p90,
                            "threshold_minutes": threshold_minutes,
                        },
                    )
                )
    return anomalies


# ---------------------------------------------------------------------------
# 메인 진입점
# ---------------------------------------------------------------------------


def detect_anomalies(
    kpis: dict[str, Any],
    zone_voc_counts: dict[str, int] | None = None,
    baseline_zone_avg: float = 0.0,
    breakfast_15m_items: list[dict[str, Any]] | None = None,
) -> list[AnomalyDetection]:
    """KPI와 메트릭 기반으로 이상을 감지한다.

    결정론적: 동일 입력 → 동일 출력.

    Args:
        kpis: calculate_kpis()의 kpis 딕셔너리 출력
        zone_voc_counts: 구역별 VOC 건수 (선택)
        baseline_zone_avg: 구역별 기준 평균 VOC 건수 (선택)
        breakfast_15m_items: 15분 조식 레코드 리스트 (선택)

    Returns:
        감지된 이상 결과 리스트
    """
    anomalies: list[AnomalyDetection] = []

    # NEGATIVE 비율 이상
    negative_rate = kpis.get("negative_rate", 0.0)
    anomaly = _detect_negative_rate_anomaly(negative_rate)
    if anomaly is not None:
        anomalies.append(anomaly)

    # 구역별 VOC 급증
    if zone_voc_counts and baseline_zone_avg > 0:
        anomalies.extend(
            _detect_zone_spike(zone_voc_counts, baseline_zone_avg)
        )

    # 대기 시간 p90
    if breakfast_15m_items:
        anomalies.extend(_detect_wait_anomaly(breakfast_15m_items))

    return anomalies
