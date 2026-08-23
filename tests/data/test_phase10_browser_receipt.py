"""Phase 10 browser receipt의 격리 경계·same-release 결속을 검증한다."""

from __future__ import annotations

import copy
import sys
from datetime import datetime, timezone
from pathlib import Path

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
from infrastructure.acceptance import phase10_browser_receipt as browser  # noqa: E402
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
        product_release_id=browser.PHASE10_PREFIX + "1" * 64,
        evidence=evidence,
        created_at=datetime(2026, 8, 23, tzinfo=timezone.utc),
    )


def _receipt(manifest: ProductReleaseEvidenceManifest) -> dict:
    payload = {
        "schema_version": browser.RECEIPT_VERSION,
        "verified": True,
        "target_project": browser.TARGET_PROJECT,
        "frontend_url": browser.FRONTEND_URL,
        "product_release_id": manifest.product_release_id,
        "active_generation": 7,
        "source": _source().model_dump(mode="json"),
        "operator_assertions": {
            "completion_visible": True,
            "evidence_visible": True,
            "browser_engine": "chromium",
            "trace_or_network_capture_retained": False,
        },
        "screenshot": {
            "path": "output/playwright/phase10.png",
            "sha256": "2" * 64,
            "size_bytes": 2048,
        },
        "database_evidence": {
            "request_id": "11111111-1111-4111-8111-111111111111",
            "run_status": "SUCCEEDED",
            "query_id": "query-1",
            "query_status": "SUCCEEDED",
            "row_count": 1,
            "artifact_id": "22222222-2222-4222-8222-222222222222",
            "artifact_status": "APPROVED",
            "cached": False,
            "receipt_complete": True,
            "binding_match": True,
        },
        "sealed_at": "2026-08-23T00:00:00+00:00",
    }
    payload["receipt_sha256"] = canonical_sha256(payload)
    return payload


def test_browser_database_boundary_is_exact() -> None:
    browser._database_url(
        "postgresql+psycopg://phase10_runtime@127.0.0.1:55440/"
        "phase10_p0_same_release_acceptance"
    )
    with pytest.raises(browser.Phase10BrowserReceiptError, match="database"):
        browser._database_url(
            "postgresql+psycopg://postgres@127.0.0.1:55440/"
            "phase4_runtime_catalog_acceptance"
        )


def test_browser_receipt_revalidates_durable_evidence_and_checksum(monkeypatch) -> None:
    manifest = _manifest()
    receipt = _receipt(manifest)
    monkeypatch.setattr(browser, "_screenshot_receipt", lambda _path: dict(receipt["screenshot"]))
    monkeypatch.setattr(
        browser,
        "_durable_evidence",
        lambda _url, _request_id: (
            manifest,
            7,
            dict(receipt["database_evidence"]),
        ),
    )

    browser.validate_receipt(
        receipt,
        database_url=(
            "postgresql+psycopg://phase10_runtime@127.0.0.1:55440/"
            "phase10_p0_same_release_acceptance"
        ),
        active_manifest=manifest,
        active_generation=7,
        current_source=_source(),
    )

    tampered = copy.deepcopy(receipt)
    tampered["database_evidence"]["cached"] = True
    with pytest.raises(browser.Phase10BrowserReceiptError, match="differs"):
        browser.validate_receipt(
            tampered,
            database_url=(
                "postgresql+psycopg://phase10_runtime@127.0.0.1:55440/"
                "phase10_p0_same_release_acceptance"
            ),
            active_manifest=manifest,
            active_generation=7,
            current_source=_source(),
        )
