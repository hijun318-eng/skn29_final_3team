"""검증된 runtime catalog 후보와 product evidence를 원자적으로 append한다."""

from __future__ import annotations

import json
from dataclasses import dataclass

from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.adapters.runtime_catalog_projection import (
    RUNTIME_CATALOG_PROJECTION_VERSION,
    RuntimeCatalogProjection,
    RuntimeCatalogProjectionError,
)
from app.capability_contracts import (
    ProductReleaseEvidence,
    ProductReleaseEvidenceManifest,
)
from src.data.governance_contract import canonical_sha256


PRODUCT_RELEASE_ID_PREFIX = "ANSWERVICE-MVP-INTERNAL:"
REQUIRED_RUNTIME_IMAGE_COMPONENTS = frozenset(
    {"app-db", "backend", "datahub-gms", "frontend", "trino"}
)


class RuntimeCatalogCandidatePublishError(RuntimeError):
    """후보 pair가 검증되거나 원자적으로 저장될 수 없음을 나타낸다."""


class RuntimeCatalogCandidatePublishConflict(RuntimeCatalogCandidatePublishError):
    """동일 ID가 다른 immutable 내용에 이미 사용되었음을 나타낸다."""


@dataclass(frozen=True)
class PublishedRuntimeCatalogCandidate:
    """DB에서 exact read-back한 projection/product candidate pair identity다."""

    projection_id: str
    projection_sha256: str
    product_release_id: str
    product_manifest_sha256: str
    migration_revision: str


def product_release_id_for(evidence: ProductReleaseEvidence) -> str:
    """전체 typed evidence에서 재현 가능한 product release ID를 만든다."""

    return PRODUCT_RELEASE_ID_PREFIX + canonical_sha256(
        evidence.model_dump(mode="json")
    )


def validate_runtime_catalog_candidate_pair(
    projection: RuntimeCatalogProjection,
    manifest: ProductReleaseEvidenceManifest,
) -> None:
    """Product evidence가 exact projection과 clean source를 결속하는지 확인한다."""

    evidence = manifest.evidence
    catalog = evidence.catalog
    vector = evidence.release_vector
    image_components = {image.component for image in evidence.images}
    if evidence.source.dirty or evidence.source.dirty_patch_sha256 is not None:
        raise RuntimeCatalogCandidatePublishError(
            "runtime catalog candidate requires a clean source receipt"
        )
    if not REQUIRED_RUNTIME_IMAGE_COMPONENTS.issubset(image_components):
        raise RuntimeCatalogCandidatePublishError(
            "runtime catalog candidate image receipts are incomplete"
        )
    if (
        catalog.release_id != projection.catalog_release_id
        or catalog.manifest_sha256 != projection.manifest_sha256
        or catalog.projection_sha256 != projection.projection_sha256
        or vector.data_release_id != projection.catalog_release_id
        or vector.semantic_release_id != projection.catalog_release_id
        or vector.policy_release_id != projection.release.policy_version
        or vector.prompt_release_id != evidence.model.release_id
        or vector.runtime_release_id
        != f"{RUNTIME_CATALOG_PROJECTION_VERSION}:{projection.projection_sha256}"
    ):
        raise RuntimeCatalogCandidatePublishError(
            "product release evidence does not bind the runtime projection"
        )
    if manifest.product_release_id != product_release_id_for(evidence):
        raise RuntimeCatalogCandidatePublishError(
            "product release ID does not match its evidence"
        )


