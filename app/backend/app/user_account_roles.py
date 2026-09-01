"""사용자 계정의 두 공개 Role과 내부 권한 Role 간 경계를 정의한다."""

from __future__ import annotations

from typing import Literal, TypeAlias

from app.contract_core import Role


UserAccountRole: TypeAlias = Literal["analyst", "admin"]
PUBLIC_USER_ACCOUNT_ROLES: tuple[UserAccountRole, ...] = ("analyst", "admin")
INTERNAL_USER_ACCOUNT_ROLES: tuple[Role, ...] = (
    Role.ANALYST,
    Role.PLATFORM_ADMIN,
)


def is_internal_user_account_role(role: Role) -> bool:
    """DB 로그인 계정에 허용된 두 내부 Role인지 정확히 판정한다."""

    return role in INTERNAL_USER_ACCOUNT_ROLES


def public_user_account_role(role: Role | str) -> UserAccountRole:
    """내부 저장 Role을 두 값뿐인 사용자 계정 공개 계약으로 변환한다."""

    value = role.value if isinstance(role, Role) else role
    if value == Role.ANALYST.value:
        return "analyst"
    if value in {"admin", Role.PLATFORM_ADMIN.value}:
        return "admin"
    raise ValueError("지원하지 않는 사용자 계정 역할입니다.")


def internal_user_account_role(role: UserAccountRole | str) -> Role:
    """검증된 공개 계정 Role을 기존 내부 권한 Role로 변환한다."""

    if role == "analyst":
        return Role.ANALYST
    if role == "admin":
        return Role.PLATFORM_ADMIN
    raise ValueError("계정 역할은 analyst 또는 admin이어야 합니다.")
