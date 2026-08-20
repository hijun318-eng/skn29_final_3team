"""Metric review 승인 경계가 v2 결정과 checksum receipt를 정확히 만드는지 검증한다."""

from __future__ import annotations

import sys
from copy import deepcopy
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
DATAHUB = ROOT / "infrastructure" / "database" / "datahub"
for entry in (str(ROOT), str(DATAHUB), str(ROOT / "tests" / "data")):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from metadata_contract_primitives import SemanticMetadataError  # noqa: E402
from metric_review_decision import (  # noqa: E402
    APPROVAL_STATUS,
    build_metric_review_approval,
    unwrap_metric_review_approval,
)
from policy_compiler import compile_authoring_policy  # noqa: E402
from release_bundle import ReleaseBinding  # noqa: E402
from semantic_authoring import AUTHORING_CONTRACT_VERSION_V4, assemble_authoring_bundle  # noqa: E402
from src.data.governance_contract import canonical_sha256  # noqa: E402
from test_metric_governance_v2 import _v2_bundle  # noqa: E402
from test_release_bundle_builder import _runtime  # noqa: E402


def _review(bundle: dict) -> dict[str, object]:
    """검증된 v2 fixture의 의미를 review 전용 표현으로 되돌린 일반 후보를 만든다."""

    metrics = []
    rules_by_id = {item["id"]: item for item in bundle["metric_rules"]}
    time_rules = {
        (item["field"]["asset_fqn"], item["field"]["column"]): item
        for item in bundle["time_rules"]["fields"]
    }
    for rule in bundle["metric_rules"]:
        governance = rule["governance"]
        source = rule["source"]
        if source["kind"] == "column":
            review_source = {
                "kind": "COLUMN",
                "asset_fqn": source["field"]["asset_fqn"],
                "column": source["field"]["column"],
            }
            formula = {
                "kind": "COLUMN",
                "aggregation": rule["aggregation"],
                "reduction": rule["reduction"],
            }
        else:
            review_source = {
                "kind": "METRIC_OPERANDS",
                "metric_ids": [
                    source["numerator_metric_id"],
                    source["denominator_metric_id"],
                ],
            }
            formula = {
                "kind": "RATIO",
                "numerator_metric_id": source["numerator_metric_id"],
                "denominator_metric_id": source["denominator_metric_id"],
                "zero_policy": source["zero_policy"],
            }
        physical = (
            source
            if source["kind"] == "column"
            else rules_by_id[source["numerator_metric_id"]]["source"]
        )
        approved_time = time_rules[
            (physical["field"]["asset_fqn"], governance["time"]["field"])
        ]
        metrics.append(
            {
                "id": rule["id"],
                "name": governance["semantic"]["name"],
                "visibility": governance["visibility"],
                "review_status": "REVIEW_REQUIRED",
                "definition": governance["semantic"]["definition"],
                "formula": formula,
                "source": review_source,
                "grain": deepcopy(governance["grain"]),
                "time": {
                    **deepcopy(governance["time"]),
                    "bucket": approved_time["bucket"],
                    "timezone_mode": approved_time["timezone_mode"],
                },
                "join": deepcopy(governance["join"]),
                "aliases": deepcopy(governance["semantic"]["aliases"][1:]),
                "permission": deepcopy(governance["permission"]),
                "unit": rule["unit"],
                "result_field": rule["result_field"],
                "query_strategies": deepcopy(governance["query_strategies"]),
            }
        )
    return {
        "contract_version": "answervice.metric_review.v1",
        "review_status": "REVIEW_REQUIRED",
        "release_id": "arbitrary-reviewed-release",
        "serving_schema": "quartz.core",
        "source_sql_sha256": "a" * 64,
        "business_metric_target_count": 2,
        "allowed_roles": ["analyst"],
        "review_owner_candidate_urn": "urn:li:corpGroup:quartz_stewards",
        "metrics": metrics,
    }


