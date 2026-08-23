"""Phase 10 host validation receipt의 고정 lane·격리 결속을 검증한다."""

from __future__ import annotations

import copy
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "app" / "backend"
for entry in (str(ROOT), str(BACKEND)):
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
from infrastructure.acceptance import phase10_host_validation as host  # noqa: E402
from src.data.governance_contract import canonical_sha256  # noqa: E402


def _source() -> SourceReceipt:
    return SourceReceipt(
        commit_sha="a" * 40,
        dirty=True,
        dirty_patch_sha256="b" * 64,
    )


def _manifest() -> ProductReleaseEvidenceManifest:
    evidence = ProductReleaseEvidence(
        source=_source(),
        images=(ImageReceipt(component="backend", digest="sha256:" + "c" * 64),),
        migration=MigrationReceipt(revision="20260823_35", chain_sha256="d" * 64),
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
        product_release_id=host.PHASE10_PREFIX + "1" * 64,
        evidence=evidence,
        created_at=datetime(2026, 8, 23, tzinfo=timezone.utc),
    )


def _receipt(manifest: ProductReleaseEvidenceManifest) -> dict:
    checks = [
        {
            "check_id": check.identifier,
            "status": "PASSED",
            "exit_code": 0,
            "duration_ms": 1,
            "output_sha256": "2" * 64,
        }
        for check in host.validation_checks(_source())
    ]
    payload = {
        "schema_version": host.RECEIPT_VERSION,
        "verified": True,
        "target_project": host.TARGET_PROJECT,
        "product_release_id": manifest.product_release_id,
        "active_generation": 8,
        "source": _source().model_dump(mode="json"),
        "checks": checks,
        "failed_check_ids": [],
        "historical_evidence_mixed": False,
        "skipped_evidence_count": 0,
        "sealed_at": "2026-08-23T00:00:00+00:00",
    }
    payload["receipt_sha256"] = canonical_sha256(payload)
    return payload


def test_host_database_boundary_is_exact() -> None:
    host._database_url(
        "postgresql+psycopg://phase10_runtime@127.0.0.1:55440/"
        "phase10_p0_same_release_acceptance"
    )
    with pytest.raises(host.Phase10HostValidationError, match="database"):
        host._database_url(
            "postgresql+psycopg://postgres@127.0.0.1:55440/"
            "phase4_runtime_catalog_acceptance"
        )


def test_host_check_decodes_utf8_and_tolerates_missing_captured_streams(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}

    def fake_run(*_args: object, **kwargs: object) -> SimpleNamespace:
        captured.update(kwargs)
        return SimpleNamespace(returncode=0, stdout=None, stderr=None)

    monkeypatch.setattr(host.subprocess, "run", fake_run)

    result = host._run_check(
        host.ValidationCheck("utf8_output", ("unused",), cwd=tmp_path)
    )

    assert captured["encoding"] == "utf-8"
    assert captured["errors"] == "replace"
    assert result["status"] == "PASSED"
    assert len(result["output_sha256"]) == 64


def test_host_receipt_requires_every_current_check_and_rejects_tampering() -> None:
    manifest = _manifest()
    receipt = _receipt(manifest)

    host.validate_receipt(
        receipt,
        active_manifest=manifest,
        active_generation=8,
        current_source=_source(),
    )

    tampered = copy.deepcopy(receipt)
    tampered["checks"].pop()
    with pytest.raises(host.Phase10HostValidationError, match="differs"):
        host.validate_receipt(
            tampered,
            active_manifest=manifest,
            active_generation=8,
            current_source=_source(),
        )
