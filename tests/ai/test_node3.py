import copy
import json
import unittest
from pathlib import Path

from src.ai.node3 import explain_result
from src.ai.schema import ContractError
from tests.ai.test_contracts import VALID_PAYLOADS


class Node3Tests(unittest.TestCase):
    def test_only_describes_g3_pass_shaped_result(self):
        payload = VALID_PAYLOADS["node3_request"]
        result = explain_result(payload)

        self.assertEqual(result, explain_result(payload))
        self.assertIn('"room_revenue":1000', result["explanation"])
        self.assertIn("metrics=room_revenue", result["conditions"])
        self.assertEqual(result["sources"], payload["source_ids"])
        self.assertEqual(result["limitations"], ["masking"])
        self.assertNotIn("authorized", result)
        self.assertNotIn("sql", result)
        self.assertNotIn("gate", result)

    def test_approved_six_asset_derived_metric_is_selected_and_evidence_is_preserved(self):
        context = json.loads(
            Path("src/data/pms_crm_pos_context.i5.v1.json").read_text(encoding="utf-8")
        )
        payload = copy.deepcopy(VALID_PAYLOADS["node3_request"])
        metric_id = "total_guest_revenue_krw"
        payload.update(
            {
                "metric": metric_id,
                "source_ids": [asset["urn"] for asset in context["assets"]],
                "metric_selection": {
                    "selected_metric_id": metric_id,
                    "selected_metric_ids": [metric_id],
                    "context_metric_ids": [metric_id],
                    "entitled_metric_ids": [metric_id],
                },
                "sampling": True,
                "masking": True,
                "partial": True,
                "result_reference": {
                    "kind": "query_execution_id",
                    "value": "G120-046-query",
                },
            }
        )

        result = explain_result(payload)

        self.assertIn(f"metrics={metric_id}", result["conditions"])
        self.assertEqual(payload["source_ids"], result["sources"])
        self.assertEqual(["sampling", "masking", "partial"], result["limitations"])
        self.assertIn("sampling=true", result["conditions"])
        self.assertIn("masking=true", result["conditions"])
        self.assertIn("partial=true", result["conditions"])
        self.assertIn(
            "result_reference=query_execution_id:G120-046-query",
            result["conditions"],
        )

    def test_multi_source_metric_selection_fails_closed(self):
        metric_id = "total_guest_revenue_krw"
        base = copy.deepcopy(VALID_PAYLOADS["node3_request"])
        base.update(
            {
                "metric": metric_id,
                "source_ids": ["source-a", "source-b"],
                "metric_selection": {
                    "selected_metric_id": metric_id,
                    "selected_metric_ids": [metric_id],
                    "context_metric_ids": [metric_id],
                    "entitled_metric_ids": [metric_id],
                },
            }
        )
        invalid = []

        missing_selection = copy.deepcopy(base)
        missing_selection.pop("metric_selection")
        invalid.append(missing_selection)

        mismatched_metrics = copy.deepcopy(base)
        mismatched_metrics["metric_selection"]["context_metric_ids"] = ["other_metric"]
        invalid.append(mismatched_metrics)

        outside_context = copy.deepcopy(base)
        outside_context["metric_selection"]["selected_metric_id"] = "other_metric"
        invalid.append(outside_context)

        outside_entitlement = copy.deepcopy(base)
        outside_entitlement["metric_selection"]["entitled_metric_ids"] = ["other_metric"]
        invalid.append(outside_entitlement)

        missing_context_binding = copy.deepcopy(base)
        missing_context_binding["metric_selection"]["context_metric_ids"].pop()
        invalid.append(missing_context_binding)

        duplicate_source = copy.deepcopy(base)
        duplicate_source["source_ids"][1] = duplicate_source["source_ids"][0]
        invalid.append(duplicate_source)

        for payload in invalid:
            with self.subTest(metric_selection=payload.get("metric_selection")):
                with self.assertRaises(ContractError):
                    explain_result(payload)

    def test_multiple_metrics_are_preserved_in_conditions_and_entitlement(self):
        payload = copy.deepcopy(VALID_PAYLOADS["node3_request"])
        payload["metric_selection"] = {
            "selected_metric_id": "points_sum",
            "selected_metric_ids": ["points_sum", "points_average"],
            "context_metric_ids": ["points_sum", "points_average"],
            "entitled_metric_ids": ["points_average", "points_sum"],
        }
        payload["metric"] = "points_sum"

        result = explain_result(payload)

        self.assertIn("metrics=points_sum,points_average", result["conditions"])

    def test_g3_failure_and_schema_drift_are_rejected(self):
        failed = copy.deepcopy(VALID_PAYLOADS["node3_request"])
        failed["g3_result"] = "fail"
        with self.assertRaises(ContractError):
            explain_result(failed)

        missing = copy.deepcopy(VALID_PAYLOADS["node3_request"])
        missing.pop("result_reference")
        with self.assertRaises(ContractError):
            explain_result(missing)

        extra = copy.deepcopy(VALID_PAYLOADS["node3_request"])
        extra["sql"] = "SELECT 1"
        with self.assertRaises(ContractError):
            explain_result(extra)


if __name__ == "__main__":
    unittest.main()
