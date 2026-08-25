"""검증된 runtime catalog projection을 컴파일·봉인·저장·활성화한다."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "app" / "backend"))

from app.adapters.catalog_snapshot import CatalogSnapshotLoader  # noqa: E402
from app.adapters.datahub_catalog import DataHubCatalogClient  # noqa: E402
from app.adapters.legacy_semantic_release import (  # noqa: E402
    compile_legacy_semantic_release,
)
from app.adapters.runtime_catalog_projection import (  # noqa: E402
    LEGACY_SHADOW,
    RuntimeCatalogProjection,
    build_source_selection_manifest,
)
from app.adapters.runtime_catalog_repository import (  # noqa: E402
    ACTIVE_RUNTIME_POINTER,
    PostgresRuntimeCatalogProjectionRepository,
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
from app.runtime_release import runtime_contract_receipt  # noqa: E402
from src.ai.model_contracts import (  # noqa: E402
    canonical_json_sha256,
    model_release_checksum,
    model_release_manifest,
)


SOURCE_SUFFIXES = frozenset(
    {".css", ".html", ".js", ".json", ".py", ".sql", ".toml", ".ts", ".tsx", ".yaml", ".yml"}
)
SOURCE_ROOTS = (
    "app/backend/app",
    "app/backend/migrations/versions",
    "app/frontend",
    "evals/semantic_review",
    "infrastructure/database/datahub",
    "infrastructure/database/scripts",
    "src",
)
EXCLUDED_PARTS = frozenset({"__pycache__", "dist", "node_modules", ".venv"})


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _tree_digest() -> str:
    digest = hashlib.sha256()
    count = 0
    for relative_root in SOURCE_ROOTS:
        source_root = ROOT / relative_root
        if not source_root.is_dir():
            continue
        paths = sorted(
            (
                path
                for path in source_root.rglob("*")
                if path.is_file()
                and path.suffix.lower() in SOURCE_SUFFIXES
                and not EXCLUDED_PARTS.intersection(path.parts)
            ),
            key=lambda path: path.relative_to(ROOT).as_posix(),
        )
        for path in paths:
            relative = path.relative_to(ROOT).as_posix().encode("utf-8")
            digest.update(relative)
            digest.update(b"\0")
            digest.update(path.read_bytes())
            digest.update(b"\0")
            count += 1
    if count == 0:
        raise RuntimeError("runtime source files are unavailable")
    return digest.hexdigest()


def _migration_receipt() -> MigrationReceipt:
    migration_root = ROOT / "app" / "backend" / "migrations" / "versions"
    paths = sorted(migration_root.glob("*.py"), key=lambda path: path.name)
    if not paths:
        raise RuntimeError("migration chain is unavailable")
    chain = hashlib.sha256()
    revisions: list[tuple[str, str]] = []
    for path in paths:
        content = path.read_bytes()
        match = re.search(rb'^revision\s*=\s*["\']([^"\']+)["\']', content, re.MULTILINE)
        if match is None:
            raise RuntimeError(f"migration revision is missing: {path.name}")
        revision = match.group(1).decode("ascii")
        revisions.append((path.name, revision))
        chain.update(path.name.encode("utf-8"))
        chain.update(b"\0")
        chain.update(content)
        chain.update(b"\0")
    return MigrationReceipt(revision=revisions[-1][1], chain_sha256=chain.hexdigest())


def _image_receipts(values: Sequence[str]) -> tuple[ImageReceipt, ...]:
    receipts = []
    for value in values:
        component, separator, digest = value.partition("=")
        if not separator:
            raise ValueError("--image must use component=sha256:<64 hex> format")
        receipts.append(ImageReceipt(component=component.strip(), digest=digest.strip()))
    return tuple(sorted(receipts, key=lambda item: item.component))


def _trino_fingerprints(snapshot: Any, release: Any) -> tuple[dict[str, Any], ...]:
    assets = release.as_bundle()["schema_context"]["assets"]
    fqns = sorted(str(asset["fqn"]) for asset in assets)
    fingerprints = []
    for fqn in fqns:
        dataset = snapshot.datasets_by_fqn.get(fqn)
        if dataset is None:
            raise RuntimeError(f"release dataset is missing from the snapshot: {fqn}")
        fingerprints.append(
            {
                "fqn": fqn,
                "table_type": dataset.table_type,
                "column_count": len(dataset.trino_schema_columns),
                "relation_sha256": dataset.trino_schema_checksum,
            }
        )
    return tuple(fingerprints)


def _evidence(
    projection: RuntimeCatalogProjection,
    images: tuple[ImageReceipt, ...],
) -> ProductReleaseEvidence:
    source_digest = _tree_digest()
    model_manifest = model_release_manifest()
    return ProductReleaseEvidence(
        source=SourceReceipt(
            commit_sha=source_digest,
            dirty=True,
            dirty_patch_sha256=source_digest,
        ),
        images=images,
        migration=_migration_receipt(),
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
            data_release_id=f"catalog-data:{projection.catalog_sha256}",
            semantic_release_id=projection.catalog_release_id,
            prompt_release_id=str(model_manifest["manifest_version"]),
            policy_release_id=projection.release.policy_version,
            runtime_release_id=runtime_contract_receipt(),
        ),
    )


def _database_url(args: argparse.Namespace) -> URL:
    return URL.create(
        "postgresql+psycopg",
        username=_required("APP_ADMIN_USER"),
        password=_required("APP_ADMIN_PASSWORD"),
        host=args.db_host,
        port=args.db_port,
        database=os.getenv("APP_DB_NAME") or _required("APP_DB"),
    )


async def _put_manifest(
    factory: async_sessionmaker[AsyncSession],
    product_release_id: str,
    evidence: ProductReleaseEvidence,
) -> ProductReleaseEvidenceManifest:
    async with factory.begin() as session:
        row = (
            await session.execute(
                text(
                    "SELECT manifest_json FROM governance.product_release_manifests "
                    "WHERE product_release_id = :product_release_id"
                ),
                {"product_release_id": product_release_id},
            )
        ).mappings().one_or_none()
        if row is None:
            candidate = ProductReleaseEvidenceManifest.seal(
                product_release_id=product_release_id,
                evidence=evidence,
            )
            document = candidate.model_dump(mode="json")
            evidence_json = document["evidence"]
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
                        :product_release_id, :contract_version, :manifest_sha256,
                        CAST(:manifest_json AS jsonb), :source_commit_sha, :source_dirty,
                        :dirty_patch_sha256, CAST(:image_digests_json AS jsonb),
                        :migration_revision, :migration_chain_sha256,
                        :model_release_id, :model_manifest_sha256,
                        :catalog_release_id, :catalog_manifest_sha256,
                        :catalog_projection_sha256, CAST(:release_vector_json AS jsonb), :created_at
                    ) ON CONFLICT (product_release_id) DO NOTHING
                    """
                ),
                {
                    "product_release_id": candidate.product_release_id,
                    "contract_version": candidate.schema_version,
                    "manifest_sha256": candidate.manifest_sha256,
                    "manifest_json": _canonical_json(document),
                    "source_commit_sha": evidence.source.commit_sha,
                    "source_dirty": evidence.source.dirty,
                    "dirty_patch_sha256": evidence.source.dirty_patch_sha256,
                    "image_digests_json": _canonical_json(evidence_json["images"]),
                    "migration_revision": evidence.migration.revision,
                    "migration_chain_sha256": evidence.migration.chain_sha256,
                    "model_release_id": evidence.model.release_id,
                    "model_manifest_sha256": evidence.model.manifest_sha256,
                    "catalog_release_id": evidence.catalog.release_id,
                    "catalog_manifest_sha256": evidence.catalog.manifest_sha256,
                    "catalog_projection_sha256": evidence.catalog.projection_sha256,
                    "release_vector_json": _canonical_json(evidence_json["release_vector"]),
                    "created_at": candidate.created_at,
                },
            )
            row = (
                await session.execute(
                    text(
                        "SELECT manifest_json FROM governance.product_release_manifests "
                        "WHERE product_release_id = :product_release_id"
                    ),
                    {"product_release_id": product_release_id},
                )
            ).mappings().one()
        stored = ProductReleaseEvidenceManifest.model_validate(row["manifest_json"])
        if stored.evidence.model_dump(mode="json") != evidence.model_dump(mode="json"):
            raise RuntimeError("product release ID is occupied by different evidence")
        return stored


