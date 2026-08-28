"""검증된 release를 DataHub v1.7 native semantic graph shadow로 투영한다.

이 모듈은 외부 I/O 없이 SemanticModel·논리 Dataset·semantic field·Structured
Properties를 생성하고, canonical 계약과 native aspect에서 각각 독립적으로 compile한
표현 가능 범위가 같은지 검증한다. JOIN 실행 전략과 시간·preaggregation 정책은 native
모델이 표현하지 못하므로 canonical runtime policy가 계속 권한을 가진다.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Any

from metadata_aspects import Aspect
from metadata_contract import validate_bundle
from native_metric_shadow import (
    DATAHUB_NATIVE_MODEL_VERSION,
    NATIVE_PLATFORM_URN,
    NativeMetricShadowError,
    iter_native_metric_aspects,
    native_metric_expression,
    schema_field_urn,
)
from src.data.governance_contract import canonical_sha256, catalog_hash
from src.data.metric_governance import business_metric_ids


NATIVE_SEMANTIC_SHADOW_VERSION = "ANSWERVICE-DATAHUB-NATIVE-SEMANTIC-SHADOW-v1"
NATIVE_SEMANTIC_IDENTITY_VERSION = "ANSWERVICE-NATIVE-SEMANTIC-IDENTITY-v1"
_SEMANTIC_MODEL_PATH = "answervice.semantic_models"
_SEMANTIC_MODEL_ID = "analysis"
_LOGICAL_DATASET_PREFIX = "answervice.semantic"
_STRING_TYPE_URN = "urn:li:dataType:datahub.string"
_PROPERTY_PREFIX = "io.answervice.semantic"
_PROPERTY_SPECS = (
    (
        "grainKind",
        "Semantic grain kind",
        "Canonical grain kind of a logical semantic dataset.",
        "dataset",
    ),
    (
        "fieldRole",
        "Semantic field role",
        "Canonical role set of an annotated semantic field.",
        "schemaField",
    ),
    (
        "metricVisibility",
        "Metric visibility",
        "Canonical public visibility of a native business metric.",
        "metric",
    ),
)
_ROLE_ORDER = ("MEASURE", "TIME", "DIMENSION", "FILTER", "GRAIN_KEY", "JOIN_KEY")
_CARDINALITY = {
    "one_to_one": "ONE_ONE",
    "one_to_many": "ONE_N",
    "many_to_one": "N_ONE",
    "many_to_many": "N_N",
}
_AGGREGATION = {
    "none": None,
    "sum": "SUM",
    "count": "COUNT",
    "count_distinct": "COUNT_DISTINCT",
    "min": "MIN",
    "max": "MAX",
    "average": "AVG",
}


class NativeSemanticShadowError(NativeMetricShadowError):
    """Native semantic shadow를 모호함 없이 만들거나 비교할 수 없음을 알린다."""


def semantic_model_urn(bundle: Mapping[str, Any]) -> str:
    """Release checksum과 무관한 stable SemanticModel compound URN을 반환한다."""

    if not isinstance(bundle, Mapping):
        raise NativeSemanticShadowError("native SemanticModel bundle is invalid")
    return (
        f"urn:li:semanticModel:({NATIVE_PLATFORM_URN},"
        f"{_SEMANTIC_MODEL_PATH},{_SEMANTIC_MODEL_ID})"
    )


def logical_dataset_urn(asset_fqn: str) -> str:
    """물리 FQN에 안정적으로 대응하는 DataHub logical Dataset URN을 반환한다."""

    _fqn_parts(asset_fqn)
    return (
        f"urn:li:dataset:({NATIVE_PLATFORM_URN},"
        f"{_LOGICAL_DATASET_PREFIX}.{asset_fqn},PROD)"
    )


def structured_property_urn(name: str) -> str:
    """Phase 8 소유 Structured Property의 stable URN을 반환한다."""

    if name not in {item[0] for item in _PROPERTY_SPECS}:
        raise NativeSemanticShadowError("native Structured Property name is invalid")
    return f"urn:li:structuredProperty:{_PROPERTY_PREFIX}.{name}"


def iter_native_semantic_aspects(bundle: Mapping[str, Any]) -> Iterator[Aspect]:
    """검증 bundle에서 Phase 8 native semantic aspect 전체를 결정론적으로 생성한다."""

    validate_bundle(bundle)
    inventory = _semantic_inventory(bundle)
    model_urn = semantic_model_urn(bundle)
    assets = inventory["assets"]
    fields = inventory["fields"]

    for name, display_name, description, entity_type in _PROPERTY_SPECS:
        urn = structured_property_urn(name)
        qualified_name = f"{_PROPERTY_PREFIX}.{name}"
        yield "structuredProperty", urn, "structuredPropertyKey", {"id": qualified_name}
        yield "structuredProperty", urn, "propertyDefinition", {
            "qualifiedName": qualified_name,
            "displayName": display_name,
            "valueType": _STRING_TYPE_URN,
            "cardinality": "SINGLE",
            "entityTypes": [f"urn:li:entityType:datahub.{entity_type}"],
            "description": description,
            "immutable": False,
            # PDL 주석의 v1 예시와 달리 pinned v1.7 GMS validator는
            # Structured Property version에 14자리 숫자만 허용한다.
            "version": "20260822000000",
        }
        yield "structuredProperty", urn, "status", {"removed": False}

    yield "semanticModel", model_urn, "semanticModelKey", {
        "platform": NATIVE_PLATFORM_URN,
        "path": _SEMANTIC_MODEL_PATH,
        "id": _SEMANTIC_MODEL_ID,
    }
    yield "semanticModel", model_urn, "semanticModelInfo", {
        "name": "Answervice Analysis Semantic Model",
        "description": "Checksum-bound native semantic shadow for governed analysis.",
        "datasets": [logical_dataset_urn(fqn) for fqn in sorted(assets)],
        "relationships": inventory["relationships"],
    }
    yield "semanticModel", model_urn, "status", {"removed": False}
    yield "semanticModel", model_urn, "ownership", _model_ownership(bundle)
    yield "semanticModel", model_urn, "domains", _model_domains(bundle)

    for fqn in sorted(assets):
        asset = assets[fqn]
        logical_urn = logical_dataset_urn(fqn)
        physical_urn = str(asset["urn"])
        logical_fields = [
            (column, fields[(fqn, column)])
            for asset_fqn, column in sorted(fields)
            if asset_fqn == fqn
        ]
        yield "dataset", logical_urn, "datasetKey", {
            "platform": NATIVE_PLATFORM_URN,
            "name": f"{_LOGICAL_DATASET_PREFIX}.{fqn}",
            "origin": "PROD",
        }
        yield "dataset", logical_urn, "datasetProperties", {
            "name": f"Semantic {fqn}",
            "qualifiedName": f"{_LOGICAL_DATASET_PREFIX}.{fqn}",
            "description": f"Logical semantic projection of {fqn}.",
        }
        yield "dataset", logical_urn, "semanticModelProperties", {
            "alias": fqn,
            "semanticModel": model_urn,
        }
        yield "dataset", logical_urn, "subTypes", {
            "typeNames": ["Semantic Model Dataset"]
        }
        yield "dataset", logical_urn, "upstreamLineage", {
            "upstreams": [{"dataset": physical_urn, "type": "TRANSFORMED"}],
            "fineGrainedLineages": [
                {
                    "upstreamType": "FIELD_SET",
                    "upstreams": [schema_field_urn(physical_urn, column)],
                    "downstreamType": "FIELD",
                    "downstreams": [schema_field_urn(logical_urn, column)],
                    "transformOperation": "IDENTITY",
                    "confidenceScore": 1.0,
                }
                for column, _field in logical_fields
            ],
        }
        yield "dataset", logical_urn, "structuredProperties", _assignment(
            "grainKind", str(asset["grain"]["kind"])
        )
        yield "dataset", logical_urn, "status", {"removed": False}
        yield "dataset", logical_urn, "ownership", _ownership(asset)
        yield "dataset", logical_urn, "domains", {"domains": [asset["domain_urn"]]}

        for column, field in logical_fields:
            field_urn = schema_field_urn(logical_urn, column)
            annotation: dict[str, Any] = {
                "type": field["type"],
                "expression": _field_expression(fqn, column),
            }
            if field["aggregation"] is not None:
                annotation["aggregationFunction"] = field["aggregation"]
            if field["type"] == "DIMENSION":
                annotation["dimension"] = {"isTime": field["is_time"]}
            yield "schemaField", field_urn, "schemaFieldKey", {
                "parent": logical_urn,
                "fieldPath": column,
            }
            yield "schemaField", field_urn, "semanticFieldAnnotation", annotation
            yield "schemaField", field_urn, "structuredProperties", _assignment(
                "fieldRole", field["field_role"]
            )
            yield "schemaField", field_urn, "status", {"removed": False}

    for entity_type, urn, name, raw in iter_native_metric_aspects(bundle):
        value = dict(raw)
        if name == "metricInfo":
            value["semanticModel"] = model_urn
        yield entity_type, urn, name, value
        if name == "metricInfo":
            yield entity_type, urn, "structuredProperties", _assignment(
                "metricVisibility", "BUSINESS"
            )


def native_semantic_shadow_projection(bundle: Mapping[str, Any]) -> dict[str, Any]:
    """Native semantic aspect와 legacy/native equality를 checksum receipt로 봉인한다."""

    validate_bundle(bundle)
    aspects = sorted(
        (
            {
                "entity_type": entity_type,
                "urn": urn,
                "aspect_name": name,
                "value": value,
            }
            for entity_type, urn, name, value in iter_native_semantic_aspects(bundle)
        ),
        key=lambda item: (item["urn"], item["aspect_name"]),
    )
    legacy = legacy_semantic_surface(bundle)
    compiled = compiled_native_semantic_surface(aspects)
    if compiled != legacy:
        raise NativeSemanticShadowError("legacy/native semantic surface differs")
    inventory = _semantic_inventory(bundle)
    business_count = len(
        business_metric_ids(
            {str(item["id"]): item for item in bundle["metric_rules"]}.values()
        )
    )
    membership = [
        {
            "entity_type": item["entity_type"],
            "urn": item["urn"],
            "aspect_name": item["aspect_name"],
        }
        for item in aspects
    ]
    return {
        "contract_version": NATIVE_SEMANTIC_SHADOW_VERSION,
        "datahub_model_version": DATAHUB_NATIVE_MODEL_VERSION,
        "logical_identity_version": NATIVE_SEMANTIC_IDENTITY_VERSION,
        "catalog_version": bundle["catalog_version"],
        "catalog_sha256": catalog_hash(bundle),
        "semantic_model_urn": semantic_model_urn(bundle),
        "projection_sha256": canonical_sha256(aspects),
        "aspect_membership_sha256": canonical_sha256(membership),
        "release_membership_sha256": canonical_sha256(
            {
                "catalog_version": bundle["catalog_version"],
                "catalog_sha256": catalog_hash(bundle),
                "aspects": membership,
            }
        ),
        "legacy_surface_sha256": canonical_sha256(legacy),
        "compiled_native_surface_sha256": canonical_sha256(compiled),
        "native_aspect_count": len(aspects),
        "structured_property_count": len(_PROPERTY_SPECS),
        "semantic_model_count": 1,
        "logical_dataset_count": len(inventory["assets"]),
        "semantic_field_count": len(inventory["fields"]),
        "relationship_count": len(inventory["relationships"]),
        "business_metric_count": business_count,
        "runtime_authority_activated": False,
        "canonical_execution_policy_remains_authoritative": True,
        "nonrepresentable_policy_sha256": canonical_sha256(
            {
                "join_graph": bundle["join_graph"],
                "time_rules": bundle["time_rules"],
                "query_policy": bundle["query_policy"],
            }
        ),
    }


def legacy_semantic_surface(bundle: Mapping[str, Any]) -> dict[str, Any]:
    """Canonical bundle에서 DataHub v1.7이 표현 가능한 semantic surface를 compile한다."""

    validate_bundle(bundle)
    inventory = _semantic_inventory(bundle)
    model_urn = semantic_model_urn(bundle)
    datasets = []
    for fqn in sorted(inventory["assets"]):
        asset = inventory["assets"][fqn]
        datasets.append(
            {
                "alias": fqn,
                "logical_urn": logical_dataset_urn(fqn),
                "physical_urn": str(asset["urn"]),
                "grain_kind": str(asset["grain"]["kind"]),
                "fields": [
                    {
                        "name": column,
                        "annotation": _field_annotation_surface(
                            fqn, column, inventory["fields"][(fqn, column)]
                        ),
                        "field_role": inventory["fields"][(fqn, column)]["field_role"],
                    }
                    for asset_fqn, column in sorted(inventory["fields"])
                    if asset_fqn == fqn
                ],
            }
        )
    rules = {str(item["id"]): item for item in bundle["metric_rules"]}
    metrics = [
        {
            "id": metric_id,
            "expression": native_metric_expression(metric_id, rules),
            "semantic_model": model_urn,
            "visibility": "BUSINESS",
        }
        for metric_id in sorted(business_metric_ids(rules.values()))
    ]
    return {
        "semantic_model": model_urn,
        "datasets": datasets,
        "relationships": inventory["relationships"],
        "metrics": metrics,
    }


def compiled_native_semantic_surface(
    aspects: list[Mapping[str, Any]],
) -> dict[str, Any]:
    """Native aspect 목록만으로 legacy와 비교 가능한 semantic surface를 복원한다."""

    grouped: dict[str, dict[str, Mapping[str, Any]]] = {}
    for item in aspects:
        try:
            urn = str(item["urn"])
            name = str(item["aspect_name"])
            value = item["value"]
        except (KeyError, TypeError) as error:
            raise NativeSemanticShadowError("native semantic aspect is malformed") from error
        if not isinstance(value, Mapping) or name in grouped.setdefault(urn, {}):
            raise NativeSemanticShadowError("native semantic aspect is duplicate or invalid")
        grouped[urn][name] = value

    models = [
        (urn, values)
        for urn, values in grouped.items()
        if "semanticModelKey" in values
    ]
    if len(models) != 1:
        raise NativeSemanticShadowError("native semantic model membership differs")
    model_urn, model = models[0]
    info = _mapping(model.get("semanticModelInfo"), "native semantic model info")
    dataset_urns = info.get("datasets")
    if not isinstance(dataset_urns, list):
        raise NativeSemanticShadowError("native semantic model datasets are invalid")
    datasets: list[dict[str, Any]] = []
    for dataset_urn in sorted(str(item) for item in dataset_urns):
        values = grouped.get(dataset_urn)
        if values is None:
            raise NativeSemanticShadowError("native logical dataset is missing")
        properties = _mapping(
            values.get("semanticModelProperties"), "native semantic dataset properties"
        )
        lineage = _mapping(values.get("upstreamLineage"), "native semantic lineage")
        upstreams = lineage.get("upstreams")
        if not isinstance(upstreams, list) or len(upstreams) != 1:
            raise NativeSemanticShadowError("native semantic upstream differs")
        upstream = _mapping(upstreams[0], "native semantic upstream")
        grain_kind = _assigned_value(values, "grainKind")
        fields: list[dict[str, Any]] = []
        for _field_urn, field_values in sorted(grouped.items()):
            key = field_values.get("schemaFieldKey")
            if not isinstance(key, Mapping) or key.get("parent") != dataset_urn:
                continue
            column = str(key.get("fieldPath"))
            annotation = _mapping(
                field_values.get("semanticFieldAnnotation"),
                "native semantic field annotation",
            )
            fields.append(
                {
                    "name": column,
                    "annotation": dict(annotation),
                    "field_role": _assigned_value(field_values, "fieldRole"),
                }
            )
        datasets.append(
            {
                "alias": str(properties.get("alias")),
                "logical_urn": dataset_urn,
                "physical_urn": str(upstream.get("dataset")),
                "grain_kind": grain_kind,
                "fields": sorted(fields, key=lambda item: item["name"]),
            }
        )

    metrics: list[dict[str, Any]] = []
    for _urn, values in sorted(grouped.items()):
        key = values.get("metricKey")
        if not isinstance(key, Mapping):
            continue
        metric_info = _mapping(values.get("metricInfo"), "native metric info")
        metrics.append(
            {
                "id": str(key.get("id")),
                "expression": metric_info.get("expression"),
                "semantic_model": metric_info.get("semanticModel"),
                "visibility": _assigned_value(values, "metricVisibility"),
            }
        )
    relationships = info.get("relationships")
    if not isinstance(relationships, list):
        raise NativeSemanticShadowError("native semantic relationships are invalid")
    return {
        "semantic_model": model_urn,
        "datasets": sorted(datasets, key=lambda item: item["alias"]),
        "relationships": relationships,
        "metrics": sorted(metrics, key=lambda item: item["id"]),
    }


def _semantic_inventory(bundle: Mapping[str, Any]) -> dict[str, Any]:
    assets = {str(item["fqn"]): item for item in bundle["schema_context"]["assets"]}
    fields: dict[tuple[str, str], dict[str, Any]] = {}

    def add(reference: object, role: str, aggregation: str | None = None) -> None:
        field = _mapping(reference, "semantic field reference")
        fqn, column = str(field.get("asset_fqn")), str(field.get("column"))
        _validate_field(assets, fqn, column)
        value = fields.setdefault(
            (fqn, column), {"roles": set(), "aggregations": set()}
        )
        value["roles"].add(role)
        if aggregation is not None:
            value["aggregations"].add(aggregation)

    for metric in bundle["metric_rules"]:
        source = _mapping(metric.get("source"), "semantic metric source")
        if source.get("kind") == "column":
            aggregation = _AGGREGATION.get(str(metric.get("aggregation")))
            if str(metric.get("aggregation")) not in _AGGREGATION:
                raise NativeSemanticShadowError("semantic measure aggregation is unsupported")
            add(source.get("field"), "MEASURE", aggregation or "__NONE__")
        time_field = metric.get("time_field")
        if time_field is not None:
            add(time_field, "TIME")
        for dimension in metric.get("dimensions", []):
            add(dimension, "DIMENSION")
        for required_filter in metric.get("required_filters", []):
            add(_mapping(required_filter, "semantic filter").get("field"), "FILTER")

    for dimension in bundle["dimensions"]:
        add(
            {
                "asset_fqn": dimension["asset_fqn"],
                "column": dimension["column"],
            },
            "DIMENSION",
        )
    for time_field in bundle["time_rules"].get("fields", []):
        add(_mapping(time_field, "semantic time field").get("field"), "TIME")

    relationships: list[dict[str, Any]] = []
    for edge in sorted(bundle["join_graph"]["edges"], key=lambda item: str(item["id"])):
        left, right = str(edge["left"]), str(edge["right"])
        conditions = edge.get("equality_conditions")
        if not isinstance(conditions, list) or not conditions:
            raise NativeSemanticShadowError("semantic relationship equality is empty")
        from_columns: list[str] = []
        to_columns: list[str] = []
        for condition in conditions:
            value = _mapping(condition, "semantic equality condition")
            left_column, right_column = str(value["left_column"]), str(value["right_column"])
            add({"asset_fqn": left, "column": left_column}, "JOIN_KEY")
            add({"asset_fqn": right, "column": right_column}, "JOIN_KEY")
            from_columns.append(left_column)
            to_columns.append(right_column)
        cardinality = _CARDINALITY.get(str(edge.get("cardinality")))
        if cardinality is None:
            raise NativeSemanticShadowError("semantic relationship cardinality is unsupported")
        relationships.append(
            {
                "name": str(edge["id"]),
                "from": left,
                "fromColumns": from_columns,
                "to": right,
                "toColumns": to_columns,
                "cardinality": cardinality,
            }
        )
        for condition in edge.get("temporal_conditions", []):
            temporal = _mapping(condition, "semantic temporal condition")
            add(temporal.get("event_field"), "TIME")
            validity = str(temporal.get("validity_asset_fqn"))
            add(
                {"asset_fqn": validity, "column": temporal.get("valid_from_column")},
                "TIME",
            )
            if temporal.get("valid_to_column") is not None:
                add(
                    {"asset_fqn": validity, "column": temporal.get("valid_to_column")},
                    "TIME",
                )
        preaggregation = edge.get("preaggregation")
        if isinstance(preaggregation, Mapping):
            for name in ("grain", "keys"):
                for reference in preaggregation.get(name, []):
                    add(reference, "GRAIN_KEY")

    selected_fqns = {fqn for fqn, _column in fields}
    for fqn in sorted(selected_fqns):
        asset = assets[fqn]
        for column in asset["grain"]["keys"]:
            add({"asset_fqn": fqn, "column": column}, "GRAIN_KEY")

    finalized: dict[tuple[str, str], dict[str, Any]] = {}
    for key, value in fields.items():
        roles = set(value["roles"])
        aggregations = set(value["aggregations"])
        if len(aggregations) > 1:
            raise NativeSemanticShadowError("semantic field has conflicting aggregations")
        if "MEASURE" in roles:
            field_type = "MEASURE"
        elif roles & {"TIME", "DIMENSION", "GRAIN_KEY", "JOIN_KEY"}:
            field_type = "DIMENSION"
        elif "FILTER" in roles:
            field_type = "FILTER"
        else:  # pragma: no cover - every producer assigns a role
            field_type = "OTHER"
        aggregation = next(iter(aggregations), None)
        finalized[key] = {
            "type": field_type,
            "aggregation": None if aggregation == "__NONE__" else aggregation,
            "is_time": "TIME" in roles,
            "field_role": "+".join(role for role in _ROLE_ORDER if role in roles),
        }
    selected_assets = {fqn: assets[fqn] for fqn in sorted(selected_fqns)}
    if not selected_assets or not finalized:
        raise NativeSemanticShadowError("semantic projection is empty")
    return {
        "assets": selected_assets,
        "fields": finalized,
        "relationships": relationships,
    }


def _field_annotation_surface(
    fqn: str,
    column: str,
    field: Mapping[str, Any],
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "type": field["type"],
        "expression": _field_expression(fqn, column),
    }
    if field["aggregation"] is not None:
        result["aggregationFunction"] = field["aggregation"]
    if field["type"] == "DIMENSION":
        result["dimension"] = {"isTime": field["is_time"]}
    return result


def _field_expression(fqn: str, column: str) -> dict[str, Any]:
    parts = [*_fqn_parts(fqn), column]
    if not column.isascii() or not column.isidentifier():
        raise NativeSemanticShadowError("semantic field identifier is invalid")
    expression = ".".join(f'"{part}"' for part in parts)
    return {"dialects": [{"dialect": "ANSI_SQL", "expression": expression}]}


def _fqn_parts(value: object) -> list[str]:
    if not isinstance(value, str):
        raise NativeSemanticShadowError("semantic asset FQN is invalid")
    parts = value.split(".")
    if len(parts) < 2 or any(not part.isascii() or not part.isidentifier() for part in parts):
        raise NativeSemanticShadowError("semantic asset FQN is invalid")
    return parts


def _validate_field(
    assets: Mapping[str, Mapping[str, Any]], fqn: str, column: str
) -> None:
    asset = assets.get(fqn)
    if asset is None or column not in {str(item["name"]) for item in asset["columns"]}:
        raise NativeSemanticShadowError("semantic field is outside the release")


def _assignment(name: str, value: str) -> dict[str, Any]:
    if not value or value != value.strip():
        raise NativeSemanticShadowError("structured property value is invalid")
    return {
        "properties": [
            {
                "propertyUrn": structured_property_urn(name),
                "values": [{"string": value}],
            }
        ]
    }


def _assigned_value(values: Mapping[str, Any], name: str) -> str:
    structured = _mapping(
        values.get("structuredProperties"), "native structured properties"
    )
    properties = structured.get("properties")
    expected_urn = structured_property_urn(name)
    if not isinstance(properties, list):
        raise NativeSemanticShadowError("native structured property assignment is invalid")
    matches = [
        item
        for item in properties
        if isinstance(item, Mapping) and item.get("propertyUrn") == expected_urn
    ]
    if len(matches) != 1 or matches[0].get("values") is None:
        raise NativeSemanticShadowError("native structured property membership differs")
    assigned = matches[0]["values"]
    if (
        not isinstance(assigned, list)
        or len(assigned) != 1
        or not isinstance(assigned[0], Mapping)
        or set(assigned[0]) != {"string"}
        or not isinstance(assigned[0]["string"], str)
    ):
        raise NativeSemanticShadowError("native structured property value differs")
    return assigned[0]["string"]


def _ownership(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "owners": [{"owner": value["owner_urn"], "type": "TECHNICAL_OWNER"}]
    }


def _model_ownership(bundle: Mapping[str, Any]) -> dict[str, Any]:
    owners = {str(asset["owner_urn"]) for asset in bundle["schema_context"]["assets"]}
    if not owners:
        raise NativeSemanticShadowError("semantic model owner is empty")
    return {
        "owners": [
            {"owner": owner, "type": "TECHNICAL_OWNER"}
            for owner in sorted(owners)
        ]
    }


def _model_domains(bundle: Mapping[str, Any]) -> dict[str, Any]:
    domains = sorted({str(asset["domain_urn"]) for asset in bundle["schema_context"]["assets"]})
    if not domains:
        raise NativeSemanticShadowError("semantic model domain is empty")
    return {"domains": domains}


def _mapping(value: object, context: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise NativeSemanticShadowError(f"{context} is invalid")
    return value
