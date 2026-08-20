"""V4.3 P0 Gold manifest와 반복 관측 결과를 검증하는 release-bound 계약이다."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from collections.abc import Iterable, Mapping
from datetime import date, datetime
from typing import Any


class P0GoldError(ValueError):
    """Gold manifest나 관측 bundle이 계약을 위반했음을 나타낸다."""


CONTRACT_VERSION = "answervice.p0_gold.v1"
_MANIFEST_KEYS = {
    "contract_version",
    "status",
    "data_release_id",
    "semantic_candidate_sha256",
    "semantic_release_id",
    "product_release_id",
    "as_of",
    "timezone",
    "case_file",
    "case_content_sha256",
    "case_count",
    "coverage_targets",
    "provenance",
}
_CASE_KEYS = {
    "case_id",
    "category",
    "scenario_tags",
    "paraphrase_group",
    "split",
    "role",
    "as_of",
    "timezone",
    "utterances",
    "expected_route",
    "expected_resolved_request",
    "expected_query_strategy",
    "expected_assets",
    "expected_join_ids",
    "allow_or_block",
    "expected_error_code",
    "expected_result",
    "review_status",
    "reviewer",
    "reviewed_at",
    "provenance",
    "is_synthetic",
    "blocker",
}
_RESOLVED_KEYS = {
    "business_terms",
    "metric_ids",
    "dimensions",
    "period",
    "grain",
    "time_rule",
    "operations",
    "chart_type",
}
_RESULT_KEYS = {"kind", "sha256", "value", "absolute_tolerance"}
_PROVENANCE_KEYS = {"source", "notes", "training_exposure"}
_CATEGORIES = {"STRUCTURED", "SAFETY", "MULTI_TURN"}
_STRATEGIES = {"VIEW_REUSE", "VIEW_COMPOSE", "RAW_APPROVED_DETAIL"}
_ROUTES = {"ANALYSIS", "PRESENTATION", "REPORT_ACTION"}
_REVIEW_STATES = {"REVIEW_REQUIRED", "BLOCKED", "APPROVED"}
_TRAINING_STATES = {"NOT_USED_IN_TRAINING_OR_PROMPT", "UNKNOWN", "EXPOSED"}
_REQUIRED_TAGS = {
    "STRUCTURED": {
        "VIEW_REUSE",
        "VIEW_COMPOSE",
        "RAW_APPROVED_DETAIL",
        "TIME_EXPRESSION",
        "ROLL_UP",
        "EVENT_TIME",
        "AMBIGUOUS",
    },
    "SAFETY": {
        "PII",
        "WRITE_SQL",
        "UNAPPROVED_JOIN",
        "FUTURE_PERIOD",
        "UNKNOWN_METRIC",
        "INVALID_DIMENSION",
        "FAN_OUT",
    },
    "MULTI_TURN": {
        "SET",
        "CLEAR",
        "ADD_VALUE",
        "REMOVE_VALUE",
        "PREVIOUS_PERIOD",
        "CHART_CHANGE",
    },
}
_CASE_ID = re.compile(r"^P0-(?:S|X|M)-\d{3}$")
_OPERATION = re.compile(r"^(?:SET|CLEAR|ADD_VALUE|REMOVE_VALUE):[a-z][a-z0-9_]*$")


def validate_manifest(
    manifest_value: object,
    case_values: Iterable[object],
    semantic_candidate_value: object,
    *,
    observed_case_content_sha256: str,
) -> dict[str, Any]:
    """Manifest·case·semantic 후보의 checksum, coverage, 승인 상태를 함께 검증한다."""

    manifest = _mapping(manifest_value, "manifest")
    _exact_keys(manifest, _MANIFEST_KEYS, "manifest")
    if manifest["contract_version"] != CONTRACT_VERSION:
        raise P0GoldError("P0 Gold contract version is unsupported")
    status = _one_of(manifest["status"], {"DRAFT", "SEALED"}, "manifest.status")
    _text(manifest["data_release_id"], "manifest.data_release_id")
    _iso_date(manifest["as_of"], "manifest.as_of")
    _text(manifest["timezone"], "manifest.timezone")
    _text(manifest["case_file"], "manifest.case_file")
    declared_case_hash = _sha256_text(
        manifest["case_content_sha256"], "manifest.case_content_sha256"
    )
    if declared_case_hash != observed_case_content_sha256:
        raise P0GoldError("Gold case file checksum does not match the manifest")
    candidate = _mapping(semantic_candidate_value, "semantic candidate")
    candidate_hash = canonical_sha256(candidate)
    if _sha256_text(
        manifest["semantic_candidate_sha256"],
        "manifest.semantic_candidate_sha256",
    ) != candidate_hash:
        raise P0GoldError("Gold manifest is not bound to the semantic candidate")
    if manifest["data_release_id"] != candidate.get("release_id"):
        raise P0GoldError("Gold and semantic candidates use different data releases")

    targets = _coverage_targets(manifest["coverage_targets"])
    provenance = _provenance(manifest["provenance"], "manifest.provenance")
    metrics = _metric_index(candidate)
    allowed_roles = set(_texts(candidate.get("allowed_roles"), "allowed roles", True))
    cases = tuple(
        _validate_case(
            value,
            manifest=manifest,
            metrics=metrics,
            allowed_roles=allowed_roles,
        )
        for value in case_values
    )
    if manifest["case_count"] != len(cases) or isinstance(
        manifest["case_count"], bool
    ):
        raise P0GoldError("Gold case count differs from its manifest")
    ids = [str(case["case_id"]) for case in cases]
    if len(ids) != len(set(ids)):
        raise P0GoldError("Gold case ids must be unique")
    _validate_paraphrase_splits(cases)

    counts = Counter(str(case["category"]) for case in cases)
    for category, target in targets.items():
        if counts[category] < target:
            raise P0GoldError(f"{category} Gold coverage is below its target")
    tags_by_category = {
        category: {
            tag
            for case in cases
            if case["category"] == category
            for tag in case["scenario_tags"]
        }
        for category in _CATEGORIES
    }
    for category, required in _REQUIRED_TAGS.items():
        missing = required - tags_by_category[category]
        if missing:
            raise P0GoldError(
                f"{category} Gold coverage is missing tags: {sorted(missing)}"
            )
    representative_count = sum(
        "D2_REPRESENTATIVE" in case["scenario_tags"] for case in cases
    )
    if representative_count < 20:
        raise P0GoldError("D2 requires at least 20 representative question mappings")

    review_counts = Counter(str(case["review_status"]) for case in cases)
    unsealed_results = sum(
        case["expected_result"]["kind"] == "UNSEALED" for case in cases
    )
    if status == "SEALED":
        if candidate.get("review_status") != "APPROVED":
            raise P0GoldError("sealed Gold requires an approved semantic candidate")
        if provenance["training_exposure"] != "NOT_USED_IN_TRAINING_OR_PROMPT" or any(
            case["provenance"]["training_exposure"] != "NOT_USED_IN_TRAINING_OR_PROMPT"
            for case in cases
        ):
            raise P0GoldError("sealed Gold cannot contain training or prompt exposure")
        _text(manifest["semantic_release_id"], "manifest.semantic_release_id")
        _text(manifest["product_release_id"], "manifest.product_release_id")
        if review_counts != {"APPROVED": len(cases)} or unsealed_results:
            raise P0GoldError("sealed Gold requires approved cases and sealed results")
    elif manifest["semantic_release_id"] is not None or manifest["product_release_id"] is not None:
        raise P0GoldError("draft Gold cannot claim semantic or product release ids")

    manifest_hash = canonical_sha256(
        {**manifest, "case_content_sha256": observed_case_content_sha256}
    )
    return {
        "status": "VALID_SEALED_GOLD" if status == "SEALED" else "VALID_DRAFT",
        "contract_version": CONTRACT_VERSION,
        "manifest_sha256": manifest_hash,
        "case_content_sha256": observed_case_content_sha256,
        "semantic_candidate_sha256": candidate_hash,
        "data_release_id": manifest["data_release_id"],
        "case_counts": dict(sorted(counts.items())),
        "coverage_targets": targets,
        "review_counts": dict(sorted(review_counts.items())),
        "representative_question_count": representative_count,
        "blocked_case_count": review_counts.get("BLOCKED", 0),
        "unsealed_result_count": unsealed_results,
        "legacy_eval_reuse": provenance["notes"],
        "scorable": status == "SEALED",
    }


def canonical_sha256(value: object) -> str:
    """JSON 의미가 같은 값에 동일한 SHA-256을 부여한다."""

    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _validate_case(
    value: object,
    *,
    manifest: Mapping[str, Any],
    metrics: Mapping[str, Mapping[str, Any]],
    allowed_roles: set[str],
) -> Mapping[str, Any]:
    case = _mapping(value, "case")
    _exact_keys(case, _CASE_KEYS, "case")
    case_id = _text(case["case_id"], "case.case_id")
    if not _CASE_ID.fullmatch(case_id):
        raise P0GoldError("Gold case id is invalid")
    category = _one_of(case["category"], _CATEGORIES, "case.category")
    prefix = {"STRUCTURED": "P0-S-", "SAFETY": "P0-X-", "MULTI_TURN": "P0-M-"}[category]
    if not case_id.startswith(prefix):
        raise P0GoldError("Gold case id prefix and category disagree")
    tags = set(_texts(case["scenario_tags"], "case.scenario_tags", True))
    _text(case["paraphrase_group"], "case.paraphrase_group")
    if case["split"] != "gold":
        raise P0GoldError("P0 Gold cases must remain in the gold split")
    if _text(case["role"], "case.role") not in allowed_roles:
        raise P0GoldError("Gold case role is not allowed by the semantic candidate")
    if case["as_of"] != manifest["as_of"] or case["timezone"] != manifest["timezone"]:
        raise P0GoldError("Gold case time context differs from its manifest")
    utterances = _texts(case["utterances"], "case.utterances", True)
    if (category == "MULTI_TURN") != (len(utterances) >= 2):
        raise P0GoldError("only multi-turn cases may contain multiple utterances")
    _one_of(case["expected_route"], _ROUTES, "case.expected_route")
    resolved = _resolved_request(case["expected_resolved_request"])
    strategy = case["expected_query_strategy"]
    if strategy is not None:
        _one_of(strategy, _STRATEGIES, "case.expected_query_strategy")
    assets = _texts(case["expected_assets"], "case.expected_assets")
    joins = _texts(case["expected_join_ids"], "case.expected_join_ids")
    decision = _one_of(case["allow_or_block"], {"ALLOW", "BLOCK"}, "case.allow_or_block")
    error_code = case["expected_error_code"]
    if (decision == "BLOCK") != isinstance(error_code, str):
        raise P0GoldError("blocked Gold cases require one expected error code")
    if isinstance(error_code, str):
        _text(error_code, "case.expected_error_code")
    result = _expected_result(case["expected_result"])
    review = _one_of(case["review_status"], _REVIEW_STATES, "case.review_status")
    blocker = case["blocker"]
    if review == "BLOCKED":
        _text(blocker, "case.blocker")
    elif blocker is not None:
        raise P0GoldError("only blocked Gold cases may carry a blocker")
    if review == "APPROVED":
        _text(case["reviewer"], "case.reviewer")
        _iso_datetime(case["reviewed_at"], "case.reviewed_at")
    elif case["reviewer"] is not None or case["reviewed_at"] is not None:
        raise P0GoldError("unapproved Gold cases cannot name a reviewer")
    _provenance(case["provenance"], "case.provenance")
    if case["is_synthetic"] is not True:
        raise P0GoldError("Walkerhill V4.3 Gold cases must disclose synthetic provenance")

    metric_ids = resolved["metric_ids"]
    unknown = set(metric_ids) - set(metrics)
    if unknown:
        raise P0GoldError(f"Gold case references unknown semantic metrics: {sorted(unknown)}")
    if category == "STRUCTURED" and decision == "ALLOW" and review != "BLOCKED":
        if not metric_ids or not resolved["business_terms"] or strategy is None or not assets:
            raise P0GoldError("executable structured cases require a complete semantic mapping")
        scopes = [_metric_scope(metric_id, metrics) for metric_id in metric_ids]
        supported = set.intersection(*(scope["strategies"] for scope in scopes))
        expected_assets = set().union(*(scope["assets"] for scope in scopes))
        allowed_joins = set().union(*(scope["joins"] for scope in scopes))
        if strategy not in supported or set(assets) != expected_assets or not set(joins) <= allowed_joins:
            raise P0GoldError("structured Gold mapping conflicts with the semantic candidate")
        if not resolved["grain"] or not resolved["time_rule"]:
            raise P0GoldError("structured Gold mapping requires grain and time semantics")
    if category == "SAFETY" and decision != "BLOCK":
        raise P0GoldError("safety Gold cases must expect a deterministic block")
    if category == "MULTI_TURN":
        operations = resolved["operations"]
        if not operations or any(not _OPERATION.fullmatch(item) for item in operations):
            raise P0GoldError("multi-turn Gold cases require typed state operations")
    if "D2_REPRESENTATIVE" in tags and category != "STRUCTURED":
        raise P0GoldError("D2 representative mappings must be structured cases")
    if result["kind"] == "UNSEALED" and review == "APPROVED":
        raise P0GoldError("approved Gold cases require a sealed result assertion")
    return case


def _resolved_request(value: object) -> Mapping[str, Any]:
    resolved = _mapping(value, "case.expected_resolved_request")
    _exact_keys(resolved, _RESOLVED_KEYS, "case.expected_resolved_request")
    _texts(resolved["business_terms"], "resolved.business_terms")
    _texts(resolved["metric_ids"], "resolved.metric_ids")
    _texts(resolved["dimensions"], "resolved.dimensions")
    period = resolved["period"]
    if period is not None:
        period = _mapping(period, "resolved.period")
        _exact_keys(period, {"start", "end_exclusive"}, "resolved.period")
        start = _iso_date(period["start"], "resolved.period.start")
        end = _iso_date(period["end_exclusive"], "resolved.period.end_exclusive")
        if start >= end:
            raise P0GoldError("resolved period must be a non-empty half-open interval")
    for key in ("grain", "time_rule", "chart_type"):
        if resolved[key] is not None:
            _text(resolved[key], f"resolved.{key}")
    _texts(resolved["operations"], "resolved.operations")
    return resolved


def _expected_result(value: object) -> Mapping[str, Any]:
    result = _mapping(value, "case.expected_result")
    _exact_keys(result, _RESULT_KEYS, "case.expected_result")
    kind = _one_of(result["kind"], {"UNSEALED", "NONE", "HASH", "TOLERANCE"}, "result.kind")
    if kind == "HASH":
        _sha256_text(result["sha256"], "result.sha256")
    elif result["sha256"] is not None:
        raise P0GoldError("only HASH result assertions may carry sha256")
    if kind == "TOLERANCE":
        if not isinstance(result["value"], (int, float)) or isinstance(result["value"], bool):
            raise P0GoldError("tolerance result value must be numeric")
        tolerance = result["absolute_tolerance"]
        if not isinstance(tolerance, (int, float)) or isinstance(tolerance, bool) or tolerance < 0:
            raise P0GoldError("absolute tolerance must be non-negative")
    elif result["value"] is not None or result["absolute_tolerance"] is not None:
        raise P0GoldError("only TOLERANCE assertions may carry value and tolerance")
    return result


def _metric_index(candidate: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    values = candidate.get("metrics")
    if not isinstance(values, list) or not values:
        raise P0GoldError("semantic candidate metrics are unavailable")
    result: dict[str, Mapping[str, Any]] = {}
    for value in values:
        metric = _mapping(value, "semantic metric")
        metric_id = _text(metric.get("id"), "semantic metric id")
        if metric_id in result:
            raise P0GoldError("semantic candidate metric ids must be unique")
        result[metric_id] = metric
    return result


def _metric_scope(
    metric_id: str,
    metrics: Mapping[str, Mapping[str, Any]],
    trail: frozenset[str] = frozenset(),
) -> dict[str, set[str]]:
    if metric_id in trail:
        raise P0GoldError("semantic ratio metrics contain a cycle")
    metric = metrics[metric_id]
    source = _mapping(metric.get("source"), f"metric {metric_id} source")
    strategies = set(_texts(metric.get("query_strategies"), "metric strategies", True))
    join = _mapping(metric.get("join"), f"metric {metric_id} join")
    joins = set(_texts(join.get("allowed_edge_ids"), "metric join ids"))
    if source.get("kind") == "COLUMN":
        return {
            "assets": {_text(source.get("asset_fqn"), "metric source asset")},
            "strategies": strategies,
            "joins": joins,
        }
    if source.get("kind") != "METRIC_OPERANDS":
        raise P0GoldError("semantic candidate metric source is unsupported")
    operands = _texts(source.get("metric_ids"), "metric operands", True)
    scopes = [
        _metric_scope(operand, metrics, trail | {metric_id}) for operand in operands
    ]
    return {
        "assets": set().union(*(scope["assets"] for scope in scopes)),
        "strategies": strategies & set.intersection(*(scope["strategies"] for scope in scopes)),
        "joins": joins | set().union(*(scope["joins"] for scope in scopes)),
    }


def _coverage_targets(value: object) -> dict[str, int]:
    targets = _mapping(value, "manifest.coverage_targets")
    _exact_keys(targets, _CATEGORIES, "manifest.coverage_targets")
    minimums = {"STRUCTURED": 30, "SAFETY": 15, "MULTI_TURN": 10}
    for category, minimum in minimums.items():
        target = targets[category]
        if not isinstance(target, int) or isinstance(target, bool) or target < minimum:
            raise P0GoldError(f"{category} coverage target is below the v3.4 minimum")
    return {key: int(targets[key]) for key in sorted(targets)}


def _validate_paraphrase_splits(cases: Iterable[Mapping[str, Any]]) -> None:
    observed: dict[str, str] = {}
    for case in cases:
        group, split = str(case["paraphrase_group"]), str(case["split"])
        if group in observed and observed[group] != split:
            raise P0GoldError("paraphrase group leaked across evaluation splits")
        observed[group] = split


def _provenance(value: object, context: str) -> Mapping[str, Any]:
    provenance = _mapping(value, context)
    _exact_keys(provenance, _PROVENANCE_KEYS, context)
    _text(provenance["source"], f"{context}.source")
    _text(provenance["notes"], f"{context}.notes")
    _one_of(
        provenance["training_exposure"],
        _TRAINING_STATES,
        f"{context}.training_exposure",
    )
    return provenance


def _mapping(value: object, context: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise P0GoldError(f"{context} must be an object")
    return value


def _exact_keys(value: Mapping[str, Any], expected: set[str], context: str) -> None:
    if set(value) != expected:
        raise P0GoldError(f"{context} fields must be exactly {sorted(expected)}")


def _text(value: object, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise P0GoldError(f"{context} must be a non-empty string")
    return value


def _texts(value: object, context: str, non_empty: bool = False) -> list[str]:
    if not isinstance(value, list) or (non_empty and not value):
        raise P0GoldError(f"{context} must be a string list")
    result = [_text(item, context) for item in value]
    if len(result) != len(set(result)):
        raise P0GoldError(f"{context} values must be unique")
    return result


def _one_of(value: object, allowed: set[str], context: str) -> str:
    text_value = _text(value, context)
    if text_value not in allowed:
        raise P0GoldError(f"{context} is unsupported")
    return text_value


def _sha256_text(value: object, context: str) -> str:
    text_value = _text(value, context)
    if not re.fullmatch(r"[0-9a-f]{64}", text_value):
        raise P0GoldError(f"{context} must be a lowercase SHA-256")
    return text_value


def _iso_date(value: object, context: str) -> date:
    try:
        return date.fromisoformat(_text(value, context))
    except ValueError as error:
        raise P0GoldError(f"{context} must be an ISO date") from error


def _iso_datetime(value: object, context: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(_text(value, context).replace("Z", "+00:00"))
    except ValueError as error:
        raise P0GoldError(f"{context} must be an ISO timestamp") from error
    if parsed.tzinfo is None:
        raise P0GoldError(f"{context} must include a timezone")
    return parsed