async def _active_pointer(
    factory: async_sessionmaker[AsyncSession],
) -> Mapping[str, Any] | None:
    async with factory() as session:
        return (
            await session.execute(
                text(
                    "SELECT projection_id, product_release_id, generation "
                    "FROM governance.runtime_catalog_active_pointer "
                    "WHERE pointer_name = :pointer_name"
                ),
                {"pointer_name": ACTIVE_RUNTIME_POINTER},
            )
        ).mappings().one_or_none()


async def _run(args: argparse.Namespace) -> None:
    client = DataHubCatalogClient.from_env(timeout_seconds=args.datahub_timeout)
    try:
        snapshot = await CatalogSnapshotLoader(client, ttl_seconds=1.0).load()
    finally:
        await client.aclose()
    release = compile_legacy_semantic_release(snapshot, args.catalog_release)
    projection = RuntimeCatalogProjection.compile(
        snapshot,
        release,
        source_selection=build_source_selection_manifest(
            release,
            authority_mode=LEGACY_SHADOW,
        ),
        trino_fingerprints=_trino_fingerprints(snapshot, release),
    )
    images = _image_receipts(args.image)
    evidence = _evidence(projection, images)
    product_release_id = (
        "ANSWERVICE-UNIFIED-DEV-v1:"
        + canonical_json_sha256(evidence.model_dump(mode="json"))
    )
    engine = create_async_engine(_database_url(args), pool_pre_ping=True)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    repository = PostgresRuntimeCatalogProjectionRepository(factory)
    try:
        await repository.put_projection(projection)
        manifest = await _put_manifest(factory, product_release_id, evidence)
        pointer = await _active_pointer(factory)
        if pointer is None:
            active = await repository.activate(
                projection_id=projection.projection_id,
                product_release_id=manifest.product_release_id,
                expected_generation=0,
                action="ACTIVATE",
                actor=args.actor,
                reason=args.reason,
            )
            activation = "ACTIVATED"
        elif (
            pointer["projection_id"] == projection.projection_id
            and pointer["product_release_id"] == manifest.product_release_id
        ):
            active = await repository.load_active()
            activation = "ALREADY_ACTIVE"
        else:
            raise RuntimeError(
                "a different runtime catalog is active; explicit rollback or cutover is required"
            )
        if (
            active.projection.projection_sha256 != projection.projection_sha256
            or active.product_release_id != manifest.product_release_id
        ):
            raise RuntimeError("runtime catalog activation read-back differs")
        print(f"RUNTIME_CATALOG_ACTIVATION={activation}")
        print(f"AUTHORITY_MODE={LEGACY_SHADOW}")
        print(f"CATALOG_RELEASE={projection.catalog_release_id}")
        print(f"PROJECTION_ID={projection.projection_id}")
        print(f"PRODUCT_RELEASE_ID={manifest.product_release_id}")
        print(f"GENERATION={active.generation}")
        print("SOURCE_EVIDENCE=DIRTY_WORKSPACE_SNAPSHOT")
        print("RUNTIME_CATALOG_VERIFY=PASS")
    finally:
        await engine.dispose()


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--catalog-release",
        required=True,
        help="활성화할 승인 semantic catalog release ID",
    )
    parser.add_argument("--image", action="append", required=True)
    parser.add_argument("--db-host", default="127.0.0.1")
    parser.add_argument("--db-port", type=int, default=25432)
    parser.add_argument("--datahub-timeout", type=float, default=20.0)
    parser.add_argument(
        "--actor",
        default=os.getenv("DATAHUB_PUBLISH_ACTOR_URN", "answervice-runtime-publisher"),
    )
    parser.add_argument(
        "--reason",
        default="Activate the verified unified MCP, RAG, and ML runtime catalog.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(_run(_arguments()))
