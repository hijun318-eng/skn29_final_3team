"""RuntimeCatalogProjection 저장·조회와 generation CAS activation을 소유한다."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.adapters.runtime_catalog_projection import (
    RuntimeCatalogProjection,
    RuntimeCatalogProjectionError,
)
from app.capability_contracts import ProductReleaseEvidenceManifest
from src.ai.model_contracts import model_release_checksum, model_release_manifest


ACTIVE_RUNTIME_POINTER = "analysis"


class RuntimeCatalogRepositoryError(RuntimeError):
    """Projection 저장소를 읽거나 검증할 수 없음을 나타낸다."""


class RuntimeCatalogActivationConflict(RuntimeCatalogRepositoryError):
    """CAS generation 또는 product/projection 결속이 달라 activation을 거부한다."""


@dataclass(frozen=True)
class ActiveRuntimeCatalogProjection:
    """활성 pointer와 immutable projection/product receipt를 한 번에 읽은 결과다."""

    projection: RuntimeCatalogProjection
    product_release_id: str
    generation: int


class PostgresRuntimeCatalogProjectionRepository:
    """Out-of-band publisher write와 runtime read를 동일 검증 경계로 제공한다."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sessionmaker = sessionmaker

    async def put_projection(
        self,
        projection: RuntimeCatalogProjection,
    ) -> RuntimeCatalogProjection:
        """동일 ID의 exact 문서는 멱등 허용하고 다른 내용은 충돌로 닫는다."""

        document = projection.as_document()
        try:
            async with self._sessionmaker.begin() as session:
                await session.execute(
                    text(
                        """
                        INSERT INTO governance.runtime_catalog_projections (
                            projection_id, contract_version, projection_sha256,
                            catalog_release_id, catalog_sha256, canonical_sha256,
                            manifest_sha256, membership_sha256,
                            source_selection_sha256, trino_fingerprint_sha256,
                            authority_mode, projection_json
                        ) VALUES (
                            :projection_id, :contract_version, :projection_sha256,
                            :catalog_release_id, :catalog_sha256, :canonical_sha256,
                            :manifest_sha256, :membership_sha256,
                            :source_selection_sha256, :trino_fingerprint_sha256,
                            :authority_mode, CAST(:projection_json AS jsonb)
                        )
                        ON CONFLICT (projection_id) DO NOTHING
                        """
                    ),
                    {
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
                    },
                )
                row = (
                    await session.execute(
                        text(
                            """
                            SELECT projection_json, projection_sha256
                            FROM governance.runtime_catalog_projections
                            WHERE projection_id = :projection_id
                            """
                        ),
                        {"projection_id": projection.projection_id},
                    )
                ).mappings().one()
                stored = RuntimeCatalogProjection.from_document(
                    row["projection_json"],
                    expected_projection_sha256=str(row["projection_sha256"]),
                )
                if stored.as_document() != document:
                    raise RuntimeCatalogActivationConflict(
                        "runtime projection ID is occupied by different content"
                    )
                return stored
        except RuntimeCatalogRepositoryError:
            raise
        except (RuntimeCatalogProjectionError, SQLAlchemyError) as error:
            raise RuntimeCatalogRepositoryError(
                "runtime projection could not be stored"
            ) from error

    async def load_active(self) -> ActiveRuntimeCatalogProjection:
        """활성 pointer·projection·product manifest를 한 SQL snapshot에서 검증한다."""

        try:
            async with self._sessionmaker() as session:
                row = (
                    await session.execute(
                        text(_ACTIVE_SELECT),
                        {"pointer_name": ACTIVE_RUNTIME_POINTER},
                    )
                ).mappings().one_or_none()
            if row is None:
                raise RuntimeCatalogRepositoryError(
                    "active runtime catalog projection is unavailable"
                )
            return _active_from_row(row)
        except RuntimeCatalogRepositoryError:
            raise
        except (RuntimeCatalogProjectionError, SQLAlchemyError) as error:
            raise RuntimeCatalogRepositoryError(
                "active runtime catalog projection could not be read"
            ) from error

    async def load_candidate(
        self,
        projection_id: str,
        product_release_id: str,
    ) -> ActiveRuntimeCatalogProjection:
        """전역 pointer를 바꾸지 않고 explicit candidate pair를 canary에 제공한다."""

        try:
            async with self._sessionmaker() as session:
                row = (
                    await session.execute(
                        text(_CANDIDATE_SELECT),
                        {
                            "projection_id": projection_id,
                            "product_release_id": product_release_id,
                        },
                    )
                ).mappings().one_or_none()
            if row is None:
                raise RuntimeCatalogRepositoryError(
                    "runtime catalog candidate is unavailable"
                )
            return _active_from_row(row, generation=0)
        except RuntimeCatalogRepositoryError:
            raise
        except (RuntimeCatalogProjectionError, SQLAlchemyError) as error:
            raise RuntimeCatalogRepositoryError(
                "runtime catalog candidate could not be read"
            ) from error

    async def load_product_release(
        self,
        product_release_id: str,
    ) -> ActiveRuntimeCatalogProjection:
        """active pointer와 무관하게 immutable product release의 projection을 읽는다.

        Product manifest가 봉인한 projection checksum으로 정확히 하나의 projection을
        결속한다. 따라서 기존 Conversation은 active pointer가 전진해도 고정 release가
        보존되어 있는 동안 같은 catalog를 계속 사용할 수 있다.
        """

        if not product_release_id.strip():
            raise RuntimeCatalogRepositoryError("product release id cannot be blank")
        try:
            async with self._sessionmaker() as session:
                rows = (
                    await session.execute(
                        text(_PRODUCT_RELEASE_SELECT),
                        {"product_release_id": product_release_id},
                    )
                ).mappings().all()
            if len(rows) != 1:
                raise RuntimeCatalogRepositoryError(
                    "product release runtime catalog is unavailable or ambiguous"
                )
            return _active_from_row(rows[0], generation=0)
        except RuntimeCatalogRepositoryError:
            raise
        except (RuntimeCatalogProjectionError, SQLAlchemyError) as error:
            raise RuntimeCatalogRepositoryError(
                "product release runtime catalog could not be read"
            ) from error

    async def activate(
        self,
        *,
        projection_id: str,
        product_release_id: str,
        expected_generation: int,
        action: str,
        actor: str,
        reason: str,
    ) -> ActiveRuntimeCatalogProjection:
        """Pointer generation이 정확할 때만 activate/rollback하고 append-only receipt를 남긴다."""

        if (
            action not in {"ACTIVATE", "ROLLBACK"}
            or isinstance(expected_generation, bool)
            or expected_generation < 0
            or not actor.strip()
            or not reason.strip()
            or len(actor) > 160
            or len(reason) > 500
        ):
            raise ValueError("runtime catalog activation command is invalid")
        try:
            async with self._sessionmaker.begin() as session:
                current = (
                    await session.execute(
                        text(
                            """
                            SELECT projection_id, product_release_id, generation
                            FROM governance.runtime_catalog_active_pointer
                            WHERE pointer_name = :pointer_name
                            FOR UPDATE
                            """
                        ),
                        {"pointer_name": ACTIVE_RUNTIME_POINTER},
                    )
                ).mappings().one_or_none()
                observed_generation = int(current["generation"]) if current else 0
                if observed_generation != expected_generation:
                    raise RuntimeCatalogActivationConflict(
                        "runtime catalog activation generation changed"
                    )
                target_row = (
                    await session.execute(
                        text(_CANDIDATE_SELECT),
                        {
                            "projection_id": projection_id,
                            "product_release_id": product_release_id,
                        },
                    )
                ).mappings().one_or_none()
                if target_row is None:
                    raise RuntimeCatalogActivationConflict(
                        "runtime catalog projection and product release do not match"
                    )
                validate_product_release_model_compatibility(
                    target_row["product_manifest_json"]
                )
                _active_from_row(target_row, generation=expected_generation + 1)
                if current is None:
                    await session.execute(
                        text(
                            """
                            INSERT INTO governance.runtime_catalog_active_pointer (
                                pointer_name, projection_id, product_release_id,
                                generation, activated_by
                            ) VALUES (
                                :pointer_name, :projection_id, :product_release_id,
                                1, :actor
                            )
                            """
                        ),
                        {
                            "pointer_name": ACTIVE_RUNTIME_POINTER,
                            "projection_id": projection_id,
                            "product_release_id": product_release_id,
                            "actor": actor,
                        },
                    )
                else:
                    result = await session.execute(
                        text(
                            """
                            UPDATE governance.runtime_catalog_active_pointer
                            SET projection_id = :projection_id,
                                product_release_id = :product_release_id,
                                generation = generation + 1,
                                activated_by = :actor,
                                activated_at = now()
                            WHERE pointer_name = :pointer_name
                              AND generation = :expected_generation
                            """
                        ),
                        {
                            "pointer_name": ACTIVE_RUNTIME_POINTER,
                            "projection_id": projection_id,
                            "product_release_id": product_release_id,
                            "expected_generation": expected_generation,
                            "actor": actor,
                        },
                    )
                    if result.rowcount != 1:
                        raise RuntimeCatalogActivationConflict(
                            "runtime catalog activation generation changed"
                        )
                await session.execute(
                    text(
                        """
                        INSERT INTO governance.runtime_catalog_activation_receipts (
                            pointer_name, action,
                            previous_projection_id, previous_product_release_id,
                            target_projection_id, target_product_release_id,
                            expected_generation, resulting_generation,
                            actor, reason
                        ) VALUES (
                            :pointer_name, :action,
                            :previous_projection_id, :previous_product_release_id,
                            :target_projection_id, :target_product_release_id,
                            :expected_generation, :resulting_generation,
                            :actor, :reason
                        )
                        """
                    ),
                    {
                        "pointer_name": ACTIVE_RUNTIME_POINTER,
                        "action": action,
                        "previous_projection_id": (
                            current["projection_id"] if current else None
                        ),
                        "previous_product_release_id": (
                            current["product_release_id"] if current else None
                        ),
                        "target_projection_id": projection_id,
                        "target_product_release_id": product_release_id,
                        "expected_generation": expected_generation,
                        "resulting_generation": expected_generation + 1,
                        "actor": actor,
                        "reason": reason,
                    },
                )
                active_row = (
                    await session.execute(
                        text(_ACTIVE_SELECT),
                        {"pointer_name": ACTIVE_RUNTIME_POINTER},
                    )
                ).mappings().one()
                return _active_from_row(active_row)
        except RuntimeCatalogRepositoryError:
            raise
        except IntegrityError as error:
            raise RuntimeCatalogActivationConflict(
                "runtime catalog activation conflicted"
            ) from error
        except (RuntimeCatalogProjectionError, SQLAlchemyError) as error:
            raise RuntimeCatalogRepositoryError(
                "runtime catalog activation failed"
            ) from error


