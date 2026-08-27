"""활성 runtime catalog 복구 baseline의 exact equality와 무변경 dry-run을 검증한다."""

from __future__ import annotations

import copy
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "app" / "backend"
DATAHUB = ROOT / "infrastructure" / "database" / "datahub"
BACKEND_TESTS = ROOT / "tests" / "backend"
for entry in (str(ROOT), str(BACKEND), str(DATAHUB), str(BACKEND_TESTS)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from app.adapters.runtime_catalog_candidate_publisher import (  # noqa: E402
    product_release_id_for,
)
from app.adapters.runtime_catalog_projection import (  # noqa: E402
    LEGACY_SHADOW,
    RuntimeCatalogProjection,
    build_source_selection_manifest,
)
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
from compile_runtime_catalog_projection import candidate_receipt  # noqa: E402
from export_runtime_catalog_baseline import (  # noqa: E402
    build_runtime_catalog_baseline,
    plan_runtime_catalog_restore,
    validate_runtime_catalog_baseline,
    write_runtime_catalog_baseline,
)
from test_metric_governance_runtime_v2 import _verified_candidate  # noqa: E402


def _product_manifest(
    projection: RuntimeCatalogProjection,
    *,
    model_release_id: str,
    source_dirty: bool = False,
) -> ProductReleaseEvidenceManifest:
    evidence = ProductReleaseEvidence(
        source=SourceReceipt(
            commit_sha="a" * 40,
            dirty=source_dirty,
            dirty_patch_sha256="d" * 64 if source_dirty else None,
        ),
        images=tuple(
            ImageReceipt(component=component, digest=f"sha256:{index * 64}")
            for index, component in zip(
                "12345",
                ("app-db", "backend", "datahub-gms", "frontend", "trino"),
                strict=True,
            )
        ),
        migration=MigrationReceipt(revision="20260825_36", chain_sha256="b" * 64),
        model=ModelReceipt(
            release_id=model_release_id,
            manifest_sha256="c" * 64,
        ),
        catalog=CatalogReceipt(
            release_id=projection.catalog_release_id,
            manifest_sha256=projection.manifest_sha256,
            projection_sha256=projection.projection_sha256,
        ),
        release_vector=ProductReleaseVector(
            data_release_id=projection.catalog_release_id,
            semantic_release_id=projection.catalog_release_id,
            prompt_release_id=model_release_id,
            policy_release_id=projection.release.policy_version,
            runtime_release_id=(
                "RuntimeCatalogProjection.v1:" + projection.projection_sha256
            ),
        ),
    )
    return ProductReleaseEvidenceManifest.seal(
        product_release_id=product_release_id_for(evidence),
        evidence=evidence,
        created_at=datetime(2026, 8, 27, tzinfo=timezone.utc),
    )


def _fixture() -> tuple[
    RuntimeCatalogProjection,
    RuntimeCatalogProjection,
    dict[str, object],
    dict[str, object],
]:
    active, native, _snapshot = _verified_candidate()
    previous = RuntimeCatalogProjection.compile(
        active.snapshot,
        active.release,
        source_selection=build_source_selection_manifest(
            active.release,
            authority_mode=LEGACY_SHADOW,
        ),
        trino_fingerprints=active.trino_fingerprints,
    )
    # 과거 감사 증거는 현재 publication 정책에 맞춰 backfill하지 않는다.
    previous_manifest = _product_manifest(
        previous,
        model_release_id="model-previous",
        source_dirty=True,
    )
    active_manifest = _product_manifest(active, model_release_id="model-active")
    receipts = [
        {
            "activation_id": "00000000-0000-0000-0000-000000000001",
            "pointer_name": "analysis",
            "action": "ACTIVATE",
            "previous_projection_id": None,
            "previous_product_release_id": None,
            "target_projection_id": previous.projection_id,
            "target_product_release_id": previous_manifest.product_release_id,
            "expected_generation": 0,
            "resulting_generation": 1,
            "actor": "semantic-operator",
            "reason": "initial activation",
            "created_at": "2026-08-27T00:00:00+00:00",
        },
        {
            "activation_id": "00000000-0000-0000-0000-000000000002",
            "pointer_name": "analysis",
            "action": "ACTIVATE",
            "previous_projection_id": previous.projection_id,
            "previous_product_release_id": previous_manifest.product_release_id,
            "target_projection_id": active.projection_id,
            "target_product_release_id": active_manifest.product_release_id,
            "expected_generation": 1,
            "resulting_generation": 2,
            "actor": "semantic-operator",
            "reason": "verified candidate activation",
            "created_at": "2026-08-27T01:00:00+00:00",
        },
    ]
    state = {
        "active_pointer": {
            "pointer_name": "analysis",
            "projection_id": active.projection_id,
            "product_release_id": active_manifest.product_release_id,
            "generation": 2,
            "activated_by": "semantic-operator",
            "activated_at": "2026-08-27T01:00:00+00:00",
        },
        # DB/API 반환 순서는 baseline identity가 아니다.
        "runtime_projections": [active.as_document(), previous.as_document()],
        "product_release_manifests": [
            active_manifest.model_dump(mode="json"),
            previous_manifest.model_dump(mode="json"),
        ],
        "activation_receipts": list(reversed(receipts)),
    }
    return active, previous, state, candidate_receipt(active, native)


def test_baseline_seals_live_exact_match_and_complete_receipt_dependencies() -> None:
    active, _previous, unordered_state, receipt = _fixture()

    first = build_runtime_catalog_baseline(unordered_state, active, receipt)
    second = build_runtime_catalog_baseline(
        {
            **unordered_state,
            "runtime_projections": list(
                reversed(unordered_state["runtime_projections"])
            ),
            "product_release_manifests": list(
                reversed(unordered_state["product_release_manifests"])
            ),
            "activation_receipts": list(
                reversed(unordered_state["activation_receipts"])
            ),
        },
        active,
        receipt,
    )

    assert first == second
    assert first["content_sha256"] == active.projection_sha256
    assert first["inventory"]["runtime_projection_count"] == 2
    assert first["inventory"]["activation_receipt_count"] == 2
    assert first["inventory"]["dataset_count"] > 0
    assert first["inventory"]["column_count"] > 0
    validate_runtime_catalog_baseline(first)

    dry_run = plan_runtime_catalog_restore(first)
    assert dry_run["status"] == "RESTORE_DRY_RUN_VALIDATED"
    assert dry_run["mutation_count"] == 0
    assert dry_run["target_generation"] == 2


def test_baseline_rejects_live_datahub_projection_drift() -> None:
    _active, previous, state, receipt = _fixture()

    with pytest.raises(ValueError, match="live DataHub.*active projection"):
        build_runtime_catalog_baseline(state, previous, receipt)


def test_baseline_rejects_content_or_receipt_tampering() -> None:
    active, _previous, state, receipt = _fixture()
    document = build_runtime_catalog_baseline(state, active, receipt)

    tampered = copy.deepcopy(document)
    tampered["active_pointer"]["activated_by"] = "unknown"
    with pytest.raises(ValueError, match="deployment receipt checksum"):
        validate_runtime_catalog_baseline(tampered)


def test_baseline_export_never_overwrites_existing_file(tmp_path: Path) -> None:
    active, _previous, state, receipt = _fixture()
    document = build_runtime_catalog_baseline(state, active, receipt)
    target = tmp_path / "runtime-catalog-baseline.json"

    export_receipt = write_runtime_catalog_baseline(document, target)

    assert export_receipt["status"] == "EXPORTED_WITHOUT_MUTATION"
    assert target.exists()
    with pytest.raises(FileExistsError):
        write_runtime_catalog_baseline(document, target)
    with pytest.raises(ValueError, match="absolute"):
        write_runtime_catalog_baseline(document, Path("relative.json"))
