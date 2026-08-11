import copy
import unittest

from evals.runner import EvaluationError, evaluate_cases
from src.ai.fake_model import FakeModelAdapter
from src.ai.training.evaluate_lora import (
    DEFAULT_MODEL,
    DEFAULT_REVISION,
    EvidenceError,
    IMMUTABLE_EVIDENCE_FIELDS,
    _percentile,
    compare_captured_evidence,
    observed_metrics,
)
from tests.ai.test_contracts import VALID_PAYLOADS


def valid_case():
    adapter = FakeModelAdapter()
    request = copy.deepcopy(VALID_PAYLOADS["node3_request"])
    return {
        "case_id": "required30-node3-001",
        "node": "node3",
        "request": request,
        "expected_output": adapter.generate("node3", request),
    }


class EvaluationRunnerTests(unittest.TestCase):
    def test_instruct_2507_checkpoint_is_pinned(self):
        self.assertEqual("Qwen/Qwen3-4B-Instruct-2507", DEFAULT_MODEL)
        self.assertEqual("cdbee75f17c01a7cc42f958dc650907174af0554", DEFAULT_REVISION)

    def test_nearest_rank_percentile_is_deterministic(self):
        observations = [4.0, 1.0, 3.0, 2.0]

        self.assertEqual(2.0, _percentile(observations, 50))
        self.assertEqual(4.0, _percentile(observations, 95))

    def test_captured_comparison_requires_equal_immutable_hashes(self):
        evidence = {
            field: f"{number:064x}"
            for number, field in enumerate(IMMUTABLE_EVIDENCE_FIELDS, start=1)
        }
        self.assertTrue(compare_captured_evidence(evidence, dict(evidence))["comparable"])

        changed = dict(evidence)
        changed["runtime_sha256"] = "f" * 64
        comparison = compare_captured_evidence(evidence, changed)
        self.assertFalse(comparison["comparable"])
        self.assertEqual(["runtime_sha256"], comparison["mismatched_fields"])

        with self.assertRaises(EvidenceError):
            compare_captured_evidence({"model_sha256": "0" * 64}, evidence)

    def test_observed_metrics_keep_unknown_cost_nullable(self):
        self.assertEqual(
            {
                "accuracy": 0.5,
                "p50_ms": 10.0,
                "p95_ms": 20.0,
                "peak_vram_bytes": None,
                "cost_usd": None,
            },
            observed_metrics(
                accuracy=0.5,
                p50_ms=10.0,
                p95_ms=20.0,
                peak_vram_bytes=None,
            ),
        )

    def test_result_and_hash_are_reproducible(self):
        first = evaluate_cases([valid_case()])
        second = evaluate_cases([valid_case()])

        self.assertEqual(first, second)
        self.assertEqual(first["total"], 1)
        self.assertEqual(first["passed"], 1)
        self.assertEqual(first["failed"], 0)

    def test_expected_output_mismatch_fails(self):
        case = valid_case()
        case["expected_output"]["explanation"] = "unsupported"
        result = evaluate_cases([case])
        self.assertEqual(result["failed"], 1)

    def test_missing_extra_and_duplicate_case_ids_are_rejected(self):
        missing = valid_case()
        missing.pop("expected_output")
        with self.assertRaises(EvaluationError):
            evaluate_cases([missing])

        extra = valid_case()
        extra["unexpected"] = True
        with self.assertRaises(EvaluationError):
            evaluate_cases([extra])

        case = valid_case()
        with self.assertRaises(EvaluationError):
            evaluate_cases([case, case])


if __name__ == "__main__":
    unittest.main()
