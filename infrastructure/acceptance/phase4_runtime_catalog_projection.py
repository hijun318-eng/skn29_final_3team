"""Compile, canary, activate, and roll back RuntimeCatalogProjection in isolation.

The current DataHub and Trino endpoints are read-only release sources. DataHub
full scroll/read-back runs exactly once in this out-of-band compiler. Runtime
checks read the immutable PostgreSQL projection and use only bounded DataHub
Search. All database writes are hard-bound to the Phase 4 acceptance database.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import subprocess
import sys
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from time import monotonic
from typing import Any
from uuid import UUID, uuid4

import httpx
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BACKEND = ROOT / "app" / "backend"
DATAHUB = ROOT / "infrastructure" / "database" / "datahub"
for entry in (str(ROOT), str(BACKEND), str(DATAHUB), str(HERE)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from app.adapters.catalog_snapshot import CatalogSnapshotLoader  # noqa: E402
from app.adapters.datahub_catalog import (  # noqa: E402
    DataHubCatalogClient,
    DataHubCatalogError,
)
from app.adapters.legacy_semantic_release import (  # noqa: E402
    compile_legacy_semantic_release,
)
from app.adapters.query_governance import QueryGovernanceEngine  # noqa: E402
from app.adapters.report_repository import PostgresReportRepository  # noqa: E402
from app.adapters.runtime_catalog_projection import (  # noqa: E402
    LEGACY_SHADOW,
    NATIVE_PRIORITY,
    RuntimeCatalogProjection,
    build_source_selection_manifest,
)
from app.adapters.runtime_catalog_repository import (  # noqa: E402
    ActiveRuntimeCatalogProjection,
    PostgresRuntimeCatalogProjectionRepository,
    RuntimeCatalogActivationConflict,
    RuntimeCatalogRepositoryError,
)
from app.adapters.trino_async import TrinoAsyncClient  # noqa: E402
from app.adapters.trino_schema import TrinoSchemaInspector  # noqa: E402
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
from app.database import get_sessionmaker  # noqa: E402
from app.ports.data_platform import (  # noqa: E402
    ExecutionAssetSelection,
    ReleaseReceiptChangedError,
)
from app.runtime_release import runtime_contract_receipt  # noqa: E402
from native_metric_publication import verify_native_metric_shadow  # noqa: E402
from native_metric_shadow import (  # noqa: E402
    iter_native_metric_aspects,
    native_metric_shadow_projection,
    native_metric_urn,
)
from phase2b_datahub_candidate import (  # noqa: E402
    AcceptanceError,
    IsolatedSystemClient,
    TARGET_PORT,
    TARGET_PROJECT,
    _build_bundle,
    _target_scope,
)
from phase3b_native_metric_shadow import RetryingIsolatedClient  # noqa: E402
from src.ai.model_contracts import (  # noqa: E402
    model_release_checksum,
    model_release_manifest,
)
from src.data.datahub_connection import DataHubConnectionSettings  # noqa: E402
from src.data.governance_contract import canonical_json, canonical_sha256, catalog_hash  # noqa: E402
from src.report.domain import (  # noqa: E402
    BlockType,
    DefinitionStatus,
    ReportBlock,
    ReportDefinitionVersion,
)


DATABASE_NAME = "phase4_runtime_catalog_acceptance"
DATABASE_PORT = 55440
MIGRATION_REVISION = "20260822_33"
_OBJECT_KINDS = (
    "CONVERSATION",
    "TURN",
    "CONTEXT",
    "RUN",
    "ARTIFACT",
    "VIEW",
    "REPORT",
)


class Phase4Error(AcceptanceError):
    """Phase 4 cannot be proved without lowering an isolation or equality Gate."""


class RuntimeSearchOnlyCatalog:
    """Delegate bounded reads while making a runtime full scroll an explicit failure."""

    def __init__(self, delegate: DataHubCatalogClient) -> None:
        self._delegate = delegate
        self.full_read_attempt_count = 0
        self.search_request_count = 0

    async def list_datasets(self):
        self.full_read_attempt_count += 1
        raise Phase4Error("runtime attempted a full DataHub Dataset read")

    async def list_glossary_terms(self):
        self.full_read_attempt_count += 1
        raise Phase4Error("runtime attempted a full DataHub Glossary read")

    async def search_candidates(self, *args: object, **kwargs: object):
        self.search_request_count += 1
        return await self._delegate.search_candidates(*args, **kwargs)

    async def semantic_search(self, *args: object, **kwargs: object):
        self.search_request_count += 1
        return await self._delegate.semantic_search(*args, **kwargs)

    async def health(self) -> bool:
        return await self._delegate.health()


class StaticProjectionRepository:
    """Expose one explicit candidate without changing the global active pointer."""

    def __init__(self, active: ActiveRuntimeCatalogProjection) -> None:
        self._active = active

    async def load_active(self) -> ActiveRuntimeCatalogProjection:
        return self._active

    async def load_product_release(
        self,
        product_release_id: str,
    ) -> ActiveRuntimeCatalogProjection:
        if product_release_id != self._active.product_release_id:
            raise RuntimeCatalogRepositoryError(
                "static product release is unavailable"
            )
        return self._active


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-project", required=True)
    parser.add_argument("--source-server", required=True)
    parser.add_argument("--target-server", required=True)
    parser.add_argument("--trino-server", required=True)
    parser.add_argument("--trino-ca-file", type=Path, required=True)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--expected-release", required=True)
    parser.add_argument("--expected-catalog-sha256", required=True)
    parser.add_argument("--expected-canonical-sha256", required=True)
    parser.add_argument("--serving-schema", required=True)
    parser.add_argument(
        "--recipe-dir", type=Path, default=DATAHUB / "recipes"
    )
    parser.add_argument(
        "--image-receipt",
        action="append",
        default=[],
        metavar="COMPONENT=sha256:DIGEST",
    )
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--verify-timeout", type=float, default=180.0)
    return parser.parse_args(argv)


def _validate_boundary(args: argparse.Namespace) -> None:
    if args.target_project != TARGET_PROJECT:
        raise Phase4Error("Phase 4 target project is outside the approved boundary")
    endpoints = (
        (httpx.URL(args.source_server), 28081, "source DataHub"),
        (httpx.URL(args.target_server), TARGET_PORT, "target DataHub"),
        (httpx.URL(args.trino_server), 18443, "source Trino"),
    )
    for endpoint, port, label in endpoints:
        if (
            endpoint.scheme != "https"
            or endpoint.host not in {"127.0.0.1", "localhost", "::1"}
            or endpoint.port != port
            or endpoint.username
            or endpoint.password
            or endpoint.query
            or endpoint.fragment
            or endpoint.path not in {"", "/"}
        ):
            raise Phase4Error(f"{label} is outside the approved loopback boundary")
    database = make_url(args.database_url)
    if (
        database.drivername != "postgresql+psycopg"
        or database.host not in {"127.0.0.1", "localhost", "::1"}
        or database.port != DATABASE_PORT
        or database.database != DATABASE_NAME
        or database.username != "postgres"
        or database.password is not None
    ):
        raise Phase4Error("Phase 4 database is outside the isolated acceptance boundary")
    if args.source_server.rstrip("/") == args.target_server.rstrip("/"):
        raise Phase4Error("read-only source and isolated target must differ")
    if args.timeout <= 0 or args.verify_timeout <= 0:
        raise Phase4Error("Phase 4 timeouts must be positive")
    try:
        ca_file = args.trino_ca_file.resolve(strict=True)
    except OSError as error:
        raise Phase4Error("Phase 4 Trino CA is unavailable") from error
    if not ca_file.is_file() or not args.trino_ca_file.is_absolute():
        raise Phase4Error("Phase 4 Trino CA is outside the explicit file boundary")
    for value in (
        args.expected_catalog_sha256,
        args.expected_canonical_sha256,
    ):
        _sha256(value, "expected checksum")
    if not args.image_receipt:
        raise Phase4Error("Phase 4 image receipts are required")


def _sha256(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise Phase4Error(f"{label} is not a lowercase SHA-256")
    return value


def _image_receipts(values: list[str]) -> tuple[ImageReceipt, ...]:
    parsed: dict[str, ImageReceipt] = {}
    for value in values:
        component, separator, digest = value.partition("=")
        if not separator or component in parsed:
            raise Phase4Error("Phase 4 image receipt is invalid or duplicate")
        parsed[component] = ImageReceipt(component=component, digest=digest)
    return tuple(parsed[name] for name in sorted(parsed))


def _git(*arguments: str) -> bytes:
    process = subprocess.run(
        ["git", *arguments],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if process.returncode != 0:
        raise Phase4Error("source receipt could not be computed")
    return process.stdout


def _source_receipt() -> tuple[SourceReceipt, datetime]:
    commit = _git("rev-parse", "HEAD").decode("ascii").strip()
    timestamp = datetime.fromisoformat(
        _git("show", "-s", "--format=%cI", "HEAD").decode("ascii").strip()
    )
    tracked = _git(
        "diff",
        "--binary",
        "HEAD",
        "--",
        ".",
        ":(exclude)infrastructure/database/.env",
    )
    untracked_paths = _git(
        "ls-files", "-z", "--others", "--exclude-standard"
    ).decode("utf-8").split("\0")
    untracked: list[dict[str, str]] = []
    for relative in sorted(item for item in untracked_paths if item):
        normalized = relative.replace("\\", "/")
        if (
            normalized == "infrastructure/database/.env"
            or normalized.startswith((".tmp", ".pytest_cache/"))
            or "/__pycache__/" in f"/{normalized}"
            or normalized.endswith((".pyc", ".pyo"))
        ):
            continue
        path = (ROOT / relative).resolve()
        try:
            path.relative_to(ROOT.resolve())
        except ValueError as error:
            raise Phase4Error("untracked source path escaped the repository") from error
        if not path.is_file():
            continue
        untracked.append(
            {"path": normalized, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        )
    dirty_payload = tracked + canonical_json(untracked).encode("utf-8")
    dirty = bool(tracked or untracked)
    patch_sha256 = hashlib.sha256(dirty_payload).hexdigest() if dirty else None
    return (
        SourceReceipt(
            commit_sha=commit,
            dirty=dirty,
            dirty_patch_sha256=patch_sha256,
        ),
        timestamp,
    )


def _migration_chain_sha256() -> str:
    files = [BACKEND / "alembic.ini", BACKEND / "migrations" / "env.py"]
    files.extend(sorted((BACKEND / "migrations" / "versions").glob("*.py")))
    manifest = [
        {
            "path": path.relative_to(ROOT).as_posix(),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        for path in files
    ]
    return canonical_sha256(manifest)


def _native_records(bundle: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, dict[str, Mapping[str, Any]]] = {}
    for entity_type, urn, name, value in iter_native_metric_aspects(bundle):
        if entity_type == "metric":
            grouped.setdefault(urn, {})[name] = value
    records: dict[str, dict[str, Any]] = {}
    for term in bundle["metric_terms"]:
        metric_id = str(term["id"])
        urn = native_metric_urn(bundle, metric_id)
        aspects = grouped.get(urn, {})
        if not {"metricInfo", "aiContext", "status"}.issubset(aspects):
            raise Phase4Error("native Metric source record is incomplete")
        records[metric_id] = {
            "urn": urn,
            "metricInfo": dict(aspects["metricInfo"]),
            "aiContext": dict(aspects["aiContext"]),
            "status": dict(aspects["status"]),
        }
    return records


def _product_manifest(
    projection: RuntimeCatalogProjection,
    *,
    authority: str,
    images: tuple[ImageReceipt, ...],
    source: SourceReceipt,
    created_at: datetime,
) -> ProductReleaseEvidenceManifest:
    model_manifest = model_release_manifest()
    evidence = ProductReleaseEvidence(
        source=source,
        images=images,
        migration=MigrationReceipt(
            revision=MIGRATION_REVISION,
            chain_sha256=_migration_chain_sha256(),
        ),
        model=ModelReceipt(
            release_id=str(model_manifest["manifest_version"]),
            manifest_sha256=model_release_checksum(),
        ),
        catalog=CatalogReceipt(
            release_id=projection.catalog_release_id,
            manifest_sha256=projection.manifest_sha256,
            projection_sha256=projection.projection_sha256,
        ),
        release_vector=ProductReleaseVector(
            data_release_id=projection.catalog_release_id,
            semantic_release_id=projection.catalog_release_id,
            prompt_release_id=str(model_manifest["manifest_version"]),
            policy_release_id=projection.release.policy_version,
            runtime_release_id=(
                f"RuntimeCatalogProjection.v1:{projection.projection_sha256}"
            ),
        ),
    )
    identity_sha256 = canonical_sha256(
        {
            "phase": "4",
            "authority": authority,
            "evidence": evidence.model_dump(mode="json"),
        }
    )
    return ProductReleaseEvidenceManifest.seal(
        product_release_id=f"ANSWERVICE-PHASE4-{authority}:{identity_sha256}",
        evidence=evidence,
        created_at=created_at,
    )


async def _put_product_manifest(sessionmaker, manifest) -> None:
    document = manifest.model_dump(mode="json")
    evidence = document["evidence"]
    source = evidence["source"]
    migration = evidence["migration"]
    model = evidence["model"]
    catalog = evidence["catalog"]
    try:
        async with sessionmaker.begin() as session:
            await session.execute(
                text(
                    """
                    INSERT INTO governance.product_release_manifests (
                        product_release_id, contract_version, manifest_sha256,
                        manifest_json, source_commit_sha, source_dirty,
                        dirty_patch_sha256, image_digests_json,
                        migration_revision, migration_chain_sha256,
                        model_release_id, model_manifest_sha256,
                        catalog_release_id, catalog_manifest_sha256,
                        catalog_projection_sha256, release_vector_json, created_at
                    ) VALUES (
                        :product_release_id, 'ProductReleaseEvidenceManifest.v1',
                        :manifest_sha256, CAST(:manifest_json AS jsonb),
                        :source_commit_sha, :source_dirty, :dirty_patch_sha256,
                        CAST(:image_digests_json AS jsonb), :migration_revision,
                        :migration_chain_sha256, :model_release_id,
                        :model_manifest_sha256, :catalog_release_id,
                        :catalog_manifest_sha256, :catalog_projection_sha256,
                        CAST(:release_vector_json AS jsonb), :created_at
                    ) ON CONFLICT (product_release_id) DO NOTHING
                    """
                ),
                {
                    "product_release_id": manifest.product_release_id,
                    "manifest_sha256": manifest.manifest_sha256,
                    "manifest_json": canonical_json(document),
                    "source_commit_sha": source["commit_sha"],
                    "source_dirty": source["dirty"],
                    "dirty_patch_sha256": source["dirty_patch_sha256"],
                    "image_digests_json": canonical_json(evidence["images"]),
                    "migration_revision": migration["revision"],
                    "migration_chain_sha256": migration["chain_sha256"],
                    "model_release_id": model["release_id"],
                    "model_manifest_sha256": model["manifest_sha256"],
                    "catalog_release_id": catalog["release_id"],
                    "catalog_manifest_sha256": catalog["manifest_sha256"],
                    "catalog_projection_sha256": catalog["projection_sha256"],
                    "release_vector_json": canonical_json(evidence["release_vector"]),
                    "created_at": manifest.created_at,
                },
            )
            stored = (
                await session.execute(
                    text(
                        "SELECT manifest_json FROM governance.product_release_manifests "
                        "WHERE product_release_id = :product_release_id"
                    ),
                    {"product_release_id": manifest.product_release_id},
                )
            ).scalar_one()
        if canonical_json(stored) != canonical_json(document):
            raise Phase4Error("product release ID is occupied by different evidence")
    except Phase4Error:
        raise
    except SQLAlchemyError as error:
        raise Phase4Error("product release manifest could not be stored") from error


async def _bind_all_object_kinds(sessionmaker, manifest) -> int:
    vector = {"runtime.catalog": "1.0.0", "analysis.run": "1.0.0"}
    async with sessionmaker.begin() as session:
        for kind in _OBJECT_KINDS:
            await session.execute(
                text(
                    """
                    INSERT INTO governance.product_release_bindings (
                        object_kind, object_id, product_release_id,
                        permission_snapshot_id, semantic_release_id,
                        capability_release_vector_json, evidence_refs_json
                    ) VALUES (
                        :kind, :object_id, :product_release_id,
                        'phase4-isolated-permission', :semantic_release_id,
                        CAST(:vector AS jsonb), '[]'::jsonb
                    ) ON CONFLICT (object_kind, object_id) DO NOTHING
                    """
                ),
                {
                    "kind": kind,
                    "object_id": f"phase4-acceptance:{kind.lower()}",
                    "product_release_id": manifest.product_release_id,
                    "semantic_release_id": (
                        manifest.evidence.release_vector.semantic_release_id
                    ),
                    "vector": canonical_json(vector),
                },
            )
        count = (
            await session.execute(
                text(
                    "SELECT count(*) FROM governance.product_release_bindings "
                    "WHERE product_release_id = :product_release_id "
                    "AND object_id LIKE 'phase4-acceptance:%'"
                ),
                {"product_release_id": manifest.product_release_id},
            )
        ).scalar_one()
    if int(count) != len(_OBJECT_KINDS):
        raise Phase4Error("seven-kind product receipt binding is incomplete")
    return int(count)


async def _exercise_report_lifecycle(
    sessionmaker,
    database_url: str,
    manifest: ProductReleaseEvidenceManifest,
) -> dict[str, Any]:
    """실제 Report definition/run 경로가 같은 immutable receipt를 전파하는지 증명한다."""

    owner_id = uuid4()
    definition_id = uuid4()
    block_id = uuid4()
    permission_id = "phase4-isolated-report-permission"
    semantic_id = manifest.evidence.release_vector.semantic_release_id
    repository = PostgresReportRepository(
        database_url,
        owner_id,
        product_release_id=manifest.product_release_id,
        permission_snapshot_id=permission_id,
        semantic_release_id=semantic_id,
        session_factory=sessionmaker,
    )
    draft = await repository.add_draft(
        ReportDefinitionVersion(
            definition_id=str(definition_id),
            version=1,
            status=DefinitionStatus.DRAFT,
            title="Phase 4 isolated receipt acceptance",
            blocks=(
                ReportBlock(
                    block_id=str(block_id),
                    title="Receipt evidence",
                    artifact_id=None,
                    columns=12,
                    type=BlockType.TEXT,
                    content="Isolated acceptance evidence only.",
                ),
            ),
        )
    )
    immutable_rejections = 0
    try:
        async with sessionmaker.begin() as session:
            await session.execute(
                text(
                    "UPDATE report_v1.report_definition_versions "
                    "SET permission_snapshot_id = 'mutated' "
                    "WHERE definition_id = :object_id AND version = 1"
                ),
                {"object_id": definition_id},
            )
    except SQLAlchemyError as error:
        if "Report release receipt is immutable" not in str(error):
            raise Phase4Error(
                "Report receipt mutation failed for an unrelated reason"
            ) from error
        immutable_rejections += 1

    approved = await repository.approve(
        str(definition_id), 1, manifest.created_at
    )
    command = await repository.queue_manual_run(
        str(definition_id),
        1,
        manifest.created_at,
        f"phase4-report:{definition_id}",
    )
    claim = await repository.claim_manual_run(command.command_id)
    if not claim["claimed"]:
        raise Phase4Error("isolated Report run was not claimed")
    run = await repository.finish_manual_run(command.command_id)
    expected_receipt = (
        manifest.product_release_id,
        permission_id,
        semantic_id,
    )
    if (
        (
            draft.product_release_id,
            draft.permission_snapshot_id,
            draft.semantic_release_id,
        )
        != expected_receipt
        or (
            approved.product_release_id,
            approved.permission_snapshot_id,
            approved.semantic_release_id,
        )
        != expected_receipt
        or (
            run.product_release_id,
            run.permission_snapshot_id,
            run.semantic_release_id,
        )
        != expected_receipt
    ):
        raise Phase4Error("Report definition/run receipt propagation differs")

    definition_object_id = f"definition:{definition_id}:v1"
    run_object_id = f"run:{run.run_id}"
    async with sessionmaker() as session:
        bindings = (await session.execute(
            text(
                """
                SELECT object_id, product_release_id, permission_snapshot_id,
                       semantic_release_id
                FROM governance.product_release_bindings
                WHERE object_kind = 'REPORT'
                  AND object_id IN (:definition_object_id, :run_object_id)
                ORDER BY object_id
                """
            ),
            {
                "definition_object_id": definition_object_id,
                "run_object_id": run_object_id,
            },
        )).mappings().all()
    if len(bindings) != 2 or any(
        (
            str(item["product_release_id"]),
            str(item["permission_snapshot_id"]),
            str(item["semantic_release_id"]),
        )
        != expected_receipt
        for item in bindings
    ):
        raise Phase4Error("Report product release bindings differ")

    try:
        async with sessionmaker.begin() as session:
            await session.execute(
                text(
                    "UPDATE report_v1.report_runs "
                    "SET permission_snapshot_id = 'mutated' WHERE run_id = :object_id"
                ),
                {"object_id": UUID(run.run_id)},
            )
    except SQLAlchemyError as error:
        if "Report release receipt is immutable" not in str(error):
            raise Phase4Error(
                "Report receipt mutation failed for an unrelated reason"
            ) from error
        immutable_rejections += 1
    if immutable_rejections != 2:
        raise Phase4Error("Report release receipt mutation was accepted")
    return {
        "definition_binding_count": 1,
        "run_binding_count": 1,
        "receipt_immutability_rejection_count": immutable_rejections,
        "run_status": run.status.value,
    }


async def _readiness(engine: QueryGovernanceEngine) -> tuple[dict[str, str], str, float]:
    started = monotonic()
    stages, receipt = await engine.catalog_readiness()
    latency_ms = (monotonic() - started) * 1_000
    if (
        stages
        != {
            "semantic_release": "ready",
            "catalog_manifest": "ready",
            "trino_schema": "ready",
        }
        or receipt is None
    ):
        raise Phase4Error("RuntimeCatalogProjection readiness is not complete")
    return stages, receipt, round(latency_ms, 3)


def _direct_business_metric(projection: RuntimeCatalogProjection) -> tuple[str, str]:
    bundle = projection.release.as_bundle()
    terms = {str(item["id"]): item for item in bundle["metric_terms"]}
    for rule in bundle["metric_rules"]:
        metric_id = str(rule["id"])
        if metric_id in terms and rule.get("source", {}).get("kind") == "column":
            return metric_id, str(terms[metric_id]["name"])
    raise Phase4Error("candidate release has no direct BUSINESS Metric")


def _execution_selection(candidates, metric_id: str) -> ExecutionAssetSelection:
    selectable = {
        str(metric.get("id"))
        for asset in candidates.assets
        for metric in asset.get("metrics", ())
        if isinstance(metric, Mapping) and metric.get("candidate_selectable") is True
    }
    if metric_id not in selectable:
        raise Phase4Error("bounded candidate Search did not return the canary Metric")
    return ExecutionAssetSelection(
        output_metric_ids=(metric_id,),
        execution_metric_ids=(metric_id,),
        field_references=(),
        receipt_context_release=candidates.context_release,
        receipt_catalog_checksum=candidates.catalog_checksum,
        receipt_canonical_checksum=candidates.canonical_checksum,
        receipt_product_release_id=candidates.product_release_id,
        receipt_runtime_projection_checksum=candidates.runtime_projection_checksum,
    )


async def _immutability_and_mixed_release_check(sessionmaker) -> dict[str, Any]:
    async with sessionmaker() as session:
        mixed = (
            await session.execute(
                text(
                    """
                    SELECT count(*)
                    FROM governance.runtime_catalog_active_pointer a
                    JOIN governance.runtime_catalog_projections p
                      ON p.projection_id = a.projection_id
                    JOIN governance.product_release_manifests m
                      ON m.product_release_id = a.product_release_id
                    WHERE p.catalog_release_id <> m.catalog_release_id
                       OR p.manifest_sha256 <> m.catalog_manifest_sha256
                       OR p.projection_sha256 <> m.catalog_projection_sha256
                    """
                )
            )
        ).scalar_one()
        receipts = (
            await session.execute(
                text(
                    """
                    SELECT action, expected_generation, resulting_generation
                    FROM governance.runtime_catalog_activation_receipts
                    ORDER BY resulting_generation
                    """
                )
            )
        ).mappings().all()
    immutable_rejections = 0
    for statement in (
        "UPDATE governance.runtime_catalog_projections SET created_at = created_at",
        "UPDATE governance.runtime_catalog_activation_receipts SET created_at = created_at",
        "UPDATE governance.product_release_bindings SET bound_at = bound_at",
    ):
        try:
            async with sessionmaker.begin() as session:
                await session.execute(text(statement))
        except SQLAlchemyError:
            immutable_rejections += 1
    if int(mixed) != 0 or immutable_rejections != 3:
        raise Phase4Error("mixed-release or immutable evidence Gate failed")
    return {
        "mixed_release_pointer_count": int(mixed),
        "immutable_mutation_rejection_count": immutable_rejections,
        "activation_receipts": [dict(item) for item in receipts],
    }


async def run(args: argparse.Namespace) -> dict[str, Any]:
    _validate_boundary(args)
    source_environment = dict(os.environ)
    source_environment["DATAHUB_GMS_URL"] = args.source_server
    read_settings = DataHubConnectionSettings.from_env(source_environment)
    bundle = await _build_bundle(args, read_settings)
    if catalog_hash(bundle) != args.expected_catalog_sha256:
        raise Phase4Error("out-of-band source catalog checksum differs")

    native_projection = native_metric_shadow_projection(bundle)
    trino_user = os.getenv("TRINO_DATAHUB_USER", "")
    trino_password = os.getenv("TRINO_DATAHUB_PASSWORD", "")
    client_id = os.getenv("DATAHUB_SYSTEM_CLIENT_ID", "")
    client_secret = os.getenv("DATAHUB_SYSTEM_CLIENT_SECRET", "")
    if not all((trino_user, trino_password, client_id, client_secret)):
        raise Phase4Error("Phase 4 isolated credentials are incomplete")

    sessionmaker = get_sessionmaker(args.database_url)
    repository = PostgresRuntimeCatalogProjectionRepository(sessionmaker)
    try:
        await repository.load_active()
    except RuntimeCatalogRepositoryError:
        pass
    else:
        raise Phase4Error("Phase 4 acceptance pointer is not initially empty")

    account = token = token_id = None
    catalog: DataHubCatalogClient | None = None
    runtime_catalog: RuntimeSearchOnlyCatalog | None = None
    engines: list[QueryGovernanceEngine] = []
    try:
        async with IsolatedSystemClient(
            args.target_server,
            ca_file=read_settings.ca_file,
            client_id=client_id,
            client_secret=client_secret,
            timeout_seconds=args.timeout,
        ) as raw_target:
            target = RetryingIsolatedClient(raw_target)
            await _target_scope(raw_target, bundle, require_complete=True)
            native_verified = await verify_native_metric_shadow(
                target,
                bundle,
                expected_projection_sha256=native_projection["projection_sha256"],
            )
            account = await raw_target.create_temporary_service_account()
            token, token_id = await raw_target.create_temporary_access_token(account)
            catalog = DataHubCatalogClient(
                args.target_server,
                token,
                ca_file=read_settings.ca_file,
                expected_actor_urn=account,
                timeout_seconds=args.timeout,
                page_size=50,
                max_entities=10_000,
            )
            try:
                healthy = await catalog.health()
            except DataHubCatalogError as error:
                raise Phase4Error(
                    f"target DataHub read identity health failed: {error.category}"
                ) from error
            if not healthy:
                raise Phase4Error("temporary isolated DataHub read identity is unhealthy")

            # This is the only full DataHub read in the workflow.
            try:
                snapshot = await CatalogSnapshotLoader(
                    catalog,
                    max_concurrency=3,
                    ttl_seconds=max(args.verify_timeout, 1.0),
                ).load()
            except DataHubCatalogError as error:
                raise Phase4Error(
                    f"target DataHub full read-back failed: {error.category}"
                ) from error
            release = compile_legacy_semantic_release(
                snapshot, args.expected_release
            )
            if (
                release.catalog_checksum != args.expected_catalog_sha256
                or release.canonical_checksum != args.expected_canonical_sha256
            ):
                raise Phase4Error("target full read-back differs from the source release")

            trino = TrinoAsyncClient(
                args.trino_server,
                trino_user,
                trino_password,
                ca_file=args.trino_ca_file,
                request_timeout_seconds=args.timeout,
            )
            try:
                schema = TrinoSchemaInspector(trino, timeout_seconds=args.timeout)
                datasets = tuple(
                    snapshot.datasets_by_fqn[asset.fqn] for asset in release.assets
                )
                fingerprints = await schema.fingerprints(datasets)
                baseline = RuntimeCatalogProjection.compile(
                    snapshot,
                    release,
                    source_selection=build_source_selection_manifest(
                        release, authority_mode=LEGACY_SHADOW
                    ),
                    trino_fingerprints=fingerprints,
                )
                candidate = RuntimeCatalogProjection.compile(
                    snapshot,
                    release,
                    source_selection=build_source_selection_manifest(
                        release,
                        authority_mode=NATIVE_PRIORITY,
                        native_records=_native_records(bundle),
                        native_projection_sha256=native_projection["projection_sha256"],
                        native_membership_sha256=native_projection[
                            "release_membership_sha256"
                        ],
                    ),
                    trino_fingerprints=fingerprints,
                )
                if (
                    baseline.canonical_sha256 != candidate.canonical_sha256
                    or baseline.catalog_sha256 != candidate.catalog_sha256
                    or len(baseline.release.assets) != len(candidate.release.assets)
                    or len(baseline.release.metrics) != len(candidate.release.metrics)
                ):
                    raise Phase4Error("legacy/native projection equality is incomplete")

                images = _image_receipts(args.image_receipt)
                source, created_at = _source_receipt()
                baseline_manifest = _product_manifest(
                    baseline,
                    authority=LEGACY_SHADOW,
                    images=images,
                    source=source,
                    created_at=created_at,
                )
                candidate_manifest = _product_manifest(
                    candidate,
                    authority=NATIVE_PRIORITY,
                    images=images,
                    source=source,
                    created_at=created_at,
                )
                await repository.put_projection(baseline)
                await repository.put_projection(candidate)
                await _put_product_manifest(sessionmaker, baseline_manifest)
                await _put_product_manifest(sessionmaker, candidate_manifest)
                baseline_pair = await repository.load_candidate(
                    baseline.projection_id, baseline_manifest.product_release_id
                )
                candidate_pair = await repository.load_candidate(
                    candidate.projection_id, candidate_manifest.product_release_id
                )
                pair_mismatch_rejections = 0
                try:
                    await repository.load_candidate(
                        candidate.projection_id,
                        baseline_manifest.product_release_id,
                    )
                except RuntimeCatalogRepositoryError:
                    pair_mismatch_rejections += 1
                if pair_mismatch_rejections != 1:
                    raise Phase4Error("projection/product pair mismatch was accepted")

                active = await repository.activate(
                    projection_id=baseline.projection_id,
                    product_release_id=baseline_manifest.product_release_id,
                    expected_generation=0,
                    action="ACTIVATE",
                    actor="phase4-acceptance",
                    reason="establish legacy shadow rollback baseline",
                )
                if active.generation != 1:
                    raise Phase4Error("initial activation generation differs")
                stale_cas_rejections = 0
                try:
                    await repository.activate(
                        projection_id=candidate.projection_id,
                        product_release_id=candidate_manifest.product_release_id,
                        expected_generation=0,
                        action="ACTIVATE",
                        actor="phase4-acceptance",
                        reason="stale generation negative",
                    )
                except RuntimeCatalogActivationConflict:
                    stale_cas_rejections += 1

                runtime_catalog = RuntimeSearchOnlyCatalog(catalog)
                candidate_engine = QueryGovernanceEngine(
                    runtime_catalog,
                    schema,
                    expected_context_release=args.expected_release,
                    search_mode="datahub_lexical",
                    projection_repository=StaticProjectionRepository(candidate_pair),
                )
                engines.append(candidate_engine)
                candidate_stages, candidate_receipt, candidate_latency = await _readiness(
                    candidate_engine
                )
                if candidate_receipt != candidate_manifest.product_release_id:
                    raise Phase4Error("candidate canary receipt differs")
                metric_id, query = _direct_business_metric(candidate)
                canary_candidates = await candidate_engine.search_asset_candidates(
                    query, {"role": "analyst", "parameters": {}}
                )
                canary_selection = _execution_selection(canary_candidates, metric_id)
                await candidate_engine.resolve_execution_assets(
                    canary_selection, {"role": "analyst", "parameters": {}}
                )
                pointer_after_canary = await repository.load_active()
                if pointer_after_canary.product_release_id != baseline_manifest.product_release_id:
                    raise Phase4Error("candidate canary changed the active pointer")

                active = await repository.activate(
                    projection_id=candidate.projection_id,
                    product_release_id=candidate_manifest.product_release_id,
                    expected_generation=1,
                    action="ACTIVATE",
                    actor="phase4-acceptance",
                    reason="native candidate passed explicit canary",
                )
                if active.generation != 2:
                    raise Phase4Error("candidate activation generation differs")
                active_engine = QueryGovernanceEngine(
                    runtime_catalog,
                    schema,
                    expected_context_release=args.expected_release,
                    search_mode="datahub_lexical",
                    projection_repository=repository,
                )
                engines.append(active_engine)
                receipt_candidates = await active_engine.search_asset_candidates(
                    query, {"role": "analyst", "parameters": {}}
                )
                receipt_selection = _execution_selection(receipt_candidates, metric_id)

                rolled_back = await repository.activate(
                    projection_id=baseline.projection_id,
                    product_release_id=baseline_manifest.product_release_id,
                    expected_generation=2,
                    action="ROLLBACK",
                    actor="phase4-acceptance",
                    reason="rehearse exact rollback after native activation",
                )
                rollback_stages, rollback_receipt, rollback_latency = await _readiness(
                    active_engine
                )
                if (
                    rolled_back.generation != 3
                    or rollback_receipt != baseline_manifest.product_release_id
                ):
                    raise Phase4Error("rollback pointer or readiness differs")
                mixed_release_blocks = 0
                try:
                    await active_engine.resolve_execution_assets(
                        receipt_selection,
                        {"role": "analyst", "parameters": {}},
                    )
                except ReleaseReceiptChangedError:
                    mixed_release_blocks += 1
                if mixed_release_blocks != 1:
                    raise Phase4Error("mixed-release execution was not blocked")

                final_active = await repository.activate(
                    projection_id=candidate.projection_id,
                    product_release_id=candidate_manifest.product_release_id,
                    expected_generation=3,
                    action="ACTIVATE",
                    actor="phase4-acceptance",
                    reason="restore canary-verified native projection",
                )
                cold_stages, cold_receipt, cold_latency = await _readiness(active_engine)
                warm_stages, warm_receipt, warm_latency = await _readiness(active_engine)
                final_candidates = await active_engine.search_asset_candidates(
                    query, {"role": "analyst", "parameters": {}}
                )
                final_selection = _execution_selection(final_candidates, metric_id)
                final_assets = await active_engine.resolve_execution_assets(
                    final_selection, {"role": "analyst", "parameters": {}}
                )
                if (
                    final_active.generation != 4
                    or cold_receipt != candidate_manifest.product_release_id
                    or warm_receipt != candidate_manifest.product_release_id
                    or final_candidates.product_release_id != candidate_manifest.product_release_id
                    or not final_assets
                ):
                    raise Phase4Error("final active projection receipt differs")

                report_lifecycle = await _exercise_report_lifecycle(
                    sessionmaker,
                    args.database_url,
                    candidate_manifest,
                )
                binding_count = await _bind_all_object_kinds(
                    sessionmaker, candidate_manifest
                )
                database_checks = await _immutability_and_mixed_release_check(
                    sessionmaker
                )
                if (
                    stale_cas_rejections != 1
                    or runtime_catalog.full_read_attempt_count != 0
                    or len(database_checks["activation_receipts"]) != 4
                ):
                    raise Phase4Error("Phase 4 CAS or runtime read boundary failed")
                return {
                    "status": "PHASE4_RUNTIME_CATALOG_PROJECTION_PASSED",
                    "target_project": args.target_project,
                    "database": DATABASE_NAME,
                    "release_id": release.catalog_version,
                    "catalog_sha256": release.catalog_checksum,
                    "canonical_sha256": release.canonical_checksum,
                    "source_selection_manifest": True,
                    "legacy_authority_mode": LEGACY_SHADOW,
                    "candidate_authority_mode": NATIVE_PRIORITY,
                    "legacy_projection_sha256": baseline.projection_sha256,
                    "candidate_projection_sha256": candidate.projection_sha256,
                    "candidate_membership_sha256": candidate.membership_sha256,
                    "trino_fingerprint_sha256": candidate.trino_fingerprint_sha256,
                    "asset_membership_count": len(candidate.release.assets),
                    "metric_membership_count": len(candidate.release.metrics),
                    "native_metric_count": native_verified["native_metric_count"],
                    "native_projection_sha256": native_projection["projection_sha256"],
                    "native_membership_sha256": native_projection[
                        "release_membership_sha256"
                    ],
                    "membership_equality": "100%",
                    "canonical_equality": "100%",
                    "pair_mismatch_rejection_count": pair_mismatch_rejections,
                    "stale_cas_rejection_count": stale_cas_rejections,
                    "mixed_release_block_count": mixed_release_blocks,
                    "mixed_release_execution_count": 0,
                    "runtime_full_scroll_attempt_count": (
                        runtime_catalog.full_read_attempt_count
                    ),
                    "bounded_search_request_count": runtime_catalog.search_request_count,
                    "candidate_canary": {
                        "stages": candidate_stages,
                        "latency_ms": candidate_latency,
                        "pointer_generation": pointer_after_canary.generation,
                        "pointer_unchanged": True,
                    },
                    "rollback": {
                        "stages": rollback_stages,
                        "latency_ms": rollback_latency,
                        "generation": rolled_back.generation,
                        "verified": True,
                    },
                    "cold_readiness": {
                        "stages": cold_stages,
                        "latency_ms": cold_latency,
                    },
                    "warm_readiness": {
                        "stages": warm_stages,
                        "latency_ms": warm_latency,
                    },
                    "final_generation": final_active.generation,
                    "final_product_release_id": candidate_manifest.product_release_id,
                    "seven_kind_binding_count": binding_count,
                    "report_lifecycle": report_lifecycle,
                    "temporary_read_token_revoked": True,
                    "temporary_service_account_deleted": True,
                    "runtime_contract_receipt": runtime_contract_receipt(),
                    **database_checks,
                }
            finally:
                await trino.aclose()
    finally:
        for engine in reversed(engines):
            await engine.aclose()
        cleanup_errors: list[BaseException] = []
        if account is not None:
            # The system client context has closed here, so cleanup is performed by a
            # fresh bounded client against the same approved target only.
            try:
                async with IsolatedSystemClient(
                    args.target_server,
                    ca_file=read_settings.ca_file,
                    client_id=client_id,
                    client_secret=client_secret,
                    timeout_seconds=args.timeout,
                ) as cleanup:
                    if token_id is not None:
                        await cleanup.revoke_access_token(token_id)
                    await cleanup.delete_service_account(account)
            except BaseException as error:
                cleanup_errors.append(error)
        if catalog is not None:
            await catalog.aclose()
        if cleanup_errors:
            raise Phase4Error("temporary target identity cleanup failed") from cleanup_errors[0]


def main(argv: list[str] | None = None) -> int:
    try:
        result = _run_acceptance(parse_args(argv))
    except (AcceptanceError, OSError, RuntimeError, ValueError) as error:
        output = {"status": "FAILED", "error_type": type(error).__name__}
        if isinstance(error, (AcceptanceError, RuntimeCatalogRepositoryError)):
            output["reason"] = str(error)
        print(json.dumps(output, sort_keys=True), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


def _run_acceptance(args: argparse.Namespace) -> dict[str, Any]:
    """Run psycopg on a Windows-compatible selector event loop."""

    if sys.platform == "win32":
        with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
            return runner.run(run(args))
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
