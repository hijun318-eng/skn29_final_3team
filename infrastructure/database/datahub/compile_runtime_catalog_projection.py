"""Live DataHub·Trino read-back에서 비활성 RuntimeCatalogProjection 후보를 컴파일한다.

이 명령은 조회 전용 identity만 사용한다. native Metric aspect·graph equality와 전체
Dataset/Glossary snapshot, Trino fingerprint가 모두 일치할 때 candidate checksum을
출력하며 App DB 저장이나 active pointer 변경은 수행하지 않는다.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
BACKEND = ROOT / "app" / "backend"
for entry in (str(ROOT), str(BACKEND), str(HERE)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from app.adapters.catalog_snapshot import CatalogSnapshot, CatalogSnapshotLoader  # noqa: E402
from app.adapters.datahub_catalog import (  # noqa: E402
    DataHubCatalogClient,
    DataHubCatalogError,
)
from app.adapters.legacy_semantic_release import (  # noqa: E402
    compile_legacy_semantic_release,
)
from app.adapters.runtime_catalog_projection import (  # noqa: E402
    NATIVE_PRIORITY,
    RuntimeCatalogProjection,
    build_source_selection_manifest,
)
from app.adapters.trino_async import TrinoAsyncClient  # noqa: E402
from app.adapters.trino_schema import TrinoSchemaInspector  # noqa: E402
from app.services.context.semantic_release import CanonicalSemanticRelease  # noqa: E402
from http_client import DataHubMetadataAdminClient  # noqa: E402
from canonical_metadata_manifest import load_canonical_metadata_manifest  # noqa: E402
from canonical_quality_gate import verify_canonical_quality_gate  # noqa: E402
from native_metric_publication import verify_native_metric_shadow  # noqa: E402
from native_metric_shadow import (  # noqa: E402
    native_metric_runtime_records,
    native_metric_shadow_projection,
)
from src.data.datahub_connection import DataHubConnectionSettings  # noqa: E402
from src.data.governance_contract import canonical_json  # noqa: E402


RUNTIME_CATALOG_CANDIDATE_RECEIPT_VERSION = (
    "answervice.runtime-catalog-candidate.v1"
)
_NATIVE_READBACK_STATUS = "SHADOW_READBACK_VERIFIED_NOT_ACTIVE"


class RuntimeCatalogCandidateError(RuntimeError):
    """Live source가 하나의 비활성 runtime projection 후보로 봉인될 수 없음을 나타낸다."""


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """조회 전용 live compiler의 release·transport 상한을 해석한다."""

    parser = argparse.ArgumentParser(description=__doc__)
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


def compile_verified_runtime_catalog_candidate(
    snapshot: CatalogSnapshot,
    release: CanonicalSemanticRelease,
    trino_fingerprints: tuple[Mapping[str, Any], ...],
    native_readback: Mapping[str, Any],
) -> RuntimeCatalogProjection:
    """Exact native read-back receipt와 snapshot·Trino 증거를 candidate로 봉인한다."""

    bundle = release.as_bundle()
    expected_native = native_metric_shadow_projection(bundle)
    _validate_native_readback(native_readback, expected_native)
    return RuntimeCatalogProjection.compile(
        snapshot,
        release,
        source_selection=build_source_selection_manifest(
            release,
            authority_mode=NATIVE_PRIORITY,
            native_records=native_metric_runtime_records(bundle),
            native_projection_sha256=str(native_readback["projection_sha256"]),
            native_membership_sha256=str(
                native_readback["release_membership_sha256"]
            ),
        ),
        trino_fingerprints=trino_fingerprints,
    )


def _validate_native_readback(
    observed: Mapping[str, Any],
    expected: Mapping[str, Any],
) -> None:
    if not isinstance(observed, Mapping) or observed.get("status") != _NATIVE_READBACK_STATUS:
        raise RuntimeCatalogCandidateError("native Metric exact read-back is unavailable")
    for name in (
        "catalog_version",
        "catalog_sha256",
        "projection_sha256",
        "release_membership_sha256",
        "native_metric_count",
    ):
        if observed.get(name) != expected.get(name):
            raise RuntimeCatalogCandidateError(
                "native Metric read-back differs from the runtime release"
            )


def candidate_receipt(
    projection: RuntimeCatalogProjection,
    native_readback: Mapping[str, Any],
    quality_receipt: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """비밀이나 전체 projection JSON 없이 check 결과의 재검증 identity만 반환한다."""

    snapshot = projection.snapshot
    receipt = {
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
        "native_readback_status": str(native_readback["status"]),
        "native_metric_count": int(native_readback["native_metric_count"]),
        "native_projection_sha256": str(native_readback["projection_sha256"]),
        "native_membership_sha256": str(
            native_readback["release_membership_sha256"]
        ),
        "trino_relation_count": len(projection.trino_fingerprints),
    }
    if quality_receipt is not None:
        receipt.update(
            {
                "quality_status": str(quality_receipt["status"]),
                "quality_receipt_sha256": str(
                    quality_receipt["receipt_sha256"]
                ),
                "quality_expires_at": str(quality_receipt["expires_at"]),
                "quality_dataset_check_count": int(
                    quality_receipt["dataset_check_count"]
                ),
                "quality_business_metric_check_count": int(
                    quality_receipt["business_metric_check_count"]
                ),
                "quality_lineage_edge_count": int(
                    quality_receipt["lineage_edge_count"]
                ),
            }
        )
    return receipt


async def compile_live_candidate(
    arguments: argparse.Namespace,
) -> tuple[RuntimeCatalogProjection, Mapping[str, Any], Mapping[str, Any]]:
    """Fresh full read-back과 exact native/Trino 검증으로 candidate 객체를 만든다."""

    if arguments.timeout <= 0:
        raise RuntimeCatalogCandidateError("runtime catalog timeout must be positive")
    trino_password = os.getenv("TRINO_RUNTIME_PASSWORD", "")
    if (
        not isinstance(arguments.trino_user, str)
        or not arguments.trino_user.strip()
        or not trino_password
        or not isinstance(arguments.trino_ca_file, Path)
    ):
        raise RuntimeCatalogCandidateError(
            "runtime Trino credentials and CA are required"
        )
    datahub_environment = dict(os.environ)
    datahub_environment["DATAHUB_GMS_URL"] = arguments.datahub_server
    settings = DataHubConnectionSettings.from_env(datahub_environment)
    async with (
        DataHubCatalogClient(
            settings.base_url,
            settings.token,
            ca_file=settings.ca_file,
            expected_actor_urn=settings.actor_urn,
            timeout_seconds=arguments.timeout,
            page_size=50,
            max_entities=100_000,
        ) as catalog,
        DataHubMetadataAdminClient(
            settings.base_url,
            token=settings.token,
            ca_file=settings.ca_file,
            timeout_seconds=arguments.timeout,
        ) as native_client,
        TrinoAsyncClient(
            arguments.trino_server,
            arguments.trino_user,
            trino_password,
            ca_file=arguments.trino_ca_file,
            request_timeout_seconds=arguments.timeout,
        ) as trino,
    ):
        snapshot = await CatalogSnapshotLoader(
            catalog,
            max_concurrency=8,
            ttl_seconds=max(arguments.timeout, 1.0),
        ).load()
        release = compile_legacy_semantic_release(
            snapshot,
            arguments.expected_release,
        )
        expected_native = native_metric_shadow_projection(release.as_bundle())
        native_readback = await verify_native_metric_shadow(
            native_client,
            release.as_bundle(),
            expected_projection_sha256=str(expected_native["projection_sha256"]),
        )
        datasets = tuple(
            snapshot.datasets_by_fqn[asset.fqn] for asset in release.assets
        )
        fingerprints = await TrinoSchemaInspector(
            trino,
            timeout_seconds=arguments.timeout,
        ).fingerprints(datasets)
        projection = compile_verified_runtime_catalog_candidate(
            snapshot,
            release,
            fingerprints,
            native_readback,
        )
        canonical_manifest = load_canonical_metadata_manifest(HERE / "metadata")
        quality_receipt = await verify_canonical_quality_gate(
            native_client,
            trino,
            canonical_manifest,
            catalog_release_id=release.catalog_version,
            live_seed_versions={
                dataset.fqn: dataset.seed_version for dataset in datasets
            },
            trino_fingerprints=fingerprints,
            checked_at=datetime.now(timezone.utc),
            ttl_seconds=arguments.quality_receipt_ttl_seconds,
            timeout_seconds=arguments.timeout,
        )
        return projection, native_readback, quality_receipt


async def execute(arguments: argparse.Namespace) -> dict[str, Any]:
    """Live candidate를 컴파일하고 비밀 없는 checksum receipt로 축약한다."""

    projection, native_readback, quality_receipt = await compile_live_candidate(arguments)
    return candidate_receipt(projection, native_readback, quality_receipt)


async def async_main(argv: list[str] | None = None) -> int:
    """Candidate receipt를 canonical JSON 한 줄로 출력한다."""

    print(canonical_json(await execute(parse_args(argv))))
    return 0


def main(argv: list[str] | None = None) -> int:
    """예상 가능한 compiler 실패를 비밀 없는 오류 유형으로 축약한다."""

    try:
        return asyncio.run(async_main(argv))
    except (OSError, RuntimeError, ValueError, UnicodeError, json.JSONDecodeError) as error:
        output = {"status": "ERROR", "error_type": type(error).__name__}
        if isinstance(error, DataHubCatalogError):
            output["error_category"] = error.category
        print(
            json.dumps(
                output,
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
