from __future__ import annotations

import json
import os
from pathlib import Path
from sys import path
from unittest.mock import patch
from uuid import UUID

import pytest
from fastapi import HTTPException


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "app/backend"
path.insert(0, str(BACKEND))

from app.access_policy import (  # noqa: E402
    ACCESS_POLICY_VERSION,
    effective_access,
    load_access_policy,
    load_server_access_profiles,
    resolve_access_profile,
    test_seed_role as resolve_test_seed_role,
)
from app.api.audit_router import get_effective_access  # noqa: E402
from app.contracts import RequestContext, Role  # noqa: E402


def test_versioned_seed_maps_each_test_subject_through_a_group_role():
    policy = load_access_policy()
    assert policy["policy_version"] == ACCESS_POLICY_VERSION
    assert {
        resolve_test_seed_role(UUID(int=index)) for index in (1, 2, 3)
    } == {Role.HOTEL_ANALYST, Role.REPORT_ADMIN, Role.DATA_ADMIN}
    serialized = json.dumps(policy)
    for forbidden in ("token", "digest", "password", "secret"):
        assert forbidden not in serialized.lower()


def test_analysis_profiles_match_server_contract_and_default_to_pms_only():
    policy = load_access_policy()
    contract = load_server_access_profiles()
    assert set(policy["access_profiles"]) == set(contract["profiles"]) == {
        "pms_only", "crm_only", "pms_crm", "integrated_revenue",
        "integrated_operations",
    }
    profile = resolve_access_profile(UUID(int=1), Role.HOTEL_ANALYST, None)
    assert profile.name == "pms_only"
    assert profile.datahub_principal == contract["profiles"]["pms_only"]["datahub_actor"]
    assert profile.credential_env == "DATAHUB_PMS_ONLY_TOKEN"
    assert profile.domains == ("urn:li:domain:rooms",)
    with pytest.raises(PermissionError):
        resolve_access_profile(UUID(int=3), Role.DATA_ADMIN, "pms_only")


def test_effective_access_exposes_only_authenticated_self_and_policy_version():
    context = RequestContext(user_id=UUID(int=2), role=Role.REPORT_ADMIN)
    with patch.dict(os.environ, {"AUTH_MODE": "test"}, clear=False):
        response = get_effective_access(context)
    assert response == {
        "policy_version": ACCESS_POLICY_VERSION,
        "subject": str(UUID(int=2)),
        "role": "report_admin",
        "mapping_source": "test_seed",
    }
    assert not ({"group", "token", "digest", "users"} & set(response))


def test_release_principal_remains_identity_truth_and_policy_is_read_only_metadata():
    subject = UUID("00000000-0000-0000-0000-000000000011")
    with patch.dict(os.environ, {"AUTH_MODE": "release"}, clear=False):
        response = effective_access(subject, Role.DATA_ADMIN)
    assert response["subject"] == str(subject)
    assert response["role"] == "data_admin"
    assert response["mapping_source"] == "release_principal"


def test_invalid_policy_or_test_role_mismatch_fails_closed(tmp_path: Path):
    invalid = tmp_path / "policy.json"
    invalid.write_text('{"policy_version":"unknown"}', encoding="utf-8")
    with patch.dict(os.environ, {"ACCESS_POLICY_PATH": str(invalid)}, clear=False):
        with pytest.raises(RuntimeError):
            load_access_policy()

    with patch.dict(os.environ, {"AUTH_MODE": "test"}, clear=False):
        with pytest.raises(RuntimeError):
            effective_access(UUID(int=1), Role.DATA_ADMIN)
        with pytest.raises(HTTPException) as unavailable:
            get_effective_access(
                RequestContext(user_id=UUID(int=1), role=Role.DATA_ADMIN)
            )
    assert unavailable.value.status_code == 503
