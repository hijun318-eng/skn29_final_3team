import copy
import json
import unittest
from collections import Counter
from pathlib import Path

from evals.runner import (
    EvaluationError,
    compare_runs,
    evaluate_required30,
    validate_data_manifest,
    validate_split_manifest,
)
from tests.support.fakes import ContractFakeModelAdapter as FakeModelAdapter
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
            evaluate_required30(cases[:-1], adapter)
        self.assertEqual(30, evaluate_required30(cases, adapter)["passed"])

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
        declared = source["counts"]
        self.assertEqual(
            {
                "required30": declared["required30"],
                "gold120": declared["gold120_partial"],
            },
            summary["set_counts"],
        )
        self.assertEqual(
            {
                "gold": declared["gold120_partial"],
                "train": 0,
                "validation": declared["required30"],
            },
            summary["split_counts"],
        )
        self.assertEqual(
            dict(Counter(case["status"] for case in source["cases"])),
            summary["status_counts"],
        )
        self.assertEqual("NOT_RUN", summary["model_execution"])

        leaked = copy.deepcopy(source)
        leaked["cases"][30]["paraphrase_group"] = leaked["cases"][0]["paraphrase_group"]
        with self.assertRaisesRegex(EvaluationError, "leaked"):
            validate_data_manifest(leaked)

        wrong_count = copy.deepcopy(source)
        wrong_count["counts"]["required30"] = 29
        with self.assertRaisesRegex(EvaluationError, "count"):
            validate_data_manifest(wrong_count)

        wrong_target = copy.deepcopy(source)
        wrong_target["counts"]["gold120_target"] = 121
        with self.assertRaisesRegex(EvaluationError, "target"):
            validate_data_manifest(wrong_target)

    def test_r2_manifest_accepts_zero_and_full_gold_boundaries(self):
        source = json.loads(
            (ROOT / "src" / "data" / "evaluation_fixture_manifest.i3.v1.json").read_text(
                encoding="utf-8"
            )
        )
        required = [case for case in source["cases"] if case["set"] == "required30"]
        gold_template = next(case for case in source["cases"] if case["set"] == "gold120")

        empty = copy.deepcopy(source)
        empty["counts"]["gold120_partial"] = 0
        empty["cases"] = copy.deepcopy(required)
        self.assertEqual(0, validate_data_manifest(empty)["set_counts"]["gold120"])

        full = copy.deepcopy(source)
        full["counts"]["gold120_partial"] = full["counts"]["gold120_target"]
        full["cases"] = copy.deepcopy(required)
        for number in range(full["counts"]["gold120_target"]):
            case = copy.deepcopy(gold_template)
            case["case_id"] = f"G120-SYN-{number:03d}"
            case["paraphrase_group"] = f"gold-synthetic-{number:03d}"
            full["cases"].append(case)
        summary = validate_data_manifest(full)
        self.assertEqual(full["counts"]["gold120_target"], summary["set_counts"]["gold120"])
        self.assertEqual(
            len(full["cases"]), sum(summary["status_counts"].values())
        )

        over_target = copy.deepcopy(full)
        over_target["counts"]["gold120_partial"] += 1
        with self.assertRaisesRegex(EvaluationError, "partial"):
            validate_data_manifest(over_target)

    def test_external_results_record_serving_and_keep_base_default(self):
        comparison = json.loads(
            (ROOT / "evals" / "base_comparison.v0.1.json").read_text(encoding="utf-8")
        )
        serving = json.loads(
            (ROOT / "src" / "modelops" / "serving_manifest.v0.1.json").read_text(encoding="utf-8")
        )
        self.assertEqual("PASS_BASE_SELECTED", comparison["status"])
        self.assertEqual("PASS", serving["status"])
        split = json.loads(
            (ROOT / "evals" / "split_manifest.v0.1.json").read_text(
                encoding="utf-8"
            )
        )
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
        self.assertEqual("NOT_READY", split["typed_missing"]["gold"]["status"])
        self.assertEqual("DISABLED", split["auto_regeneration"])
        release = json.loads(
            (ROOT / "src" / "modelops" / "release_candidate.i5.v1.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual("DRAFT", release["status"])
        self.assertEqual("NOT_READY", release["readiness"])
        self.assertEqual("Base", release["product_default"])
        self.assertEqual([], release["sql_lora_enabled_nodes"])


class ProductionClientTests(unittest.TestCase):
    def test_success_validates_schema_and_records_attempt(self):
        adapter = FakeModelAdapter()
        client = ProductionModelClient(
            lambda node, payload, timeout: adapter.generate(node, payload)
        )
        output = client.generate("node3", VALID_PAYLOADS["node3_request"])
        self.assertIn("explanation", output)
        self.assertEqual("node3", client.last_trace["node"])
        self.assertEqual("SUCCESS", client.last_trace["status"])
        self.assertEqual(1, client.last_trace["attempts"])
        self.assertFalse(client.last_trace["fallback"])
        self.assertEqual(0, client.last_trace["circuit_failures"])
        self.assertGreaterEqual(client.last_trace["duration_ms"], 0)

    def test_timeout_retries_once_then_fails_without_a_result(self):
        calls = []

        def timeout_transport(node, payload, timeout):
            calls.append(timeout)
            raise TimeoutError("secret upstream detail")

        client = ProductionModelClient(timeout_transport, timeout_seconds=0.5)
        with self.assertRaisesRegex(TimeoutError, "TIMEOUT"):
            client.generate("node1", VALID_PAYLOADS["node1_request"])
        self.assertEqual(2, len(calls))
        self.assertEqual("TIMEOUT", client.last_trace["status"])
        self.assertFalse(client.last_trace["fallback"])
        self.assertNotIn("secret", json.dumps(client.last_trace))

    def test_schema_failure_opens_circuit_after_two_calls(self):
        calls = 0

        def invalid_transport(node, payload, timeout):
            nonlocal calls
            calls += 1
            return {}

        client = ProductionModelClient(invalid_transport, failure_threshold=2)
        with self.assertRaisesRegex(TimeoutError, "SCHEMA_INVALID"):
            client.generate("node1", VALID_PAYLOADS["node1_request"])
        with self.assertRaisesRegex(TimeoutError, "SCHEMA_INVALID"):
            client.generate("node1", VALID_PAYLOADS["node1_request"])
        with self.assertRaisesRegex(TimeoutError, "CIRCUIT_OPEN"):
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
