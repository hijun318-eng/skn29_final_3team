"""Phase 8 native semantic shadow의 순수 projection과 wire 계약을 검증한다."""

from __future__ import annotations

import asyncio
import sys
from copy import deepcopy
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
DATAHUB = ROOT / "infrastructure" / "database" / "datahub"
BACKEND = ROOT / "app" / "backend"
for entry in (str(ROOT), str(DATAHUB), str(BACKEND), str(ROOT / "tests" / "data")):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from metadata_wire import metadata_change_proposals  # noqa: E402
from native_semantic_publication import (  # noqa: E402
    grouped_native_semantic_aspects,
    native_semantic_status_targets,
    publish_native_semantic_shadow,
    relationship_capability_probe_aspects,
    restore_phase3_metric_aspects,
    verify_native_semantic_shadow,
)
from native_semantic_shadow import (  # noqa: E402
    NativeSemanticShadowError,
    compiled_native_semantic_surface,
    iter_native_semantic_aspects,
    legacy_semantic_surface,
    logical_dataset_urn,
    native_semantic_shadow_projection,
    semantic_model_urn,
    structured_property_urn,
)
from test_datahub_metadata_publication import arbitrary_ratio_bundle  # noqa: E402


def _aspects(bundle: dict) -> list[dict]:
    return [
        {
            "entity_type": entity_type,
            "urn": urn,
            "aspect_name": name,
            "value": value,
        }
        for entity_type, urn, name, value in iter_native_semantic_aspects(bundle)
    ]


def _grouped(bundle: dict) -> dict[str, dict[str, dict]]:
    result: dict[str, dict[str, dict]] = {}
    for item in _aspects(bundle):
        result.setdefault(item["urn"], {})[item["aspect_name"]] = item["value"]
    return result


def test_projection_compiles_exact_legacy_native_surface() -> None:
    bundle = arbitrary_ratio_bundle()
    projection = native_semantic_shadow_projection(bundle)
    aspects = _aspects(bundle)

    assert projection["legacy_surface_sha256"] == projection[
        "compiled_native_surface_sha256"
    ]
    assert compiled_native_semantic_surface(aspects) == legacy_semantic_surface(bundle)
    assert projection["semantic_model_count"] == 1
    assert projection["structured_property_count"] == 3
    assert projection["logical_dataset_count"] == 2
    assert projection["semantic_field_count"] == 9
    assert projection["relationship_count"] == 1
    assert projection["runtime_authority_activated"] is False
    assert projection["canonical_execution_policy_remains_authoritative"] is True


def test_relationship_cardinality_and_field_roles_are_native() -> None:
    bundle = arbitrary_ratio_bundle()
    grouped = _grouped(bundle)
    model = grouped[semantic_model_urn(bundle)]["semanticModelInfo"]
    quartz_urn = logical_dataset_urn("quartz.core.events")
    event_id = next(
        aspects
        for aspects in grouped.values()
        if aspects.get("schemaFieldKey")
        == {"parent": quartz_urn, "fieldPath": "event_id"}
    )

    assert model["relationships"] == [
        {
            "name": "event_account",
            "from": "quartz.core.events",
            "fromColumns": ["account_id"],
            "to": "ember.core.accounts",
            "toColumns": ["account_id"],
            "cardinality": "N_ONE",
        }
    ]
    assert event_id["semanticFieldAnnotation"]["type"] == "MEASURE"
    assert event_id["semanticFieldAnnotation"]["aggregationFunction"] == "COUNT"
    assignment = event_id["structuredProperties"]["properties"][0]
    assert assignment["propertyUrn"] == structured_property_urn("fieldRole")
    assert assignment["values"] == [{"string": "MEASURE+GRAIN_KEY"}]


def test_metric_info_binds_semantic_model_and_visibility() -> None:
    bundle = arbitrary_ratio_bundle()
    grouped = _grouped(bundle)
    metrics = [values for values in grouped.values() if "metricKey" in values]

    assert len(metrics) == len(bundle["metric_terms"])
    assert all(
        values["metricInfo"]["semanticModel"] == semantic_model_urn(bundle)
        for values in metrics
    )
    assert all(
        values["structuredProperties"]["properties"][0]["values"]
        == [{"string": "BUSINESS"}]
        for values in metrics
    )


def test_logical_identity_is_stable_but_release_membership_is_bound() -> None:
    baseline = arbitrary_ratio_bundle()
    successor = deepcopy(baseline)
    successor["catalog_version"] = "catalog-r10"

    assert semantic_model_urn(baseline) == semantic_model_urn(successor)
    assert logical_dataset_urn("quartz.core.events") == logical_dataset_urn(
        "quartz.core.events"
    )
    assert native_semantic_shadow_projection(baseline)["release_membership_sha256"] != (
        native_semantic_shadow_projection(successor)["release_membership_sha256"]
    )


