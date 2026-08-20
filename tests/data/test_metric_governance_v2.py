"""일반 v2 Metric visibility·권한·물리 scope·DataHub projection 계약을 검증한다."""

from __future__ import annotations

import json
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

from metadata_aspects import iter_aspects  # noqa: E402
from metadata_contract import (  # noqa: E402
    SemanticMetadataError,
    validate_bundle,
    validate_metric_query_policy,
)
from app.adapters.catalog_snapshot import CatalogSnapshot  # noqa: E402
from app.adapters.datahub_metadata import parse_dataset, parse_glossary_term  # noqa: E402
from app.adapters.release_manifest import validate_release_manifest  # noqa: E402
from src.data.governance_contract import (  # noqa: E402
    dataset_runtime_property_projection,
    release_manifest,
)
from src.data.metric_governance import (  # noqa: E402
    RUNTIME_GOVERNANCE_VERSION_V2,
)
from test_datahub_metadata_publication import (  # noqa: E402
    _aspect_index,
    _graphql_dataset,
    _graphql_term,
    arbitrary_ratio_bundle,
)


def _v2_bundle() -> dict:
    """두 숨은 operand와 공개 ratio를 포함한 schema 독립 v2 release를 만든다."""

    bundle = arbitrary_ratio_bundle()
    metrics = {item["id"]: item for item in bundle["metric_rules"]}
    terms = {item["id"]: item for item in bundle["metric_terms"]}
    assets = {item["fqn"]: item for item in bundle["schema_context"]["assets"]}
    support = {"amount_total", "event_count"}
    for metric in metrics.values():
        source = metric["source"]
        if source["kind"] != "column":
            continue
        asset = assets[source["field"]["asset_fqn"]]
        term = terms.get(metric["id"])
        semantic = (
            {
                "name": term["name"],
                "definition": term["definition"],
                "aliases": deepcopy(term["aliases"]),
            }
            if term is not None and metric["id"] not in support
            else {
                "name": f"Support {metric['id']}",
                "definition": f"Internal executable operand for {metric['id']}.",
                "aliases": [f"Support {metric['id']}", metric["id"]],
            }
        )
        metric["governance"] = {
            "visibility": "SUPPORT" if metric["id"] in support else "BUSINESS",
            "semantic": semantic,
            "grain": {
                "kind": asset["grain"]["kind"],
                "keys": deepcopy(asset["grain"]["keys"]),
                "dimensions": [item["column"] for item in metric["dimensions"]],
            },
            "time": {
                "field": metric["time_field"]["column"],
                "semantics": "event_time",
                "timezone": bundle["time_rules"]["timezone"],
                "interval": "[start,end)",
            },
            "join": {"required": False, "allowed_edge_ids": []},
            "permission": {
                "roles": ["analyst"],
                "contains_pii": False,
                "synthetic": asset["synthetic"],
            },
            "query_strategies": ["RAW_APPROVED_DETAIL"],
        }
    ratio = metrics["amount_per_event"]
    ratio_term = terms[ratio["id"]]
    operand_governance = metrics["amount_total"]["governance"]
    ratio["governance"] = {
        **deepcopy(operand_governance),
        "visibility": "BUSINESS",
        "semantic": {
            "name": ratio_term["name"],
            "definition": ratio_term["definition"],
            "aliases": deepcopy(ratio_term["aliases"]),
        },
    }
    bundle["metric_terms"] = [
        term for term in bundle["metric_terms"] if term["id"] not in support
    ]
    return bundle


def test_v2_support_rules_are_checksum_bound_but_not_glossary_terms() -> None:
    """SUPPORT Rule은 전체 release property에 남고 DataHub Term으로는 발행되지 않는다."""

    bundle = _v2_bundle()
    validate_bundle(bundle)
    manifest = release_manifest(bundle)
    asset = next(
        item
        for item in bundle["schema_context"]["assets"]
        if item["fqn"] == "quartz.core.events"
    )
    properties = dataset_runtime_property_projection(bundle, asset, manifest)

    assert properties["contract_version"] == RUNTIME_GOVERNANCE_VERSION_V2
    assert {item["id"] for item in json.loads(properties["metric_rules"])} == {
        "amount_total",
        "event_count",
        "account_count",
        "amount_per_event",
    }
    assert {item["id"]: item["term_urn"] for item in json.loads(properties["metrics"])} == {
        "amount_total": None,
        "event_count": None,
    }
    assert {item["id"] for item in bundle["metric_terms"]} == {
        "account_count",
        "amount_per_event",
    }


