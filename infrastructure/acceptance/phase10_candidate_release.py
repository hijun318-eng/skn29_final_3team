#!/usr/bin/env python3
"""Seal and rehearse the isolated Phase 10 same-release candidate.

The Phase 9 App DB is read-only.  All projection, manifest, pointer, and
activation writes are restricted to the dedicated Phase 10 database.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import psycopg
from psycopg.rows import dict_row
from sqlalchemy.engine import URL, make_url


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "app" / "backend"
HERE = Path(__file__).resolve().parent
for entry in (str(ROOT), str(BACKEND), str(HERE)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from app.adapters.runtime_catalog_projection import (  # noqa: E402
    RuntimeCatalogProjection,
)
from app.adapters.runtime_catalog_repository import (  # noqa: E402
    ActiveRuntimeCatalogProjection,
    PostgresRuntimeCatalogProjectionRepository,
    RuntimeCatalogRepositoryError,
)
from app.capability_contracts import (  # noqa: E402
    CatalogReceipt,
    ImageReceipt,
    MigrationReceipt,
    ModelReceipt,
    ProductReleaseEvidence,
    ProductReleaseEvidenceManifest,
    ProductReleaseVector,
)
from app.database import dispose_database, get_sessionmaker  # noqa: E402
from phase4_runtime_catalog_projection import (  # noqa: E402
    _migration_chain_sha256,
    _put_product_manifest,
    _source_receipt,
)
from src.ai.model_contracts import (  # noqa: E402
    model_release_checksum,
    model_release_manifest,
)
from src.data.governance_contract import canonical_sha256  # noqa: E402


TARGET_PROJECT = "answervice-phase2b-datahub"
HOST = "127.0.0.1"
PORT = 55440
SOURCE_DATABASE = "phase4_runtime_catalog_acceptance"
SOURCE_USER = "postgres"
TARGET_DATABASE = "phase10_p0_same_release_acceptance"
TARGET_USER = "phase10_migrator"
PHASE9_PREFIX = "ANSWERVICE-PHASE9-MULTI-ASSET-JOIN:"
PHASE10_PREFIX = "ANSWERVICE-PHASE10-P0-SAME-RELEASE:"
EXPECTED_IMAGE_COMPONENTS = frozenset(
    {"app-db", "backend", "datahub-gms", "frontend", "trino"}
)


class Phase10CandidateReleaseError(RuntimeError):
    """The isolated candidate boundary or release evidence is incomplete."""


@dataclass(frozen=True)
class SourceActiveRelease:
    generation: int
    projection: RuntimeCatalogProjection
    manifest: ProductReleaseEvidenceManifest


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-project", required=True)
    parser.add_argument("--source-database-url", required=True)
    parser.add_argument("--target-database-url", required=True)
    parser.add_argument("--image", action="append", default=[])
    return parser.parse_args(argv)


def _validate_database_url(
    value: str,
    *,
    database: str,
    user: str,
    label: str,
) -> URL:
    url = make_url(value)
    if (
        url.drivername != "postgresql+psycopg"
        or url.host not in {HOST, "localhost", "::1"}
        or url.port != PORT
        or url.database != database
        or url.username != user
        or url.password is not None
        or url.query
    ):
        raise Phase10CandidateReleaseError(
            f"Phase 10 {label} database is outside the isolated boundary"
        )
    return url


def validate_boundary(args: argparse.Namespace) -> tuple[URL, URL]:
    if args.target_project != TARGET_PROJECT:
        raise Phase10CandidateReleaseError(
            "Phase 10 target project is outside the approved boundary"
        )
    source = _validate_database_url(
        args.source_database_url,
        database=SOURCE_DATABASE,
        user=SOURCE_USER,
        label="source",
    )
    target = _validate_database_url(
        args.target_database_url,
        database=TARGET_DATABASE,
        user=TARGET_USER,
        label="target",
    )
    if source.render_as_string(hide_password=False) == target.render_as_string(
        hide_password=False
    ):
        raise Phase10CandidateReleaseError(
            "Phase 10 source and target databases must differ"
        )
    return source, target


def parse_images(values: Iterable[str]) -> tuple[ImageReceipt, ...]:
    parsed: dict[str, ImageReceipt] = {}
    for value in values:
        component, separator, digest = value.partition("=")
        if not separator or not component or component in parsed:
            raise Phase10CandidateReleaseError(
                "Phase 10 image receipt is invalid or duplicated"
            )
        try:
            parsed[component] = ImageReceipt(component=component, digest=digest)
        except ValueError as error:
            raise Phase10CandidateReleaseError(
                "Phase 10 image receipt is invalid"
            ) from error
    if set(parsed) != EXPECTED_IMAGE_COMPONENTS:
        raise Phase10CandidateReleaseError(
            "Phase 10 image component inventory is incomplete"
        )
    return tuple(parsed[name] for name in sorted(parsed))


def _connect(url: URL, *, row_mapping: bool = False) -> psycopg.Connection[Any]:
    kwargs: dict[str, Any] = {
        "host": url.host,
        "port": url.port,
        "dbname": url.database,
        "user": url.username,
    }
    return psycopg.connect(
        **kwargs,
        row_factory=dict_row if row_mapping else None,
    )


def load_source_active(url: URL) -> SourceActiveRelease:
    with _connect(url, row_mapping=True) as connection:
        row = connection.execute(
            """
            SELECT a.generation, p.projection_json, p.projection_sha256,
                   m.manifest_json
            FROM governance.runtime_catalog_active_pointer a
            JOIN governance.runtime_catalog_projections p
              ON p.projection_id = a.projection_id
            JOIN governance.product_release_manifests m
              ON m.product_release_id = a.product_release_id
            WHERE a.pointer_name = 'analysis'
            """
        ).fetchone()
    if row is None:
        raise Phase10CandidateReleaseError(
            "Phase 9 source active release is unavailable"
        )
    try:
        projection = RuntimeCatalogProjection.from_document(
            row["projection_json"],
            expected_projection_sha256=str(row["projection_sha256"]),
        )
        manifest = ProductReleaseEvidenceManifest.model_validate(row["manifest_json"])
    except (KeyError, TypeError, ValueError) as error:
        raise Phase10CandidateReleaseError(
            "Phase 9 source release receipt is invalid"
        ) from error
    if (
        not manifest.product_release_id.startswith(PHASE9_PREFIX)
        or manifest.evidence.catalog.release_id != projection.catalog_release_id
        or manifest.evidence.catalog.manifest_sha256 != projection.manifest_sha256
        or manifest.evidence.catalog.projection_sha256
        != projection.projection_sha256
    ):
        raise Phase10CandidateReleaseError(
            "Phase 9 source product/projection binding differs"
        )
    return SourceActiveRelease(int(row["generation"]), projection, manifest)


def target_migration_revision(url: URL) -> str:
    with _connect(url) as connection:
        row = connection.execute(
            "SELECT version_num FROM governance.alembic_version"
        ).fetchone()
    revision = str(row[0] if row else "")
    if not revision:
        raise Phase10CandidateReleaseError(
            "Phase 10 target migration revision is unavailable"
        )
    return revision


def target_pointer_count(url: URL) -> int:
    with _connect(url) as connection:
        row = connection.execute(
            "SELECT count(*) FROM governance.runtime_catalog_active_pointer"
        ).fetchone()
    return int(row[0] if row else 0)


def _manifest(
    projection: RuntimeCatalogProjection,
    *,
    images: tuple[ImageReceipt, ...],
    migration_revision: str,
) -> ProductReleaseEvidenceManifest:
    source, created_at = _source_receipt()
    model_manifest = model_release_manifest()
    image_sha256 = canonical_sha256(
        [image.model_dump(mode="json") for image in images]
    )
    evidence = ProductReleaseEvidence(
        source=source,
        images=images,
        migration=MigrationReceipt(
            revision=migration_revision,
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
            runtime_release_id=f"PHASE10-RUNTIME-v1:{image_sha256}",
        ),
    )
    identity = canonical_sha256(
        {
            "phase": "10",
            "contract": "p0_same_release_candidate.v1",
            "evidence": evidence.model_dump(mode="json"),
        }
    )
    return ProductReleaseEvidenceManifest.seal(
        product_release_id=f"{PHASE10_PREFIX}{identity}",
        evidence=evidence,
        created_at=created_at,
    )


def _latest_rehearsal(
    url: URL,
    candidate_id: str,
    active_generation: int,
) -> list[dict[str, Any]]:
    with _connect(url, row_mapping=True) as connection:
        rows = connection.execute(
            """
            SELECT action, previous_product_release_id,
                   target_product_release_id, expected_generation,
                   resulting_generation
            FROM governance.runtime_catalog_activation_receipts
            WHERE resulting_generation <= %s
            ORDER BY resulting_generation DESC
            LIMIT 3
            """,
            (active_generation,),
        ).fetchall()
    ordered = list(reversed(rows))
    if len(ordered) != 3:
        return []
    first, rollback, final = ordered
    baseline = first["previous_product_release_id"]
    if (
        first["action"] != "ACTIVATE"
        or first["target_product_release_id"] != candidate_id
        or not baseline
        or rollback["action"] != "ROLLBACK"
        or rollback["target_product_release_id"] != baseline
        or final["action"] != "ACTIVATE"
        or final["target_product_release_id"] != candidate_id
        or int(first["resulting_generation"]) + 1
        != int(rollback["resulting_generation"])
        or int(rollback["resulting_generation"]) + 1
        != int(final["resulting_generation"])
        or int(final["resulting_generation"]) != active_generation
    ):
        return []
    return ordered


async def _activate_candidate(
    *,
    target_url: str,
    target_url_object: URL,
    source: SourceActiveRelease,
    candidate: ProductReleaseEvidenceManifest,
) -> tuple[ActiveRuntimeCatalogProjection, list[dict[str, Any]]]:
    sessionmaker = get_sessionmaker(target_url)
    repository = PostgresRuntimeCatalogProjectionRepository(sessionmaker)
    try:
        await repository.put_projection(source.projection)
        await _put_product_manifest(sessionmaker, source.manifest)
        await _put_product_manifest(sessionmaker, candidate)
        pointer_count = target_pointer_count(target_url_object)
        if pointer_count not in {0, 1}:
            raise Phase10CandidateReleaseError(
                "Phase 10 target active pointer inventory differs"
            )
        if pointer_count == 0:
            await repository.activate(
                projection_id=source.projection.projection_id,
                product_release_id=source.manifest.product_release_id,
                expected_generation=0,
                action="ACTIVATE",
                actor="phase10-isolated-release",
                reason="Seed the read-only Phase 9 baseline in the Phase 10 database",
            )
        active = await repository.load_active()
        if not active.product_release_id.startswith((PHASE9_PREFIX, PHASE10_PREFIX)):
            raise Phase10CandidateReleaseError(
                "Phase 10 target active release has an unexpected identity"
            )
        if active.product_release_id == candidate.product_release_id:
            rehearsal = _latest_rehearsal(
                target_url_object,
                candidate.product_release_id,
                active.generation,
            )
            if not rehearsal:
                raise Phase10CandidateReleaseError(
                    "Phase 10 candidate is active without a complete rollback rehearsal"
                )
            return active, rehearsal

        baseline = active
        canary = await repository.load_candidate(
            source.projection.projection_id,
            candidate.product_release_id,
        )
        if (
            canary.projection.as_document() != source.projection.as_document()
            or canary.product_release_id != candidate.product_release_id
        ):
            raise Phase10CandidateReleaseError(
                "Phase 10 candidate canary read-back differs"
            )
        first = await repository.activate(
            projection_id=canary.projection.projection_id,
            product_release_id=canary.product_release_id,
            expected_generation=baseline.generation,
            action="ACTIVATE",
            actor="phase10-isolated-release",
            reason="Activate the same-release Phase 10 candidate after canary read-back",
        )
        rolled_back = await repository.activate(
            projection_id=baseline.projection.projection_id,
            product_release_id=baseline.product_release_id,
            expected_generation=first.generation,
            action="ROLLBACK",
            actor="phase10-isolated-release",
            reason="Rehearse rollback to the immediately previous isolated release",
        )
        final = await repository.activate(
            projection_id=canary.projection.projection_id,
            product_release_id=canary.product_release_id,
            expected_generation=rolled_back.generation,
            action="ACTIVATE",
            actor="phase10-isolated-release",
            reason="Reactivate the Phase 10 candidate after successful rollback",
        )
        rehearsal = _latest_rehearsal(
            target_url_object,
            candidate.product_release_id,
            final.generation,
        )
        if not rehearsal:
            raise Phase10CandidateReleaseError(
                "Phase 10 rollback rehearsal receipt differs"
            )
        return final, rehearsal
    except RuntimeCatalogRepositoryError as error:
        raise Phase10CandidateReleaseError(
            "Phase 10 projection activation failed"
        ) from error
    finally:
        await dispose_database()


async def run(args: argparse.Namespace) -> dict[str, Any]:
    source_url, target_url = validate_boundary(args)
    images = parse_images(args.image)
    source = load_source_active(source_url)
    revision = target_migration_revision(target_url)
    candidate = _manifest(
        source.projection,
        images=images,
        migration_revision=revision,
    )
    active, rehearsal = await _activate_candidate(
        target_url=args.target_database_url,
        target_url_object=target_url,
        source=source,
        candidate=candidate,
    )
    return {
        "status": "PHASE10_CANDIDATE_RELEASE_READY",
        "target_project": TARGET_PROJECT,
        "source_generation": source.generation,
        "active_generation": active.generation,
        "product_release_id": candidate.product_release_id,
        "manifest_sha256": candidate.manifest_sha256,
        "projection_sha256": source.projection.projection_sha256,
        "migration_revision": revision,
        "image_components": sorted(image.component for image in images),
        "rollback_rehearsal": rehearsal,
    }


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        if sys.platform == "win32":
            with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
                result = runner.run(run(args))
        else:
            result = asyncio.run(run(args))
    except (OSError, RuntimeError, ValueError, psycopg.Error) as error:
        message = (
            str(error)
            if isinstance(error, Phase10CandidateReleaseError)
            else "Phase 10 candidate release failed"
        )
        print(
            json.dumps(
                {
                    "status": "PHASE10_CANDIDATE_RELEASE_ERROR",
                    "error": message,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
