"""Dependency-free deterministic runner for versioned AI node evaluation cases."""

from __future__ import annotations

import argparse
import json
from hashlib import sha256
from pathlib import Path
from statistics import median
from typing import Any, Iterable, Protocol

from src.ai.node1 import normalize_question
from src.ai.node2 import generate_sql, repair_sql
from src.ai.node3 import explain_result


class EvaluationError(ValueError):
    """Raised when an evaluation case is malformed."""


_CASE_FIELDS = {"case_id", "node", "request", "expected_output"}
_NODE_RUNNERS = {
    "node1": normalize_question,
    "node2": generate_sql,
    "node2_repair": repair_sql,
    "node3": explain_result,
}


class ModelAdapter(Protocol):
    def generate(self, node: str, payload: dict[str, Any]) -> dict[str, Any]: ...


class LocalNodeAdapter:
    """Run the checked-in deterministic node implementations directly."""

    def generate(self, node: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            runner = _NODE_RUNNERS[node]
        except KeyError as exc:
            raise EvaluationError(f"unknown node: {node}") from exc
        return runner(payload)


def evaluate_cases(
    cases: Iterable[dict[str, Any]],
    adapter: ModelAdapter | None = None,
) -> dict[str, Any]:
    """Evaluate cases twice and return stable exact-match results."""
    model = adapter or LocalNodeAdapter()
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

        first = model.generate(case["node"], case["request"])
        second = model.generate(case["node"], case["request"])
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
    adapter: ModelAdapter | None = None,
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset", type=Path)
    args = parser.parse_args()
    cases = json.loads(args.dataset.read_text(encoding="utf-8"))
    summary = evaluate_cases(cases)
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
