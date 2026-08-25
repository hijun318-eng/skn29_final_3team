"""MCP·ML Tool의 capability와 역할 허용 목록을 한 경계에서 판정한다."""

from __future__ import annotations

import os
from collections.abc import Collection

from app.contract_core import Role


# The current canonical role for a room-demand owner is ``analyst``.
# ``platform_admin`` is the current system-administrator role.
ML_ALLOWED_ROLES = frozenset({Role.ANALYST.value, Role.PLATFORM_ADMIN.value})


def role_enforcement_enabled() -> bool:
    """역할 검사를 기본 활성화하고 운영자가 명시적으로 끈 경우만 비활성화한다."""

    return os.getenv("MCP_ROLE_ENFORCEMENT_ENABLED", "true").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def is_mcp_tool_allowed(
    *,
    tool_name: str,
    role: Role,
    required_roles: Collection[str],
    capability_allowed: bool,
) -> bool:
    """Tool별 capability와 Registry 역할 조건을 함께 만족할 때만 호출을 허용한다."""

    if not role_enforcement_enabled():
        return True
    if tool_name == "ml.predict":
        return capability_allowed and role.value in ML_ALLOWED_ROLES
    return capability_allowed and role.value in required_roles


def is_ml_allowed(*, role: Role, capability_allowed: bool) -> bool:
    """승인된 예측 Tool을 분석가와 플랫폼 관리자 capability에만 노출한다."""

    return is_mcp_tool_allowed(
        tool_name="ml.predict",
        role=role,
        required_roles=ML_ALLOWED_ROLES,
        capability_allowed=capability_allowed,
    )
