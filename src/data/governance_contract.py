"""publisher와 runtime이 동일하게 계산하는 DataHub release projection·checksum 계약을 정의한다."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from src.data.metric_governance import (
    DATASET_RUNTIME_PROPERTY_KEYS,
    RATIO_ZERO_POLICIES,
    RUNTIME_GOVERNANCE_VERSION,
    RUNTIME_GOVERNANCE_VERSION_V2,
    TERM_RUNTIME_PROPERTY_KEYS,
    business_metric_ids,
    dataset_runtime_property_keys,
    runtime_governance_version,
)


SEMANTIC_RELEASE_KEYS = frozenset(
    {
        "catalog_version",
        "policy_version",
        "governance_entities",
        "schema_context",
        "metric_rules",
        "metric_terms",
        "dimensions",
        "join_graph",
        "time_rules",
        "parameter_contract",
        "query_policy",
    }
)


RELEASE_MANIFEST_KEYS = frozenset(
    {
        "catalog_version",
        "catalog_sha256",
        "glossary_sha256",
        "datasets",
        "metric_terms",
        "dataset_count",
        "column_count",
        "metric_term_count",
        "shared_semantic_sha256",
    }
)
DATASET_MANIFEST_KEYS = frozenset(
    {
        "urn",
        "fqn",
        "schema_sha1",
        "table_type",
        "trino_schema_sha256",
        "semantic_sha256",
        "column_count",
    }
)
TERM_MANIFEST_KEYS = frozenset({"id", "urn", "semantic_sha256"})
def canonical_json(value: object) -> str:
    """Unicode를 보존하고 key를 정렬한 공백 없는 JSON으로 직렬화해 환경과 무관한 hash 입력을 만든다."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def canonical_sha256(value: object) -> str:
    """canonical JSON의 UTF-8 bytes를 SHA-256으로 요약해 publisher/runtime 비교용 fingerprint를 만든다."""
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


sha256 = canonical_sha256


def datahub_schema_projection(asset: Mapping[str, Any]) -> list[dict[str, Any]]:
    """asset column에서 DataHub schema hash 계약에 포함되는 이름·순서·native type·nullable만 투영한다."""
    return [
        {
            "name": column["name"],
            "ordinal_position": column["ordinal_position"],
            "native_type": column["native_type"],
            "nullable": column["nullable"],
        }
        for column in asset["columns"]
    ]


def datahub_schema_sha1(asset: Mapping[str, Any]) -> str:
    """asset 형식의 DataHub field projection을 SHA-1 fingerprint로 계산한다."""

    return datahub_schema_readback_sha1(datahub_schema_projection(asset))


def datahub_schema_readback_sha1(fields: list[Mapping[str, Any]]) -> str:
    """connector가 반환한 field 순서·원본 타입·nullable의 독립 fingerprint를 만든다.

    DataHub connector에 따라 ``schemaMetadata.hash``가 비어 있을 수 있으므로 그 값을
    성공 조건으로 사용하지 않는다. 호출자는 실제 GraphQL field read-back을 이 공통
    shape로 투영해야 하며, Trino 실행 타입 fingerprint는 별도로 계산한다.
    """

    projection = [
        {
            "name": field["name"],
            "ordinal_position": field["ordinal_position"],
            "native_type": field["native_type"],
            "nullable": field["nullable"],
        }
        for field in fields
    ]
    payload = canonical_json(projection).encode("utf-8")
    # SHA-1은 외부 DataHub wire contract 호환용 식별자이며 release 무결성은 별도의 SHA-256이 담당한다.
    return hashlib.sha1(payload, usedforsecurity=False).hexdigest()


def trino_schema_projection(asset: Mapping[str, Any]) -> dict[str, Any]:
    """FQN·table type·ordinal 순 column을 live ``information_schema``와 같은 canonical shape로 투영한다."""

    return {
        "fqn": asset["fqn"],
        "table_type": asset["table_type"],
        "columns": [
            {
                "ordinal_position": column["ordinal_position"],
                "name": column["name"],
                "native_type": column["native_type"],
                "nullable": column["nullable"],
            }
            for column in asset["columns"]
        ],
    }


def trino_schema_sha256(asset: Mapping[str, Any]) -> str:
    """Trino relation projection을 SHA-256으로 요약해 배포 뒤 schema drift를 검출할 fingerprint를 만든다."""
    return canonical_sha256(trino_schema_projection(asset))


trino_schema_hash = trino_schema_sha256


