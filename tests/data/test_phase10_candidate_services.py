from __future__ import annotations

import copy
import asyncio
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

from infrastructure.acceptance import phase10_candidate_services as services  # noqa: E402
from infrastructure.acceptance.phase10_candidate_services import (
    CONTAINERS,
    ENV_FILE,
    PHASE10_PREFIX,
    Phase10CandidateServiceError,
    _seal_lease,
    parse_args,
    validate_boundary,
    validate_lease,
)


def _args(extra: list[str] | None = None):
    return parse_args(
        [
            "start",
            "--target-project",
            "answervice-phase2b-datahub",
            "--target-server",
            "https://127.0.0.1:38081",
            "--env-file",
            str(ENV_FILE),
            *(extra or []),
        ]
    )


def test_candidate_service_boundary_is_exact() -> None:
    validate_boundary(_args())

    with pytest.raises(Phase10CandidateServiceError, match="project"):
        validate_boundary(_args(["--target-project", "answervice"]))
    with pytest.raises(Phase10CandidateServiceError, match="endpoint"):
        validate_boundary(
            _args(["--target-server", "https://127.0.0.1:28081"])
        )
    with pytest.raises(Phase10CandidateServiceError, match="environment"):
        validate_boundary(_args(["--env-file", str(Path(__file__))]))


def test_candidate_service_lease_has_no_token_secret_and_rejects_tampering() -> None:
    lease = _seal_lease(
        "urn:li:corpuser:service_phase10",
        "token-id-only",
        PHASE10_PREFIX + "a" * 64,
    )

    validate_lease(lease)
    assert lease["containers"] == list(CONTAINERS)
    assert "access_token" not in lease
    assert "token_secret" not in lease

    tampered = copy.deepcopy(lease)
    tampered["target_project"] = "answervice"
    with pytest.raises(Phase10CandidateServiceError, match="lease"):
        validate_lease(tampered)


def test_running_candidate_receipt_rebinds_containers_images_and_readiness(monkeypatch) -> None:
    source = SourceReceipt(
        commit_sha="a" * 40,
        dirty=True,
        dirty_patch_sha256="b" * 64,
    )
    backend_id = "sha256:" + "c" * 64
    frontend_id = "sha256:" + "d" * 64
    evidence = ProductReleaseEvidence(
        source=source,
        images=(
            ImageReceipt(component="backend", digest=backend_id),
            ImageReceipt(component="frontend", digest=frontend_id),
        ),
        migration=MigrationReceipt(revision="20260823_35", chain_sha256="e" * 64),
        model=ModelReceipt(release_id="model-v1", manifest_sha256="f" * 64),
        catalog=CatalogReceipt(
            release_id="catalog-v1",
            manifest_sha256="0" * 64,
            projection_sha256="1" * 64,
        ),
        release_vector=ProductReleaseVector(
            data_release_id="catalog-v1",
            semantic_release_id="catalog-v1",
            prompt_release_id="model-v1",
            policy_release_id="policy-v1",
            runtime_release_id="runtime-v1",
        ),
    )
    manifest = ProductReleaseEvidenceManifest.seal(
        product_release_id=PHASE10_PREFIX + "2" * 64,
        evidence=evidence,
        created_at=datetime(2026, 8, 23, tzinfo=timezone.utc),
    )
    lease = _seal_lease(
        "urn:li:corpuser:service_phase10",
        "token-id-only",
        manifest.product_release_id,
    )
    monkeypatch.setattr(services, "_read_lease", lambda: lease)
    monkeypatch.setattr(services, "_source_receipt", lambda: (source, manifest.created_at))
    monkeypatch.setattr(services, "_active_manifest", lambda: (manifest, 9))
    monkeypatch.setattr(
        services,
        "_image_identity",
        lambda name: (
            backend_id if name == services.BACKEND_IMAGE else frontend_id,
            "component",
            source.commit_sha,
            "true",
            source.dirty_patch_sha256,
        ),
    )
    monkeypatch.setattr(
        services,
        "_container_identity",
        lambda _name: (services.TARGET_PROJECT, services.SCOPE_LABEL, "healthy"),
    )
    monkeypatch.setattr(
        services,
        "_container_image_id",
        lambda name: backend_id if name == CONTAINERS[0] else frontend_id,
    )

    class Response:
        status_code = 200
        text = "<title>ANSWERVICE</title>"

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "data": {
                    "status": "ready",
                    "dependencies": {"app_postgres": "ready", "scheduler": "not_required"},
                }
            }

    class Client:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, _url):
            return Response()

    monkeypatch.setattr(services.httpx, "AsyncClient", Client)
    receipt = asyncio.run(services.inspect_candidate_services(_args()))

    assert receipt["verified"] is True
    assert receipt["active_generation"] == 9
    assert receipt["product_release_id"] == manifest.product_release_id
    assert set(receipt["containers"]) == set(CONTAINERS)
