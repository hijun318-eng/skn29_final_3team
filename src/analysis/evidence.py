"""근거 수집/포맷 모듈.

감지 결과와 분석 데이터를 DSG v2.0 §8의 view 기반 evidence 구조로 변환한다.
모든 함수는 순수 함수로 DB/IO/네트워크 접근이 없다.

evidence 구조는 evidence 테이블(DB-024) 스키마를 따른다:
    evidence_id, analysis_run_id, evidence_type, source_table, source_key,
    metric_code, observed_window, comparison_window, value, unit,
    sample_size, is_counter_evidence, limitations

References:
    - docs/markdown/ai_docs/02_data_standard_guide.md §8 (analysis view)
    - docs/markdown/ai_docs/02_data_standard_guide.md §13 (scenario manifest)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# 근거 유형 상수
# ---------------------------------------------------------------------------

#: 대기 시간 관련 근거
EVIDENCE_TYPE_WAIT: str = "metric_observation"

#: 감성 관련 근거
EVIDENCE_TYPE_SENTIMENT: str = "voc_sentiment"

#: 운영 관련 근거
EVIDENCE_TYPE_OPERATIONS: str = "operations_metric"

#: 대조 근거 (반대 증거)
EVIDENCE_TYPE_COUNTER: str = "counter_evidence"


# ---------------------------------------------------------------------------
# 결과 모델
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EvidenceRecord:
    """단일 근거 레코드.

    DSG v2.0 §8의 evidence 테이블(DB-024) 구조를 따른다.

    Attributes:
        evidence_id: 근거 고유 식별자
        evidence_type: 근거 유형
        source_table: 출처 테이블/뷰
        source_key: 출처 키
        metric_code: 지표 코드
        observed_window: 관찰 윈도우
        comparison_window: 비교 윈도우
        value: 관찰 값
        unit: 단위
        sample_size: 표본 크기
        is_counter_evidence: 대조 근거 여부
        limitations: 한계 사항
    """

    evidence_id: str
    evidence_type: str
    source_table: str
    source_key: str
    metric_code: str
    observed_window: str
    comparison_window: str
    value: float | int
    unit: str
    sample_size: int
    is_counter_evidence: bool
    limitations: str


@dataclass(frozen=True, slots=True)
class EvidenceBundle:
    """근거 묶음 결과.

    Attributes:
        analysis_run_id: 분석 실행 식별자
        records: 근거 레코드 목록
        evidence_ids: 근거 ID 목록 (report.evidence_ids용)
        summary: 전체 요약
    """

    analysis_run_id: str
    records: tuple[EvidenceRecord, ...]
    evidence_ids: tuple[str, ...]
    summary: str


# ---------------------------------------------------------------------------
# 근거 생성 함수 (순수 함수)
# ---------------------------------------------------------------------------


def _build_wait_evidence(
    anomaly_details: dict[str, Any],
    evidence_id: str,
) -> EvidenceRecord:
    """대기 시간 관련 근거를 생성한다.

    Args:
        anomaly_details: 이상 감지 상세 정보
        evidence_id: 근거 ID

    Returns:
        근거 레코드
    """
    zone = anomaly_details.get("zone", "unknown")
    p90 = anomaly_details.get("p90_wait_min", 0)
    threshold = anomaly_details.get("threshold_minutes", 0)

    return EvidenceRecord(
        evidence_id=evidence_id,
        evidence_type=EVIDENCE_TYPE_WAIT,
        source_table="analytics.v_breakfast_15m",
        source_key=f"service_area_id={zone}",
        metric_code="wait_p90_min",
        observed_window="current_period",
        comparison_window=f"threshold={threshold}",
        value=p90,
        unit="min",
        sample_size=1,
        is_counter_evidence=False,
        limitations="합성 데이터 기반 관찰",
    )


def _build_negative_rate_evidence(
    anomaly_details: dict[str, Any],
    evidence_id: str,
) -> EvidenceRecord:
    """NEGATIVE 감성 비율 관련 근거를 생성한다.

    Args:
        anomaly_details: 이상 감지 상세 정보
        evidence_id: 근거 ID

    Returns:
        근거 레코드
    """
    rate = anomaly_details.get("negative_rate", 0.0)
    threshold = anomaly_details.get("threshold", 0.0)

    return EvidenceRecord(
        evidence_id=evidence_id,
        evidence_type=EVIDENCE_TYPE_SENTIMENT,
        source_table="analytics.v_voc_summary",
        source_key="sentiment_label=NEGATIVE",
        metric_code="negative_wait_voc_rate",
        observed_window="current_period",
        comparison_window=f"threshold={threshold}",
        value=rate,
        unit="ratio",
        sample_size=1,
        is_counter_evidence=False,
        limitations="합성 데이터 기반 관찰",
    )


def _build_zone_spike_evidence(
    anomaly_details: dict[str, Any],
    evidence_id: str,
) -> EvidenceRecord:
    """구역별 VOC 급증 관련 근거를 생성한다.

    Args:
        anomaly_details: 이상 감지 상세 정보
        evidence_id: 근거 ID

    Returns:
        근거 레코드
    """
    zone = anomaly_details.get("zone", "unknown")
    count = anomaly_details.get("count", 0)
    baseline = anomaly_details.get("baseline_avg", 0)

    return EvidenceRecord(
        evidence_id=evidence_id,
        evidence_type=EVIDENCE_TYPE_OPERATIONS,
        source_table="analytics.v_voc_summary",
        source_key=f"service_area_id={zone}",
        metric_code="voc_count",
        observed_window="current_period",
        comparison_window=f"baseline_avg={baseline}",
        value=count,
        unit="count",
        sample_size=1,
        is_counter_evidence=False,
        limitations="합성 데이터 기반 관찰",
    )


#: rule_id → 근거 생성 함수 매핑
_EVIDENCE_BUILDERS: dict[str, Any] = {
    "R-WAIT-P90": _build_wait_evidence,
    "R-NEGATIVE-RATE": _build_negative_rate_evidence,
    "R-ZONE-SPIKE": _build_zone_spike_evidence,
}


def _make_evidence_id(rule_id: str, index: int) -> str:
    """근거 ID를 결정론적으로 생성한다.

    Args:
        rule_id: 규칙 식별자
        index: 순번

    Returns:
        근거 ID 문자열
    """
    return f"EV-{rule_id}-{index:03d}"


# ---------------------------------------------------------------------------
# 메인 진입점
# ---------------------------------------------------------------------------


def build_evidence(
    analysis_run_id: str,
    anomalies: list[dict[str, Any]],
) -> EvidenceBundle:
    """감지 결과를 evidence 구조로 변환한다.

    각 이상 항목에 대해 적절한 근거 레코드를 생성하고,
    evidence_ids와 summary를 포함한 EvidenceBundle을 반환한다.

    결정론적: 동일 입력 → 동일 출력.

    Args:
        analysis_run_id: 분석 실행 식별자
        anomalies: detect_anomalies() 출력의 이상 결과를 dict로 변환한 리스트.
            각 dict는 rule_id, severity, message, details를 포함한다.

    Returns:
        EvidenceBundle: 근거 묶음 결과
    """
    records: list[EvidenceRecord] = []

    # rule_id별 카운터 (ID 유니크 보장)
    rule_counters: dict[str, int] = {}

    for anomaly in anomalies:
        rule_id = anomaly.get("rule_id", "UNKNOWN")
        details = anomaly.get("details", {})

        builder = _EVIDENCE_BUILDERS.get(rule_id)
        if builder is None:
            continue

        count = rule_counters.get(rule_id, 0) + 1
        rule_counters[rule_id] = count
        evidence_id = _make_evidence_id(rule_id, count)

        record = builder(details, evidence_id)
        records.append(record)

    evidence_ids = tuple(r.evidence_id for r in records)
    summary = (
        f"근거 {len(records)}건 수집 완료"
        if records
        else "수집된 근거 없음"
    )

    return EvidenceBundle(
        analysis_run_id=analysis_run_id,
        records=tuple(records),
        evidence_ids=evidence_ids,
        summary=summary,
    )