def test_backend_readback_keeps_support_rules_internal() -> None:
    """Backend parser가 v2 전체 registry를 읽되 SUPPORT에 Term을 요구하지 않는다."""

    bundle = _v2_bundle()
    validate_bundle(bundle)
    aspects = _aspect_index(bundle)
    asset = next(
        item
        for item in bundle["schema_context"]["assets"]
        if item["fqn"] == "quartz.core.events"
    )

    parsed = parse_dataset(_graphql_dataset(asset, bundle, aspects))

    assert {item["id"] for item in parsed.metric_rules} == {
        "amount_total",
        "event_count",
        "account_count",
        "amount_per_event",
    }
    local = {item["id"]: item for item in parsed.metrics}
    assert local["amount_total"]["visibility"] == "SUPPORT"
    assert local["amount_total"]["term_urn"] is None
    assert local["event_count"]["visibility"] == "SUPPORT"


def test_backend_manifest_reconstructs_v2_with_hidden_rules() -> None:
    """Runtime catalog hash가 공개 Term만이 아니라 숨은 Rule까지 포함해 일치한다."""

    bundle = _v2_bundle()
    validate_bundle(bundle)
    aspects = _aspect_index(bundle)
    datasets = tuple(
        parse_dataset(_graphql_dataset(asset, bundle, aspects))
        for asset in bundle["schema_context"]["assets"]
    )
    terms = []
    for definition in bundle["metric_terms"]:
        raw = _graphql_term(definition, aspects)
        raw["status"] = {
            "removed": False,
            "lifecycleStage": {
                "urn": definition["approved_lifecycle_urn"],
                "name": "APPROVED",
            },
        }
        terms.append(parse_glossary_term(raw))
    snapshot = CatalogSnapshot(
        datasets_by_urn={item.urn: item for item in datasets},
        datasets_by_fqn={item.fqn: item for item in datasets},
        terms_by_urn={item.urn: item for item in terms},
        terms_by_id={item.id: item for item in terms},
        governance_entities={
            name: tuple(values)
            for name, values in bundle["governance_entities"].items()
        },
    )

    validate_release_manifest(snapshot, datasets)


def test_v2_support_rules_do_not_create_field_term_associations() -> None:
    """숨은 operand가 Dataset field의 사용자 노출 Glossary association으로 새지 않는다."""

    bundle = _v2_bundle()
    aspects = list(iter_aspects(bundle))
    quartz = next(
        value
        for entity, urn, aspect, value in aspects
        if entity == "dataset"
        and urn == bundle["schema_context"]["assets"][0]["urn"]
        and aspect == "editableSchemaMetadata"
    )

    assert all(
        "glossaryTerms" not in item
        for item in quartz["editableSchemaFieldInfo"]
    )


def test_v2_rejects_a_glossary_term_for_support_rule() -> None:
    """지원 operand를 Business Term 수에 끼워 넣어 완료 수치를 부풀리지 못하게 한다."""

    bundle = _v2_bundle()
    support = next(
        term
        for term in arbitrary_ratio_bundle()["metric_terms"]
        if term["id"] == "event_count"
    )
    support_semantic = next(
        item["governance"]["semantic"]
        for item in bundle["metric_rules"]
        if item["id"] == "event_count"
    )
    support.update(deepcopy(support_semantic))
    bundle["metric_terms"].append(support)

    with pytest.raises(SemanticMetadataError, match="exactly cover"):
        validate_bundle(bundle)


def test_v2_rejects_metric_permission_outside_asset_entitlement() -> None:
    """Metric role은 source asset이 허용하지 않은 권한을 새로 만들 수 없다."""

    bundle = _v2_bundle()
    bundle["metric_rules"][0]["governance"]["permission"]["roles"] = ["outsider"]

    with pytest.raises(SemanticMetadataError, match="permission exceeds"):
        validate_bundle(bundle)


def test_v2_rejects_mixed_metric_contract_versions() -> None:
    """동일 release에 v1과 v2 Rule을 섞어 일부 정책을 우회하지 못하게 한다."""

    bundle = _v2_bundle()
    bundle["metric_rules"][0].pop("governance")

    with pytest.raises(SemanticMetadataError, match="cannot mix"):
        validate_bundle(bundle)


def test_v2_rejects_ratio_governance_different_from_operands() -> None:
    """Ratio가 operand와 다른 권한이나 실행 전략으로 계산 범위를 바꾸지 못하게 한다."""

    bundle = _v2_bundle()
    ratio = next(
        item for item in bundle["metric_rules"] if item["id"] == "amount_per_event"
    )
    ratio["governance"]["query_strategies"] = ["VIEW_REUSE"]

    with pytest.raises(SemanticMetadataError, match="must match both"):
        validate_bundle(bundle)


def test_v2_rejects_query_policy_without_ratio_zero_guard_function() -> None:
    """Ratio 규칙은 요구하면서 NULLIF 실행은 금지하는 모순된 release를 거부한다."""

    bundle = _v2_bundle()
    bundle["query_policy"]["allowed_functions"] = [
        item
        for item in bundle["query_policy"]["allowed_functions"]
        if item.casefold() != "nullif"
    ]

    with pytest.raises(SemanticMetadataError, match="does not cover"):
        validate_metric_query_policy(bundle)
