"""승인 전 Metric 검토안과 현재 live semantic release의 공개 기능 차이를 계산한다.

이 모듈은 Metric 이름이나 제품 시나리오를 알지 못한다. 검증된 review candidate와
DataHub·Trino에서 재구성한 현재 release만 비교하며, 기존 BUSINESS Metric이 후보에서
사라지거나 SUPPORT로 바뀌면 명시적인 폐기 결정 전까지 다음 authoring 단계를 막는다.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from metadata_contract import validate_bundle
from metadata_contract_primitives import SemanticMetadataError, array, mapping, text
from src.data.governance_contract import canonical_sha256, catalog_hash
from src.data.metric_governance import metric_visibility


TRANSITION_CONTRACT_VERSION = "answervice.metric_review_transition.v1"
READY_STATUS = "READY_FOR_POLICY_DECISION"
DEPRECATION_REVIEW_STATUS = "DEPRECATION_REVIEW_REQUIRED"


def plan_metric_review_transition(
    review: Mapping[str, Any],
    review_validation: Mapping[str, Any],
    baseline_bundle: Mapping[str, Any],
) -> dict[str, object]:
    """검토 후보가 현재 공개 Metric을 암묵적으로 제거하는지 계산한다.

    ``review_validation``은 ``validate_metric_review``의 결과여야 한다. 현재 bundle은
    publication contract 전체를 다시 검증한 뒤 사용한다. 반환값은 변경 계획일 뿐
    승인이나 발행 권한을 만들지 않으며 ``publishable``은 항상 ``False``다.
    """

    candidate = mapping(review, "metric review")
    validation = mapping(review_validation, "metric review validation")
    if (
        validation.get("status") != "VALID_REVIEW_DRAFT"
        or validation.get("approval_status") != "NOT_APPROVED"
        or validation.get("publishable") is not False
    ):
        raise SemanticMetadataError(
            "metric transition requires one validated non-publishable review draft"
        )
    candidate_sha256 = text(
        validation.get("candidate_sha256"), "metric review candidate checksum"
    )
    if candidate_sha256 != canonical_sha256(candidate):
        raise SemanticMetadataError(
            "metric review validation does not match the candidate content"
        )

    # Live discovery already validates this bundle. Re-validating at this boundary keeps
    # the pure function fail-closed when reused by another operator or test harness.
    validate_bundle(baseline_bundle)
    baseline_rules = _rules_by_id(
        baseline_bundle.get("metric_rules"), "baseline metric rules"
    )
    candidate_rules = _review_metrics_by_id(candidate.get("metrics"))
    baseline_business = {
        metric_id
        for metric_id, rule in baseline_rules.items()
        if _visibility(rule, f"baseline metric[{metric_id}]") == "BUSINESS"
    }
    candidate_business = {
        metric_id
        for metric_id, rule in candidate_rules.items()
        if rule.get("visibility") == "BUSINESS"
    }
    candidate_support = set(candidate_rules) - candidate_business
    retirement_candidates = baseline_business - candidate_business
    visibility_changes = baseline_business & candidate_support
    status = (
        DEPRECATION_REVIEW_STATUS if retirement_candidates else READY_STATUS
    )
    return {
        "contract_version": TRANSITION_CONTRACT_VERSION,
        "status": status,
        "candidate_sha256": candidate_sha256,
        "baseline_catalog_version": text(
            baseline_bundle.get("catalog_version"), "baseline catalog version"
        ),
        "baseline_catalog_sha256": catalog_hash(baseline_bundle),
        "baseline_business_metric_count": len(baseline_business),
        "candidate_business_metric_count": len(candidate_business),
        "candidate_support_metric_count": len(candidate_support),
        "added_business_metric_ids": sorted(candidate_business - baseline_business),
        "retained_business_metric_ids": sorted(candidate_business & baseline_business),
        "retirement_candidate_ids": sorted(retirement_candidates),
        "visibility_change_candidate_ids": sorted(visibility_changes),
        "approval_status": "NOT_APPROVED",
        "publishable": False,
    }


def _rules_by_id(value: object, context: str) -> dict[str, Mapping[str, Any]]:
    """검증된 release Rule을 중복 없는 ID map으로 정규화한다."""

    result: dict[str, Mapping[str, Any]] = {}
    for index, raw in enumerate(array(value, context, non_empty=True, limit=64)):
        rule = mapping(raw, f"{context}[{index}]")
        metric_id = text(rule.get("id"), f"{context}[{index}].id")
        if metric_id in result:
            raise SemanticMetadataError("metric transition input contains duplicate ids")
        result[metric_id] = rule
    return result


def _review_metrics_by_id(value: object) -> dict[str, Mapping[str, Any]]:
    """review Metric의 visibility를 확인하고 ID map을 반환한다."""

    rules = _rules_by_id(value, "candidate metrics")
    if any(rule.get("visibility") not in {"BUSINESS", "SUPPORT"} for rule in rules.values()):
        raise SemanticMetadataError("metric review visibility is unsupported")
    return rules


def _visibility(rule: Mapping[str, Any], context: str) -> str:
    """v1/v2 공통 visibility 해석 오류를 semantic typed failure로 바꾼다."""

    try:
        return metric_visibility(rule)
    except ValueError as error:
        raise SemanticMetadataError(f"{context} has invalid governance") from error