def _validation(review: dict[str, object]) -> dict[str, object]:
    return {
        "status": "VALID_REVIEW_DRAFT",
        "candidate_sha256": canonical_sha256(review),
        "approval_status": "NOT_APPROVED",
        "publishable": False,
    }


def _approval() -> tuple[dict, dict]:
    baseline = _v2_bundle()
    review = _review(baseline)
    approval = build_metric_review_approval(
        review,
        _validation(review),
        baseline,
        catalog_version="catalog-r10-runtime-v2",
        policy_version="policy-r6-runtime-v2",
        schema_context_version="context-r10-runtime-v2",
        schema_version="schema-r10-runtime-v2",
        seed_version="seed-r3-runtime-v2",
        glossary_version="glossary-r4-runtime-v2",
    )
    return approval, baseline


def test_review_approval_compiles_business_terms_and_hidden_support_rules() -> None:
    """BUSINESS만 Term이 되고 SUPPORT operand는 실행 Rule에만 남는다."""

    approval, baseline = _approval()
    decision = unwrap_metric_review_approval(approval)
    _scopes, inventory, datasets, _terms = _runtime(baseline)
    by_name = {item.name: item for item in datasets}
    bindings = tuple(
        ReleaseBinding(relation, by_name[relation.fqn])
        for relation in inventory.relations
    )

    policy = compile_authoring_policy(decision, bindings)
    target = assemble_authoring_bundle(policy, bindings)

    assert approval["status"] == APPROVAL_STATUS
    assert policy["contract_version"] == AUTHORING_CONTRACT_VERSION_V4
    assert approval["business_metric_ids"] == ["account_count", "amount_per_event"]
    assert approval["support_metric_ids"] == ["amount_total", "event_count"]
    assert {item["id"] for item in target["metric_rules"]} == {
        "account_count",
        "amount_per_event",
        "amount_total",
        "event_count",
    }
    assert {item["id"] for item in target["metric_terms"]} == {
        "account_count",
        "amount_per_event",
    }
    assert all(
        item["governance"]["semantic"]["name"]
        in item["governance"]["semantic"]["aliases"]
        for item in target["metric_rules"]
    )
    assert "nullif" in policy["query_policy"]["allowed_functions"]


def test_review_approval_blocks_implicit_removal_and_live_scope_drift() -> None:
    """기존 공개 기능 제거와 live baseline 밖 물리 참조는 승격 전에 실패한다."""

    baseline = _v2_bundle()
    review = _review(baseline)
    review["metrics"] = [
        item for item in review["metrics"] if item["id"] != "account_count"
    ]
    with pytest.raises(SemanticMetadataError, match="retirement decision"):
        build_metric_review_approval(
            review,
            _validation(review),
            baseline,
            catalog_version="catalog-r10",
            policy_version="policy-r6",
            schema_context_version="context-r10",
            schema_version="schema-r10",
            seed_version="seed-r3",
            glossary_version="glossary-r4",
        )

    review = _review(baseline)
    column = next(
        item for item in review["metrics"] if item["source"]["kind"] == "COLUMN"
    )
    column["source"]["asset_fqn"] = "unknown.core.missing"
    with pytest.raises(SemanticMetadataError, match="live baseline scope"):
        build_metric_review_approval(
            review,
            _validation(review),
            baseline,
            catalog_version="catalog-r10",
            policy_version="policy-r6",
            schema_context_version="context-r10",
            schema_version="schema-r10",
            seed_version="seed-r3",
            glossary_version="glossary-r4",
        )


def test_approval_receipt_rejects_decision_or_scope_tampering() -> None:
    """승인 후 decision 또는 노출 scope 수정은 receipt checksum으로 거부한다."""

    approval, _baseline = _approval()
    changed = deepcopy(approval)
    changed["decision"]["metric_rules"][0]["unit"] = "changed"
    with pytest.raises(SemanticMetadataError, match="checksum differs"):
        unwrap_metric_review_approval(changed)

    changed = deepcopy(approval)
    changed["support_metric_ids"].reverse()
    with pytest.raises(SemanticMetadataError, match="Metric scope differs"):
        unwrap_metric_review_approval(changed)
