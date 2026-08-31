"""인증 Role을 애플리케이션 Capability와 의미 계약 entitlement로 변환하는 중앙 정책이다.

사용자명·질문·화면 경로는 이 정책의 입력이 아니다. 인증 저장소가 확정한 Role만 받아
API 기능 권한과 DataHub/Template의 허용 Role 상속을 결정해 모든 실행 경계가 같은
감사 가능한 규칙을 사용하게 한다.
"""

from __future__ import annotations

from collections.abc import Iterable
import hashlib
import json
from uuid import UUID

from app.contract_core import Capability, Role
from src.data.entitlement_roles import normalize_entitlement_roles


_ROLE_CAPABILITIES: dict[Role, frozenset[Capability]] = {
    Role.ANALYST: frozenset(
        {
            Capability.RUN_ANALYSIS,
            Capability.READ_ANALYSIS,
            Capability.DRAFT_REPORT,
        }
    ),
    Role.REPORT_ADMIN: frozenset(
        {
            Capability.DRAFT_REPORT,
            Capability.MANAGE_REPORT,
        }
    ),
    Role.DATA_ADMIN: frozenset({Capability.MANAGE_DATA}),
    Role.PLATFORM_ADMIN: frozenset(Capability),
}

_EFFECTIVE_ROLES: dict[Role, frozenset[Role]] = {
    Role.ANALYST: frozenset({Role.ANALYST}),
    Role.REPORT_ADMIN: frozenset({Role.REPORT_ADMIN}),
    Role.DATA_ADMIN: frozenset({Role.DATA_ADMIN}),
    Role.PLATFORM_ADMIN: frozenset(Role),
}

PERMISSION_SNAPSHOT_VERSION = "PERMISSION-SNAPSHOT-v1"


def capabilities_for(role: Role) -> tuple[Capability, ...]:
    """인증 Role의 Capability를 wire 응답과 정책 snapshot에 안정적인 순서로 반환한다."""

    return tuple(sorted(_ROLE_CAPABILITIES[role], key=lambda item: item.value))


def has_capability(role: Role, capability: Capability) -> bool:
    """인증 Role이 요청한 단일 서비스 Capability를 갖는지 중앙 정책으로 판정한다."""

    return capability in _ROLE_CAPABILITIES[role]


def effective_roles(role: Role) -> frozenset[Role]:
    """Role 기반 외부 entitlement 대조에 사용할 상속된 역할 집합을 반환한다.

    일반 역할은 자기 자신만 만족한다. ``platform_admin``만 현재 Role 전체를 상속하므로
    기존 DataHub·Template 계약을 권한 확대용으로 다시 발행하지 않아도 관리자가 같은
    정책을 통과하며, 원래 허용 Role과 실제 실행 Role은 감사 로그에서 구분된다.
    """

    return _EFFECTIVE_ROLES[role]


def role_is_entitled(role: Role | str, allowed_roles: Iterable[Role | str]) -> bool:
    """인증 Role이 외부 계약의 허용 Role 중 하나를 직접 또는 명시적 상속으로 만족하는지 판정한다.

    알 수 없는 Role 문자열은 허용으로 보정하지 않고 거부한다. 외부 metadata도
    현재 canonical Role과 정확히 일치해야 한다.
    """

    try:
        authenticated = role if isinstance(role, Role) else Role(str(role))
        allowed = frozenset(
            Role(item)
            for item in normalize_entitlement_roles(
                item.value if isinstance(item, Role) else item
                for item in allowed_roles
            )
        )
    except ValueError:
        return False
    return bool(effective_roles(authenticated) & allowed)


def permission_snapshot_id(subject_id: UUID, role: Role) -> str:
    """서버가 인증한 주체와 현재 중앙 권한 정책을 canonical receipt로 봉인한다."""

    payload = {
        "version": PERMISSION_SNAPSHOT_VERSION,
        "subject_id": str(subject_id),
        "role": role.value,
        "effective_roles": sorted(item.value for item in effective_roles(role)),
        "capabilities": [item.value for item in capabilities_for(role)],
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"{PERMISSION_SNAPSHOT_VERSION}:{digest}"
