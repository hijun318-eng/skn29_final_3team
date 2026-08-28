"""DataHub v1.7 native semantic shadow의 발행·exact read-back·rollback을 제공한다."""

from __future__ import annotations

from collections.abc import Mapping
from time import time_ns
from typing import Any

from metadata_rest import assert_contains, aspect_value, preflight_owner_entities
from metadata_wire import validated_audit_stamp
from native_metric_shadow import iter_native_metric_aspects
from native_semantic_shadow import (
    DATAHUB_NATIVE_MODEL_VERSION,
    NativeSemanticShadowError,
    compiled_native_semantic_surface,
    iter_native_semantic_aspects,
    logical_dataset_urn,
    native_semantic_shadow_projection,
    semantic_model_urn,
)
from src.data.governance_contract import canonical_sha256


_SEMANTIC_MODEL_PROBE = """
query NativeSemanticModelProbe {
  searchAcrossEntities(
    input: {types: [SEMANTIC_MODEL], query: "*", start: 0, count: 1}
  ) {
    total
    count
    start
  }
}
""".strip()


def grouped_native_semantic_aspects(
    bundle: Mapping[str, Any],
) -> dict[tuple[str, str], dict[str, dict[str, Any]]]:
    """Entity별 aspect를 dependency-safe 발행 순서로 묶는다."""

    grouped: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}
    for entity_type, urn, name, value in iter_native_semantic_aspects(bundle):
        aspects = grouped.setdefault((entity_type, urn), {})
        if name in aspects:
            raise NativeSemanticShadowError("native semantic aspect is duplicate")
        aspects[name] = value
    order = {
        "structuredProperty": 0,
        "semanticModel": 1,
        "dataset": 2,
        "schemaField": 3,
        "metric": 4,
    }
    return dict(
        sorted(
            grouped.items(),
            key=lambda item: (order.get(item[0][0], 99), item[0][1]),
        )
    )


async def probe_native_semantic_model(client: Any) -> dict[str, Any]:
    """Pinned GMS의 SemanticModel entity type이 GraphQL search에 등록됐는지 확인한다."""

    payload = await client.graphql(_SEMANTIC_MODEL_PROBE, {})
    data = payload.get("data") if isinstance(payload, Mapping) else None
    result = data.get("searchAcrossEntities") if isinstance(data, Mapping) else None
    if not isinstance(result, Mapping):
        raise NativeSemanticShadowError("native SemanticModel probe returned no result")
    total, count, start = result.get("total"), result.get("count"), result.get("start")
    if (
        not isinstance(total, int)
        or isinstance(total, bool)
        or total < 0
        or not isinstance(count, int)
        or isinstance(count, bool)
        or count < 0
        or start != 0
    ):
        raise NativeSemanticShadowError("native SemanticModel probe is malformed")
    return {
        "status": "NATIVE_SEMANTIC_MODEL_ENTITY_AVAILABLE",
        "datahub_model_version": DATAHUB_NATIVE_MODEL_VERSION,
        "existing_semantic_model_count": total,
    }