def asset_semantic_projection(
    bundle: Mapping[str, Any],
    asset: Mapping[str, Any],
) -> dict[str, Any]:
    """한 asset과 그 FQN을 source로 삼는 metric rule만 정렬해 asset 단위 semantic identity를 만든다."""
    metrics = sorted(
        (
            metric
            for metric in bundle["metric_rules"]
            if column_metric_asset(metric) == asset["fqn"]
        ),
        key=lambda item: item["id"],
    )
    return {
        "asset": asset,
        "metric_rules": sorted(metrics, key=lambda item: item["id"]),
    }


def asset_semantic_sha256(
    bundle: Mapping[str, Any],
    asset: Mapping[str, Any],
) -> str:
    """asset 단위 semantic projection의 SHA-256을 계산해 부분 변조와 release 교체를 검출한다."""
    return canonical_sha256(asset_semantic_projection(bundle, asset))


asset_semantic_hash = asset_semantic_sha256


def shared_semantic_projection(bundle: Mapping[str, Any]) -> dict[str, Any]:
    """release 공통 version·native governance·dimension·join·time·parameter·query policy를 canonical 순서로 투영한다."""
    governance = bundle["governance_entities"]
    return {
        "catalog_version": bundle["catalog_version"],
        "policy_version": bundle["policy_version"],
        "schema_context_version": bundle["schema_context"]["version"],
        "governance_entities": {
            name: sorted(
                (dict(item) for item in governance[name]),
                key=lambda item: item["urn"],
            )
            for name in governance
        },
        "dimensions": sorted(bundle["dimensions"], key=lambda item: item["id"]),
        "join_graph": {
            "edges": sorted(bundle["join_graph"]["edges"], key=lambda item: item["id"])
        },
        "time_rules": bundle["time_rules"],
        "parameter_contract": {
            "style": bundle["parameter_contract"]["style"],
            "parameters": sorted(
                bundle["parameter_contract"]["parameters"], key=lambda item: item["name"]
            ),
        },
        "query_policy": bundle["query_policy"],
    }


def validate_governance_reference_coverage(bundle: Mapping[str, Any]) -> None:
    """공개 governance URN 집합이 asset·term의 실제 owner·domain·lifecycle 참조와 정확히 같은지 검증한다."""

    governed = [
        *bundle["schema_context"]["assets"],
        *bundle["metric_terms"],
    ]
    references = {
        "owners": {item["owner_urn"] for item in governed},
        "domains": {item["domain_urn"] for item in governed},
        "approved_lifecycles": {
            item["approved_lifecycle_urn"] for item in governed
        },
    }
    for kind, observed in references.items():
        declared = {item["urn"] for item in bundle["governance_entities"][kind]}
        # 부분집합 검사는 미사용 승인 주체를 release에 끼워 넣을 수 있으므로 양방향 exact coverage를 요구한다.
        if declared != observed:
            raise ValueError(
                f"governance_entities.{kind} must exactly match referenced URNs"
            )


def glossary_projection(bundle: Mapping[str, Any]) -> list[dict[str, Any]]:
    """metric term을 URN 순서로 복사해 glossary checksum의 결정론적 입력을 만든다."""
    return sorted(
        (dict(item) for item in bundle["metric_terms"]),
        key=lambda item: item["urn"],
    )


def glossary_sha256(bundle: Mapping[str, Any]) -> str:
    """정렬된 glossary projection의 SHA-256을 계산해 정의·alias·governance 변경을 추적한다."""
    return canonical_sha256(glossary_projection(bundle))


glossary_hash = glossary_sha256


def catalog_projection(bundle: Mapping[str, Any]) -> dict[str, Any]:
    """공통 semantic, URN 순 asset semantic, metric id/URN 참조를 결합해 전체 catalog identity를 만든다."""
    return {
        "shared": shared_semantic_projection(bundle),
        "assets": [
            asset_semantic_projection(bundle, asset)
            for asset in sorted(
                bundle["schema_context"]["assets"], key=lambda item: item["urn"]
            )
        ],
        "metric_term_refs": sorted(
            ({"id": item["id"], "urn": item["urn"]} for item in bundle["metric_terms"]),
            key=lambda item: item["urn"],
        ),
        "derived_metric_rules": sorted(
            (
                dict(metric)
                for metric in bundle["metric_rules"]
                if metric_source_kind(metric) == "ratio"
            ),
            key=lambda item: item["id"],
        ),
    }


def catalog_sha256(bundle: Mapping[str, Any]) -> str:
    """전체 catalog projection을 SHA-256으로 요약해 모든 runtime 엔터티가 공유할 release fingerprint를 만든다."""
    return canonical_sha256(catalog_projection(bundle))


catalog_hash = catalog_sha256


