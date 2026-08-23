"""승인 전 업무 metric 검토안을 SQL 구조 근거와 대조하는 일반 계약이다."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from metadata_contract_primitives import (
    SemanticMetadataError,
    array,
    exact_keys,
    identifier,
    mapping,
    text,
    unique_texts,
)
from runtime_governance_draft import GovernanceDraft
from src.data.entitlement_roles import validate_entitlement_roles


CONTRACT_VERSION = "answervice.metric_review.v1"
REVIEW_STATUS = "REVIEW_REQUIRED"
APPROVED_STATUS = "APPROVED"
_TOP_LEVEL_KEYS = {
    "contract_version",
    "review_status",
    "release_id",
    "serving_schema",
    "source_sql_sha256",
    "business_metric_target_count",
    "allowed_roles",
    "review_owner_candidate_urn",
    "metrics",
}
_APPROVAL_KEYS = {"reviewer", "reviewed_at"}
_METRIC_KEYS = {
    "id",
    "name",
    "visibility",
    "review_status",
    "definition",
    "formula",
    "source",
    "grain",
    "time",
    "join",
    "aliases",
    "permission",
    "unit",
    "result_field",
    "query_strategies",
}
_COLUMN_AGGREGATIONS = {"sum", "count", "count_distinct", "min", "max", "average"}
_COLUMN_REDUCTIONS = {"sum", "min", "max", "average", "scalar"}
_QUERY_STRATEGIES = {"VIEW_REUSE", "VIEW_COMPOSE", "RAW_APPROVED_DETAIL"}
_ZERO_POLICIES = {"null_on_zero_denominator"}
_VISIBILITIES = {"BUSINESS", "SUPPORT"}


def validate_metric_review(
    document: object,
    sql_evidence: GovernanceDraft,
) -> dict[str, object]:
    """검토안 또는 명시적으로 승인된 문서의 업무 필드와 물리 참조를 검증한다."""

    candidate = mapping(document, "metric review")
    status = candidate.get("review_status")
    expected_keys = (
        _TOP_LEVEL_KEYS | _APPROVAL_KEYS
        if status == APPROVED_STATUS
        else _TOP_LEVEL_KEYS
    )
    exact_keys(candidate, expected_keys, "metric review")
    if candidate["contract_version"] != CONTRACT_VERSION:
        raise SemanticMetadataError("metric review contract version is unsupported")
    if status not in {REVIEW_STATUS, APPROVED_STATUS}:
        raise SemanticMetadataError("metric review status is unsupported")
    if (
        text(candidate["release_id"], "release id") != sql_evidence.release_version
        or text(candidate["serving_schema"], "serving schema")
        != sql_evidence.serving_schema
        or text(candidate["source_sql_sha256"], "source SQL checksum")
        != sql_evidence.source_sha256
    ):
        raise SemanticMetadataError("metric review does not match its SQL release evidence")
    owner = text(candidate["review_owner_candidate_urn"], "review owner candidate")
    if not owner.startswith("urn:li:corpGroup:"):
        raise SemanticMetadataError("review owner candidate must be a CorpGroup URN")
    if status == APPROVED_STATUS:
        reviewer = text(candidate["reviewer"], "metric review reviewer")
        if reviewer != owner:
            raise SemanticMetadataError(
                "approved metric review reviewer must match its governed owner"
            )
        _review_timestamp(candidate["reviewed_at"])
    target = candidate["business_metric_target_count"]
    if not isinstance(target, int) or isinstance(target, bool) or not 1 <= target <= 64:
        raise SemanticMetadataError("business metric target count is invalid")
    allowed_roles = frozenset(
        unique_texts(candidate["allowed_roles"], "allowed roles", non_empty=True)
    )
    try:
        validate_entitlement_roles(allowed_roles)
    except ValueError as error:
        raise SemanticMetadataError(
            "metric review contains an unsupported authentication role"
        ) from error
    views = {
        view.fqn: {field.name for field in view.fields}
        for view in sql_evidence.views
    }
    metrics = _validate_metrics(
        candidate["metrics"],
        views,
        allowed_roles,
        expected_status=str(status),
    )
    business = [item for item in metrics.values() if item["visibility"] == "BUSINESS"]
    if len(business) != target:
        raise SemanticMetadataError("business metric count differs from its declared target")
    _validate_ratios(metrics)
    _validate_business_aliases(business)
    return {
        "status": (
            "VALID_APPROVED_REVIEW"
            if status == APPROVED_STATUS
            else "VALID_REVIEW_DRAFT"
        ),
        "contract_version": CONTRACT_VERSION,
        "candidate_sha256": _sha256(candidate),
        "source_sql_sha256": sql_evidence.source_sha256,
        "business_metric_count": len(business),
        "support_metric_count": len(metrics) - len(business),
        "metric_count": len(metrics),
        "approval_status": (
            APPROVED_STATUS if status == APPROVED_STATUS else "NOT_APPROVED"
        ),
        "publishable": status == APPROVED_STATUS,
    }


def _validate_metrics(
    value: object,
    views: Mapping[str, set[str]],
    allowed_roles: frozenset[str],
    *,
    expected_status: str,
) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for index, raw in enumerate(array(value, "metrics", non_empty=True, limit=64)):
        context = f"metric[{index}]"
        metric = mapping(raw, context)
        exact_keys(metric, _METRIC_KEYS, context)
        metric_id = identifier(metric["id"], f"{context}.id")
        if metric_id in result:
            raise SemanticMetadataError("metric review ids must be unique")
        visibility = text(metric["visibility"], f"{context}.visibility")
        if (
            visibility not in _VISIBILITIES
            or metric["review_status"] != expected_status
        ):
            raise SemanticMetadataError(
                "every metric must match the review-level approval status"
            )
        text(metric["definition"], f"{context}.definition")
        text(metric["name"], f"{context}.name")
        identifier(metric["result_field"], f"{context}.result_field")
        text(metric["unit"], f"{context}.unit")
        unique_texts(metric["aliases"], f"{context}.aliases", non_empty=True)
        strategies = frozenset(
            unique_texts(metric["query_strategies"], f"{context}.query_strategies", non_empty=True)
        )
        if not strategies <= _QUERY_STRATEGIES:
            raise SemanticMetadataError("metric review contains an unsupported query strategy")
        _validate_permission(metric["permission"], allowed_roles, context)
        source_asset = _validate_source_and_formula(metric, views, context)
        _validate_scope(
            metric,
            source_asset,
            views[source_asset] if source_asset else set(),
            context,
        )
        result[metric_id] = metric
    return result


def _review_timestamp(value: object) -> datetime:
    """승인 시각이 timezone을 포함한 ISO timestamp인지 검증한다."""

    raw = text(value, "metric review reviewed_at")
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as error:
        raise SemanticMetadataError(
            "metric review reviewed_at must be an ISO timestamp"
        ) from error
    if parsed.tzinfo is None:
        raise SemanticMetadataError(
            "metric review reviewed_at must include a timezone"
        )
    return parsed


def _validate_permission(
    value: object,
    allowed_roles: frozenset[str],
    context: str,
) -> None:
    permission = mapping(value, f"{context}.permission")
    exact_keys(permission, {"roles", "contains_pii", "synthetic"}, f"{context}.permission")
    roles = frozenset(
        unique_texts(permission["roles"], f"{context}.permission.roles", non_empty=True)
    )
    if not roles <= allowed_roles:
        raise SemanticMetadataError("metric permission references an undeclared role")
    if not isinstance(permission["contains_pii"], bool) or not isinstance(
        permission["synthetic"], bool
    ):
        raise SemanticMetadataError("metric permission flags must be boolean")


def _validate_source_and_formula(
    metric: Mapping[str, Any],
    views: Mapping[str, set[str]],
    context: str,
) -> str:
    source = mapping(metric["source"], f"{context}.source")
    formula = mapping(metric["formula"], f"{context}.formula")
    if source.get("kind") == "COLUMN":
        exact_keys(source, {"kind", "asset_fqn", "column"}, f"{context}.source")
        exact_keys(formula, {"kind", "aggregation", "reduction"}, f"{context}.formula")
        asset = text(source["asset_fqn"], f"{context}.source.asset_fqn")
        column = identifier(source["column"], f"{context}.source.column")
        if asset not in views or column not in views[asset]:
            raise SemanticMetadataError("metric source is not present in the SQL release")
        aggregation = text(formula["aggregation"], f"{context}.formula.aggregation")
        reduction = text(formula["reduction"], f"{context}.formula.reduction")
        if (
            formula["kind"] != "COLUMN"
            or aggregation not in _COLUMN_AGGREGATIONS
            or reduction not in _COLUMN_REDUCTIONS
        ):
            raise SemanticMetadataError("column metric formula is unsupported")
        if aggregation in {"sum", "count", "count_distinct"} and reduction != "sum":
            raise SemanticMetadataError("additive column metrics must use sum reduction")
        return asset
    if source.get("kind") == "METRIC_OPERANDS":
        exact_keys(source, {"kind", "metric_ids"}, f"{context}.source")
        exact_keys(
            formula,
            {"kind", "numerator_metric_id", "denominator_metric_id", "zero_policy"},
            f"{context}.formula",
        )
        operands = tuple(
            identifier(value, f"{context}.source.metric_ids")
            for value in unique_texts(
                source["metric_ids"],
                f"{context}.source.metric_ids",
                non_empty=True,
            )
        )
        numerator = identifier(
            formula["numerator_metric_id"],
            f"{context}.formula.numerator_metric_id",
        )
        denominator = identifier(
            formula["denominator_metric_id"],
            f"{context}.formula.denominator_metric_id",
        )
        zero_policy = text(formula["zero_policy"], f"{context}.formula.zero_policy")
        if (
            len(operands) != 2
            or formula["kind"] != "RATIO"
            or (numerator, denominator) != operands
            or operands[0] == operands[1]
            or zero_policy not in _ZERO_POLICIES
        ):
            raise SemanticMetadataError("ratio metric operands or zero policy are invalid")
        return ""
    raise SemanticMetadataError("metric source must be a column or metric operands")


def _validate_scope(
    metric: Mapping[str, Any],
    source_asset: str,
    source_columns: set[str],
    context: str,
) -> None:
    grain = mapping(metric["grain"], f"{context}.grain")
    exact_keys(grain, {"kind", "keys", "dimensions"}, f"{context}.grain")
    text(grain["kind"], f"{context}.grain.kind")
    keys = frozenset(unique_texts(grain["keys"], f"{context}.grain.keys", non_empty=True))
    dimensions = frozenset(unique_texts(grain["dimensions"], f"{context}.grain.dimensions"))
    time = mapping(metric["time"], f"{context}.time")
    exact_keys(
        time,
        {
            "field",
            "semantics",
            "timezone",
            "interval",
            "bucket",
            "timezone_mode",
        },
        f"{context}.time",
    )
    time_field = identifier(time["field"], f"{context}.time.field")
    text(time["semantics"], f"{context}.time.semantics")
    text(time["timezone"], f"{context}.time.timezone")
    text(time["bucket"], f"{context}.time.bucket")
    text(time["timezone_mode"], f"{context}.time.timezone_mode")
    if time["interval"] != "[start,end)":
        raise SemanticMetadataError("metric time intervals must use half-open boundaries")
    join = mapping(metric["join"], f"{context}.join")
    exact_keys(join, {"required", "allowed_edge_ids"}, f"{context}.join")
    edges = tuple(unique_texts(join["allowed_edge_ids"], f"{context}.join.allowed_edge_ids"))
    if not isinstance(join["required"], bool) or (join["required"] and not edges):
        raise SemanticMetadataError("metric join requirement and allowed edges disagree")
    if source_asset and not keys | dimensions | {time_field} <= source_columns:
        raise SemanticMetadataError("metric grain or time references a column outside its source asset")


def _validate_ratios(metrics: Mapping[str, Mapping[str, Any]]) -> None:
    for metric_id, metric in metrics.items():
        source = mapping(metric["source"], f"metric[{metric_id}].source")
        if source.get("kind") != "METRIC_OPERANDS":
            continue
        numerator_id, denominator_id = source["metric_ids"]
        numerator = metrics.get(str(numerator_id))
        denominator = metrics.get(str(denominator_id))
        if numerator is None or denominator is None:
            raise SemanticMetadataError("ratio operands must reference metrics in the same review")
        numerator_source = mapping(numerator["source"], "ratio numerator source")
        denominator_source = mapping(denominator["source"], "ratio denominator source")
        if (
            numerator_source.get("kind") != "COLUMN"
            or denominator_source.get("kind") != "COLUMN"
            or numerator_source["asset_fqn"] != denominator_source["asset_fqn"]
            or metric["grain"] != numerator["grain"]
            or metric["grain"] != denominator["grain"]
            or metric["time"] != numerator["time"]
            or metric["time"] != denominator["time"]
            or metric["join"] != numerator["join"]
            or metric["join"] != denominator["join"]
            or metric["permission"] != numerator["permission"]
            or metric["permission"] != denominator["permission"]
        ):
            raise SemanticMetadataError(
                "ratio metrics and operands must share one physical calculation scope"
            )


def _validate_business_aliases(metrics: list[Mapping[str, Any]]) -> None:
    observed: dict[str, str] = {}
    for metric in metrics:
        for alias in (metric["name"], *metric["aliases"]):
            normalized = " ".join(str(alias).casefold().split())
            previous = observed.get(normalized)
            if previous is not None and previous != metric["id"]:
                raise SemanticMetadataError("business metric aliases must be globally unambiguous")
            observed[normalized] = str(metric["id"])


def _sha256(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
