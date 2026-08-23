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
import unicodedata

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
NATIVE_METRIC_IDENTITY_VERSION = "ANSWERVICE-NATIVE-METRIC-IDENTITY-v1"
_STABLE_METRIC_PATH = "answervice.business_metrics"
_SCHEMA_FIELD_RESERVED_CHARACTERS = frozenset({",", "(", ")", "␟"})
_INJECTION_MARKERS = (
    "ignore previous",
    "ignore all instructions",
    "system prompt",
    "developer message",
    "assistant:",
    "jailbreak",
    "<system",
    "</system",
    "```",
    "{{",
    "}}",
)


class NativeMetricShadowError(ValueError):
    """Native Metric shadow를 release identity에 안전하게 결속할 수 없음을 알린다."""


def native_metric_path(bundle: Mapping[str, Any]) -> str:
    """Release checksum과 분리된 stable logical Metric namespace를 반환한다."""

    if not isinstance(bundle, Mapping):
        raise NativeMetricShadowError("native Metric bundle is invalid")
    return _STABLE_METRIC_PATH


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
            "expression": native_metric_expression(metric_id, rules),
        }
        yield "metric", urn, "aiContext", native_metric_ai_context(term)
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
        # The approved lifecycle used by Dataset/Glossary is not registered for
        # Metric in pinned v1.7. Metric retirement therefore uses status.removed
        # only; release membership remains in the checksum-bound manifest.
        yield "metric", urn, "status", {"removed": False}
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
        "RUNTIME_PROJECTION_ACTIVATION_REQUIRED",
    ]
    if support_derived:
        blockers.append("SUPPORT_DERIVATION_REMAINS_CANONICAL")
    projection_sha256 = canonical_sha256(aspects)
    metric_urns = sorted(native_metric_urn(bundle, metric_id) for metric_id in public_ids)
    return {
        "contract_version": NATIVE_METRIC_SHADOW_VERSION,
        "datahub_model_version": DATAHUB_NATIVE_MODEL_VERSION,
        "logical_identity_version": NATIVE_METRIC_IDENTITY_VERSION,
        "catalog_version": bundle["catalog_version"],
        "catalog_sha256": catalog_hash(bundle),
        "native_metric_path": native_metric_path(bundle),
        "stable_logical_identity": True,
        "release_membership_mode": "EXTERNAL_CHECKSUM_MANIFEST_PLUS_EXPLICIT_STATUS_FILTER",
        "release_membership_sha256": canonical_sha256(
            {
                "catalog_version": bundle["catalog_version"],
                "catalog_sha256": catalog_hash(bundle),
                "metric_urns": metric_urns,
            }
        ),
        "projection_sha256": projection_sha256,
        "shadow_publishable": True,
        "runtime_cutover_ready": False,
        "runtime_cutover_blockers": blockers,
        "business_metric_count": len(public_ids),
        "support_metric_count": len(support_ids),
        "support_derived_metric_count": support_derived,
        "native_metric_count": len(public_ids),
        "native_ai_context_count": len(public_ids),
        "native_expression_count": len(public_ids),
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


def native_metric_expression(
    metric_id: str,
    rules: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Canonical column/ratio 계약을 pinned MetricInfo ANSI expression으로 투영한다."""

    expression = _metric_sql(metric_id, rules, frozenset())
    if not expression or len(expression) > 2_000:
        raise NativeMetricShadowError("native Metric expression is invalid")
    return {"dialects": [{"dialect": "ANSI_SQL", "expression": expression}]}


def native_metric_ai_context(term: Mapping[str, Any]) -> dict[str, Any]:
    """승인된 Glossary alias만 별도 v1 ``aiContext`` aspect로 투영한다."""

    values = [term.get("name"), term.get("definition"), *term.get("aliases", [])]
    if any(not _safe_native_text(value) for value in values):
        raise NativeMetricShadowError("native Metric text failed the injection Gate")
    aliases = list(term["aliases"])
    if not aliases or len(aliases) > 32 or len(set(aliases)) != len(aliases):
        raise NativeMetricShadowError("native Metric aliases are invalid")
    return {"synonyms": aliases}


def _metric_sql(
    metric_id: str,
    rules: Mapping[str, Mapping[str, Any]],
    visiting: frozenset[str],
) -> str:
    if metric_id in visiting or metric_id not in rules:
        raise NativeMetricShadowError("native Metric expression dependency is invalid")
    metric = rules[metric_id]
    source = metric.get("source")
    if not isinstance(source, Mapping):
        raise NativeMetricShadowError("native Metric expression source is invalid")
    if source.get("kind") == "ratio":
        operands = ratio_operand_ids(metric)
        if operands is None:
            raise NativeMetricShadowError("native Metric ratio expression is invalid")
        numerator, denominator = operands
        nested = visiting | {metric_id}
        return (
            f"({_metric_sql(numerator, rules, nested)}) / "
            f"NULLIF(({_metric_sql(denominator, rules, nested)}), 0)"
        )
    if source.get("kind") != "column":
        raise NativeMetricShadowError("native Metric expression source is unsupported")
    field = source.get("field")
    if not isinstance(field, Mapping):
        raise NativeMetricShadowError("native Metric expression field is invalid")
    reference = _qualified_sql_identifier(field.get("asset_fqn"), field.get("column"))
    aggregation = metric.get("aggregation")
    if aggregation == "none":
        return reference
    if aggregation == "count_distinct":
        return f"COUNT(DISTINCT {reference})"
    function = {
        "sum": "SUM",
        "count": "COUNT",
        "min": "MIN",
        "max": "MAX",
        "average": "AVG",
    }.get(aggregation)
    if function is None:
        raise NativeMetricShadowError("native Metric aggregation is unsupported")
    return f"{function}({reference})"


def _qualified_sql_identifier(asset_fqn: object, column: object) -> str:
    if not isinstance(asset_fqn, str) or not isinstance(column, str):
        raise NativeMetricShadowError("native Metric SQL identifier is invalid")
    parts = [*asset_fqn.split("."), column]
    if len(parts) < 2 or any(not _identifier(part) for part in parts):
        raise NativeMetricShadowError("native Metric SQL identifier is invalid")
    return ".".join(f'"{part}"' for part in parts)


def _safe_native_text(value: object) -> bool:
    if not isinstance(value, str) or value != value.strip() or not value:
        return False
    normalized = " ".join(value.casefold().split())
    if any(marker in normalized for marker in _INJECTION_MARKERS):
        return False
    return not any(
        unicodedata.category(character) == "Cf"
        or (
            unicodedata.category(character) == "Cc"
            and character not in {"\n", "\r", "\t"}
        )
        for character in value
    )


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