def release_manifest(bundle: Mapping[str, Any]) -> dict[str, Any]:
    """dataset·term별 fingerprint와 전체 count·공통 hash를 계산해 완전 readback 검증용 manifest를 만든다."""
    assets = bundle["schema_context"]["assets"]
    manifest = {
        "catalog_version": bundle["catalog_version"],
        "catalog_sha256": catalog_sha256(bundle),
        "glossary_sha256": glossary_sha256(bundle),
        "datasets": [
            {
                "urn": asset["urn"],
                "fqn": asset["fqn"],
                "schema_sha1": asset["datahub_schema_hash"],
                "table_type": asset["table_type"],
                "trino_schema_sha256": trino_schema_sha256(asset),
                "semantic_sha256": asset_semantic_sha256(bundle, asset),
                "column_count": len(asset["columns"]),
            }
            for asset in sorted(assets, key=lambda item: item["urn"])
        ],
        "metric_terms": [
            {
                "id": term["id"],
                "urn": term["urn"],
                "semantic_sha256": canonical_sha256(term),
            }
            for term in glossary_projection(bundle)
        ],
        "dataset_count": len(assets),
        "column_count": sum(len(asset["columns"]) for asset in assets),
        "metric_term_count": len(bundle["metric_terms"]),
        "shared_semantic_sha256": canonical_sha256(
            shared_semantic_projection(bundle)
        ),
    }
    # manifest field를 exact set으로 고정해야 publisher/runtime version drift가 조용히 무시되지 않는다.
    _require_exact_keys(manifest, RELEASE_MANIFEST_KEYS, "release manifest")
    for item in manifest["datasets"]:
        _require_exact_keys(item, DATASET_MANIFEST_KEYS, "dataset manifest entry")
    for item in manifest["metric_terms"]:
        _require_exact_keys(item, TERM_MANIFEST_KEYS, "term manifest entry")
    return manifest


def manifest_sha256(bundle: Mapping[str, Any]) -> str:
    """계산된 release manifest 자체의 SHA-256을 반환해 DataHub 엔터티별 복제본이 동일한지 확인하게 한다."""
    return canonical_sha256(release_manifest(bundle))


def shared_semantic_hash(bundle: Mapping[str, Any]) -> str:
    """release 공통 정책 projection만 SHA-256으로 요약해 asset별 의미와 독립된 변경 증거를 만든다."""
    return canonical_sha256(shared_semantic_projection(bundle))


def dataset_runtime_property_projection(
    bundle: Mapping[str, Any],
    asset: Mapping[str, Any],
    manifest: Mapping[str, Any],
) -> dict[str, str]:
    """검증 bundle·asset·manifest를 DataHub dataset에 기록할 정확한 unprefixed 문자열 속성으로 직렬화한다."""

    version = runtime_governance_version(bundle)
    all_metrics = list(bundle["metric_rules"])
    metrics = sorted(
        (
            metric
            for metric in all_metrics
            if column_metric_asset(metric) == asset["fqn"]
        ),
        key=lambda item: item["id"],
    )
    terms = {item["id"]: item for item in bundle["metric_terms"]}
    business_ids = business_metric_ids(all_metrics)
    runtime_metrics = [
        {
            "id": metric["id"],
            "term_urn": (
                terms[metric["id"]]["urn"]
                if metric["id"] in business_ids
                else None
            ),
            "field": metric["source"]["field"]["column"],
            "aggregation": metric["aggregation"],
            "time_field": metric["time_field"]["column"],
            "result_field": metric["result_field"],
            "reduction": metric["reduction"],
            "dimensions": metric["dimensions"],
            "required_filters": [
                {
                    "field": item["field"]["column"],
                    "operator": item["operator"],
                    "parameter": item["parameter"],
                }
                for item in metric["required_filters"]
            ],
        }
        for metric in metrics
    ]
    governance_entities = shared_semantic_projection(bundle)["governance_entities"]
    governance_urns = {
        name: [item["urn"] for item in values]
        for name, values in governance_entities.items()
    }
    result = {
        "contract_version": version,
        "approval_status": str(asset["approval_status"]),
        "catalog_version": str(bundle["catalog_version"]),
        "catalog_sha256": str(manifest["catalog_sha256"]),
        "schema_context_version": str(bundle["schema_context"]["version"]),
        "governance_urns": canonical_json(governance_urns),
        "release_manifest": canonical_json(manifest),
        "manifest_sha256": canonical_sha256(manifest),
        "fqn": str(asset["fqn"]),
        "policy_version": str(bundle["policy_version"]),
        "schema_version": str(asset["schema_version"]),
        "seed_version": str(asset["seed_version"]),
        "synthetic": canonical_json(asset["synthetic"]),
        "entitlements": canonical_json(asset["entitlements"]),
        "grain": canonical_json(asset["grain"]),
        "typed_columns": canonical_json(asset["columns"]),
        "column_roles": canonical_json(
            {column["name"]: column["role"] for column in asset["columns"]}
        ),
        "metrics": canonical_json(runtime_metrics),
        "dimensions": canonical_json(bundle["dimensions"]),
        "join_graph": canonical_json(bundle["join_graph"]),
        "time_rules": canonical_json(bundle["time_rules"]),
        "parameter_contract": canonical_json(bundle["parameter_contract"]),
        "query_policy": canonical_json(bundle["query_policy"]),
    }
    if version == RUNTIME_GOVERNANCE_VERSION_V2:
        result["metric_rules"] = canonical_json(
            sorted(all_metrics, key=lambda item: item["id"])
        )
    _require_exact_keys(
        result,
        dataset_runtime_property_keys(version),
        "dataset properties",
    )
    return result


