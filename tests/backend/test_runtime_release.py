"""정적 runtime 계약과 live semantic release의 제품 receipt 결속을 검증한다."""

from __future__ import annotations

from pathlib import Path
from sys import path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

BACKEND = Path(__file__).resolve().parents[2] / "app" / "backend"
path.insert(0, str(BACKEND))

from app.runtime_release import (
    PRODUCT_RELEASE_RECEIPT_VERSION,
    active_runtime_contracts,
    product_release_receipt,
    runtime_contract_receipt,
    validate_model_runtime_compatibility,
)
from src.ai.schema import ContractError


def _release(**overrides: str) -> SimpleNamespace:
    values = {
        "catalog_version": "catalog-v1",
        "policy_version": "policy-v1",
        "catalog_checksum": "a" * 64,
        "manifest_checksum": "b" * 64,
        "canonical_checksum": "c" * 64,
        "format_version": active_runtime_contracts()[
            "canonical_semantic_release_version"
        ],
        "runtime_contract_version": active_runtime_contracts()[
            "runtime_governance_version"
        ],
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_active_model_manifest_matches_every_runtime_contract_axis() -> None:
    assert validate_model_runtime_compatibility() == active_runtime_contracts()
    assert runtime_contract_receipt().startswith(
        f"{PRODUCT_RELEASE_RECEIPT_VERSION}:"
    )


def test_product_receipt_changes_when_catalog_or_policy_identity_changes() -> None:
    baseline = product_release_receipt(_release())

    assert baseline != product_release_receipt(_release(catalog_checksum="d" * 64))
    assert baseline != product_release_receipt(_release(policy_version="policy-v2"))


def test_manifest_runtime_mismatch_fails_closed() -> None:
    incompatible = {
        "compatible_runtime": {
            **active_runtime_contracts(),
            "analysis_plan_version": "unsupported-plan",
        }
    }
    with patch(
        "app.runtime_release.model_release_manifest",
        return_value=incompatible,
    ):
        with pytest.raises(ContractError, match="incompatible"):
            validate_model_runtime_compatibility()


def test_semantic_release_contract_mismatch_fails_closed() -> None:
    with pytest.raises(ContractError, match="semantic release is incompatible"):
        product_release_receipt(_release(runtime_contract_version="legacy-runtime"))
