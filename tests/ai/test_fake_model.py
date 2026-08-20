import copy
import unittest

from src.ai.schema import ContractError
from tests.ai.test_contracts import VALID_PAYLOADS
from tests.support.fakes import ContractFakeModelAdapter


class ContractFakeModelTests(unittest.TestCase):
    def test_requires_an_explicit_programmed_response(self):
        with self.assertRaisesRegex(AssertionError, "no programmed response"):
            ContractFakeModelAdapter().generate(
                "node2", copy.deepcopy(VALID_PAYLOADS["node2_request"])
            )

    def test_request_is_validated_before_the_queue_is_consumed(self):
        adapter = ContractFakeModelAdapter(VALID_PAYLOADS["node2_response"])
        invalid = copy.deepcopy(VALID_PAYLOADS["node2_request"])
        invalid["unexpected"] = True

        with self.assertRaises(ContractError):
            adapter.generate("node2", invalid)

        self.assertEqual(1, adapter.remaining)
        self.assertEqual(
            VALID_PAYLOADS["node2_response"],
            adapter.generate("node2", VALID_PAYLOADS["node2_request"]),
        )

    def test_response_schema_is_validated(self):
        partial_lineage = {
            "sql": "SELECT 1 LIMIT 1",
            "used_assets": ["arbitrary_catalog.semantic.fact"],
        }
        adapter = ContractFakeModelAdapter(partial_lineage)

        with self.assertRaises(ContractError):
            adapter.generate("node2", VALID_PAYLOADS["node2_request"])

        sql_only = ContractFakeModelAdapter({"sql": "SELECT 1 LIMIT 1"})
        self.assertEqual(
            {"sql": "SELECT 1 LIMIT 1"},
            sql_only.generate("node2", VALID_PAYLOADS["node2_request"]),
        )

    def test_callable_queue_receives_a_copy_and_returns_an_independent_copy(self):
        observed = {}

        def programmed(node, request):
            observed.update(node=node, request=request)
            request["question_id"] = "mutated-inside-callable"
            return VALID_PAYLOADS["node2_response"]

        original = copy.deepcopy(VALID_PAYLOADS["node2_request"])
        adapter = ContractFakeModelAdapter([programmed])

        response = adapter.generate("node2", original)
        response["used_assets"].append("caller-mutation")

        self.assertEqual("node2", observed["node"])
        self.assertNotEqual("mutated-inside-callable", original["question_id"])
        self.assertNotIn("caller-mutation", adapter.calls[0]["response"]["used_assets"])


if __name__ == "__main__":
    unittest.main()
