"""Live DataHub와 활성 runtime release를 읽기 전용 복구 baseline으로 봉인한다.

이 명령은 fresh DataHub·Trino candidate를 active RuntimeCatalogProjection과 exact
비교한다. 활성화 이력이 참조하는 immutable projection/product release만 함께 내보내며
DataHub, App DB, active pointer에는 어떤 mutation도 수행하지 않는다.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
BACKEND = ROOT / "app" / "backend"
for entry in (str(ROOT), str(BACKEND), str(HERE)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from app.adapters.runtime_catalog_candidate_publisher import (  # noqa: E402
    RuntimeCatalogCandidatePublishError,
    validate_runtime_catalog_candidate_pair,
)
from app.adapters.runtime_catalog_projection import (  # noqa: E402
    RuntimeCatalogProjection,
    RuntimeCatalogProjectionError,
)
from app.capability_contracts import ProductReleaseEvidenceManifest  # noqa: E402
from app.database import get_sessionmaker  # noqa: E402
from compile_runtime_catalog_projection import (  # noqa: E402
    RUNTIME_CATALOG_CANDIDATE_RECEIPT_VERSION,
    candidate_receipt,
    compile_live_candidate,
)
from src.data.governance_contract import canonical_json, canonical_sha256  # noqa: E402


BASELINE_SCHEMA_VERSION = "answervice.runtime-catalog-recovery-baseline.v1"
BASELINE_SCOPE = "ACTIVE_RUNTIME_GOVERNED_CATALOG"
EXPORT_RECEIPT_VERSION = "answervice.runtime-catalog-baseline-export.v1"
RESTORE_DRY_RUN_VERSION = "answervice.runtime-catalog-restore-dry-run.v1"
_NATIVE_READBACK_STATUS = "SHADOW_READBACK_VERIFIED_NOT_ACTIVE"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")

_DOCUMENT_KEYS = frozenset(
    {
        "schema_version",
        "scope",
        "content_sha256",
        "inventory",
        "active_pointer",
        "runtime_projections",
        "product_release_manifests",
        "activation_receipts",
        "live_candidate_receipt",
        "deployment_receipt_sha256",
    }
)
_POINTER_KEYS = frozenset(
    {
        "pointer_name",
        "projection_id",
        "product_release_id",
        "generation",
        "activated_by",
        "activated_at",
    }
)
_ACTIVATION_KEYS = frozenset(
    {
        "activation_id",
        "pointer_name",
        "action",
        "previous_projection_id",
        "previous_product_release_id",
        "target_projection_id",
        "target_product_release_id",
        "expected_generation",
        "resulting_generation",
        "actor",
        "reason",
        "created_at",
    }
)
_LIVE_RECEIPT_KEYS = frozenset(
    {
        "schema_version",
        "status",
        "catalog_release_id",
        "catalog_sha256",
        "canonical_sha256",
        "manifest_sha256",
        "projection_id",
        "projection_sha256",
        "membership_sha256",
        "source_selection_sha256",
        "trino_fingerprint_sha256",
        "authority_mode",
        "dataset_count",
        "business_term_count",
        "dataset_term_edge_count",
        "field_term_edge_count",
        "native_readback_status",
        "native_metric_count",
        "native_projection_sha256",
        "native_membership_sha256",
        "trino_relation_count",
        "quality_status",
        "quality_receipt_sha256",
        "quality_expires_at",
        "quality_dataset_check_count",
        "quality_business_metric_check_count",
        "quality_lineage_edge_count",
    }
)
_INVENTORY_KEYS = frozenset(
    {
        "dataset_count",
        "column_count",
        "business_term_count",
        "dimension_member_term_count",
        "trino_relation_count",
        "runtime_projection_count",
        "product_release_count",
        "activation_receipt_count",
    }
)


class RuntimeCatalogBaselineError(ValueError):
    """Live/active equality 또는 복구 의존성이 완전하지 않음을 나타낸다."""


async def read_active_runtime_catalog_state(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> dict[str, Any]:
    """한 SQL snapshot에서 active pointer와 그 이력의 immutable 의존성을 읽는다."""

    try:
        async with sessionmaker() as session:
            row = (
                await session.execute(text(_ACTIVE_RECOVERY_SELECT))
            ).mappings().one()
    except SQLAlchemyError as error:
        raise RuntimeCatalogBaselineError(
            "active runtime catalog recovery state could not be read"
        ) from error
    return {
        "active_pointer": row["active_pointer"],
        "runtime_projections": row["runtime_projections"],
        "product_release_manifests": row["product_release_manifests"],
        "activation_receipts": row["activation_receipts"],
    }


def build_runtime_catalog_baseline(
    active_state: Mapping[str, Any],
    live_projection: RuntimeCatalogProjection,
    live_candidate_receipt: Mapping[str, Any],
) -> dict[str, Any]:
    """Fresh live projection과 active DB state가 같은 경우에만 복구 문서를 만든다."""

    pointer, projections, manifests, receipts = _normalize_recovery_state(
        active_state
    )
    active_projection = _validate_recovery_graph(
        pointer, projections, manifests, receipts
    )
    if not isinstance(live_projection, RuntimeCatalogProjection) or (
        live_projection.as_document() != active_projection.as_document()
    ):
        raise RuntimeCatalogBaselineError(
            "live DataHub projection differs from the active projection"
        )
    live_receipt = _validated_live_receipt(
        live_candidate_receipt, live_projection
    )
    inventory = _inventory(active_projection, projections, manifests, receipts)
    payload = {
        "schema_version": BASELINE_SCHEMA_VERSION,
        "scope": BASELINE_SCOPE,
        # RuntimeCatalogProjection의 canonical exact-set checksum을 재정의하지 않는다.
        "content_sha256": active_projection.projection_sha256,
        "inventory": inventory,
        "active_pointer": pointer,
        "runtime_projections": [item.as_document() for item in projections],
        "product_release_manifests": [
            item.model_dump(mode="json") for item in manifests
        ],
        "activation_receipts": receipts,
        "live_candidate_receipt": live_receipt,
    }
    document = {
        **payload,
        "deployment_receipt_sha256": canonical_sha256(payload),
    }
    validate_runtime_catalog_baseline(document)
    return document


def validate_runtime_catalog_baseline(document: Mapping[str, Any]) -> None:
    """파일 checksum, live receipt, pointer와 전체 receipt dependency를 재검증한다."""

    if not isinstance(document, Mapping) or set(document) != _DOCUMENT_KEYS:
        raise RuntimeCatalogBaselineError("runtime catalog baseline fields differ")
    if document.get("schema_version") != BASELINE_SCHEMA_VERSION:
        raise RuntimeCatalogBaselineError(
            "runtime catalog baseline schema version is invalid"
        )
    if document.get("scope") != BASELINE_SCOPE:
        raise RuntimeCatalogBaselineError("runtime catalog baseline scope is invalid")
    deployment_checksum = _checksum(
        document.get("deployment_receipt_sha256"), "deployment receipt checksum"
    )
    payload = dict(document)
    payload.pop("deployment_receipt_sha256")
    if canonical_sha256(payload) != deployment_checksum:
        raise RuntimeCatalogBaselineError(
            "runtime catalog deployment receipt checksum differs"
        )

    pointer, projections, manifests, receipts = _normalize_recovery_state(document)
    active_projection = _validate_recovery_graph(
        pointer, projections, manifests, receipts
    )
    if document.get("content_sha256") != active_projection.projection_sha256:
        raise RuntimeCatalogBaselineError(
            "runtime catalog content checksum differs from the active projection"
        )
    _validated_live_receipt(
        _mapping(document.get("live_candidate_receipt"), "live candidate receipt"),
        active_projection,
    )
    expected_inventory = _inventory(
        active_projection, projections, manifests, receipts
    )
    inventory = _mapping(document.get("inventory"), "runtime catalog inventory")
    if set(inventory) != _INVENTORY_KEYS or dict(inventory) != expected_inventory:
        raise RuntimeCatalogBaselineError(
            "runtime catalog baseline inventory differs from its content"
        )


def plan_runtime_catalog_restore(document: Mapping[str, Any]) -> dict[str, Any]:
    """Mutation 없이 insert 순서와 active pointer 복원 가능성만 검증한다."""

    validate_runtime_catalog_baseline(document)
    pointer = _mapping(document["active_pointer"], "active pointer")
    inventory = _mapping(document["inventory"], "runtime catalog inventory")
    return {
        "schema_version": RESTORE_DRY_RUN_VERSION,
        "status": "RESTORE_DRY_RUN_VALIDATED",
        "scope": BASELINE_SCOPE,
        "content_sha256": document["content_sha256"],
        "deployment_receipt_sha256": document["deployment_receipt_sha256"],
        "projection_insert_count": inventory["runtime_projection_count"],
        "product_release_insert_count": inventory["product_release_count"],
        "activation_receipt_insert_count": inventory[
            "activation_receipt_count"
        ],
        "target_projection_id": pointer["projection_id"],
        "target_product_release_id": pointer["product_release_id"],
        "target_generation": pointer["generation"],
        "mutation_count": 0,
    }


def write_runtime_catalog_baseline(
    document: Mapping[str, Any], output: Path
) -> dict[str, Any]:
    """기존 파일을 덮어쓰지 않고 canonical 복구 baseline 한 건만 생성한다."""

    validate_runtime_catalog_baseline(document)
    if not output.is_absolute():
        raise RuntimeCatalogBaselineError(
            "runtime catalog baseline output path must be absolute"
        )
    parent = output.parent.resolve(strict=True)
    if not parent.is_dir():
        raise RuntimeCatalogBaselineError(
            "runtime catalog baseline output directory is unavailable"
        )
    target = parent / output.name
    with target.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(canonical_json(document))
        stream.write("\n")
    inventory = _mapping(document["inventory"], "runtime catalog inventory")
    return {
        "schema_version": EXPORT_RECEIPT_VERSION,
        "status": "EXPORTED_WITHOUT_MUTATION",
        "scope": BASELINE_SCOPE,
        "content_sha256": document["content_sha256"],
        "deployment_receipt_sha256": document["deployment_receipt_sha256"],
        "dataset_count": inventory["dataset_count"],
        "column_count": inventory["column_count"],
        "activation_receipt_count": inventory["activation_receipt_count"],
        "output": str(target),
    }


def _normalize_recovery_state(
    state: Mapping[str, Any],
) -> tuple[
    dict[str, Any],
    tuple[RuntimeCatalogProjection, ...],
    tuple[ProductReleaseEvidenceManifest, ...],
    list[dict[str, Any]],
]:
    if not isinstance(state, Mapping):
        raise RuntimeCatalogBaselineError("runtime catalog recovery state is invalid")
    pointer = _normalize_pointer(state.get("active_pointer"))

    raw_projections = _nonempty_list(
        state.get("runtime_projections"), "runtime projections"
    )
    try:
        projections = tuple(
            sorted(
                (
                    RuntimeCatalogProjection.from_document(
                        _mapping(item, "runtime projection")
                    )
                    for item in raw_projections
                ),
                key=lambda item: item.projection_id,
            )
        )
    except RuntimeCatalogProjectionError as error:
        raise RuntimeCatalogBaselineError(
            "runtime catalog baseline contains an invalid projection"
        ) from error
    if len({item.projection_id for item in projections}) != len(projections):
        raise RuntimeCatalogBaselineError(
            "runtime catalog baseline contains duplicate projections"
        )

    raw_manifests = _nonempty_list(
        state.get("product_release_manifests"), "product release manifests"
    )
    try:
        manifests = tuple(
            sorted(
                (
                    ProductReleaseEvidenceManifest.model_validate(item)
                    for item in raw_manifests
                ),
                key=lambda item: item.product_release_id,
            )
        )
    except ValidationError as error:
        raise RuntimeCatalogBaselineError(
            "runtime catalog baseline contains an invalid product release"
        ) from error
    if len({item.product_release_id for item in manifests}) != len(manifests):
        raise RuntimeCatalogBaselineError(
            "runtime catalog baseline contains duplicate product releases"
        )

    raw_receipts = _nonempty_list(
        state.get("activation_receipts"), "activation receipts"
    )
    receipts = sorted(
        (_normalize_activation_receipt(item) for item in raw_receipts),
        key=lambda item: (item["resulting_generation"], item["activation_id"]),
    )
    if len({item["activation_id"] for item in receipts}) != len(receipts):
        raise RuntimeCatalogBaselineError(
            "runtime catalog baseline contains duplicate activation receipts"
        )
    return pointer, projections, manifests, receipts


def _validate_recovery_graph(
    pointer: Mapping[str, Any],
    projections: Sequence[RuntimeCatalogProjection],
    manifests: Sequence[ProductReleaseEvidenceManifest],
    receipts: Sequence[Mapping[str, Any]],
) -> RuntimeCatalogProjection:
    projection_by_id = {item.projection_id: item for item in projections}
    manifest_by_id = {item.product_release_id: item for item in manifests}
    referenced_projection_ids = {str(pointer["projection_id"])}
    referenced_product_ids = {str(pointer["product_release_id"])}
    previous_projection_id: str | None = None
    previous_product_id: str | None = None

    for generation, receipt in enumerate(receipts, start=1):
        if (
            receipt["pointer_name"] != "analysis"
            or receipt["expected_generation"] != generation - 1
            or receipt["resulting_generation"] != generation
            or receipt["previous_projection_id"] != previous_projection_id
            or receipt["previous_product_release_id"] != previous_product_id
        ):
            raise RuntimeCatalogBaselineError(
                "runtime catalog activation receipt chain is incomplete"
            )
        target_projection_id = str(receipt["target_projection_id"])
        target_product_id = str(receipt["target_product_release_id"])
        referenced_projection_ids.add(target_projection_id)
        referenced_product_ids.add(target_product_id)
        if previous_projection_id is not None:
            referenced_projection_ids.add(previous_projection_id)
            referenced_product_ids.add(str(previous_product_id))
        previous_projection_id = target_projection_id
        previous_product_id = target_product_id

    if (
        pointer["pointer_name"] != "analysis"
        or pointer["generation"] != len(receipts)
        or pointer["projection_id"] != previous_projection_id
        or pointer["product_release_id"] != previous_product_id
    ):
        raise RuntimeCatalogBaselineError(
            "active pointer differs from the activation receipt chain"
        )
    if set(projection_by_id) != referenced_projection_ids or set(
        manifest_by_id
    ) != referenced_product_ids:
        raise RuntimeCatalogBaselineError(
            "runtime catalog recovery dependencies are incomplete or out of scope"
        )

    for manifest in manifest_by_id.values():
        projection_sha256 = manifest.evidence.catalog.projection_sha256
        projection = next(
            (
                item
                for item in projections
                if item.projection_sha256 == projection_sha256
            ),
            None,
        )
        if projection is None:
            raise RuntimeCatalogBaselineError(
                "product release projection dependency is unavailable"
            )
        catalog = manifest.evidence.catalog
        if (
            catalog.release_id != projection.catalog_release_id
            or catalog.manifest_sha256 != projection.manifest_sha256
        ):
            raise RuntimeCatalogBaselineError(
                "historical product release does not bind its projection"
            )

    active_projection = projection_by_id[str(pointer["projection_id"])]
    active_manifest = manifest_by_id[str(pointer["product_release_id"])]
    try:
        validate_runtime_catalog_candidate_pair(active_projection, active_manifest)
    except RuntimeCatalogCandidatePublishError as error:
        raise RuntimeCatalogBaselineError(
            "active product release does not satisfy publication policy"
        ) from error

    for receipt in receipts:
        target_projection = projection_by_id[str(receipt["target_projection_id"])]
        target_manifest = manifest_by_id[str(receipt["target_product_release_id"])]
        if (
            target_manifest.evidence.catalog.projection_sha256
            != target_projection.projection_sha256
        ):
            raise RuntimeCatalogBaselineError(
                "activation receipt target pair is inconsistent"
            )
    return active_projection


def _validated_live_receipt(
    value: Mapping[str, Any], projection: RuntimeCatalogProjection
) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _LIVE_RECEIPT_KEYS:
        raise RuntimeCatalogBaselineError("live candidate receipt fields differ")
    receipt = json.loads(canonical_json(value))
    snapshot = projection.snapshot
    quality_status = _text(value.get("quality_status"), "quality status")
    if quality_status != "VERIFIED":
        raise RuntimeCatalogBaselineError("live candidate quality is not verified")
    quality_dataset_check_count = _integer(
        value.get("quality_dataset_check_count"),
        "quality dataset check count",
    )
    quality_business_metric_check_count = _integer(
        value.get("quality_business_metric_check_count"),
        "quality business metric check count",
    )
    expected_business_metric_count = sum(
        item["visibility"] == "BUSINESS"
        for item in projection.source_selection["metrics"]
    )
    if (
        quality_dataset_check_count != len(snapshot.datasets_by_urn)
        or quality_business_metric_check_count != expected_business_metric_count
    ):
        raise RuntimeCatalogBaselineError(
            "live candidate quality coverage differs from the runtime projection"
        )
    expected = {
        "schema_version": RUNTIME_CATALOG_CANDIDATE_RECEIPT_VERSION,
        "status": "CHECKED_NOT_PUBLISHED",
        "catalog_release_id": projection.catalog_release_id,
        "catalog_sha256": projection.catalog_sha256,
        "canonical_sha256": projection.canonical_sha256,
        "manifest_sha256": projection.manifest_sha256,
        "projection_id": projection.projection_id,
        "projection_sha256": projection.projection_sha256,
        "membership_sha256": projection.membership_sha256,
        "source_selection_sha256": projection.source_selection_sha256,
        "trino_fingerprint_sha256": projection.trino_fingerprint_sha256,
        "authority_mode": projection.source_selection["authority_mode"],
        "dataset_count": len(snapshot.datasets_by_urn),
        "business_term_count": len(snapshot.terms_by_urn),
        "dataset_term_edge_count": sum(
            len(dataset.dataset_terms)
            for dataset in snapshot.datasets_by_urn.values()
        ),
        "field_term_edge_count": sum(
            len(terms)
            for dataset in snapshot.datasets_by_urn.values()
            for terms in dataset.field_terms.values()
        ),
        "native_readback_status": _NATIVE_READBACK_STATUS,
        "native_metric_count": sum(
            item["visibility"] == "BUSINESS"
            for item in projection.source_selection["metrics"]
        ),
        "native_projection_sha256": projection.source_selection[
            "native_projection_sha256"
        ],
        "native_membership_sha256": projection.source_selection[
            "native_membership_sha256"
        ],
        "trino_relation_count": len(projection.trino_fingerprints),
        "quality_status": quality_status,
        "quality_receipt_sha256": _checksum(
            value.get("quality_receipt_sha256"),
            "quality receipt checksum",
        ),
        "quality_expires_at": _timestamp(
            value.get("quality_expires_at"),
            "quality receipt expiration",
        ),
        "quality_dataset_check_count": quality_dataset_check_count,
        "quality_business_metric_check_count": (
            quality_business_metric_check_count
        ),
        "quality_lineage_edge_count": _integer(
            value.get("quality_lineage_edge_count"),
            "quality lineage edge count",
        ),
    }
    if receipt != expected:
        raise RuntimeCatalogBaselineError(
            "live candidate receipt differs from the runtime projection"
        )
    return receipt


def _inventory(
    active: RuntimeCatalogProjection,
    projections: Sequence[RuntimeCatalogProjection],
    manifests: Sequence[ProductReleaseEvidenceManifest],
    receipts: Sequence[Mapping[str, Any]],
) -> dict[str, int]:
    snapshot = active.snapshot
    return {
        "dataset_count": len(snapshot.datasets_by_urn),
        "column_count": sum(
            len(dataset.trino_schema_columns)
            for dataset in snapshot.datasets_by_urn.values()
        ),
        "business_term_count": len(snapshot.terms_by_urn),
        "dimension_member_term_count": len(
            snapshot.dimension_member_terms_by_urn
        ),
        "trino_relation_count": len(active.trino_fingerprints),
        "runtime_projection_count": len(projections),
        "product_release_count": len(manifests),
        "activation_receipt_count": len(receipts),
    }


def _normalize_pointer(value: object) -> dict[str, Any]:
    pointer = _mapping(value, "active pointer")
    if set(pointer) != _POINTER_KEYS:
        raise RuntimeCatalogBaselineError("active pointer fields differ")
    generation = _integer(pointer.get("generation"), "active generation")
    if generation < 1:
        raise RuntimeCatalogBaselineError("active generation is invalid")
    return {
        "pointer_name": _text(pointer.get("pointer_name"), "pointer name"),
        "projection_id": _text(pointer.get("projection_id"), "projection ID"),
        "product_release_id": _text(
            pointer.get("product_release_id"), "product release ID"
        ),
        "generation": generation,
        "activated_by": _text(pointer.get("activated_by"), "activation actor"),
        "activated_at": _timestamp(
            pointer.get("activated_at"), "activation timestamp"
        ),
    }


def _normalize_activation_receipt(value: object) -> dict[str, Any]:
    receipt = _mapping(value, "activation receipt")
    if set(receipt) != _ACTIVATION_KEYS:
        raise RuntimeCatalogBaselineError("activation receipt fields differ")
    action = _text(receipt.get("action"), "activation action")
    if action not in {"ACTIVATE", "ROLLBACK"}:
        raise RuntimeCatalogBaselineError("activation receipt action is invalid")
    previous_projection = _optional_text(
        receipt.get("previous_projection_id"), "previous projection ID"
    )
    previous_product = _optional_text(
        receipt.get("previous_product_release_id"), "previous product release ID"
    )
    if (previous_projection is None) != (previous_product is None):
        raise RuntimeCatalogBaselineError(
            "activation receipt previous pair is incomplete"
        )
    try:
        activation_id = str(UUID(str(receipt.get("activation_id"))))
    except (TypeError, ValueError, AttributeError) as error:
        raise RuntimeCatalogBaselineError(
            "activation receipt ID is invalid"
        ) from error
    return {
        "activation_id": activation_id,
        "pointer_name": _text(receipt.get("pointer_name"), "pointer name"),
        "action": action,
        "previous_projection_id": previous_projection,
        "previous_product_release_id": previous_product,
        "target_projection_id": _text(
            receipt.get("target_projection_id"), "target projection ID"
        ),
        "target_product_release_id": _text(
            receipt.get("target_product_release_id"),
            "target product release ID",
        ),
        "expected_generation": _integer(
            receipt.get("expected_generation"), "expected generation"
        ),
        "resulting_generation": _integer(
            receipt.get("resulting_generation"), "resulting generation"
        ),
        "actor": _text(receipt.get("actor"), "activation actor"),
        "reason": _text(receipt.get("reason"), "activation reason"),
        "created_at": _timestamp(
            receipt.get("created_at"), "activation receipt timestamp"
        ),
    }


def _mapping(value: object, context: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise RuntimeCatalogBaselineError(f"{context} must be an object")
    return value


def _nonempty_list(value: object, context: str) -> list[Any]:
    if not isinstance(value, list) or not value:
        raise RuntimeCatalogBaselineError(f"{context} must be a non-empty list")
    return value


def _text(value: object, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RuntimeCatalogBaselineError(f"{context} must be non-empty text")
    return value


def _optional_text(value: object, context: str) -> str | None:
    return None if value is None else _text(value, context)


def _integer(value: object, context: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise RuntimeCatalogBaselineError(f"{context} must be a non-negative integer")
    return value


def _timestamp(value: object, context: str) -> str:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as error:
            raise RuntimeCatalogBaselineError(f"{context} is invalid") from error
    else:
        raise RuntimeCatalogBaselineError(f"{context} is invalid")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise RuntimeCatalogBaselineError(f"{context} must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat()


def _checksum(value: object, context: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise RuntimeCatalogBaselineError(f"{context} is invalid")
    return value


def _arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--datahub-server",
        default=os.getenv("DATAHUB_GMS_URL", "https://127.0.0.1:18081"),
    )
    parser.add_argument(
        "--trino-server",
        default=os.getenv("TRINO_URL", "https://127.0.0.1:18443"),
    )
    parser.add_argument("--trino-user", default=os.getenv("TRINO_RUNTIME_USER"))
    parser.add_argument(
        "--trino-ca-file",
        type=Path,
        default=os.getenv("TRINO_TLS_CA_FILE")
        or os.getenv("TRINO_TLS_CA_HOST_FILE"),
    )
    parser.add_argument(
        "--expected-release",
        default=os.getenv("ANALYTICS_CONTEXT_RELEASE") or None,
    )
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument(
        "--quality-receipt-ttl-seconds",
        type=float,
        default=os.getenv("CANONICAL_QUALITY_RECEIPT_TTL_SECONDS", "3600"),
    )
    return parser.parse_args(argv)


async def execute(arguments: argparse.Namespace) -> dict[str, Any]:
    """Fresh live compile, active equality, export, restore dry-run을 순서대로 수행한다."""

    live_projection, native_readback, quality_receipt = await compile_live_candidate(arguments)
    state = await read_active_runtime_catalog_state(get_sessionmaker())
    document = build_runtime_catalog_baseline(
        state,
        live_projection,
        candidate_receipt(live_projection, native_readback, quality_receipt),
    )
    export_receipt = write_runtime_catalog_baseline(document, arguments.output)
    stored = json.loads(arguments.output.read_text(encoding="utf-8"))
    dry_run = plan_runtime_catalog_restore(stored)
    return {**export_receipt, "restore_dry_run": dry_run}


async def _async_main(argv: Sequence[str] | None = None) -> int:
    print(canonical_json(await execute(_arguments(argv))))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """비밀 없는 receipt만 출력하고 예상 오류는 유형으로 축약한다."""

    try:
        if sys.platform == "win32":
            with asyncio.Runner(
                loop_factory=asyncio.SelectorEventLoop
            ) as runner:
                return runner.run(_async_main(argv))
        return asyncio.run(_async_main(argv))
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as error:
        print(
            json.dumps(
                {"status": "ERROR", "error_type": type(error).__name__},
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2


_ACTIVE_RECOVERY_SELECT = """
WITH active_pointer AS (
    SELECT pointer_name, projection_id, product_release_id, generation,
           activated_by, activated_at
    FROM governance.runtime_catalog_active_pointer
    WHERE pointer_name = 'analysis'
),
receipts AS (
    SELECT activation_id, pointer_name, action,
           previous_projection_id, previous_product_release_id,
           target_projection_id, target_product_release_id,
           expected_generation, resulting_generation, actor, reason, created_at
    FROM governance.runtime_catalog_activation_receipts
    WHERE pointer_name = 'analysis'
),
projection_ids AS (
    SELECT projection_id FROM active_pointer
    UNION
    SELECT previous_projection_id FROM receipts
    WHERE previous_projection_id IS NOT NULL
    UNION
    SELECT target_projection_id FROM receipts
),
product_release_ids AS (
    SELECT product_release_id FROM active_pointer
    UNION
    SELECT previous_product_release_id FROM receipts
    WHERE previous_product_release_id IS NOT NULL
    UNION
    SELECT target_product_release_id FROM receipts
)
SELECT
    (
        SELECT jsonb_build_object(
            'pointer_name', pointer_name,
            'projection_id', projection_id,
            'product_release_id', product_release_id,
            'generation', generation,
            'activated_by', activated_by,
            'activated_at', activated_at
        )
        FROM active_pointer
    ) AS active_pointer,
    COALESCE((
        SELECT jsonb_agg(p.projection_json ORDER BY p.projection_id)
        FROM governance.runtime_catalog_projections AS p
        JOIN projection_ids AS ids ON ids.projection_id = p.projection_id
    ), '[]'::jsonb) AS runtime_projections,
    COALESCE((
        SELECT jsonb_agg(m.manifest_json ORDER BY m.product_release_id)
        FROM governance.product_release_manifests AS m
        JOIN product_release_ids AS ids
          ON ids.product_release_id = m.product_release_id
    ), '[]'::jsonb) AS product_release_manifests,
    COALESCE((
        SELECT jsonb_agg(
            jsonb_build_object(
                'activation_id', activation_id::text,
                'pointer_name', pointer_name,
                'action', action,
                'previous_projection_id', previous_projection_id,
                'previous_product_release_id', previous_product_release_id,
                'target_projection_id', target_projection_id,
                'target_product_release_id', target_product_release_id,
                'expected_generation', expected_generation,
                'resulting_generation', resulting_generation,
                'actor', actor,
                'reason', reason,
                'created_at', created_at
            ) ORDER BY resulting_generation, activation_id
        )
        FROM receipts
    ), '[]'::jsonb) AS activation_receipts
"""


if __name__ == "__main__":
    raise SystemExit(main())
