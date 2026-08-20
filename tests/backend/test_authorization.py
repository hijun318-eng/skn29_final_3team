"""Role 이름이 아니라 중앙 Capability·entitlement 정책으로 서비스 권한을 검증한다."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app" / "backend"))

from app.authorization import (  # noqa: E402
    capabilities_for,
    has_capability,
    role_is_entitled,
)
from app.contracts import Capability, Role, SessionData  # noqa: E402


def test_platform_admin_has_all_current_application_capabilities() -> None:
    assert set(capabilities_for(Role.PLATFORM_ADMIN)) == set(Capability)
    assert all(
        has_capability(Role.PLATFORM_ADMIN, capability)
        for capability in Capability
    )


def test_ordinary_roles_do_not_gain_cross_role_entitlements() -> None:
    assert role_is_entitled(Role.ANALYST, [Role.ANALYST])
    assert not role_is_entitled(Role.ANALYST, [Role.REPORT_ADMIN])
    assert not role_is_entitled(Role.REPORT_ADMIN, [Role.ANALYST])
    assert not role_is_entitled(Role.DATA_ADMIN, [Role.ANALYST])


def test_platform_admin_satisfies_existing_external_role_contracts() -> None:
    assert role_is_entitled(Role.PLATFORM_ADMIN, [Role.ANALYST])
    assert role_is_entitled(Role.PLATFORM_ADMIN, [Role.REPORT_ADMIN])
    assert role_is_entitled(Role.PLATFORM_ADMIN, [Role.DATA_ADMIN])
    assert role_is_entitled(Role.PLATFORM_ADMIN, ["analyst"])
    assert role_is_entitled(Role.ANALYST, ["analyst"])
    assert not role_is_entitled(Role.PLATFORM_ADMIN, ["unknown-role"])
    assert not role_is_entitled(
        Role.PLATFORM_ADMIN, ["unknown-role", "analyst"]
    )


def test_session_data_exposes_server_owned_capabilities() -> None:
    session = SessionData(
        role=Role.PLATFORM_ADMIN,
        capabilities=capabilities_for(Role.PLATFORM_ADMIN),
    )

    assert session.role is Role.PLATFORM_ADMIN
    assert set(session.capabilities) == set(Capability)
