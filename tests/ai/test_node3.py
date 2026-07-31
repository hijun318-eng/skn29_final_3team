import copy
import unittest

from src.ai.node3 import explain_result
from src.ai.schema import ContractError
from tests.ai.test_contracts import VALID_PAYLOADS


class Node3Tests(unittest.TestCase):
    def test_only_describes_g3_pass_shaped_result(self):
        payload = VALID_PAYLOADS["node3_request"]
        result = explain_result(payload)

        self.assertEqual(result, explain_result(payload))
        self.assertIn('"room_revenue":1000', result["explanation"])
        self.assertIn("metric=room_revenue", result["conditions"])
        self.assertEqual(result["sources"], payload["source_ids"])
        self.assertEqual(result["limitations"], ["masking"])
        self.assertNotIn("authorized", result)
        self.assertNotIn("sql", result)
        self.assertNotIn("gate", result)

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
