import copy
import json
import unittest
from pathlib import Path

from evals.runner import (
    EvaluationError,
    compare_runs,
    evaluate_required30,
)
from src.ai.node1 import normalize_question
from src.ai.node3 import explain_result
from src.modelops.runtime import ModelUnavailableError, ProductionModelClient, build_trace
from tests.ai.test_contracts import VALID_PAYLOADS


ROOT = Path(__file__).resolve().parents[2]


class Wave3EvaluationTests(unittest.TestCase):
    def test_required30_rejects_partial_and_runs_complete_manifest(self):
        request = VALID_PAYLOADS["node1_request"]
        expected = normalize_question(request)
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
            "resources": {"gpu": "local-cpu"},
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

    def test_external_results_record_serving_and_keep_base_default(self):
        comparison = json.loads(
            (ROOT / "evals" / "base_comparison.v0.1.json").read_text(encoding="utf-8")
        )
        serving = json.loads(
            (ROOT / "src" / "modelops" / "serving_manifest.v0.1.json").read_text(encoding="utf-8")
        )
        self.assertEqual("PASS_BASE_SELECTED", comparison["status"])
        self.assertEqual("PASS", serving["status"])
        self.assertEqual("Base", comparison["decision"]["product_default"])
        self.assertEqual("Base", serving["product_default"])
        self.assertFalse(comparison["captured_evidence"]["comparison"]["comparable"])
        self.assertEqual("NOT_READY", comparison["captured_evidence"]["comparison"]["status"])
        self.assertEqual(0.0, comparison["observed_metrics"]["Base"]["accuracy"])
        self.assertIsNone(comparison["observed_metrics"]["LoRA"]["cost_usd"])
        self.assertEqual(724.472, serving["observed"]["p50_ms"])
        self.assertIsNone(serving["observed"]["cost_usd"])
        self.assertEqual(2, serving["runtime"]["max_concurrency"])
        self.assertTrue(serving["verification"]["restart_same_revision"])
        self.assertTrue(serving["cost_and_cleanup"]["pod_deleted_404"])
        self.assertLess(
            serving["cost_and_cleanup"]["projected_cumulative_cost_usd"],
            serving["cost_and_cleanup"]["cumulative_limit_usd"],
        )
        release = json.loads(
            (ROOT / "src" / "modelops" / "release_candidate.i5.v1.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual("SERVERLESS_SMOKE_VERIFIED", release["status"])
        self.assertEqual("ENDPOINT_ADVERTISES_ALIAS", release["readiness"])
        execution = release["typed_missing"]["model_execution"]
        self.assertEqual("SMOKE_PASS", execution["status"])
        self.assertEqual(0, execution["workers_min_after_test"])
        self.assertEqual("answervice-sql-lora-qwen3.5-4b", release["product_default"])
        self.assertEqual("Qwen/Qwen3.5-4B", release["base_model"])
        self.assertEqual(["node2", "node2_repair"], release["sql_lora_enabled_nodes"])


class ProductionClientTests(unittest.TestCase):
    def test_success_validates_schema_and_records_attempt(self):
        client = ProductionModelClient(
            lambda node, payload, timeout: explain_result(payload)
        )
        output = client.generate("node3", VALID_PAYLOADS["node3_request"])
        self.assertIn("explanation", output)
        self.assertEqual(
            {"status": "SUCCESS", "attempts": 1, "circuit_failures": 0},
            client.last_trace,
        )

    def test_timeout_retries_once_then_fails_closed_without_leaking_detail(self):
        calls = []

        def timeout_transport(node, payload, timeout):
            calls.append(timeout)
            raise TimeoutError("secret upstream detail")

        client = ProductionModelClient(timeout_transport, timeout_seconds=0.5)
        with self.assertRaisesRegex(ModelUnavailableError, "TIMEOUT"):
            client.generate("node1", VALID_PAYLOADS["node1_request"])
        self.assertEqual(2, len(calls))
        self.assertEqual("TIMEOUT", client.last_trace["status"])
        self.assertNotIn("secret", json.dumps(client.last_trace))

    def test_schema_failure_opens_circuit_after_two_calls(self):
        calls = 0

        def invalid_transport(node, payload, timeout):
            nonlocal calls
            calls += 1
            return {}

        client = ProductionModelClient(invalid_transport, failure_threshold=2)
        for _ in range(3):
            with self.assertRaises(ModelUnavailableError):
                client.generate("node1", VALID_PAYLOADS["node1_request"])
        self.assertEqual(4, calls)
        self.assertEqual("CIRCUIT_OPEN", client.last_trace["status"])
        self.assertEqual(0, client.last_trace["attempts"])

    def test_trace_is_reproducible_and_unknown_cost_stays_null(self):
        request = VALID_PAYLOADS["node3_request"]
        output = explain_result(request)
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