_ACTIVE_SELECT = """
SELECT p.projection_json, p.projection_sha256,
       a.product_release_id, a.generation,
       m.catalog_release_id AS product_catalog_release_id,
       m.catalog_manifest_sha256 AS product_catalog_manifest_sha256,
       m.catalog_projection_sha256 AS product_catalog_projection_sha256,
       m.manifest_json AS product_manifest_json
FROM governance.runtime_catalog_active_pointer a
JOIN governance.runtime_catalog_projections p
  ON p.projection_id = a.projection_id
JOIN governance.product_release_manifests m
  ON m.product_release_id = a.product_release_id
WHERE a.pointer_name = :pointer_name
"""

_CANDIDATE_SELECT = """
SELECT p.projection_json, p.projection_sha256,
       m.product_release_id, 0::bigint AS generation,
       m.catalog_release_id AS product_catalog_release_id,
       m.catalog_manifest_sha256 AS product_catalog_manifest_sha256,
       m.catalog_projection_sha256 AS product_catalog_projection_sha256,
       m.manifest_json AS product_manifest_json
FROM governance.runtime_catalog_projections p
JOIN governance.product_release_manifests m
  ON m.product_release_id = :product_release_id
WHERE p.projection_id = :projection_id
"""

_PRODUCT_RELEASE_SELECT = """
SELECT p.projection_json, p.projection_sha256,
       m.product_release_id, 0::bigint AS generation,
       m.catalog_release_id AS product_catalog_release_id,
       m.catalog_manifest_sha256 AS product_catalog_manifest_sha256,
       m.catalog_projection_sha256 AS product_catalog_projection_sha256,
       m.manifest_json AS product_manifest_json
FROM governance.product_release_manifests m
JOIN governance.runtime_catalog_projections p
  ON p.projection_sha256 = m.catalog_projection_sha256
WHERE m.product_release_id = :product_release_id
"""