class PostgresRuntimeCatalogCandidatePublisher:
    """Pointer 권한 없이 projection과 product manifest만 한 transaction으로 게시한다."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sessionmaker = sessionmaker

    async def publish_candidate(
        self,
        projection: RuntimeCatalogProjection,
        manifest: ProductReleaseEvidenceManifest,
        *,
        expected_migration_revision: str,
    ) -> PublishedRuntimeCatalogCandidate:
        """DB revision을 확인하고 immutable pair를 멱등·원자적으로 append한다."""

        if (
            not isinstance(expected_migration_revision, str)
            or not expected_migration_revision.strip()
            or len(expected_migration_revision) > 64
        ):
            raise ValueError("expected migration revision is invalid")
        validate_runtime_catalog_candidate_pair(projection, manifest)
        if manifest.evidence.migration.revision != expected_migration_revision:
            raise RuntimeCatalogCandidatePublishError(
                "product evidence migration revision differs from the App DB"
            )
        projection_document = projection.as_document()
        manifest_document = manifest.model_dump(mode="json")
        try:
            async with self._sessionmaker.begin() as session:
                revision = (
                    await session.execute(
                        text(
                            "SELECT version_num FROM governance.alembic_version"
                        )
                    )
                ).scalar_one_or_none()
                if revision != expected_migration_revision:
                    raise RuntimeCatalogCandidatePublishError(
                        "App DB migration revision differs from the publisher"
                    )
                await session.execute(
                    text(_INSERT_PROJECTION),
                    _projection_parameters(projection, projection_document),
                )
                await session.execute(
                    text(_INSERT_PRODUCT_MANIFEST),
                    _manifest_parameters(manifest, manifest_document),
                )
                row = (
                    await session.execute(
                        text(_SELECT_PUBLISHED_PAIR),
                        {
                            "projection_id": projection.projection_id,
                            "product_release_id": manifest.product_release_id,
                        },
                    )
                ).mappings().one_or_none()
                if row is None:
                    raise RuntimeCatalogCandidatePublishError(
                        "published runtime catalog candidate is unavailable"
                    )
                stored_projection = RuntimeCatalogProjection.from_document(
                    row["projection_json"],
                    expected_projection_sha256=str(row["projection_sha256"]),
                )
                stored_manifest = ProductReleaseEvidenceManifest.model_validate(
                    row["manifest_json"]
                )
                if (
                    stored_projection.as_document() != projection_document
                    or stored_manifest.model_dump(mode="json") != manifest_document
                ):
                    raise RuntimeCatalogCandidatePublishConflict(
                        "runtime catalog candidate ID is occupied by different content"
                    )
                validate_runtime_catalog_candidate_pair(
                    stored_projection,
                    stored_manifest,
                )
                return PublishedRuntimeCatalogCandidate(
                    projection_id=stored_projection.projection_id,
                    projection_sha256=stored_projection.projection_sha256,
                    product_release_id=stored_manifest.product_release_id,
                    product_manifest_sha256=stored_manifest.manifest_sha256,
                    migration_revision=expected_migration_revision,
                )
        except RuntimeCatalogCandidatePublishError:
            raise
        except IntegrityError as error:
            raise RuntimeCatalogCandidatePublishConflict(
                "runtime catalog candidate conflicts with stored evidence"
            ) from error
        except (
            RuntimeCatalogProjectionError,
            ValidationError,
            SQLAlchemyError,
        ) as error:
            raise RuntimeCatalogCandidatePublishError(
                "runtime catalog candidate could not be published"
            ) from error


def _projection_parameters(
    projection: RuntimeCatalogProjection,
    document: dict[str, object],
) -> dict[str, object]:
    return {
        "projection_id": projection.projection_id,
        "contract_version": document["schema_version"],
        "projection_sha256": projection.projection_sha256,
        "catalog_release_id": projection.catalog_release_id,
        "catalog_sha256": projection.catalog_sha256,
        "canonical_sha256": projection.canonical_sha256,
        "manifest_sha256": projection.manifest_sha256,
        "membership_sha256": projection.membership_sha256,
        "source_selection_sha256": projection.source_selection_sha256,
        "trino_fingerprint_sha256": projection.trino_fingerprint_sha256,
        "authority_mode": projection.source_selection["authority_mode"],
        "projection_json": _json(document),
    }


def _manifest_parameters(
    manifest: ProductReleaseEvidenceManifest,
    document: dict[str, object],
) -> dict[str, object]:
    evidence = manifest.evidence
    return {
        "product_release_id": manifest.product_release_id,
        "contract_version": manifest.schema_version,
        "manifest_sha256": manifest.manifest_sha256,
        "manifest_json": _json(document),
        "source_commit_sha": evidence.source.commit_sha,
        "source_dirty": evidence.source.dirty,
        "dirty_patch_sha256": evidence.source.dirty_patch_sha256,
        "image_digests_json": _json(
            [image.model_dump(mode="json") for image in evidence.images]
        ),
        "migration_revision": evidence.migration.revision,
        "migration_chain_sha256": evidence.migration.chain_sha256,
        "model_release_id": evidence.model.release_id,
        "model_manifest_sha256": evidence.model.manifest_sha256,
        "catalog_release_id": evidence.catalog.release_id,
        "catalog_manifest_sha256": evidence.catalog.manifest_sha256,
        "catalog_projection_sha256": evidence.catalog.projection_sha256,
        "release_vector_json": _json(
            evidence.release_vector.model_dump(mode="json")
        ),
        "created_at": manifest.created_at,
    }


def _json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


_INSERT_PROJECTION = """
INSERT INTO governance.runtime_catalog_projections (
    projection_id, contract_version, projection_sha256,
    catalog_release_id, catalog_sha256, canonical_sha256,
    manifest_sha256, membership_sha256, source_selection_sha256,
    trino_fingerprint_sha256, authority_mode, projection_json
) VALUES (
    :projection_id, :contract_version, :projection_sha256,
    :catalog_release_id, :catalog_sha256, :canonical_sha256,
    :manifest_sha256, :membership_sha256, :source_selection_sha256,
    :trino_fingerprint_sha256, :authority_mode,
    CAST(:projection_json AS jsonb)
)
ON CONFLICT (projection_id) DO NOTHING
"""

_INSERT_PRODUCT_MANIFEST = """
INSERT INTO governance.product_release_manifests (
    product_release_id, contract_version, manifest_sha256,
    manifest_json, source_commit_sha, source_dirty,
    dirty_patch_sha256, image_digests_json, migration_revision,
    migration_chain_sha256, model_release_id, model_manifest_sha256,
    catalog_release_id, catalog_manifest_sha256,
    catalog_projection_sha256, release_vector_json, created_at
) VALUES (
    :product_release_id, :contract_version, :manifest_sha256,
    CAST(:manifest_json AS jsonb), :source_commit_sha, :source_dirty,
    :dirty_patch_sha256, CAST(:image_digests_json AS jsonb),
    :migration_revision, :migration_chain_sha256, :model_release_id,
    :model_manifest_sha256, :catalog_release_id,
    :catalog_manifest_sha256, :catalog_projection_sha256,
    CAST(:release_vector_json AS jsonb), :created_at
)
ON CONFLICT (product_release_id) DO NOTHING
"""

_SELECT_PUBLISHED_PAIR = """
SELECT projection.projection_json, projection.projection_sha256,
       manifest.manifest_json
FROM governance.runtime_catalog_projections AS projection
JOIN governance.product_release_manifests AS manifest
  ON manifest.product_release_id = :product_release_id
WHERE projection.projection_id = :projection_id
"""