async def publish_native_semantic_shadow(
    client: Any,
    bundle: Mapping[str, Any],
    *,
    actor_urn: str,
    expected_projection_sha256: str,
    attempted_urns: list[str] | None = None,
) -> dict[str, Any]:
    """사전 계산된 exact hash가 일치할 때만 isolated native shadow를 UPSERT한다."""

    projection = native_semantic_shadow_projection(bundle)
    if projection["projection_sha256"] != expected_projection_sha256:
        raise NativeSemanticShadowError("native semantic checked projection differs")
    audit = validated_audit_stamp(
        {"actor": actor_urn, "time": time_ns() // 1_000_000}
    )
    await preflight_owner_entities(client, bundle)
    count = 0
    for (entity_type, urn), aspects in grouped_native_semantic_aspects(bundle).items():
        if attempted_urns is not None and urn not in attempted_urns:
            attempted_urns.append(urn)
        for name, value in aspects.items():
            try:
                await client.upsert_entity(entity_type, urn, {name: value}, audit)
            except Exception as error:
                raise NativeSemanticShadowError(
                    f"native semantic publish failed: {entity_type}.{name}"
                ) from error
        count += 1
    return {**projection, "published_entity_count": count}


async def verify_native_semantic_shadow(
    client: Any,
    bundle: Mapping[str, Any],
    *,
    expected_projection_sha256: str,
) -> dict[str, Any]:
    """모든 authored aspect를 재조회해 checksum과 legacy/native equality를 검증한다."""

    projection = native_semantic_shadow_projection(bundle)
    if projection["projection_sha256"] != expected_projection_sha256:
        raise NativeSemanticShadowError("native semantic checked projection differs")
    readback: list[dict[str, Any]] = []
    for (entity_type, urn), expected_aspects in grouped_native_semantic_aspects(
        bundle
    ).items():
        entity = await client.get_entity(urn, tuple(expected_aspects))
        for name, expected in expected_aspects.items():
            actual = aspect_value(entity, name)
            assert_contains(actual, expected, f"{urn}.{name}")
            readback.append(
                {
                    "entity_type": entity_type,
                    "urn": urn,
                    "aspect_name": name,
                    "value": _project_shape(actual, expected),
                }
            )
    readback.sort(key=lambda item: (item["urn"], item["aspect_name"]))
    readback_sha256 = canonical_sha256(readback)
    compiled_sha256 = canonical_sha256(compiled_native_semantic_surface(readback))
    if (
        readback_sha256 != expected_projection_sha256
        or compiled_sha256 != projection["legacy_surface_sha256"]
    ):
        raise NativeSemanticShadowError("native semantic read-back checksum differs")
    return {
        **projection,
        "readback_projection_sha256": readback_sha256,
        "readback_compiled_surface_sha256": compiled_sha256,
        "rest_aspect_equality": "100%",
    }


async def set_native_semantic_removed(
    client: Any,
    bundle: Mapping[str, Any],
    *,
    actor_urn: str,
    removed: bool,
) -> int:
    """Phase 8 신규 model·logical dataset·field만 explicit URN으로 retire/restore한다."""

    audit = validated_audit_stamp(
        {"actor": actor_urn, "time": time_ns() // 1_000_000}
    )
    targets = native_semantic_status_targets(bundle)
    for entity_type, urn in targets:
        await client.upsert_entity(
            entity_type,
            urn,
            {"status": {"removed": removed}},
            audit,
        )
    return len(targets)


async def restore_phase3_metric_aspects(
    client: Any,
    bundle: Mapping[str, Any],
    *,
    actor_urn: str,
) -> int:
    """Phase 8이 확장한 MetricInfo와 assignment만 Phase 3 상태로 되돌린다."""

    audit = validated_audit_stamp(
        {"actor": actor_urn, "time": time_ns() // 1_000_000}
    )
    metrics: dict[str, dict[str, dict[str, Any]]] = {}
    for _entity_type, urn, name, value in iter_native_metric_aspects(bundle):
        if name == "metricInfo":
            metrics.setdefault(urn, {})[name] = value
    for urn, aspects in sorted(metrics.items()):
        await client.upsert_entity(
            "metric",
            urn,
            {**aspects, "structuredProperties": {"properties": []}},
            audit,
        )
    return len(metrics)


def native_semantic_status_targets(
    bundle: Mapping[str, Any],
) -> list[tuple[str, str]]:
    """Rollback이 변경할 신규 Phase 8 entity만 중복 없이 반환한다."""

    targets = {("semanticModel", semantic_model_urn(bundle))}
    for entity_type, urn, name, value in iter_native_semantic_aspects(bundle):
        if entity_type == "dataset" and name == "semanticModelProperties":
            targets.add((entity_type, urn))
        elif entity_type == "schemaField" and name == "schemaFieldKey":
            targets.add((entity_type, urn))
    return sorted(targets)


def relationship_capability_probe_aspects() -> dict[
    tuple[str, str], dict[str, dict[str, Any]]
]:
    """Release 관계를 꾸미지 않고 N_ONE read-back을 증명할 비활성 probe를 만든다."""

    model_urn = (
        "urn:li:semanticModel:(urn:li:dataPlatform:datahub,"
        "answervice.semantic_models.probe,relationship_cardinality_v1)"
    )
    left = logical_dataset_urn("probe.phase8.left")
    right = logical_dataset_urn("probe.phase8.right")
    result: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}
    for urn, name, alias in ((left, "left", "probe_left"), (right, "right", "probe_right")):
        result[("dataset", urn)] = {
            "datasetKey": {
                "platform": "urn:li:dataPlatform:datahub",
                "name": f"answervice.semantic.probe.phase8.{name}",
                "origin": "PROD",
            },
            "datasetProperties": {
                "name": f"Phase 8 relationship probe {name}",
                "qualifiedName": f"answervice.semantic.probe.phase8.{name}",
                "description": "Inactive acceptance-only semantic relationship probe.",
            },
            "semanticModelProperties": {
                "alias": alias,
                "semanticModel": model_urn,
            },
            "subTypes": {"typeNames": ["Semantic Model Dataset"]},
            "status": {"removed": False},
        }
    result[("semanticModel", model_urn)] = {
        "semanticModelKey": {
            "platform": "urn:li:dataPlatform:datahub",
            "path": "answervice.semantic_models.probe",
            "id": "relationship_cardinality_v1",
        },
        "semanticModelInfo": {
            "name": "Phase 8 relationship cardinality probe",
            "description": "Inactive acceptance-only N_ONE capability probe.",
            "datasets": [left, right],
            "relationships": [
                {
                    "name": "probe_many_to_one",
                    "from": "probe_left",
                    "fromColumns": ["foreign_key"],
                    "to": "probe_right",
                    "toColumns": ["primary_key"],
                    "cardinality": "N_ONE",
                }
            ],
        },
        "status": {"removed": False},
    }
    return result


def _project_shape(actual: object, expected: object) -> object:
    if isinstance(expected, Mapping):
        if not isinstance(actual, Mapping):  # pragma: no cover - assert_contains owns it
            raise NativeSemanticShadowError("native semantic read-back type differs")
        return {key: _project_shape(actual[key], value) for key, value in expected.items()}
    if isinstance(expected, list):
        if not isinstance(actual, list):  # pragma: no cover - assert_contains owns it
            raise NativeSemanticShadowError("native semantic read-back list differs")
        return [
            _project_shape(actual[index], value)
            for index, value in enumerate(expected)
        ]
    return actual