def _active_from_row(
    row: Mapping[str, Any],
    *,
    generation: int | None = None,
) -> ActiveRuntimeCatalogProjection:
    projection = RuntimeCatalogProjection.from_document(
        row["projection_json"],
        expected_projection_sha256=str(row["projection_sha256"]),
    )
    product_release_id = str(row["product_release_id"])
    product_manifest = row["product_manifest_json"]
    if (
        not isinstance(product_manifest, Mapping)
        or product_manifest.get("product_release_id") != product_release_id
        or row["product_catalog_release_id"] != projection.catalog_release_id
        or row["product_catalog_manifest_sha256"] != projection.manifest_sha256
        or row["product_catalog_projection_sha256"] != projection.projection_sha256
    ):
        raise RuntimeCatalogActivationConflict(
            "product release manifest does not bind the runtime projection"
        )
    observed_generation = int(row["generation"] if generation is None else generation)
    if observed_generation < 0:
        raise RuntimeCatalogActivationConflict("runtime catalog generation is invalid")
    return ActiveRuntimeCatalogProjection(
        projection=projection,
        product_release_id=product_release_id,
        generation=observed_generation,
    )


def validate_product_release_model_compatibility(document: object) -> None:
    """현재 모델 계약과 다른 Product가 active pointer가 되는 것을 차단한다."""

    try:
        manifest = ProductReleaseEvidenceManifest.model_validate(document)
    except ValidationError as error:
        raise RuntimeCatalogActivationConflict(
            "product release evidence manifest is invalid"
        ) from error
    expected_release_id = str(model_release_manifest()["manifest_version"])
    if (
        manifest.evidence.model.release_id != expected_release_id
        or manifest.evidence.model.manifest_sha256 != model_release_checksum()
    ):
        raise RuntimeCatalogActivationConflict(
            "product release model contract differs from the active runtime"
        )


def _json(value: object) -> str:
    import json

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
