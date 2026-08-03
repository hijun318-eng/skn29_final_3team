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
