"""봉인된 P0 Gold와 정규화된 반복 관측을 비교해 재현 가능한 지표를 계산한다."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from statistics import median
from typing import Any

from evals.p0_gold import P0GoldError, canonical_sha256


_OUTPUT_KEYS = {
    "route",
    "resolved_request",
    "query_strategy",
    "assets",
    "join_ids",
    "allow_or_block",
    "error_code",
    "result",
}


def evaluate_observations(
    cases: Iterable[Mapping[str, Any]],
    validation_summary: Mapping[str, Any],
    observations: Iterable[object],
    *,
    repeat: int,
) -> dict[str, Any]:
    """모든 case의 repeat 관측을 exact/tolerance 기준으로 판정하고 p50/p95를 계산한다."""

    if validation_summary.get("scorable") is not True:
        raise P0GoldError("draft or unapproved Gold cannot be scored")
    if not isinstance(repeat, int) or isinstance(repeat, bool) or repeat < 1:
        raise P0GoldError("repeat must be a positive integer")
    case_index = {str(case["case_id"]): case for case in cases}
    rows: dict[str, list[Mapping[str, Any]]] = {case_id: [] for case_id in case_index}
    for value in observations:
        row = _mapping(value, "observation")
        _exact_keys(row, {"case_id", "attempt", "latency_ms", "output"}, "observation")
        case_id = _text(row["case_id"], "observation.case_id")
        if case_id not in rows:
            raise P0GoldError("observation references an unknown Gold case")
        attempt, latency = row["attempt"], row["latency_ms"]
        if (
            not isinstance(attempt, int)
            or isinstance(attempt, bool)
            or not isinstance(latency, (int, float))
            or isinstance(latency, bool)
            or latency < 0
        ):
            raise P0GoldError("observation attempt or latency is invalid")
        rows[case_id].append(row)

    results = []
    latencies: list[float] = []
    for case_id, case in case_index.items():
        case_rows = sorted(rows[case_id], key=lambda item: item["attempt"])
        if [row["attempt"] for row in case_rows] != list(range(1, repeat + 1)):
            raise P0GoldError("every Gold case requires exactly one observation per repeat")
        matches = [_matches_expected(case, row["output"]) for row in case_rows]
        hashes = [canonical_sha256(row["output"]) for row in case_rows]
        latencies.extend(float(row["latency_ms"]) for row in case_rows)
        results.append(
            {
                "case_id": case_id,
                "category": case["category"],
                "passed": all(matches),
                "deterministic": len(set(hashes)) == 1,
                "attempts": repeat,
            }
        )
    ordered = sorted(latencies)
    categories = sorted({str(case["category"]) for case in case_index.values()})
    return {
        "manifest_sha256": validation_summary["manifest_sha256"],
        "repeat": repeat,
        "total": len(results),
        "passed": sum(row["passed"] for row in results),
        "deterministic": sum(row["deterministic"] for row in results),
        "accuracy": _accuracy(results),
        "category_accuracy": {
            category: _accuracy(
                [row for row in results if row["category"] == category]
            )
            for category in categories
        },
        "p50_ms": median(ordered),
        "p95_ms": ordered[max(0, (len(ordered) * 95 + 99) // 100 - 1)],
        "results": results,
    }


def _matches_expected(case: Mapping[str, Any], output_value: object) -> bool:
    output = _mapping(output_value, "observation.output")
    _exact_keys(output, _OUTPUT_KEYS, "observation.output")
    scalar_match = (
        output["route"] == case["expected_route"]
        and output["resolved_request"] == case["expected_resolved_request"]
        and output["query_strategy"] == case["expected_query_strategy"]
        and output["assets"] == case["expected_assets"]
        and output["join_ids"] == case["expected_join_ids"]
        and output["allow_or_block"] == case["allow_or_block"]
        and output["error_code"] == case["expected_error_code"]
    )
    expected_result = case["expected_result"]
    kind, observed = expected_result["kind"], output["result"]
    if kind == "NONE":
        result_match = observed is None
    elif kind == "HASH":
        result_match = canonical_sha256(observed) == expected_result["sha256"]
    elif kind == "TOLERANCE":
        result_match = (
            isinstance(observed, (int, float))
            and not isinstance(observed, bool)
            and abs(observed - expected_result["value"])
            <= expected_result["absolute_tolerance"]
        )
    else:
        result_match = False
    return scalar_match and result_match


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


def _accuracy(rows: list[Mapping[str, Any]]) -> float:
    if not rows:
        raise P0GoldError("accuracy requires at least one result")
    return round(sum(bool(row["passed"]) for row in rows) / len(rows), 6)
