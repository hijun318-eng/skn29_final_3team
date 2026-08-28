"""Canonical Quality·Lineage Gate의 fail-closed receipt 계약을 검증한다."""

from __future__ import annotations

import asyncio
import copy
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlglot import parse


ROOT = Path(__file__).resolve().parents[2]
DATAHUB = ROOT / "infrastructure" / "database" / "datahub"
METADATA = DATAHUB / "metadata"
for entry in (str(ROOT), str(DATAHUB)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from canonical_metadata_manifest import load_canonical_metadata_manifest  # noqa: E402
from canonical_quality_gate import (  # noqa: E402
    CanonicalQualityGateError,
    build_dataset_quality_queries,
    build_quality_receipt,
    expected_lineage_edges,
    validate_dataset_quality_rows,
    validate_metric_quality_row,
    verify_canonical_quality_gate,
)
from src.data.governance_contract import canonical_sha256  # noqa: E402


def test_dataset_queries_isolate_exact_manifest_membership_per_statement() -> None:
    document = load_canonical_metadata_manifest(METADATA).as_document()
    queries = build_dataset_quality_queries(document)

    assert len(queries) == 53
    assert all(len(parse(query, read="trino")) == 1 for query in queries)
    assert all(query.count(" AS dataset_id") == 1 for query in queries)
    assert all("COUNT_IF(" in query for query in queries)
    assert all("UNION ALL" not in query and ";" not in query for query in queries)


def test_dataset_and_metric_results_fail_closed_on_critical_violation() -> None:
    document = load_canonical_metadata_manifest(METADATA).as_document()
    rows = [
        [item["dataset_id"], 1, 0]
        for item in document["datasets"]
    ]
    validated = validate_dataset_quality_rows(
        ("dataset_id", "row_count", "required_key_violation_count"),
        rows,
        document,
    )
    assert len(validated) == 53

    failed = copy.deepcopy(rows)
    failed[0][1] = 0
    with pytest.raises(CanonicalQualityGateError, match="critical Dataset"):
        validate_dataset_quality_rows(
            ("dataset_id", "row_count", "required_key_violation_count"),
            failed,
            document,
        )
    with pytest.raises(CanonicalQualityGateError, match="critical Metric"):
        validate_metric_quality_row(
            ("metric_id", "violation_count"),
            (("room_revenue", 1),),
            "room_revenue",
        )


def test_quality_receipt_is_checksum_bound_and_expires_without_raw_pii() -> None:
    manifest = load_canonical_metadata_manifest(METADATA)
    checked_at = datetime(2026, 8, 27, tzinfo=timezone.utc)
    receipt = build_quality_receipt(
        manifest,
        catalog_release_id=manifest.as_document()["authoring"]["catalog_version"],
        dataset_results=(("dataset", 1, 0),),
        metric_results=(("metric", 0),),
        lineage_edges=(("upstream", "downstream"),),
        trino_fingerprints=({"fqn": "catalog.schema.table"},),
        checked_at=checked_at,
        ttl_seconds=3600,
    )

    content = dict(receipt)
    supplied = content.pop("receipt_sha256")
    assert supplied == canonical_sha256(content)
    assert receipt["expires_at"] == "2026-08-27T01:00:00+00:00"
    assert receipt["raw_pii_value_count"] == 0


def test_live_gate_checks_exact_lineage_and_all_business_metrics() -> None:
    manifest = load_canonical_metadata_manifest(METADATA)
    document = manifest.as_document()
    expected = expected_lineage_edges(document)
    upstreams: dict[str, list[str]] = {}
    for upstream, downstream in expected:
        upstreams.setdefault(downstream, []).append(upstream)

    class DataHub:
        async def get_entity(self, urn: str, _aspects: tuple[str, ...]):
            values = upstreams.get(urn, [])
            if not values:
                return {"aspects": {}}
            return {
                "aspects": {
                    "upstreamLineage": {
                        "value": {
                            "upstreams": [
                                {"dataset": value, "type": "TRANSFORMED"}
                                for value in values
                            ]
                        }
                    }
                }
            }

    metric_by_query = {
        item["validation_query"]: item["metric_id"]
        for item in document["metrics"]
        if item["visibility"] == "BUSINESS"
    }
    dataset_by_query = {
        query: item["dataset_id"]
        for query, item in zip(
            build_dataset_quality_queries(document),
            sorted(document["datasets"], key=lambda item: item["dataset_id"]),
        )
    }

    class Trino:
        async def execute(self, sql: str, *, deadline: float):
            assert deadline > 0
            if sql in metric_by_query:
                return SimpleNamespace(
                    columns=("metric_id", "violation_count"),
                    rows=((metric_by_query[sql], 0),),
                    next_uri=None,
                    state="FINISHED",
                )
            assert sql in dataset_by_query
            return SimpleNamespace(
                columns=(
                    "dataset_id",
                    "row_count",
                    "required_key_violation_count",
                ),
                rows=((dataset_by_query[sql], 1, 0),),
                next_uri=None,
                state="FINISHED",
            )

    fingerprints = tuple({"fqn": item["fqn"]} for item in document["datasets"])
    receipt = asyncio.run(
        verify_canonical_quality_gate(
            DataHub(),
            Trino(),
            manifest,
            catalog_release_id=document["authoring"]["catalog_version"],
            live_seed_versions={
                item["fqn"]: item["authoring"]["seed_version"]
                for item in document["datasets"]
            },
            trino_fingerprints=fingerprints,
            checked_at=datetime(2026, 8, 27, tzinfo=timezone.utc),
            ttl_seconds=3600,
            timeout_seconds=30,
        )
    )

    assert receipt["status"] == "VERIFIED"
    assert receipt["dataset_check_count"] == 53
    assert receipt["business_metric_check_count"] == 13
    assert receipt["lineage_edge_count"] == 41
