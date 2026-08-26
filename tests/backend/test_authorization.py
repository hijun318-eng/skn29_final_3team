"""두 사람 Role을 중앙 Capability·entitlement 정책으로 검증한다."""

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


def test_role_contract_contains_only_analyst_and_admin() -> None:
    assert {role.value for role in Role} == {"analyst", "admin"}


def test_each_role_has_the_exact_capability_boundary() -> None:
    assert set(capabilities_for(Role.ANALYST)) == {
        Capability.RUN_ANALYSIS,
        Capability.READ_ANALYSIS,
        Capability.DRAFT_REPORT,
    }
    assert set(capabilities_for(Role.ADMIN)) == set(Capability)
    assert all(has_capability(Role.ADMIN, capability) for capability in Capability)


def test_admin_inherits_analyst_entitlement_and_legacy_roles_fail_closed() -> None:
    assert role_is_entitled(Role.ANALYST, [Role.ANALYST])
    assert role_is_entitled(Role.ADMIN, [Role.ANALYST])
    assert role_is_entitled(Role.ADMIN, [Role.ADMIN])
    assert not role_is_entitled(Role.ANALYST, [Role.ADMIN])
    for legacy_role in ("report_admin", "data_admin", "platform_admin"):
        assert not role_is_entitled(Role.ADMIN, [legacy_role])


def test_session_data_exposes_server_owned_admin_capabilities() -> None:
    session = SessionData(
        role=Role.ADMIN,
        capabilities=capabilities_for(Role.ADMIN),
    )

    assert session.role is Role.ADMIN
    assert set(session.capabilities) == set(Capability)
