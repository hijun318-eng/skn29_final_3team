"""Phase 0B capability/evidence schema의 version·불변식·호환성을 검증한다."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from sys import path
from uuid import uuid4

import pytest
from pydantic import ValidationError

BACKEND = Path(__file__).resolve().parents[2] / "app" / "backend"
path.insert(0, str(BACKEND))

from app.api.mcp_router import (
    MCP_PROTOCOL_VERSION,
    TOOL_INPUT_SCHEMA,
    TOOL_NAME,
    TOOL_OUTPUT_SCHEMA,
)
from app.capability_contracts import (
    CapabilityBudget,
    CapabilityCoverage,
    CapabilityInvocation,
    CapabilityObjectRef,
    CapabilityReasonCode,
    CapabilityResult,
    CapabilityResultStatus,
    CatalogReceipt,
    EvidenceKind,
    EvidenceRef,
    ImageReceipt,
    MigrationReceipt,
    ModelReceipt,
    ProductReleaseEvidence,
    ProductReleaseEvidenceManifest,
    ProductReleaseVector,
    ReleaseBoundObjectKind,
    SourceReceipt,
)
from app.contracts import AnalysisRequest


def _product_evidence() -> ProductReleaseEvidence:
    return ProductReleaseEvidence(
        source=SourceReceipt(commit_sha="a" * 40, dirty=True, dirty_patch_sha256="b" * 64),
        images=(ImageReceipt(component="backend", digest=f"sha256:{'c' * 64}"),),
        migration=MigrationReceipt(revision="20260822_29", chain_sha256="d" * 64),
        model=ModelReceipt(release_id="MODEL-RELEASE-v1.32.0", manifest_sha256="e" * 64),
        catalog=CatalogReceipt(
            release_id="catalog-v1",
            manifest_sha256="f" * 64,
            projection_sha256="0" * 64,
        ),
        release_vector=ProductReleaseVector(
            data_release_id="data-v1",
            semantic_release_id="semantic-v1",
            prompt_release_id="prompt-v1",
            policy_release_id="policy-v1",
            runtime_release_id="runtime-v1",
        ),
    )


def test_typed_invocation_is_versioned_frozen_and_server_hash_bound() -> None:
    invocation = CapabilityInvocation[AnalysisRequest](
        invocation_id=uuid4(),
        request_id=uuid4(),
        conversation_id=uuid4(),
        capability="analysis.run",
        capability_version="1.0.0",
        payload=AnalysisRequest(question="이번 달 매출은?"),
        effective_subject_id=uuid4(),
        permission_snapshot_id="permission:abc",
        product_release_id="release:abc",
        capability_release_vector={"analysis.run": "1.0.0"},
        deadline_at=datetime.now(timezone.utc) + timedelta(seconds=30),
        budget=CapabilityBudget(
            wall_clock_ms=30_000,
            model_tokens=4_000,
            tool_calls=2,
            queries=1,
        ),
        idempotency_key="command-1",
        canonical_input_sha256="1" * 64,
    )

    assert invocation.schema_version == "CapabilityInvocation.v1"
    assert isinstance(invocation.payload, AnalysisRequest)
    with pytest.raises(ValidationError):
        invocation.capability = "rag.answer"


def test_evidence_ref_carries_authority_and_reference_not_raw_context() -> None:
    ref = EvidenceRef(
        evidence_id=uuid4(),
        kind=EvidenceKind.OBSERVED_DATA,
        object_ref=CapabilityObjectRef(
            object_kind=ReleaseBoundObjectKind.ARTIFACT,
            object_id=str(uuid4()),
            checksum_sha256="2" * 64,
        ),
        checksum_sha256="3" * 64,
        product_release_id="release:abc",
        observed_at=datetime.now(timezone.utc),
    )

    assert ref.schema_version == "EvidenceRef.v1"
    assert "payload" not in ref.model_dump()
    assert set(EvidenceKind) == {
        EvidenceKind.OBSERVED_DATA,
        EvidenceKind.DOCUMENTED_CONTEXT,
        EvidenceKind.MODEL_PREDICTION,
        EvidenceKind.DERIVED_INFERENCE,
    }


def test_result_status_reason_and_coverage_are_consistent() -> None:
    succeeded = CapabilityResult[dict[str, str]](
        invocation_id=uuid4(),
        request_id=uuid4(),
        status=CapabilityResultStatus.SUCCEEDED,
        payload={"artifact_id": str(uuid4())},
        coverage=CapabilityCoverage(requested=("answer",), satisfied=("answer",), complete=True),
        product_release_id="release:abc",
        permission_snapshot_id="permission:abc",
        capability_release_vector={"analysis.run": "1.0.0"},
    )
    assert succeeded.schema_version == "CapabilityResult.v1"

    with pytest.raises(ValidationError, match="typed reason_code"):
        CapabilityResult[None](
            invocation_id=uuid4(),
            request_id=uuid4(),
            status=CapabilityResultStatus.BLOCKED,
            coverage=CapabilityCoverage(requested=("answer",), satisfied=(), complete=False),
            product_release_id="release:abc",
            permission_snapshot_id="permission:abc",
            capability_release_vector={"analysis.run": "1.0.0"},
        )
    partial = CapabilityResult[None](
        invocation_id=uuid4(),
        request_id=uuid4(),
        status=CapabilityResultStatus.PARTIAL,
        reason_code=CapabilityReasonCode.DEPENDENCY_UNAVAILABLE,
        coverage=CapabilityCoverage(requested=("a", "b"), satisfied=("a",), complete=False),
        product_release_id="release:abc",
        permission_snapshot_id="permission:abc",
        capability_release_vector={"analysis.run": "1.0.0"},
    )
    assert partial.reason_code is CapabilityReasonCode.DEPENDENCY_UNAVAILABLE


def test_product_release_manifest_binds_every_required_evidence_axis() -> None:
    created_at = datetime(2026, 8, 22, tzinfo=timezone.utc)
    manifest = ProductReleaseEvidenceManifest.seal(
        product_release_id="ANSWERVICE-PRODUCT-RELEASE-v1:" + "9" * 64,
        evidence=_product_evidence(),
        created_at=created_at,
    )

    assert manifest.schema_version == "ProductReleaseEvidenceManifest.v1"
    assert len(manifest.manifest_sha256) == 64
    tampered = manifest.model_dump(mode="json")
    tampered["evidence"]["migration"]["revision"] = "tampered"
    with pytest.raises(ValidationError, match="checksum"):
        ProductReleaseEvidenceManifest.model_validate(tampered)


def test_existing_mcp_public_identifier_and_result_schema_are_unchanged() -> None:
    assert MCP_PROTOCOL_VERSION == "2026-07-28"
    assert TOOL_NAME == "analysis.get_run"
    assert TOOL_INPUT_SCHEMA == {
        "type": "object",
        "properties": {"request_id": {"type": "string", "format": "uuid"}},
        "required": ["request_id"],
        "additionalProperties": False,
    }
    assert TOOL_OUTPUT_SCHEMA == {
        "type": "object",
        "properties": {
            "request_id": {"type": "string"},
            "status": {"type": "string"},
            "trace_id": {"type": "string"},
            "query_id": {"type": ["string", "null"]},
            "artifact_id": {"type": ["string", "null"]},
        },
        "required": ["request_id", "status", "trace_id", "query_id", "artifact_id"],
    }
