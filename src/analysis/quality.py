"""품질 게이트 결정론적 판정 모듈.

DSG v2.0 §11의 9단계 품질 Gate를 순수 함수로 구현한다.
입력 데이터를 받아 통과/실패와 사유를 반환한다.

모든 임계값은 모듈 상수로 정의하며, DB/IO/네트워크 접근이 없다.

References:
    - docs/markdown/ai_docs/02_data_standard_guide.md §11 (품질 Gate)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

# ---------------------------------------------------------------------------
# 임계값 상수 (DSG §11 기반)
# ---------------------------------------------------------------------------

#: VOC 데이터 완전성 임계값 (sentiment_label이 null이 아닌 비율, 0~1)
VOC_COMPLETENESS_MIN: float = 0.95

#: 감성 분석 커버리지 임계값 (sentiment_label이 할당된 VOC 비율, 0~1)
SENTIMENT_COVERAGE_MIN: float = 0.90

#: PK 중복 허용 건수
PK_DUPLICATE_MAX: int = 0

#: 음수 값 허용 건수 (count, wait, queue, capacity 등)
NEGATIVE_VALUE_MAX: int = 0

#: 필수 bucket 비율 임계값 (누락 없는 bucket 비율, 0~1)
BUCKET_COMPLETENESS_MIN: float = 1.0


# ---------------------------------------------------------------------------
# 결과 모델
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class QualityCheck:
    """단일 품질 검사 결과.

    Attributes:
        gate: Gate 이름 (예: "pk_duplicate", "voc_completeness")
        passed: 통과 여부
        message: 판정 사유
        details: 추가 상세 정보 (선택)
    """

    gate: str
    passed: bool
    message: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class QualityGateResult:
    """전체 품질 게이트 판정 결과.

    Attributes:
        passed: 전체 통과 여부 (모든 개별 Gate 통과 시 True)
        checks: 개별 검사 결과 목록
        summary: 전체 요약 메시지
    """

    passed: bool
    checks: tuple[QualityCheck, ...]
    summary: str


# ---------------------------------------------------------------------------
# 개별 검사 함수 (순수 함수)
# ---------------------------------------------------------------------------


def _check_pk_duplicates(
    voc_items: list[dict[str, Any]],
) -> QualityCheck:
    """DSG §11.1: PK 중복 0건 검사.

    Args:
        voc_items: VOC 레코드 리스트 (voc_id 필드 필수)

    Returns:
        PK 중복 검사 결과
    """
    ids = [item.get("voc_id") for item in voc_items]
    seen: set[str] = set()
    duplicates: list[str] = []
    for vid in ids:
        if vid is None:
            continue
        if vid in seen:
            duplicates.append(str(vid))
        seen.add(vid)

    passed = len(duplicates) <= PK_DUPLICATE_MAX
    return QualityCheck(
        gate="pk_duplicate",
        passed=passed,
        message=(
            "PK 중복 없음"
            if passed
            else f"PK 중복 {len(duplicates)}건 발견"
        ),
        details={"duplicate_ids": duplicates},
    )


def _check_voc_completeness(
    voc_items: list[dict[str, Any]],
) -> QualityCheck:
    """VOC 데이터 완전성 검사.

    sentiment_label이 null이 아닌 비율이 임계값 이상인지 확인한다.

    Args:
        voc_items: VOC 레코드 리스트

    Returns:
        완전성 검사 결과
    """
    total = len(voc_items)
    if total == 0:
        return QualityCheck(
            gate="voc_completeness",
            passed=False,
            message="VOC 데이터가 없습니다",
            details={"total": 0, "complete": 0, "rate": 0.0},
        )

    complete = sum(
        1 for item in voc_items if item.get("sentiment_label") is not None
    )
    rate = complete / total
    passed = rate >= VOC_COMPLETENESS_MIN

    return QualityCheck(
        gate="voc_completeness",
        passed=passed,
        message=(
            f"VOC 완전성 {rate:.1%} (임계값 {VOC_COMPLETENESS_MIN:.0%})"
            if not passed
            else f"VOC 완전성 {rate:.1%} 통과"
        ),
        details={"total": total, "complete": complete, "rate": rate},
    )


def _check_sentiment_coverage(
    voc_items: list[dict[str, Any]],
) -> QualityCheck:
    """DSG 감성 분석 커버리지 검사.

    sentiment_label이 할당된 VOC 비율이 임계값 이상인지 확인한다.

    Args:
        voc_items: VOC 레코드 리스트

    Returns:
        커버리지 검사 결과
    """
    total = len(voc_items)
    if total == 0:
        return QualityCheck(
            gate="sentiment_coverage",
            passed=False,
            message="VOC 데이터가 없습니다",
            details={"total": 0, "covered": 0, "rate": 0.0},
        )

    valid_labels = {"NEGATIVE", "NEUTRAL", "POSITIVE"}
    covered = sum(
        1
        for item in voc_items
        if item.get("sentiment_label") in valid_labels
    )
    rate = covered / total
    passed = rate >= SENTIMENT_COVERAGE_MIN

    return QualityCheck(
        gate="sentiment_coverage",
        passed=passed,
        message=(
            f"감성 커버리지 {rate:.1%} (임계값 {SENTIMENT_COVERAGE_MIN:.0%})"
            if not passed
            else f"감성 커버리지 {rate:.1%} 통과"
        ),
        details={"total": total, "covered": covered, "rate": rate},
    )


def _check_negative_values(
    numeric_items: list[dict[str, Any]],
    fields: tuple[str, ...] = (
        "avg_wait_min",
        "p90_wait_min",
        "max_queue_length",
        "actual_arrivals",
        "expected_arrivals",
        "seated_guests",
        "service_capacity",
    ),
) -> QualityCheck:
    """DSG §11.4: 대기·처리량·대기열·인력 음수 0건 검사.

    Args:
        numeric_items: 숫자형 필드를 포함한 레코드 리스트
        fields: 검사할 필드명 목록

    Returns:
        음수 값 검사 결과
    """
    violations: list[dict[str, Any]] = []
    for item in numeric_items:
        for field_name in fields:
            val = item.get(field_name)
            if val is not None and isinstance(val, (int, float)) and val < 0:
                violations.append(
                    {"field": field_name, "value": val, "record": item}
                )

    passed = len(violations) <= NEGATIVE_VALUE_MAX
    return QualityCheck(
        gate="negative_values",
        passed=passed,
        message=(
            "음수 값 없음"
            if passed
            else f"음수 값 {len(violations)}건 발견"
        ),
        details={"violations": violations},
    )


def _check_occurred_at_order(
    voc_items: list[dict[str, Any]],
) -> QualityCheck:
    """DSG §11.6: occurred_at <= received_at 검사.

    Args:
        voc_items: VOC 레코드 리스트 (received_at, occurred_at 필드)

    Returns:
        시간 순서 검사 결과
    """
    violations: list[dict[str, str]] = []
    for item in voc_items:
        received = item.get("received_at")
        occurred = item.get("occurred_at")
        if received is None or occurred is None:
            continue
        received_dt = _parse_datetime(received)
        occurred_dt = _parse_datetime(occurred)
        if received_dt is not None and occurred_dt is not None:
            if occurred_dt > received_dt:
                violations.append(
                    {
                        "voc_id": str(item.get("voc_id", "?")),
                        "occurred_at": str(occurred),
                        "received_at": str(received),
                    }
                )

    passed = len(violations) == 0
    return QualityCheck(
        gate="occurred_at_order",
        passed=passed,
        message=(
            "시간 순서 정상"
            if passed
            else f"occurred_at > received_at {len(violations)}건"
        ),
        details={"violations": violations},
    )


def _check_bucket_completeness(
    expected_buckets: int,
    actual_buckets: int,
) -> QualityCheck:
    """DSG §11.7: 필수 bucket 누락 검사.

    보간 없이 해당 구간 NEEDS_DATA로 표시한다.

    Args:
        expected_buckets: 기대 bucket 수
        actual_buckets: 실제 유효 bucket 수

    Returns:
        bucket 완전성 검사 결과
    """
    if expected_buckets == 0:
        return QualityCheck(
            gate="bucket_completeness",
            passed=False,
            message="기대 bucket 수가 0입니다",
            details={"expected": 0, "actual": 0, "rate": 0.0},
        )

    rate = actual_buckets / expected_buckets
    passed = rate >= BUCKET_COMPLETENESS_MIN
    missing = expected_buckets - actual_buckets

    return QualityCheck(
        gate="bucket_completeness",
        passed=passed,
        message=(
            f"bucket 누락 {missing}개 (완전성 {rate:.1%})"
            if not passed
            else f"bucket 완전성 {rate:.1%} 통과"
        ),
        details={
            "expected": expected_buckets,
            "actual": actual_buckets,
            "missing": missing,
            "rate": rate,
        },
    )


# ---------------------------------------------------------------------------
# 유틸리티
# ---------------------------------------------------------------------------


def _parse_datetime(value: Any) -> datetime | None:
    """문자열 또는 datetime 값을 UTC datetime으로 파싱한다.

    Args:
        value: 파싱할 값

    Returns:
        파싱된 UTC datetime 또는 None
    """
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except (ValueError, TypeError):
            return None
    return None


# ---------------------------------------------------------------------------
# 메인 진입점
# ---------------------------------------------------------------------------


def run_quality_gate(
    voc_items: list[dict[str, Any]],
    numeric_items: list[dict[str, Any]] | None = None,
    expected_buckets: int | None = None,
    actual_buckets: int | None = None,
) -> QualityGateResult:
    """전체 품질 게이트를 실행한다.

    DSG v2.0 §11의 검사 항목을 순서대로 실행하고 결과를 반환한다.
    모든 검사는 순수 함수로 DB/IO/네트워크 접근이 없다.

    Args:
        voc_items: VOC 레코드 리스트 (fact_voc 기반)
        numeric_items: 숫자형 레코드 리스트 (fact_breakfast_15m 등).
            None이면 numeric 검사를 건너뛴다.
        expected_buckets: 기대 bucket 수. None이면 bucket 검사를 건너뛴다.
        actual_buckets: 실제 유효 bucket 수. None이면 bucket 검사를 건너뛴다.

    Returns:
        QualityGateResult: 전체 판정 결과
    """
    checks: list[QualityCheck] = []

    # §11.1: PK 중복
    checks.append(_check_pk_duplicates(voc_items))

    # 완전성 검사
    checks.append(_check_voc_completeness(voc_items))

    # 감성 커버리지 검사
    checks.append(_check_sentiment_coverage(voc_items))

    # §11.4: 음수 값
    if numeric_items is not None:
        checks.append(_check_negative_values(numeric_items))

    # §11.6: occurred_at <= received_at
    checks.append(_check_occurred_at_order(voc_items))

    # §11.7: bucket 완전성
    if expected_buckets is not None and actual_buckets is not None:
        checks.append(_check_bucket_completeness(expected_buckets, actual_buckets))

    all_passed = all(check.passed for check in checks)
    passed_count = sum(1 for check in checks if check.passed)
    total_count = len(checks)

    summary = (
        f"품질 게이트 통과 ({passed_count}/{total_count})"
        if all_passed
        else f"품질 게이트 실패 ({passed_count}/{total_count} 통과)"
    )

    return QualityGateResult(
        passed=all_passed,
        checks=tuple(checks),
        summary=summary,
    )
