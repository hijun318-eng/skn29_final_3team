"""Adapter-driven evaluator for versioned AI node cases."""

from __future__ import annotations

import json
from hashlib import sha256
from statistics import median
from typing import Any, Iterable


class EvaluationError(ValueError):
    """Raised when an evaluation case is malformed."""


_CASE_FIELDS = {"case_id", "node", "request", "expected_output"}


def evaluate_cases(
    cases: Iterable[dict[str, Any]],
    adapter: Any,
) -> dict[str, Any]:
    """Evaluate fixtures twice and return stable exact-match results."""
    seen: set[str] = set()
    results = []

    for case in cases:
        fields = set(case)
        if fields != _CASE_FIELDS:
            raise EvaluationError(
                f"case fields must be exactly {sorted(_CASE_FIELDS)}"
            )
        case_id = case["case_id"]
        if not isinstance(case_id, str) or not case_id:
            raise EvaluationError("case_id must be a non-empty string")
        if case_id in seen:
            raise EvaluationError(f"duplicate case_id: {case_id}")
        seen.add(case_id)

        first = adapter.generate(case["node"], case["request"])
        second = adapter.generate(case["node"], case["request"])
        deterministic = first == second
        expected_match = first == case["expected_output"]
        results.append(
            {
                "case_id": case_id,
                "status": "PASS" if deterministic and expected_match else "FAIL",
                "deterministic": deterministic,
                "expected_match": expected_match,
                "output_hash": _stable_hash(first),
            }
        )

    return {
        "total": len(results),
        "passed": sum(result["status"] == "PASS" for result in results),
        "failed": sum(result["status"] == "FAIL" for result in results),
        "results": results,
    }


def evaluate_required30(
    cases: Iterable[dict[str, Any]],
    adapter: Any,
) -> dict[str, Any]:
    """Reject incomplete acceptance manifests instead of reporting a partial pass."""
    materialized = list(cases)
    if len(materialized) != 30:
        raise EvaluationError("required30 must contain exactly 30 cases")
    return evaluate_cases(materialized, adapter)


def compare_runs(baseline: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    """Compare already captured runs without downloading or calling a model."""
    if baseline.get("conditions") != candidate.get("conditions"):
        raise EvaluationError("comparison conditions must be identical")
    baseline_cases = _case_results(baseline)
    candidate_cases = _case_results(candidate)
    if set(baseline_cases) != set(candidate_cases):
        raise EvaluationError("comparison case ids must be identical")
    return {
        "conditions_hash": _stable_hash(baseline["conditions"]),
        "baseline": _run_metrics(baseline, baseline_cases),
        "candidate": _run_metrics(candidate, candidate_cases),
    }


def validate_data_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    """Validate the R2 evaluation inventory without claiming model execution."""
    required = {"manifest_version", "synthetic", "counts", "cases"}
    if not required.issubset(manifest) or manifest["synthetic"] is not True:
        raise EvaluationError("R2 evaluation manifest metadata is invalid")
    counts = manifest["counts"]
    cases = manifest["cases"]
    if not isinstance(counts, dict) or not isinstance(cases, list):
        raise EvaluationError("R2 evaluation manifest counts or cases are invalid")

    seen: set[str] = set()
    set_counts = {"required30": 0, "gold120": 0}
    status_counts: dict[str, int] = {}
    split_samples = []
    for case in cases:
        needed = {"case_id", "set", "paraphrase_group", "split", "status"}
        if not needed.issubset(case) or not all(
            isinstance(case[field], str) and case[field] for field in needed
        ):
            raise EvaluationError("R2 evaluation case is invalid")
        case_id = case["case_id"]
        if case_id in seen:
            raise EvaluationError(f"duplicate case_id: {case_id}")
        if case["set"] not in set_counts:
            raise EvaluationError(f'unknown evaluation set: {case["set"]}')
        seen.add(case_id)
        set_counts[case["set"]] += 1
        status_counts[case["status"]] = status_counts.get(case["status"], 0) + 1
        split_samples.append(
            {
                "sample_id": case_id,
                "paraphrase_group": case["paraphrase_group"],
                "split": case["split"],
            }
        )

    required_count = counts.get("required30")
    gold_partial = counts.get("gold120_partial")
    gold_target = counts.get("gold120_target")
    if required_count != 30 or gold_target != 120:
        raise EvaluationError("required30 count or gold120 target is invalid")
    if (
        not isinstance(gold_partial, int)
        or isinstance(gold_partial, bool)
        or not 0 <= gold_partial <= gold_target
    ):
        raise EvaluationError("gold120 partial count is invalid")
    declared = {"required30": required_count, "gold120": gold_partial}
    if declared != set_counts:
        raise EvaluationError("R2 evaluation manifest declared counts do not match cases")
    return {
        "manifest_version": manifest["manifest_version"],
        "set_counts": set_counts,
        "split_counts": validate_split_manifest(split_samples),
        "status_counts": status_counts,
        "model_execution": "NOT_RUN",
    }


def validate_split_manifest(samples: Iterable[dict[str, Any]]) -> dict[str, int]:
    """Keep a paraphrase group wholly inside one train/validation/gold split."""
    allowed = {"train", "validation", "gold"}
    groups: dict[str, str] = {}
    counts = {split: 0 for split in sorted(allowed)}
    for sample in samples:
        if set(sample) != {"sample_id", "paraphrase_group", "split"}:
            raise EvaluationError("split sample fields are invalid")
        split = sample["split"]
        group = sample["paraphrase_group"]
        if split not in allowed or not all(isinstance(value, str) and value for value in sample.values()):
            raise EvaluationError("split sample values are invalid")
        if group in groups and groups[group] != split:
            raise EvaluationError(f"paraphrase group leaked across splits: {group}")
        groups[group] = split
        counts[split] += 1
    return counts


def _case_results(run: dict[str, Any]) -> dict[str, bool]:
    cases = run.get("cases")
    if not isinstance(cases, list) or not cases:
        raise EvaluationError("comparison cases are required")
    results: dict[str, bool] = {}
    for case in cases:
        if set(case) != {"case_id", "passed"} or not isinstance(case["passed"], bool):
            raise EvaluationError("comparison case result is invalid")
        if case["case_id"] in results:
            raise EvaluationError(f'duplicate case_id: {case["case_id"]}')
        results[case["case_id"]] = case["passed"]
    return results


def _run_metrics(run: dict[str, Any], cases: dict[str, bool]) -> dict[str, Any]:
    latencies = run.get("latencies_ms")
    if not isinstance(latencies, list) or not latencies or any(
        not isinstance(value, (int, float)) or value < 0 for value in latencies
    ):
        raise EvaluationError("non-negative latency observations are required")
    ordered = sorted(float(value) for value in latencies)
    return {
        "accuracy": sum(cases.values()) / len(cases),
        "p50_ms": median(ordered),
        "p95_ms": ordered[max(0, (len(ordered) * 95 + 99) // 100 - 1)],
        "resources": run.get("resources"),
        "cost_usd": run.get("cost_usd"),
    }


def _stable_hash(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return sha256(encoded).hexdigest()
