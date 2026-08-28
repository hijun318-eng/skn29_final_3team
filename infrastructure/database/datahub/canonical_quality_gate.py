"""Canonical metadata의 최소 Dataset·Metric 품질과 direct lineage를 live read-back으로 검증한다."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
from time import monotonic
from typing import Any

from canonical_metadata_manifest import CanonicalMetadataManifest
from src.data.governance_contract import canonical_sha256


QUALITY_GATE_SCHEMA_VERSION = "answervice.canonical-quality-gate.v1"
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_DATASET_ID = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$")
_MAX_PAGES = 100
_DATASET_QUALITY_CONCURRENCY = 4
_DATASET_QUALITY_COLUMNS = (
    "dataset_id",
    "row_count",
    "required_key_violation_count",
)


class CanonicalQualityGateError(RuntimeError):
    """Critical 품질·계보 증거가 없거나 실패해 candidate를 만들 수 없음을 나타낸다."""


def build_dataset_quality_queries(document: Mapping[str, Any]) -> tuple[str, ...]:
    """Dataset별 row count·필수 key NULL 검사를 독립 read-only query로 만든다.

    여러 물리 view를 하나의 ``UNION ALL`` plan으로 합치면 Dataset 수와 무관하게
    Trino stage 상한을 넘을 수 있다. 실행 단위를 relation별로 격리하고 호출부에서
    bounded concurrency를 적용해 planner 한도와 connector 부하를 함께 제한한다.
    """

    policies = {
        str(item["dataset_id"]): item for item in document["quality_policies"]
    }
    statements: list[str] = []
    for dataset in sorted(document["datasets"], key=lambda item: item["dataset_id"]):
        dataset_id = str(dataset["dataset_id"])
        if _DATASET_ID.fullmatch(dataset_id) is None:
            raise CanonicalQualityGateError("quality Dataset identity is invalid")
        policy = policies[dataset_id]
        if policy["status"] != "ENFORCED":
            raise CanonicalQualityGateError("quality policy is not enforced")
        keys = dataset["primary_key"]
        if not isinstance(keys, list) or not keys:
            raise CanonicalQualityGateError("quality required key contract is unavailable")
        predicate = " OR ".join(f"{_identifier(name)} IS NULL" for name in keys)
        statements.append(
            "SELECT "
            f"'{dataset_id}' AS dataset_id, "
            "COUNT(*) AS row_count, "
            f"COUNT_IF({predicate}) AS required_key_violation_count "
            f"FROM {_qualified_name(str(dataset['fqn']))}"
        )
    if not statements:
        raise CanonicalQualityGateError("quality Dataset membership is empty")
    return tuple(statements)


def expected_lineage_edges(
    document: Mapping[str, Any],
) -> tuple[tuple[str, str], ...]:
    """Canonical lineage를 DataHub physical URN direct-edge 집합으로 변환한다."""

    urns = {
        str(item["dataset_id"]): str(item["physical_urn"])
        for item in document["datasets"]
    }
    edges = set()
    for policy in document["quality_policies"]:
        lineage = policy["lineage"]
        if not isinstance(lineage, Mapping) or lineage["mode"] != "UPSTREAM":
            continue
        downstream = urns[str(policy["dataset_id"])]
        edges.update(
            (urns[str(upstream)], downstream)
            for upstream in lineage["upstream_dataset_ids"]
        )
    return tuple(sorted(edges))


async def read_live_lineage_edges(
    client: Any,
    document: Mapping[str, Any],
    *,
    concurrency: int = 8,
) -> tuple[tuple[str, str], ...]:
    """관리 Dataset의 upstreamLineage aspect만 bounded concurrency로 exact read-back한다."""

    if concurrency < 1:
        raise ValueError("lineage read concurrency must be positive")
    semaphore = asyncio.Semaphore(concurrency)

    async def read_one(dataset: Mapping[str, Any]) -> tuple[tuple[str, str], ...]:
        downstream = str(dataset["physical_urn"])
        async with semaphore:
            entity = await client.get_entity(downstream, ("upstreamLineage",))
        aspects = entity.get("aspects")
        if not isinstance(aspects, Mapping):
            raise CanonicalQualityGateError("DataHub lineage aspects are invalid")
        wrapped = aspects.get("upstreamLineage")
        if wrapped is None:
            return ()
        if not isinstance(wrapped, Mapping) or not isinstance(wrapped.get("value"), Mapping):
            raise CanonicalQualityGateError("DataHub upstream lineage is invalid")
        raw_edges = wrapped["value"].get("upstreams", [])
        if not isinstance(raw_edges, list):
            raise CanonicalQualityGateError("DataHub upstream lineage membership is invalid")
        result = []
        for raw in raw_edges:
            upstream = raw.get("dataset") if isinstance(raw, Mapping) else None
            if not isinstance(upstream, str) or not upstream:
                raise CanonicalQualityGateError("DataHub upstream lineage edge is invalid")
            result.append((upstream, downstream))
        if len(result) != len(set(result)):
            raise CanonicalQualityGateError("DataHub upstream lineage edge is duplicate")
        return tuple(result)

    groups = await asyncio.gather(*(read_one(item) for item in document["datasets"]))
    return tuple(sorted(edge for group in groups for edge in group))


def validate_dataset_quality_rows(
    columns: Sequence[str],
    rows: Sequence[Sequence[object]],
    document: Mapping[str, Any],
) -> tuple[tuple[str, int, int], ...]:
    """Dataset 결과의 exact membership·양수 row count·필수 key NULL 0을 검증한다."""

    if tuple(columns) != (
        "dataset_id",
        "row_count",
        "required_key_violation_count",
    ):
        raise CanonicalQualityGateError("Dataset quality result columns differ")
    expected = {str(item["dataset_id"]) for item in document["datasets"]}
    normalized = []
    for row in rows:
        if len(row) != 3:
            raise CanonicalQualityGateError("Dataset quality result row is invalid")
        dataset_id, row_count, violations = row
        if (
            not isinstance(dataset_id, str)
            or dataset_id not in expected
            or isinstance(row_count, bool)
            or not isinstance(row_count, int)
            or row_count < 1
            or isinstance(violations, bool)
            or not isinstance(violations, int)
            or violations != 0
        ):
            raise CanonicalQualityGateError("critical Dataset quality check failed")
        normalized.append((dataset_id, row_count, violations))
    if {item[0] for item in normalized} != expected or len(normalized) != len(expected):
        raise CanonicalQualityGateError("Dataset quality result membership differs")
    return tuple(sorted(normalized))


def validate_metric_quality_row(
    columns: Sequence[str],
    rows: Sequence[Sequence[object]],
    metric_id: str,
) -> tuple[str, int]:
    """Business Metric validation query가 자기 ID와 violation 0 한 행만 반환하게 한다."""

    if tuple(columns) != ("metric_id", "violation_count") or len(rows) != 1:
        raise CanonicalQualityGateError("Metric quality result shape differs")
    row = rows[0]
    if (
        len(row) != 2
        or row[0] != metric_id
        or isinstance(row[1], bool)
        or not isinstance(row[1], int)
        or row[1] != 0
    ):
        raise CanonicalQualityGateError("critical Metric quality check failed")
    return metric_id, row[1]


def build_quality_receipt(
    manifest: CanonicalMetadataManifest,
    *,
    catalog_release_id: str,
    dataset_results: Sequence[Sequence[object]],
    metric_results: Sequence[Sequence[object]],
    lineage_edges: Sequence[Sequence[str]],
    trino_fingerprints: Sequence[Mapping[str, Any]],
    checked_at: datetime,
    ttl_seconds: float,
) -> dict[str, Any]:
    """원문 row 없이 성공 evidence의 checksum과 만료 시각만 봉인한다."""

    if checked_at.tzinfo is None or checked_at.utcoffset() is None:
        raise ValueError("quality checked_at must be timezone-aware")
    if ttl_seconds <= 0 or ttl_seconds > 86_400:
        raise ValueError("quality receipt TTL is outside the allowed bound")
    timestamp = checked_at.astimezone(timezone.utc)
    content = {
        "schema_version": QUALITY_GATE_SCHEMA_VERSION,
        "status": "VERIFIED",
        "manifest_sha256": manifest.content_sha256,
        "catalog_release_id": catalog_release_id,
        "checked_at": timestamp.isoformat(),
        "expires_at": (timestamp + timedelta(seconds=ttl_seconds)).isoformat(),
        "dataset_check_count": len(dataset_results),
        "business_metric_check_count": len(metric_results),
        "lineage_edge_count": len(lineage_edges),
        "dataset_results_sha256": canonical_sha256(list(dataset_results)),
        "metric_results_sha256": canonical_sha256(list(metric_results)),
        "lineage_edges_sha256": canonical_sha256(list(lineage_edges)),
        "trino_fingerprints_sha256": canonical_sha256(list(trino_fingerprints)),
        "raw_pii_value_count": 0,
    }
    return {**content, "receipt_sha256": canonical_sha256(content)}


async def verify_canonical_quality_gate(
    datahub: Any,
    trino: Any,
    manifest: CanonicalMetadataManifest,
    *,
    catalog_release_id: str,
    live_seed_versions: Mapping[str, str],
    trino_fingerprints: Sequence[Mapping[str, Any]],
    checked_at: datetime,
    ttl_seconds: float,
    timeout_seconds: float,
) -> dict[str, Any]:
    """Canonical·DataHub·Trino의 최소 품질과 lineage를 한 candidate receipt로 검증한다."""

    if manifest.status != "READY" or timeout_seconds <= 0:
        raise CanonicalQualityGateError("canonical quality gate input is not ready")
    document = manifest.as_document()
    if document["authoring"]["catalog_version"] != catalog_release_id:
        raise CanonicalQualityGateError("quality catalog release differs")
    expected_fqns = {str(item["fqn"]) for item in document["datasets"]}
    if set(live_seed_versions) != expected_fqns or any(
        live_seed_versions[str(item["fqn"])] != item["authoring"]["seed_version"]
        for item in document["datasets"]
    ):
        raise CanonicalQualityGateError("Dataset freshness release differs")
    if {str(item.get("fqn")) for item in trino_fingerprints} != expected_fqns:
        raise CanonicalQualityGateError("Trino quality fingerprint membership differs")

    live_lineage = await read_live_lineage_edges(datahub, document)
    expected_lineage = expected_lineage_edges(document)
    if live_lineage != expected_lineage:
        raise CanonicalQualityGateError("DataHub direct lineage membership differs")

    dataset_semaphore = asyncio.Semaphore(_DATASET_QUALITY_CONCURRENCY)

    async def check_dataset(query: str) -> tuple[tuple[object, ...], ...]:
        async with dataset_semaphore:
            columns, rows = await _execute_rows(
                trino, query, timeout_seconds=timeout_seconds
            )
        if columns != _DATASET_QUALITY_COLUMNS:
            raise CanonicalQualityGateError("Dataset quality result columns differ")
        return rows

    dataset_row_groups = await asyncio.gather(
        *(check_dataset(query) for query in build_dataset_quality_queries(document))
    )
    dataset_rows = tuple(row for group in dataset_row_groups for row in group)
    dataset_results = validate_dataset_quality_rows(
        _DATASET_QUALITY_COLUMNS, dataset_rows, document
    )

    business_metrics = tuple(
        sorted(
            (
                (str(item["metric_id"]), str(item["validation_query"]))
                for item in document["metrics"]
                if item["visibility"] == "BUSINESS"
            ),
            key=lambda item: item[0],
        )
    )
    semaphore = asyncio.Semaphore(4)

    async def check_metric(metric_id: str, query: str) -> tuple[str, int]:
        async with semaphore:
            columns, rows = await _execute_rows(
                trino, query, timeout_seconds=timeout_seconds
            )
        return validate_metric_quality_row(columns, rows, metric_id)

    metric_results = tuple(
        await asyncio.gather(
            *(check_metric(metric_id, query) for metric_id, query in business_metrics)
        )
    )
    return build_quality_receipt(
        manifest,
        catalog_release_id=catalog_release_id,
        dataset_results=dataset_results,
        metric_results=metric_results,
        lineage_edges=live_lineage,
        trino_fingerprints=trino_fingerprints,
        checked_at=checked_at,
        ttl_seconds=ttl_seconds,
    )


async def _execute_rows(
    client: Any, sql: str, *, timeout_seconds: float
) -> tuple[tuple[str, ...], tuple[tuple[object, ...], ...]]:
    deadline = monotonic() + timeout_seconds
    page = await client.execute(sql, deadline=deadline)
    columns = tuple(page.columns)
    rows = list(page.rows)
    for _ in range(_MAX_PAGES):
        if page.next_uri is None:
            if page.state != "FINISHED":
                raise CanonicalQualityGateError("Trino quality query did not finish")
            return columns, tuple(rows)
        page = await client.next_page(page.next_uri, deadline=deadline)
        columns = tuple(page.columns) or columns
        rows.extend(page.rows)
    raise CanonicalQualityGateError("Trino quality query exceeded its page bound")


def _identifier(value: object) -> str:
    text = str(value)
    if _IDENTIFIER.fullmatch(text) is None:
        raise CanonicalQualityGateError("quality SQL identifier is invalid")
    return f'"{text}"'


def _qualified_name(value: str) -> str:
    parts = value.split(".")
    if len(parts) != 3:
        raise CanonicalQualityGateError("quality Dataset FQN must have three parts")
    return ".".join(_identifier(part) for part in parts)
