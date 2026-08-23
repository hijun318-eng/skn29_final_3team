"""모델·계획·컴파일러·semantic catalog를 하나의 검증 가능한 제품 release로 결속한다."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.services.analysis.logical_plan import ANALYSIS_PLAN_VERSION
from app.services.analysis.typed_sql_compiler import TYPED_SQL_COMPILER_VERSION
from app.services.context.semantic_release import CANONICAL_SEMANTIC_RELEASE_VERSION
from src.ai.model_contracts import (
    canonical_json_sha256,
    model_release_checksum,
    model_release_manifest,
)
from src.ai.schema import ContractError
from src.data.metric_governance import RUNTIME_GOVERNANCE_VERSION_V2


PRODUCT_RELEASE_RECEIPT_VERSION = "ANSWERVICE-PRODUCT-RELEASE-v1"


def active_runtime_contracts() -> dict[str, str]:
    """현재 실행 코드가 실제로 지원하는 정적 계약 버전을 반환한다."""

    return {
        "analysis_plan_version": ANALYSIS_PLAN_VERSION,
        "typed_sql_compiler_version": TYPED_SQL_COMPILER_VERSION,
        "canonical_semantic_release_version": CANONICAL_SEMANTIC_RELEASE_VERSION,
        "runtime_governance_version": RUNTIME_GOVERNANCE_VERSION_V2,
    }


def validate_model_runtime_compatibility() -> dict[str, str]:
    """active model manifest와 현재 실행 계약의 정확한 호환성 선언을 검증한다."""

    declared = model_release_manifest().get("compatible_runtime")
    current = active_runtime_contracts()
    if not isinstance(declared, Mapping) or dict(declared) != current:
        raise ContractError(
            "active model release is incompatible with the runtime contracts"
        )
    return current


def runtime_contract_receipt() -> str:
    """catalog를 읽기 전에도 기동 조합을 식별할 수 있는 정적 release receipt를 만든다."""

    identity = {
        "receipt_version": PRODUCT_RELEASE_RECEIPT_VERSION,
        "model_manifest_version": str(model_release_manifest()["manifest_version"]),
        "model_manifest_sha256": model_release_checksum(),
        "runtime": validate_model_runtime_compatibility(),
    }
    return f"{PRODUCT_RELEASE_RECEIPT_VERSION}:{canonical_json_sha256(identity)}"


def product_release_receipt(release: Any) -> str:
    """검증된 catalog identity와 정적 runtime identity를 한 SHA-256 receipt로 결속한다."""

    required = {
        "catalog_version",
        "policy_version",
        "catalog_checksum",
        "manifest_checksum",
        "canonical_checksum",
        "format_version",
        "runtime_contract_version",
    }
    values = {name: getattr(release, name, None) for name in required}
    if any(not isinstance(value, str) or not value for value in values.values()):
        raise ContractError("semantic release identity is incomplete")
    runtime = validate_model_runtime_compatibility()
    if (
        values["format_version"] != runtime["canonical_semantic_release_version"]
        or values["runtime_contract_version"] != runtime["runtime_governance_version"]
    ):
        raise ContractError("semantic release is incompatible with the runtime contracts")
    identity = {
        "receipt_version": PRODUCT_RELEASE_RECEIPT_VERSION,
        "catalog": dict(sorted(values.items())),
        "model_manifest_version": str(model_release_manifest()["manifest_version"]),
        "model_manifest_sha256": model_release_checksum(),
        "runtime": runtime,
    }
    return f"{PRODUCT_RELEASE_RECEIPT_VERSION}:{canonical_json_sha256(identity)}"
