import copy
import json
import unittest
from pathlib import Path

from evals.runner import (
    EvaluationError,
    compare_runs,
    evaluate_required30,
    validate_data_manifest,
    validate_split_manifest,
)
from src.ai.fake_model import FakeModelAdapter
from src.modelops.runtime import ProductionModelClient, build_trace
from tests.ai.test_contracts import VALID_PAYLOADS


ROOT = Path(__file__).resolve().parents[2]


class Wave3EvaluationTests(unittest.TestCase):
    def test_required30_rejects_partial_and_runs_complete_manifest(self):
        adapter = FakeModelAdapter()
        request = VALID_PAYLOADS["node1_request"]
        expected = adapter.generate("node1", request)
        cases = [
            {
                "case_id": f"required30-local-{number:02d}",
                "node": "node1",
                "request": request,
                "expected_output": expected,
            }
            for number in range(30)
        ]
        with self.assertRaisesRegex(EvaluationError, "exactly 30"):
            evaluate_required30(cases[:-1])
        self.assertEqual(30, evaluate_required30(cases)["passed"])

    def test_base_comparison_requires_same_conditions_and_cases(self):
        baseline = {
            "conditions": {"prompt": "PROMPT-v1.0.0", "temperature": 0},
            "cases": [{"case_id": "case-1", "passed": True}],
            "latencies_ms": [10, 20],
            "resources": {"gpu": "local-fake"},
            "cost_usd": 0,
        }
        candidate = copy.deepcopy(baseline)
        candidate["latencies_ms"] = [12, 24]
        result = compare_runs(baseline, candidate)
        self.assertEqual(1.0, result["baseline"]["accuracy"])
        self.assertEqual(24.0, result["candidate"]["p95_ms"])

        candidate["conditions"]["temperature"] = 1
        with self.assertRaisesRegex(EvaluationError, "identical"):
            compare_runs(baseline, candidate)

    def test_r2_manifest_counts_and_split_are_consumed(self):
        source = json.loads(
            (ROOT / "src" / "data" / "evaluation_fixture_manifest.i3.v1.json").read_text(
                encoding="utf-8"
            )
        )
        summary = validate_data_manifest(source)
        self.assertEqual({"required30": 30, "gold120": 5}, summary["set_counts"])
        self.assertEqual(
            {"gold": 5, "train": 0, "validation": 30},
            summary["split_counts"],
        )
        self.assertEqual({"REVIEW": 35}, summary["status_counts"])
        self.assertEqual("NOT_RUN", summary["model_execution"])

        leaked = copy.deepcopy(source)
        leaked["cases"][30]["paraphrase_group"] = leaked["cases"][0]["paraphrase_group"]
        with self.assertRaisesRegex(EvaluationError, "leaked"):
            validate_data_manifest(leaked)

        wrong_count = copy.deepcopy(source)
        wrong_count["counts"]["required30"] = 29
        with self.assertRaisesRegex(EvaluationError, "counts"):
            validate_data_manifest(wrong_count)

    def test_external_results_are_explicitly_not_run(self):
        comparison = json.loads(
            (ROOT / "evals" / "base_comparison.v0.1.json").read_text(encoding="utf-8")
        )
        serving = json.loads(
            (ROOT / "src" / "modelops" / "serving_manifest.v0.1.json").read_text(encoding="utf-8")
        )
        self.assertEqual("NOT_RUN", comparison["status"])
        self.assertEqual("NOT_RUN", serving["status"])
        split = json.loads(
            (ROOT / "evals" / "split_manifest.v0.1.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertIn("checkpoint", comparison["reason"])
        self.assertEqual(2, serving["runtime"]["max_concurrency"])
        self.assertTrue(serving["storage"]["external_backup_required_before_shutdown"])


class ProductionClientTests(unittest.TestCase):
    def test_success_validates_schema_and_records_attempt(self):
        adapter = FakeModelAdapter()
        client = ProductionModelClient(
            lambda node, payload, timeout: adapter.generate(node, payload)
        )
        output = client.generate("node3", VALID_PAYLOADS["node3_request"])
        self.assertIn("explanation", output)
        self.assertEqual(
            {"status": "SUCCESS", "attempts": 1, "fallback": False, "circuit_failures": 0},
            client.last_trace,
        )

    def test_timeout_retries_once_then_uses_redacted_fallback(self):
        calls = []

        def timeout_transport(node, payload, timeout):
            calls.append(timeout)
            raise TimeoutError("secret upstream detail")

        client = ProductionModelClient(timeout_transport, timeout_seconds=0.5)
        output = client.generate("node1", VALID_PAYLOADS["node1_request"])
        self.assertEqual(2, len(calls))
        self.assertEqual("TIMEOUT", client.last_trace["status"])
        self.assertNotIn("secret", json.dumps(client.last_trace))
        self.assertIn("normalized_question", output)

    def test_schema_failure_opens_circuit_after_two_calls(self):
        calls = 0

        def invalid_transport(node, payload, timeout):
            nonlocal calls
            calls += 1
            return {}

        client = ProductionModelClient(invalid_transport, failure_threshold=2)
        client.generate("node1", VALID_PAYLOADS["node1_request"])
        client.generate("node1", VALID_PAYLOADS["node1_request"])
        client.generate("node1", VALID_PAYLOADS["node1_request"])
        self.assertEqual(4, calls)
        self.assertEqual("CIRCUIT_OPEN", client.last_trace["status"])
        self.assertEqual(0, client.last_trace["attempts"])

    def test_trace_is_reproducible_and_unknown_cost_stays_null(self):
        adapter = FakeModelAdapter()
        request = VALID_PAYLOADS["node3_request"]
        output = adapter.generate("node3", request)
        arguments = {
            "trace_id": "trace-wave3",
            "node": "node3",
            "input_payload": request,
            "output_payload": output,
            "latency_ms": 3.0,
        }
        first = build_trace(**arguments)
        self.assertEqual(first, build_trace(**arguments))
        self.assertIsNone(first["cost_usd"])
        self.assertEqual(64, len(first["payload_hash"]))


if __name__ == "__main__":
    unittest.main()
