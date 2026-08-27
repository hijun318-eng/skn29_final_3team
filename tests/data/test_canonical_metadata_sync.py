"""Canonical metadata의 read-only DataHub check와 관리 범위 경계를 검증한다."""

from __future__ import annotations

import asyncio
import copy
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]
DATAHUB = ROOT / "infrastructure" / "database" / "datahub"
for entry in (str(ROOT), str(DATAHUB)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from canonical_metadata_manifest import (  # noqa: E402
    REVIEW_REQUIRED,
    CanonicalMetadataManifest,
)
import canonical_metadata_sync as sync  # noqa: E402
from canonical_metadata_sync import (  # noqa: E402
    apply_canonical_metadata_plan,
    build_canonical_metadata_apply_plan,
    build_canonical_metadata_check,
)
from export_datahub_metadata_baseline import (  # noqa: E402
    BASELINE_SCHEMA_VERSION,
    BASELINE_SCOPE,
    _derive_exact_sets,
    _inventory,
)
from src.data.governance_contract import canonical_json, canonical_sha256  # noqa: E402


DATASET = "urn:li:dataset:(urn:li:dataPlatform:trino,serving.core.daily,PROD)"
UNMANAGED = "urn:li:dataset:(urn:li:dataPlatform:trino,other.core.audit,PROD)"
DOMAIN = "urn:li:domain:answervice_serving"
OWNER = "urn:li:corpGroup:answervice_runtime_stewards"
LIFECYCLE = "urn:li:lifecycleStageType:APPROVED"
TERM = "urn:li:glossaryTerm:room_revenue"
EXTERNAL_TERM = "urn:li:glossaryTerm:external.audit"
METRIC = (
    "urn:li:metric:(urn:li:dataPlatform:datahub,"
    "answervice.business_metrics,room_revenue)"
)
EXTERNAL_METRIC = (
    "urn:li:metric:(urn:li:dataPlatform:datahub,external.metrics,audit_count)"
)


def _entity(entity_type: str, urn: str, **aspects: object) -> dict[str, object]:
    return {"entity_type": entity_type, "urn": urn, "aspects": aspects}


def _baseline(
    *,
    dataset_name: str = "Daily Revenue",
    description: str = "승인된 일별 매출",
    editable_description: str = "영업일자",
    include_column: bool = True,
    upstream_urns: tuple[str, ...] = (),
):
    fields = (
        [
            {
                "fieldPath": "business_date",
                "nativeDataType": "date",
                "nullable": False,
                "isPartOfKey": True,
                "description": "영업일자",
            }
        ]
        if include_column
        else []
    )
    ownership = {"owners": [{"owner": OWNER, "type": "TECHNICAL_OWNER"}]}
    status = {"removed": False, "lifecycleStage": LIFECYCLE}
    dataset_aspects = {
        "datasetKey": {
            "platform": "urn:li:dataPlatform:trino",
            "name": "serving.core.daily",
            "origin": "PROD",
        },
        "datasetProperties": {
            "name": dataset_name,
            "description": description,
            "customProperties": {"source": "preserved"},
        },
        "schemaMetadata": {"fields": fields},
        "editableSchemaMetadata": {
            "editableSchemaFieldInfo": [
                {
                    "fieldPath": "business_date",
                    "description": editable_description,
                    "glossaryTerms": {"terms": [{"urn": TERM}]},
                }
            ]
            if include_column
            else []
        },
        "status": status,
        "ownership": ownership,
        "domains": {"domains": [DOMAIN]},
        "glossaryTerms": {"terms": [{"urn": TERM}]},
    }
    if upstream_urns:
        dataset_aspects["upstreamLineage"] = {
            "upstreams": [
                {"dataset": urn, "type": "TRANSFORMED"}
                for urn in upstream_urns
            ]
        }
    entities = [
        _entity(
            "corpGroup",
            OWNER,
            corpGroupKey={"name": "answervice_runtime_stewards"},
            corpGroupInfo={"displayName": "Answervice Runtime Stewards"},
            status={"removed": False},
        ),
        _entity(
            "dataset",
            DATASET,
            **dataset_aspects,
        ),
        _entity(
            "dataset",
            UNMANAGED,
            datasetKey={
                "platform": "urn:li:dataPlatform:trino",
                "name": "other.core.audit",
                "origin": "PROD",
            },
            datasetProperties={"name": "Unmanaged Audit"},
            schemaMetadata={
                "fields": [
                    {
                        "fieldPath": "audit_id",
                        "nativeDataType": "bigint",
                        "nullable": False,
                        "isPartOfKey": True,
                    }
                ]
            },
        ),
        _entity(
            "domain",
            DOMAIN,
            domainKey={"id": "answervice_serving"},
            domainProperties={"name": "SERVING", "description": "Serving domain"},
        ),
        _entity(
            "glossaryTerm",
            TERM,
            glossaryTermKey={"name": "room_revenue"},
            glossaryTermInfo={
                "id": "room_revenue",
                "name": "Room Revenue",
                "definition": "승인된 객실 매출",
                "customProperties": {"answervice.aliases": '["Room Revenue"]'},
            },
            status=status,
            ownership=ownership,
            domains={"domains": [DOMAIN]},
        ),
        _entity(
            "glossaryTerm",
            EXTERNAL_TERM,
            glossaryTermKey={"name": "external.audit"},
            glossaryTermInfo={"name": "External Audit"},
        ),
        _entity(
            "lifecycleStageType",
            LIFECYCLE,
            lifecycleStageTypeKey={"id": "APPROVED"},
            lifecycleStageTypeInfo={
                "name": "APPROVED",
                "description": "Approved production lifecycle",
            },
            status={"removed": False},
        ),
        _entity(
            "metric",
            METRIC,
            metricKey={
                "platform": "urn:li:dataPlatform:datahub",
                "path": "answervice.business_metrics",
                "id": "room_revenue",
            },
            metricInfo={"name": "Room Revenue"},
            status={"removed": False},
            ownership=ownership,
            domains={"domains": [DOMAIN]},
            glossaryTerms={"terms": [{"urn": TERM}]},
        ),
        _entity(
            "metric",
            EXTERNAL_METRIC,
            metricKey={
                "platform": "urn:li:dataPlatform:datahub",
                "path": "external.metrics",
                "id": "audit_count",
            },
            metricInfo={"name": "External Audit Count"},
            status={"removed": False},
        ),
    ]
    entities.sort(key=lambda item: (item["entity_type"], item["urn"]))
    exact_sets = _derive_exact_sets(entities)
    content = {
        "schema_version": BASELINE_SCHEMA_VERSION,
        "scope": BASELINE_SCOPE,
        "inventory": _inventory(entities, exact_sets),
        "entities": entities,
        "exact_sets": exact_sets,
        "exact_set_sha256": {
            name: canonical_sha256(values) for name, values in exact_sets.items()
        },
    }
    content_sha256 = canonical_sha256(content)
    receipt = {
        "schema_version": "answervice.datahub-metadata-read-receipt.v1",
        "content_sha256": content_sha256,
        "actor_urn": "urn:li:corpuser:service_catalog_reader",
        "read_at": "2026-08-27T00:00:00+00:00",
        "source_audit_sha256": canonical_sha256([]),
        "mutation_count": 0,
    }
    return {
        **content,
        "content_sha256": content_sha256,
        "deployment_receipt": receipt,
        "deployment_receipt_sha256": canonical_sha256(receipt),
    }


def _manifest(
    baseline_sha256: str,
    *,
    business_name: str = "Daily Revenue",
    description: str = "승인된 일별 매출",
    column_description: str = "영업일자",
):
    document = {
        "source": {"datahub_baseline_sha256": baseline_sha256},
        "domains": [
            {"urn": DOMAIN, "name": "SERVING", "description": "Serving domain"}
        ],
        "owner_groups": [
            {
                "urn": OWNER,
                "name": "Answervice Runtime Stewards",
                "description": "Runtime stewards",
            }
        ],
        "lifecycles": [
            {
                "urn": LIFECYCLE,
                "name": "APPROVED",
                "description": "Approved production lifecycle",
            }
        ],
        "datasets": [
            {
                "dataset_id": "serving.daily",
                "physical_urn": DATASET,
                "fqn": "serving.core.daily",
                "business_name": business_name,
                "description": description,
                "domain_urn": DOMAIN,
                "owner_group_urn": OWNER,
                "authoring": {"approved_lifecycle_urn": LIFECYCLE},
                "columns": [
                    {
                        "column_name": "business_date",
                        "data_type": "date",
                        "nullable": False,
                        "description": column_description,
                        "term_urns": [TERM],
                    }
                ],
            }
        ],
        "glossary_terms": [
            {
                "term_id": "room_revenue",
                "urn": TERM,
                "korean_name": "Room Revenue",
                "definition": "승인된 객실 매출",
                "aliases": ["Room Revenue"],
                "domain_urn": DOMAIN,
                "owner_group_urn": OWNER,
                "lifecycle_urn": LIFECYCLE,
            }
        ],
        "metrics": [
            {
                "metric_id": "room_revenue",
                "business_name": "Room Revenue",
                "visibility": "BUSINESS",
                "term_urn": TERM,
                "runtime_rule": {
                    "id": "room_revenue",
                    "source": {
                        "kind": "column",
                        "field": {
                            "asset_fqn": "serving.core.daily",
                            "column": "business_date",
                        },
                    },
                },
            }
        ],
        "quality_policies": [
            {
                "dataset_id": "serving.daily",
                "lineage": {"mode": "SOURCE_ROOT"},
            }
        ],
    }
    review = (
        ("$.datasets[0].business_name",)
        if business_name == REVIEW_REQUIRED
        else ()
    )
    return CanonicalMetadataManifest(
        content_sha256="a" * 64,
        inventory={},
        review_required=review,
        _document_json=canonical_json(document),
    )


def _apply_plan_to_baseline(
    baseline: dict[str, object], plan: dict[str, object]
) -> dict[str, object]:
    """테스트에서 aspect upsert 후 full baseline checksum을 다시 구성한다."""

    result = copy.deepcopy(baseline)
    entities = {
        item["urn"]: item
        for item in result["entities"]
        if isinstance(item, dict)
    }
    for mutation in plan["mutations"]:
        entities[mutation["urn"]]["aspects"][mutation["aspect"]] = copy.deepcopy(
            mutation["value"]
        )
    exact_sets = _derive_exact_sets(result["entities"])
    result["exact_sets"] = exact_sets
    result["exact_set_sha256"] = {
        name: canonical_sha256(values) for name, values in exact_sets.items()
    }
    result["inventory"] = _inventory(result["entities"], exact_sets)
    content = {
        name: result[name]
        for name in (
            "schema_version",
            "scope",
            "inventory",
            "entities",
            "exact_sets",
            "exact_set_sha256",
        )
    }
    result["content_sha256"] = canonical_sha256(content)
    result["deployment_receipt"]["content_sha256"] = result["content_sha256"]
    result["deployment_receipt_sha256"] = canonical_sha256(
        result["deployment_receipt"]
    )
    return result


def test_check_is_deterministic_and_never_manages_undeclared_datasets() -> None:
    baseline = _baseline()
    manifest = _manifest(baseline["content_sha256"])

    first = build_canonical_metadata_check(manifest, baseline)
    second = build_canonical_metadata_check(manifest, copy.deepcopy(baseline))

    assert first == second
    assert first["status"] == "READY"
    assert first["mutation_count"] == 0
    assert first["planned_change_count"] == 0
    assert first["scope"]["managed_dataset_count"] == 1
    assert first["scope"]["unmanaged_dataset_count"] == 1
    assert UNMANAGED not in canonical_json(first["planned_changes"])
    assert first["diff"]["retirement_candidate_term_urns"] == []
    assert first["diff"]["retirement_candidate_metric_urns"] == []


def test_check_blocks_review_markers_without_planning_placeholder_writes() -> None:
    baseline = _baseline()
    result = build_canonical_metadata_check(
        _manifest(baseline["content_sha256"], business_name=REVIEW_REQUIRED),
        baseline,
    )

    assert result["status"] == "BLOCKED"
    assert {item["code"] for item in result["blockers"]} == {
        "MANIFEST_REVIEW_REQUIRED"
    }
    assert result["planned_change_count"] == 0
    assert REVIEW_REQUIRED not in canonical_json(result["planned_changes"])


def test_check_blocks_schema_drift_but_keeps_source_baseline_as_provenance() -> None:
    baseline = _baseline(description="이전 설명", include_column=False)
    result = build_canonical_metadata_check(_manifest("b" * 64), baseline)

    assert result["status"] == "BLOCKED"
    assert {item["code"] for item in result["blockers"]} == {
        "MANAGED_SCHEMA_DRIFT"
    }
    assert result["source_datahub_baseline_sha256"] == "b" * 64
    assert result["live_datahub_baseline_sha256"] == baseline["content_sha256"]
    assert result["planned_changes"] == [
        {
            "aspect": "datasetProperties",
            "entity_type": "dataset",
            "fields": ["description"],
            "urn": DATASET,
        }
    ]
    assert result["planned_change_count"] == 1
    assert result["mutation_count"] == 0


def test_apply_plan_is_checksum_bound_and_preserves_unmanaged_aspect_fields() -> None:
    baseline = _baseline(
        dataset_name="Old Name",
        description="이전 설명",
        editable_description="이전 영업일자",
    )
    manifest = _manifest(
        baseline["content_sha256"],
        business_name="일별 호텔 매출",
    )
    check = build_canonical_metadata_check(manifest, baseline)

    plan = build_canonical_metadata_apply_plan(
        manifest,
        baseline,
        expected_check_sha256=check["check_sha256"],
    )

    assert plan["mutation_count"] == 2
    properties = next(
        mutation["value"]
        for mutation in plan["mutations"]
        if mutation["aspect"] == "datasetProperties"
    )
    editable = next(
        mutation["value"]
        for mutation in plan["mutations"]
        if mutation["aspect"] == "editableSchemaMetadata"
    )
    assert properties == {
        "name": "일별 호텔 매출",
        "description": "승인된 일별 매출",
        "customProperties": {"source": "preserved"},
    }
    assert editable["editableSchemaFieldInfo"] == [
        {
            "fieldPath": "business_date",
            "description": "영업일자",
            "glossaryTerms": {"terms": [{"urn": TERM}]},
        }
    ]
    assert UNMANAGED not in canonical_json(plan)
    with pytest.raises(ValueError, match="stale or blocked"):
        build_canonical_metadata_apply_plan(
            manifest,
            baseline,
            expected_check_sha256="0" * 64,
        )


def test_applied_manifest_converges_and_second_plan_has_zero_mutations() -> None:
    baseline = _baseline(dataset_name="Old Name")
    manifest = _manifest(
        baseline["content_sha256"], business_name="일별 호텔 매출"
    )
    first_check = build_canonical_metadata_check(manifest, baseline)
    first_plan = build_canonical_metadata_apply_plan(
        manifest,
        baseline,
        expected_check_sha256=first_check["check_sha256"],
    )
    readback = _apply_plan_to_baseline(baseline, first_plan)

    second_check = build_canonical_metadata_check(manifest, readback)
    second_plan = build_canonical_metadata_apply_plan(
        manifest,
        readback,
        expected_check_sha256=second_check["check_sha256"],
    )

    assert readback["content_sha256"] != baseline["content_sha256"]
    assert second_check["status"] == "READY"
    assert second_check["planned_change_count"] == 0
    assert second_plan["mutation_count"] == 0


def test_lineage_diff_removes_unapproved_upstream_and_converges() -> None:
    baseline = _baseline(upstream_urns=(UNMANAGED,))
    manifest = _manifest(baseline["content_sha256"])
    check = build_canonical_metadata_check(manifest, baseline)

    assert check["planned_changes"] == [
        {
            "aspect": "upstreamLineage",
            "entity_type": "dataset",
            "fields": ["upstreams"],
            "urn": DATASET,
        }
    ]
    plan = build_canonical_metadata_apply_plan(
        manifest,
        baseline,
        expected_check_sha256=check["check_sha256"],
    )
    assert plan["mutations"][0]["value"]["upstreams"] == []

    readback = _apply_plan_to_baseline(baseline, plan)
    second = build_canonical_metadata_check(manifest, readback)
    assert second["planned_change_count"] == 0


def test_apply_executes_each_planned_aspect_once_and_rejects_tampering() -> None:
    baseline = _baseline(dataset_name="Old Name")
    manifest = _manifest(
        baseline["content_sha256"], business_name="일별 호텔 매출"
    )
    check = build_canonical_metadata_check(manifest, baseline)
    plan = build_canonical_metadata_apply_plan(
        manifest,
        baseline,
        expected_check_sha256=check["check_sha256"],
    )

    class RecordingClient:
        def __init__(self) -> None:
            self.calls: list[tuple[object, ...]] = []

        async def upsert_entity(self, *args: object) -> None:
            self.calls.append(args)

    client = RecordingClient()
    count = asyncio.run(
        apply_canonical_metadata_plan(
            client,
            plan,
            actor_urn="urn:li:corpuser:service_catalog_publisher",
            clock_ms=1,
        )
    )
    assert count == plan["mutation_count"] == len(client.calls)

    tampered = copy.deepcopy(plan)
    tampered["mutations"][0]["value"]["name"] = "변조"
    with pytest.raises(ValueError, match="receipt is invalid"):
        asyncio.run(
            apply_canonical_metadata_plan(
                client,
                tampered,
                actor_urn="urn:li:corpuser:service_catalog_publisher",
                clock_ms=1,
            )
        )


def test_full_read_helper_uses_the_supplied_timeout(monkeypatch) -> None:
    observed: list[tuple[str, float]] = []

    class FakeContext:
        def __init__(self, *_args: object, timeout_seconds: float, **_kwargs: object):
            observed.append((type(self).__name__, timeout_seconds))

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

    class FakeCatalog(FakeContext):
        async def health(self) -> bool:
            return True

    class FakeReader(FakeContext):
        pass

    async def fake_baseline(*_args: object, **_kwargs: object):
        return {"content_sha256": "a" * 64}

    monkeypatch.setattr(sync, "DataHubCatalogClient", FakeCatalog)
    monkeypatch.setattr(sync, "DataHubMetadataAdminClient", FakeReader)
    monkeypatch.setattr(sync, "build_datahub_metadata_baseline", fake_baseline)

    result = asyncio.run(
        sync._read_live_baseline(
            SimpleNamespace(
                base_url="https://datahub.test",
                token="read-token",
                ca_file=Path(__file__),
                actor_urn="urn:li:corpuser:service_catalog_reader",
            ),
            7.5,
        )
    )

    assert result == {"content_sha256": "a" * 64}
    assert observed == [("FakeCatalog", 7.5), ("FakeReader", 7.5)]
