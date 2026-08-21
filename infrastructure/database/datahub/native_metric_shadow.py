"""검증된 semantic release의 BUSINESS Metric을 DataHub v1.7 native graph shadow로 투영한다.

이 모듈은 외부 I/O 없이 공개 BUSINESS Metric만 versioned native ``metric`` aspect와
실제 Dataset·SchemaField lineage로 투영한다. SUPPORT operand와 권한·grain·fan-out·query
policy는 canonical release가 계속 소유하며, 발행과 재조회는 별도 publication adapter가
담당한다.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Any
from urllib.parse import quote

from metadata_aspects import Aspect
from metadata_contract import validate_bundle
from src.data.governance_contract import (
    canonical_sha256,
    catalog_hash,
    column_metric_asset,
    metric_asset_fqns,
    ratio_operand_ids,
    shared_semantic_hash,
)
from src.data.metric_governance import business_metric_ids


NATIVE_METRIC_SHADOW_VERSION = "ANSWERVICE-DATAHUB-NATIVE-METRIC-SHADOW-v1"
DATAHUB_NATIVE_MODEL_VERSION = "v1.7.0"
NATIVE_PLATFORM_URN = "urn:li:dataPlatform:datahub"
_PATH_PREFIX = "answervice.semantic_releases"
_SCHEMA_FIELD_RESERVED_CHARACTERS = frozenset({",", "(", ")", "␟"})


class NativeMetricShadowError(ValueError):
    """Native Metric shadow를 release identity에 안전하게 결속할 수 없음을 알린다."""


def native_metric_path(bundle: Mapping[str, Any]) -> str:
    """변경 불가능한 전체 catalog hash로 격리된 native Metric namespace를 반환한다."""

    return f"{_PATH_PREFIX}.{catalog_hash(bundle)}"


def native_metric_urn(bundle: Mapping[str, Any], metric_id: str) -> str:
    """DataHub ``MetricKey(platform,path,id)``와 같은 compound URN을 생성한다."""

    if not _identifier(metric_id):
        raise NativeMetricShadowError("native Metric id is invalid")
    return (
        f"urn:li:metric:({NATIVE_PLATFORM_URN},"
        f"{native_metric_path(bundle)},{metric_id})"
    )


def schema_field_urn(dataset_urn: str, column: str) -> str:
    """DataHub 공식 emitter와 동일한 예약문자 인코딩으로 schemaField URN을 만든다."""

    if (
        not dataset_urn.startswith("urn:li:dataset:(")
        or not isinstance(column, str)
        or not column
        or column != column.strip()
    ):
        raise NativeMetricShadowError("native Metric field lineage is invalid")
    encoded = "".join(
        quote(character, safe="")
        if character in _SCHEMA_FIELD_RESERVED_CHARACTERS
        else character
        for character in column
    )
    return f"urn:li:schemaField:({dataset_urn},{encoded})"


def iter_native_metric_aspects(bundle: Mapping[str, Any]) -> Iterator[Aspect]:
    """검증 bundle에서 공개 Metric entity와 실제 source lineage aspect를 생성한다."""

    validate_bundle(bundle)
    rules = {str(item["id"]): item for item in bundle["metric_rules"]}
    terms = {str(item["id"]): item for item in bundle["metric_terms"]}
    assets = {
        str(item["fqn"]): item for item in bundle["schema_context"]["assets"]
    }
    public_ids = business_metric_ids(list(rules.values()))
    if set(terms) != public_ids:
        raise NativeMetricShadowError(
            "native Metric terms must exactly cover BUSINESS rules"
        )
    path = native_metric_path(bundle)
    for metric_id in sorted(public_ids):
        metric = rules[metric_id]
        term = terms[metric_id]
        urn = native_metric_urn(bundle, metric_id)
        source_fields = _leaf_fields(metric_id, rules, frozenset())
        source_assets = metric_asset_fqns(metric, rules)
        if not source_fields or not source_assets:
            raise NativeMetricShadowError("native Metric source lineage is empty")
        if any(asset not in assets for asset in source_assets):
            raise NativeMetricShadowError(
                "native Metric source is outside the release"
            )

        yield "metric", urn, "metricKey", {
            "platform": NATIVE_PLATFORM_URN,
            "path": path,
            "id": metric_id,
        }
        yield "metric", urn, "metricInfo", {
            "name": term["name"],
            "description": term["definition"],
        }
        yield "metric", urn, "metricUpstreams", {
            "datasetUpstreams": [
                {"destinationUrn": assets[fqn]["urn"]}
                for fqn in sorted(source_assets)
            ],
            "fieldUpstreams": [
                {
                    "destinationUrn": schema_field_urn(
                        str(assets[fqn]["urn"]),
                        column,
                    )
                }
                for fqn, column in source_fields
            ],
        }
        operands = ratio_operand_ids(metric)
        public_operands = (
            tuple(item for item in operands if item in public_ids)
            if operands is not None
            else ()
        )
        if public_operands:
            yield "metric", urn, "metricRelationships", {
                "derivedFrom": [
                    {"destinationUrn": native_metric_urn(bundle, operand)}
                    for operand in public_operands
                ],
                "relatedMetrics": [],
            }
        yield "metric", urn, "status", {
            "removed": False,
            "lifecycleStage": term["approved_lifecycle_urn"],
        }
        yield "metric", urn, "ownership", {
            "owners": [
                {"owner": term["owner_urn"], "type": "TECHNICAL_OWNER"}
            ]
        }
        yield "metric", urn, "domains", {"domains": [term["domain_urn"]]}
        yield "metric", urn, "glossaryTerms", {
            "terms": [{"urn": term["urn"]}]
        }


def native_metric_shadow_projection(bundle: Mapping[str, Any]) -> dict[str, Any]:
    """shadow publish와 runtime cutover를 구분하는 checksum·coverage receipt를 만든다."""

    validate_bundle(bundle)
    aspects = sorted(
        (
            {
                "entity_type": entity_type,
                "urn": urn,
                "aspect_name": name,
                "value": value,
            }
            for entity_type, urn, name, value in iter_native_metric_aspects(bundle)
        ),
        key=lambda item: (item["urn"], item["aspect_name"]),
    )
    rules = {str(item["id"]): item for item in bundle["metric_rules"]}
    public_ids = business_metric_ids(list(rules.values()))
    support_ids = set(rules) - public_ids
    support_derived = sum(
        1
        for metric_id in public_ids
        if (operands := ratio_operand_ids(rules[metric_id])) is not None
        and any(item in support_ids for item in operands)
    )
    dataset_edges = sum(
        len(item["value"].get("datasetUpstreams", ()))
        for item in aspects
        if item["aspect_name"] == "metricUpstreams"
    )
    field_edges = sum(
        len(item["value"].get("fieldUpstreams", ()))
        for item in aspects
        if item["aspect_name"] == "metricUpstreams"
    )
    derived_edges = sum(
        len(item["value"].get("derivedFrom", ()))
        for item in aspects
        if item["aspect_name"] == "metricRelationships"
    )
    blockers = [
        "NATIVE_METRIC_READBACK_REQUIRED",
        "CANONICAL_EXECUTION_POLICY_REMAINS_AUTHORITATIVE",
    ]
    if support_derived:
        blockers.append("SUPPORT_DERIVATION_REMAINS_CANONICAL")
    projection_sha256 = canonical_sha256(aspects)
    return {
        "contract_version": NATIVE_METRIC_SHADOW_VERSION,
        "datahub_model_version": DATAHUB_NATIVE_MODEL_VERSION,
        "catalog_version": bundle["catalog_version"],
        "catalog_sha256": catalog_hash(bundle),
        "native_metric_path": native_metric_path(bundle),
        "projection_sha256": projection_sha256,
        "shadow_publishable": True,
        "runtime_cutover_ready": False,
        "runtime_cutover_blockers": blockers,
        "business_metric_count": len(public_ids),
        "support_metric_count": len(support_ids),
        "support_derived_metric_count": support_derived,
        "native_metric_count": len(public_ids),
        "native_aspect_count": len(aspects),
        "dataset_lineage_edge_count": dataset_edges,
        "field_lineage_edge_count": field_edges,
        "metric_derivation_edge_count": derived_edges,
        "execution_policy_sha256": canonical_sha256(
            {
                "metric_rules": bundle["metric_rules"],
                "shared_semantic_sha256": shared_semantic_hash(bundle),
            }
        ),
    }


def _leaf_fields(
    metric_id: str,
    rules: Mapping[str, Mapping[str, Any]],
    visiting: frozenset[str],
) -> tuple[tuple[str, str], ...]:
    if metric_id in visiting or metric_id not in rules:
        raise NativeMetricShadowError("native Metric dependency is cyclic or missing")
    metric = rules[metric_id]
    direct_asset = column_metric_asset(metric)
    if direct_asset is not None:
        source = metric["source"]
        return ((direct_asset, str(source["field"]["column"])),)
    operands = ratio_operand_ids(metric)
    if operands is None:
        raise NativeMetricShadowError("native Metric source kind is unsupported")
    fields = {
        field
        for operand in operands
        for field in _leaf_fields(operand, rules, visiting | {metric_id})
    }
    return tuple(sorted(fields))


def _identifier(value: object) -> bool:
    return isinstance(value, str) and value.isascii() and value.isidentifier()
