"""독립 관리자 계정의 ID·이메일 식별자 검증 계약을 확인한다."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from pydantic import ValidationError


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = ROOT / "admin" / "backend" / "app" / "schemas.py"
SPEC = importlib.util.spec_from_file_location("answervice_admin_schemas", SCHEMA_PATH)
assert SPEC is not None and SPEC.loader is not None
SCHEMAS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SCHEMAS)


@pytest.mark.parametrize("identifier", ("analyst", "ops.admin", "admin@example.com"))
def test_login_accepts_explicit_account_ids_and_emails(identifier: str) -> None:
    request = SCHEMAS.LoginRequest(email=identifier, password="correct-horse")

    assert request.email == identifier


@pytest.mark.parametrize("identifier", ("ab", "@example.com", "admin@", "bad account"))
def test_login_rejects_ambiguous_account_identifiers(identifier: str) -> None:
    with pytest.raises(ValidationError):
        SCHEMAS.LoginRequest(email=identifier, password="correct-horse")
