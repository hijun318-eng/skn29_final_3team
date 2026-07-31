"""Dependency-free deterministic runner for versioned AI node fixtures."""

from __future__ import annotations

import argparse
import json
from hashlib import sha256
from pathlib import Path
from typing import Any, Iterable

from src.ai.fake_model import FakeModelAdapter


class EvaluationError(ValueError):
    """Raised when an evaluation case is malformed."""


_CASE_FIELDS = {"case_id", "node", "request", "expected_output"}


def evaluate_cases(
    cases: Iterable[dict[str, Any]],
    adapter: FakeModelAdapter | None = None,
) -> dict[str, Any]:
    """Evaluate fixtures twice and return stable exact-match results."""
    model = adapter or FakeModelAdapter()
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


def _stable_hash(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("fixture", type=Path)
    args = parser.parse_args()
    cases = json.loads(args.fixture.read_text(encoding="utf-8"))
    summary = evaluate_cases(cases)
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
