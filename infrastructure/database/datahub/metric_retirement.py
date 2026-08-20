"""승인된 제품 범위 축소를 기존 semantic release의 추적 가능한 폐기로 변환한다.

이 모듈은 호텔 Metric 이름이나 데모 질문을 알지 못한다. 현재 검증된 release와
명시적인 retirement decision만 받아 dependency closure를 검사하고, 물리 schema는
그대로 둔 채 Metric Rule·Glossary Term membership만 제거한 다음 release를 재검증한다.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from copy import deepcopy
from datetime import datetime
from typing import Any

from metadata_contract import validate_bundle
from metadata_contract_primitives import (
    SemanticMetadataError,
    array,
    exact_keys,
    mapping,
    text,
)
from src.data.governance_contract import (
    canonical_sha256,
    catalog_hash,
    ratio_operand_ids,
)
from src.data.metric_governance import metric_visibility


RETIREMENT_DECISION_VERSION = "answervice.metric_retirement_decision.v1"
RETIREMENT_CHECK_VERSION = "answervice.metric_retirement_check.v1"
APPROVED_DECISION_STATUS = "APPROVED"
AUTHORIZATION_BASIS = "EXPLICIT_PRODUCT_SCOPE_DECISION"

_DECISION_KEYS = frozenset(
    {
        "contract_version",
        "decision_id",
        "decision_status",
        "authorization_basis",
        "authorized_by",
        "recorded_at",
        "reason",
        "previous_catalog_version",
        "previous_catalog_sha256",
        "target_catalog_version",
        "retirements",
    }
)
_RETIREMENT_KEYS = frozenset({"metric_id", "term_urn"})
_SHA256 = re.compile(r"[0-9a-f]{64}")


def validate_retirement_decision(value: object) -> dict[str, Any]:
    """폐기 대상을 release·Term URN·승인 근거에 결속하고 정규화한다."""

    decision = mapping(value, "metric retirement decision")
    exact_keys(decision, _DECISION_KEYS, "metric retirement decision")
    if decision.get("contract_version") != RETIREMENT_DECISION_VERSION:
        raise SemanticMetadataError("metric retirement decision version is unsupported")
    if decision.get("decision_status") != APPROVED_DECISION_STATUS:
        raise SemanticMetadataError("metric retirement decision is not approved")
    if decision.get("authorization_basis") != AUTHORIZATION_BASIS:
        raise SemanticMetadataError("metric retirement authorization basis is unsupported")

    decision_id = _bounded_text(decision.get("decision_id"), "decision id", 128)
    authorized_by = _bounded_text(
        decision.get("authorized_by"), "retirement authority", 255
    )
    reason = _bounded_text(decision.get("reason"), "retirement reason", 1_000)
    recorded_at = _aware_datetime(decision.get("recorded_at"))
    previous_version = _bounded_text(
        decision.get("previous_catalog_version"), "previous catalog version", 255
    )
    target_version = _bounded_text(
        decision.get("target_catalog_version"), "target catalog version", 255
    )
    if target_version == previous_version:
        raise SemanticMetadataError("retirement target must be a new catalog version")
    previous_sha256 = text(
        decision.get("previous_catalog_sha256"), "previous catalog checksum"
    )
    if _SHA256.fullmatch(previous_sha256) is None:
        raise SemanticMetadataError("previous catalog checksum must be lowercase SHA-256")

    retirements = []
    for index, raw in enumerate(
        array(decision.get("retirements"), "metric retirements", non_empty=True, limit=64)
    ):
        item = mapping(raw, f"metric retirements[{index}]")
        exact_keys(item, _RETIREMENT_KEYS, f"metric retirements[{index}]")
        metric_id = text(item.get("metric_id"), f"metric retirements[{index}].metric_id")
        term_urn = text(item.get("term_urn"), f"metric retirements[{index}].term_urn")
        if (
            not metric_id.isascii()
            or not metric_id.isidentifier()
            or not term_urn.startswith("urn:li:glossaryTerm:")
        ):
            raise SemanticMetadataError("metric retirement identity is invalid")
        retirements.append({"metric_id": metric_id, "term_urn": term_urn})
    if (
        len({item["metric_id"] for item in retirements}) != len(retirements)
        or len({item["term_urn"] for item in retirements}) != len(retirements)
        or retirements != sorted(retirements, key=lambda item: item["metric_id"])
    ):
        raise SemanticMetadataError(
            "metric retirements must have unique identities in metric id order"
        )

    return {
        "contract_version": RETIREMENT_DECISION_VERSION,
        "decision_id": decision_id,
        "decision_status": APPROVED_DECISION_STATUS,
        "authorization_basis": AUTHORIZATION_BASIS,
        "authorized_by": authorized_by,
        "recorded_at": recorded_at,
        "reason": reason,
        "previous_catalog_version": previous_version,
        "previous_catalog_sha256": previous_sha256,
        "target_catalog_version": target_version,
        "retirements": retirements,
    }


def build_retired_release(
    baseline_bundle: Mapping[str, Any],
    decision_value: object,
) -> dict[str, Any]:
    """검증된 baseline에서 승인된 BUSINESS Metric과 Term만 제거한 새 release를 만든다."""

    validate_bundle(baseline_bundle)
    decision = validate_retirement_decision(decision_value)
    if (
        baseline_bundle.get("catalog_version")
        != decision["previous_catalog_version"]
        or catalog_hash(baseline_bundle) != decision["previous_catalog_sha256"]
    ):
        raise SemanticMetadataError(
            "metric retirement decision does not match the live baseline release"
        )

    rules = _by_id(baseline_bundle.get("metric_rules"), "baseline metric rules")
    terms = _by_id(baseline_bundle.get("metric_terms"), "baseline metric terms")
    retirements = {item["metric_id"]: item["term_urn"] for item in decision["retirements"]}
    target_ids = set(retirements)
    if not target_ids < set(rules):
        raise SemanticMetadataError(
            "retirement targets must be a proper subset of baseline metrics"
        )
    for metric_id in sorted(target_ids):
        rule = rules[metric_id]
        if metric_visibility(rule) != "BUSINESS":
            raise SemanticMetadataError("only BUSINESS metrics may be retired")
        term = terms.get(metric_id)
        if term is None or term.get("urn") != retirements[metric_id]:
            raise SemanticMetadataError(
                "retirement Metric and Glossary Term identities differ"
            )

    for metric_id, rule in rules.items():
        if metric_id in target_ids:
            continue
        operands = ratio_operand_ids(rule)
        if operands is not None and target_ids.intersection(operands):
            raise SemanticMetadataError(
                "retirement set leaves a retained ratio with a removed operand"
            )

    result = deepcopy(dict(baseline_bundle))
    result["catalog_version"] = decision["target_catalog_version"]
    result["metric_rules"] = [
        deepcopy(rule)
        for metric_id, rule in sorted(rules.items())
        if metric_id not in target_ids
    ]
    result["metric_terms"] = [
        deepcopy(term)
        for metric_id, term in sorted(terms.items())
        if metric_id not in target_ids
    ]
    validate_bundle(result)
    if result["schema_context"] != baseline_bundle["schema_context"]:
        raise SemanticMetadataError("metric retirement must not change physical schema")
    return result


def metric_retirement_check(
    baseline_bundle: Mapping[str, Any],
    decision_value: object,
) -> dict[str, Any]:
    """operator가 check 결과의 predecessor·target·decision checksum을 publish에 전달하게 한다."""

    decision = validate_retirement_decision(decision_value)
    target = build_retired_release(baseline_bundle, decision)
    return {
        "contract_version": RETIREMENT_CHECK_VERSION,
        "status": "CHECKED",
        "decision_id": decision["decision_id"],
        "decision_sha256": canonical_sha256(decision),
        "previous_catalog_version": decision["previous_catalog_version"],
        "previous_catalog_sha256": decision["previous_catalog_sha256"],
        "target_catalog_version": decision["target_catalog_version"],
        "target_catalog_sha256": catalog_hash(target),
        "retirement_metric_ids": [
            item["metric_id"] for item in decision["retirements"]
        ],
        "retirement_term_urns": [
            item["term_urn"] for item in decision["retirements"]
        ],
        "baseline_metric_count": len(baseline_bundle["metric_rules"]),
        "target_metric_count": len(target["metric_rules"]),
        "ready_to_publish": True,
    }


def _by_id(value: object, context: str) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for index, raw in enumerate(array(value, context, non_empty=True, limit=64)):
        item = mapping(raw, f"{context}[{index}]")
        metric_id = text(item.get("id"), f"{context}[{index}].id")
        if metric_id in result:
            raise SemanticMetadataError(f"{context} contains duplicate ids")
        result[metric_id] = item
    return result


def _bounded_text(value: object, context: str, maximum: int) -> str:
    result = text(value, context)
    if len(result) > maximum:
        raise SemanticMetadataError(f"{context} is too long")
    return result


def _aware_datetime(value: object) -> str:
    result = text(value, "retirement recorded_at")
    try:
        parsed = datetime.fromisoformat(result)
    except ValueError as error:
        raise SemanticMetadataError("retirement recorded_at must be ISO-8601") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise SemanticMetadataError("retirement recorded_at must include a timezone")
    return result
