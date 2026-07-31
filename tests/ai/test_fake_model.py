import unittest

from src.ai.fake_model import FakeModelAdapter
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