def term_runtime_property_projection(
    term: Mapping[str, Any],
    metric: Mapping[str, Any],
    manifest: Mapping[str, Any],
) -> dict[str, str]:
    """term·metric·manifest를 DataHub Glossary Term에 기록할 정확한 unprefixed 문자열 속성으로 직렬화한다."""

    result = {
        "metric_id": str(term["id"]),
        "aliases": canonical_json(term["aliases"]),
        "approval_status": str(term["approval_status"]),
        "catalog_sha256": str(manifest["catalog_sha256"]),
        "glossary_sha256": str(manifest["glossary_sha256"]),
        "glossary_version": str(term["version"]),
        "metric_rule": canonical_json(metric),
        "unit": str(term["unit"]),
    }
    _require_exact_keys(result, TERM_RUNTIME_PROPERTY_KEYS, "term properties")
    return result


def _require_exact_keys(
    value: Mapping[str, Any], expected: frozenset[str], name: str
) -> None:
    if set(value) != expected:
        raise ValueError(f"{name} keys differ from the canonical governance contract")


def metric_source_kind(metric: Mapping[str, Any]) -> str:
    """검증 전후 metric rule에서 source kind를 부작용 없이 읽는다."""

    source = metric.get("source")
    return str(source.get("kind")) if isinstance(source, Mapping) else ""


def column_metric_asset(metric: Mapping[str, Any]) -> str | None:
    """column metric이 직접 측정하는 asset FQN을 반환하고 derived/invalid rule은 ``None``으로 둔다."""

    source = metric.get("source")
    field = source.get("field") if isinstance(source, Mapping) else None
    if (
        not isinstance(source, Mapping)
        or source.get("kind") != "column"
        or not isinstance(field, Mapping)
    ):
        return None
    value = field.get("asset_fqn")
    return str(value) if isinstance(value, str) else None


def ratio_operand_ids(metric: Mapping[str, Any]) -> tuple[str, str] | None:
    """ratio metric의 서로 다른 분자·분모 metric id를 반환하며 불완전한 참조는 거부 표식으로 둔다."""

    source = metric.get("source")
    if not isinstance(source, Mapping) or source.get("kind") != "ratio":
        return None
    numerator = source.get("numerator_metric_id")
    denominator = source.get("denominator_metric_id")
    if (
        not isinstance(numerator, str)
        or not numerator
        or not isinstance(denominator, str)
        or not denominator
        or numerator == denominator
    ):
        return None
    return numerator, denominator


def metric_asset_fqns(
    metric: Mapping[str, Any],
    metrics_by_id: Mapping[str, Mapping[str, Any]],
) -> frozenset[str]:
    """column metric의 직접 asset 또는 ratio operand가 측정하는 asset 집합을 projection 연결용으로 반환한다."""

    direct = column_metric_asset(metric)
    if direct is not None:
        return frozenset({direct})
    operands = ratio_operand_ids(metric)
    if operands is None:
        return frozenset()
    resolved = tuple(
        column_metric_asset(metrics_by_id.get(operand, {})) for operand in operands
    )
    if any(asset is None for asset in resolved):
        return frozenset()
    return frozenset(str(asset) for asset in resolved)


MANIFEST_KEYS = RELEASE_MANIFEST_KEYS
MANIFEST_DATASET_KEYS = DATASET_MANIFEST_KEYS
MANIFEST_TERM_KEYS = TERM_MANIFEST_KEYS
DATASET_PROPERTY_KEYS = DATASET_RUNTIME_PROPERTY_KEYS
TERM_PROPERTY_KEYS = TERM_RUNTIME_PROPERTY_KEYS
