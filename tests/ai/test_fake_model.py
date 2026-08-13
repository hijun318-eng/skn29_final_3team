import unittest
from copy import deepcopy

from tests.support.fakes import ContractFakeModelAdapter as FakeModelAdapter
from src.ai.schema import ContractError
from tests.ai.test_contracts import VALID_PAYLOADS


class FakeModelTests(unittest.TestCase):
    def test_all_node_outputs_are_deterministic(self):
        adapter = FakeModelAdapter()
        for node in ("node1", "node2", "node2_repair", "node3"):
            payload = VALID_PAYLOADS[f"{node}_request"]
            with self.subTest(node=node):
                self.assertEqual(adapter.generate(node, payload), adapter.generate(node, payload))

    def test_invalid_input_is_rejected_before_generation(self):
        payload = dict(VALID_PAYLOADS["node2_request"], approved=True)
        with self.assertRaises(ContractError):
            FakeModelAdapter().generate("node2", payload)

    def test_node1_prefers_specific_alias_but_keeps_generic_ambiguity(self):
        payload = deepcopy(VALID_PAYLOADS["node1_request"])
        payload["business_terms"] = {
            "recognized_room_revenue": {
                "kind": "metric",
                "aliases": ["객실 매출", "체크아웃 기준 객실 매출"],
            },
            "stay_day_allocated_room_revenue": {
                "kind": "metric",
                "aliases": ["객실 매출", "숙박일 기준 객실 매출"],
            },
        }

        payload["question"] = "이번 달 체크아웃 기준 객실 매출을 보여줘"
        specific = FakeModelAdapter().generate("node1", payload)
        self.assertEqual("recognized_room_revenue", specific["selected_metric_id"])

        payload["question"] = "이번 달 객실 매출을 보여줘"
        generic = FakeModelAdapter().generate("node1", payload)
        self.assertIsNone(generic["selected_metric_id"])
        self.assertIn("metric_ambiguous", generic["ambiguity"]["reasons"])

    def test_output_tracks_fixture_version_and_context_references(self):
        adapter = FakeModelAdapter()
        output = adapter.generate("node2", VALID_PAYLOADS["node2_request"])
        self.assertEqual(adapter.version, "MODEL-FIXTURE-v1.0.0")
        self.assertEqual(output["model"]["model_version"], adapter.model_version)
        self.assertEqual(output["model"]["fixture_version"], adapter.version)
        self.assertEqual(
            output["references"][0],
            {
                "urn": "urn:li:dataset:pms-reservations",
                "trino_fqn": "pms.public.reservations",
                "columns": ["stay_date", "room_revenue"],
                "join_ids": [],
                "metric_ids": ["room_revenue"],
            },
        )


if __name__ == "__main__":
    unittest.main()
