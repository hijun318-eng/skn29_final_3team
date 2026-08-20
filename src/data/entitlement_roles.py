"""외부 entitlement Role 문자열을 현재 인증 Role에 안전하게 연결하는 공유 계약이다.

분석 역할은 ``analyst`` 하나만 사용한다. 발행기와 runtime은 같은 집합을 사용하며
미등록 문자열을 모두 거부한다.
"""

from __future__ import annotations

from collections.abc import Iterable


CANONICAL_ENTITLEMENT_ROLES = frozenset(
    {"analyst", "report_admin", "data_admin", "platform_admin"}
)
SUPPORTED_ENTITLEMENT_ROLES = CANONICAL_ENTITLEMENT_ROLES


def normalize_entitlement_roles(values: Iterable[object]) -> frozenset[str]:
    """Role 집합을 canonical 문자열로 변환하고 미등록·빈 값을 fail-closed로 거부한다."""

    normalized: set[str] = set()
    observed = False
    for value in values:
        observed = True
        if not isinstance(value, str) or not value.strip():
            raise ValueError("entitlement roles must be non-empty strings")
        role = value.strip()
        if role not in SUPPORTED_ENTITLEMENT_ROLES:
            raise ValueError("entitlement role is unsupported")
        normalized.add(role)
    if not observed:
        return frozenset()
    return frozenset(normalized)


def validate_entitlement_roles(values: Iterable[object]) -> tuple[str, ...]:
    """발행 입력의 순서·표현은 보존하되 모든 값이 canonical Role인지 검증한다."""

    result = tuple(values)
    normalize_entitlement_roles(result)
    return result
