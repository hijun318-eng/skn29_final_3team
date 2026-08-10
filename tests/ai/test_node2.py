import copy
import unittest

from src.ai.node2 import generate_sql, repair_sql
from src.ai.schema import ContractError
from tests.ai.test_contracts import VALID_PAYLOADS


class Node2Tests(unittest.TestCase):
    def test_sql_and_references_use_only_context(self):
        response = generate_sql(VALID_PAYLOADS["node2_request"])

        self.assertIn("FROM pms.public.reservations", response["sql"])
        self.assertNotIn("current_date", response["sql"].lower())
        self.assertEqual(["stay_date", "room_revenue"], response["references"][0]["columns"])
        self.assertEqual(["period_start", "period_end"], [item["name"] for item in response["parameters"]])

    def test_context_outside_field_is_rejected(self):
        payload = copy.deepcopy(VALID_PAYLOADS["node2_request"])
        payload["context_package"]["metrics"][0]["field"] = "secret.private.revenue"

        with self.assertRaisesRegex(ContractError, "outside Context"):
            generate_sql(payload)

    def test_required_filters_are_parameterized_and_referenced(self):
        payload = copy.deepcopy(VALID_PAYLOADS["node2_request"])
        context = payload["context_package"]
        context["assets"][0]["columns"] += ["is_forecast", "data_period_status"]
        context["metrics"][0]["required_filters"] = [
            {"field": "is_forecast", "operator": "eq", "value": False},
            {"field": "data_period_status", "operator": "eq", "value": "ACTUAL"},
        ]

        response = generate_sql(payload)

        self.assertIn('"data_period_status" = :required_filter_1', response["sql"])
        self.assertIn('"is_forecast" = :required_filter_2', response["sql"])
        self.assertNotIn("ACTUAL", response["sql"])
        self.assertEqual(
            ["period_start", "period_end", "required_filter_1", "required_filter_2"],
            [item["name"] for item in response["parameters"]],
        )
        self.assertEqual(
            ["2026-07-01", "2026-07-30", "ACTUAL", False],
            [item["value"] for item in response["parameters"]],
        )
        self.assertEqual(
            ["stay_date", "room_revenue", "is_forecast", "data_period_status"],
            response["references"][0]["columns"],
        )

        context["metrics"][0]["required_filters"].reverse()
        self.assertEqual(response, generate_sql(payload))

    def test_invalid_and_duplicate_required_filters_are_rejected(self):
        for filters in (
            [
                {"field": "stay_date", "operator": "eq", "value": "2026-07-01"},
                {"field": "stay_date", "operator": "eq", "value": "2026-07-02"},
            ],
            [{"field": "secret", "operator": "eq", "value": "ACTUAL"}],
            [{"field": "stay_date OR 1=1", "operator": "eq", "value": "ACTUAL"}],
            [{"field": "stay_date", "operator": "eq", "value": ""}],
        ):
            payload = copy.deepcopy(VALID_PAYLOADS["node2_request"])
            payload["context_package"]["metrics"][0]["required_filters"] = filters
            with self.subTest(filters=filters):
                with self.assertRaisesRegex(ContractError, "required filter"):
                    generate_sql(payload)

    def test_repair_preserves_required_filter_contract(self):
        payload = copy.deepcopy(VALID_PAYLOADS["node2_repair_request"])
        payload["context_package"]["metrics"][0]["required_filters"] = [
            {"field": "stay_date", "operator": "eq", "value": "2026-07-01"}
        ]

        response = repair_sql(payload)

        self.assertIn('"stay_date" = :required_filter_1', response["corrected_sql"])
        self.assertEqual("required_filter_1", response["parameters"][-1]["name"])

    def test_repair_is_exactly_once_and_uses_normalized_codes(self):
        response = repair_sql(VALID_PAYLOADS["node2_repair_request"])
        self.assertEqual(1, response["attempt"])
        self.assertEqual("trace-1", response["trace_id"])

        unsupported = copy.deepcopy(VALID_PAYLOADS["node2_repair_request"])
        unsupported["normalized_error_code"] = "raw database stack trace"
        with self.assertRaisesRegex(ContractError, "normalized error code"):
            repair_sql(unsupported)


if __name__ == "__main__":
    unittest.main()