def test_conflicting_field_aggregations_fail_closed() -> None:
    bundle = arbitrary_ratio_bundle()
    event_count = next(item for item in bundle["metric_rules"] if item["id"] == "event_count")
    event_count["source"]["field"]["column"] = "amount"

    with pytest.raises(NativeSemanticShadowError, match="conflicting aggregations"):
        native_semantic_shadow_projection(bundle)


def test_wire_supports_semantic_and_structured_aspects_with_audit() -> None:
    audit = {"actor": "urn:li:corpuser:phase8", "time": 1_777_000_000_000}
    proposals = metadata_change_proposals(
        "semanticModel",
        "urn:li:semanticModel:(urn:li:dataPlatform:datahub,path,id)",
        {
            "semanticModelKey": {
                "platform": "urn:li:dataPlatform:datahub",
                "path": "path",
                "id": "id",
            },
            "semanticModelInfo": {"name": "model", "datasets": []},
        },
        audit,
    )
    info = next(item for item in proposals if item["aspectName"] == "semanticModelInfo")

    assert '"created":{"actor":"urn:li:corpuser:phase8"' in info["aspect"]["value"]
    assert '"lastModified":{"actor":"urn:li:corpuser:phase8"' in info["aspect"]["value"]

    assignments = metadata_change_proposals(
        "schemaField",
        "urn:li:schemaField:(urn:li:dataset:(urn:li:dataPlatform:datahub,x,PROD),id)",
        {
            "structuredProperties": {
                "properties": [
                    {
                        "propertyUrn": structured_property_urn("fieldRole"),
                        "values": [{"string": "DIMENSION"}],
                    }
                ]
            }
        },
        audit,
    )
    encoded = assignments[0]["aspect"]["value"]
    assert '"created":{"actor":"urn:li:corpuser:phase8"' in encoded
    assert '"lastModified":{"actor":"urn:li:corpuser:phase8"' in encoded


class SemanticClient:
    def __init__(self, bundle: dict) -> None:
        self.bundle = bundle
        self.grouped = grouped_native_semantic_aspects(bundle)
        self.writes: list[tuple[str, str, dict]] = []

    async def get_entity(self, urn: str, aspects: tuple[str, ...]) -> dict:
        owner = self.bundle["governance_entities"]["owners"][0]
        if urn == owner["urn"]:
            values = {
                "corpGroupInfo": {
                    "displayName": owner["name"],
                    "description": owner["description"],
                },
                "status": {"removed": False},
            }
        else:
            values = next(
                value for (_entity_type, entity_urn), value in self.grouped.items()
                if entity_urn == urn
            )
        return {
            "aspects": {
                name: {"value": deepcopy(values[name])}
                for name in aspects
            }
        }

    async def upsert_entity(
        self, entity_type: str, urn: str, aspects: dict, _audit: dict
    ) -> None:
        self.writes.append((entity_type, urn, deepcopy(aspects)))


def test_publication_is_dependency_ordered_and_readback_is_exact() -> None:
    bundle = arbitrary_ratio_bundle()
    client = SemanticClient(bundle)
    projection = native_semantic_shadow_projection(bundle)

    published = asyncio.run(
        publish_native_semantic_shadow(
            client,
            bundle,
            actor_urn="urn:li:corpuser:phase8",
            expected_projection_sha256=projection["projection_sha256"],
        )
    )
    verified = asyncio.run(
        verify_native_semantic_shadow(
            client,
            bundle,
            expected_projection_sha256=projection["projection_sha256"],
        )
    )

    assert client.writes[0][0] == "structuredProperty"
    assert client.writes[-1][0] == "metric"
    assert published["published_entity_count"] == len(client.grouped)
    assert verified["readback_projection_sha256"] == projection["projection_sha256"]
    assert verified["rest_aspect_equality"] == "100%"


def test_rollback_targets_only_new_entities_and_restores_phase3_metric_shape() -> None:
    bundle = arbitrary_ratio_bundle()
    client = SemanticClient(bundle)
    targets = native_semantic_status_targets(bundle)

    restored = asyncio.run(
        restore_phase3_metric_aspects(
            client,
            bundle,
            actor_urn="urn:li:corpuser:phase8",
        )
    )

    assert all(entity_type in {"semanticModel", "dataset", "schemaField"} for entity_type, _ in targets)
    assert not any(entity_type in {"metric", "structuredProperty"} for entity_type, _ in targets)
    assert restored == len(bundle["metric_terms"])
    assert all(write[0] == "metric" for write in client.writes)
    assert all(
        write[2]["structuredProperties"] == {"properties": []}
        and "semanticModel" not in write[2]["metricInfo"]
        for write in client.writes
    )


def test_relationship_probe_is_inactive_namespace_and_exact_n_one() -> None:
    probe = relationship_capability_probe_aspects()
    model = next(
        aspects for (entity_type, _urn), aspects in probe.items()
        if entity_type == "semanticModel"
    )

    assert len(probe) == 3
    assert model["semanticModelInfo"]["relationships"][0]["cardinality"] == "N_ONE"
    assert all(aspects["status"] == {"removed": False} for aspects in probe.values())
    assert all("probe" in urn for _entity_type, urn in probe)
