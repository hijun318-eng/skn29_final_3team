"""Phase 10 P0 same-release 판정의 PRD inventory·봉인·격리 경계를 검증한다."""

from __future__ import annotations

import copy
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
ACCEPTANCE = ROOT / "infrastructure" / "acceptance"
BACKEND = ROOT / "app" / "backend"
for entry in (str(ROOT), str(ACCEPTANCE), str(BACKEND)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from app.capability_contracts import (  # noqa: E402
    CatalogReceipt,
    ImageReceipt,
    MigrationReceipt,
    ModelReceipt,
    ProductReleaseEvidence,
    ProductReleaseEvidenceManifest,
    ProductReleaseVector,
    SourceReceipt,
)
from phase10_p0_same_release import (  # noqa: E402
    EXPECTED_RELEASE_GATES,
    Phase10Error,
    ActiveReceipt,
    PrdInventory,
    _validate_boundary,
    build_assessment,
    parse_args,
    parse_prd,
    validate_assessment,
)


def _args(extra: list[str] | None = None):
    return parse_args(
        [
            "--target-project",
            "answervice-phase2b-datahub",
            "--database-url",
            "postgresql+psycopg://phase10_runtime@127.0.0.1:55440/"
            "phase10_p0_same_release_acceptance",
            *(extra or []),
        ]
    )


def _manifest() -> ProductReleaseEvidenceManifest:
    evidence = ProductReleaseEvidence(
        source=SourceReceipt(
            commit_sha="a" * 40,
            dirty=True,
            dirty_patch_sha256="b" * 64,
        ),
        images=(ImageReceipt(component="historical", digest="sha256:" + "c" * 64),),
        migration=MigrationReceipt(revision="20260822_33", chain_sha256="d" * 64),
        model=ModelReceipt(release_id="model-v1", manifest_sha256="e" * 64),
        catalog=CatalogReceipt(
            release_id="catalog-v1",
            manifest_sha256="f" * 64,
            projection_sha256="0" * 64,
        ),
        release_vector=ProductReleaseVector(
            data_release_id="catalog-v1",
            semantic_release_id="catalog-v1",
            prompt_release_id="model-v1",
            policy_release_id="policy-v1",
            runtime_release_id="runtime-v1",
        ),
    )
    return ProductReleaseEvidenceManifest.seal(
        product_release_id="ANSWERVICE-PHASE10-P0-SAME-RELEASE:" + "1" * 64,
        evidence=evidence,
        created_at=datetime(2026, 8, 23, tzinfo=timezone.utc),
    )


def test_boundary_is_hard_bound_to_the_approved_isolated_stack() -> None:
    _validate_boundary(_args())
    with pytest.raises(Phase10Error, match="target project"):
        _validate_boundary(_args(["--target-project", "answervice"]))
    with pytest.raises(Phase10Error, match="database"):
        _validate_boundary(
            _args(
                [
                    "--database-url",
                    "postgresql+psycopg://phase10_runtime@127.0.0.1:5432/answervice",
                ]
            )
        )


def test_canonical_prd_inventory_has_no_false_verified_status() -> None:
    inventory = parse_prd((ROOT / "docs" / "product" / "01_PRD.md").read_text(encoding="utf-8"))

    assert set(inventory.release_gates) == EXPECTED_RELEASE_GATES
    assert len(inventory.requirements) >= 50
    assert set(inventory.requirements.values()).isdisjoint({"VERIFIED"})
    assert set(inventory.mapping_rows) == EXPECTED_RELEASE_GATES


def test_blocked_assessment_does_not_mix_historical_or_skipped_evidence() -> None:
    manifest = _manifest()
    inventory = PrdInventory(
        requirements={"DATA-001": "READY_TO_VERIFY"},
        release_gates={"P0-EVIDENCE": "NOT_STARTED"},
        mapping_rows={"P0-EVIDENCE": ("DATA-001",)},
    )
    assessment = build_assessment(
        inventory=inventory,
        active=ActiveReceipt(21, manifest, "20260822_33"),
        current_source=SourceReceipt(
            commit_sha="a" * 40,
            dirty=True,
            dirty_patch_sha256="9" * 64,
        ),
        current_model_sha256="e" * 64,
        current_migration_sha256="d" * 64,
        current_probes={
            "datahub": {"verified": True},
            "trino": {"verified": True},
        },
        assessed_at=datetime(2026, 8, 23, tzinfo=timezone.utc),
    )

    validate_assessment(assessment)
    assert assessment["status"] == "BLOCKED"
    assert assessment["historical_evidence_mixed"] is False
    assert assessment["skipped_evidence_count"] == 0
    assert assessment["evidence_axes"]["source"] == "MISMATCH"
    assert assessment["evidence_axes"]["browser"] == "MISSING"
    assert assessment["evidence_axes"]["datahub"] == "VERIFIED"
    assert assessment["evidence_axes"]["trino"] == "VERIFIED"
    assert "P0_REQUIREMENTS_NOT_VERIFIED" in assessment["blockers"]


def test_verified_assessment_requires_all_current_axes_and_prd_statuses() -> None:
    manifest = _manifest()
    assessment = build_assessment(
        inventory=PrdInventory(
            requirements={"DATA-001": "VERIFIED"},
            release_gates={"P0-EVIDENCE": "VERIFIED"},
            mapping_rows={"P0-EVIDENCE": ("DATA-001",)},
        ),
        active=ActiveReceipt(22, manifest, "20260822_33"),
        current_source=manifest.evidence.source,
        current_model_sha256="e" * 64,
        current_migration_sha256="d" * 64,
        current_probes={
            "datahub": {"verified": True},
            "trino": {"verified": True},
            "candidate_services": {
                "verified": True,
                "product_release_id": manifest.product_release_id,
            },
            "browser": {"verified": True},
            "host_validation": {"verified": True},
            "product_eval": {
                "verified": True,
                "product_release_id": manifest.product_release_id,
                "semantic_release_id": manifest.evidence.catalog.release_id,
            },
        },
        assessed_at=datetime(2026, 8, 23, tzinfo=timezone.utc),
    )

    validate_assessment(assessment)
    assert assessment["status"] == "VERIFIED"
    assert set(assessment["evidence_axes"].values()) == {"VERIFIED"}
    assert assessment["blockers"] == []


def test_assessment_checksum_rejects_tampering() -> None:
    manifest = _manifest()
    assessment = build_assessment(
        inventory=PrdInventory(
            requirements={"DATA-001": "BLOCKED"},
            release_gates={"P0-EVIDENCE": "BLOCKED"},
            mapping_rows={"P0-EVIDENCE": ("DATA-001",)},
        ),
        active=ActiveReceipt(21, manifest, "20260822_33"),
        current_source=manifest.evidence.source,
        current_model_sha256="e" * 64,
        current_migration_sha256="d" * 64,
        assessed_at=datetime(2026, 8, 23, tzinfo=timezone.utc),
    )
    tampered = copy.deepcopy(assessment)
    tampered["evidence_axes"]["browser"] = "VERIFIED"

    with pytest.raises(Phase10Error, match="checksum"):
        validate_assessment(tampered)
