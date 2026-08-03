import json
import unittest
from pathlib import Path
from sys import path


BACKEND = Path(__file__).resolve().parents[2] / "app" / "backend"
path.insert(0, str(BACKEND))

from app.adapters import contract_model
from app.adapters.contract_model import ContractModelAdapter, openai_transport
from src.ai.fake_model import FakeModelAdapter
from src.modelops.runtime import ProductionModelClient


class ProductionModelTest(unittest.TestCase):
    def test_transport_uses_fixed_serving_contract(self) -> None:
        captured = {}
        original = contract_model.request_json
        node_payload = self._node2_payload()

        def request(method, url, payload, token, timeout):
            captured.update(
                method=method,
                url=url,
                payload=payload,
                token=token,
                timeout=timeout,
            )
            response = FakeModelAdapter().generate("node2", node_payload)
            return {"choices": [{"message": {"content": json.dumps(response)}}]}

        contract_model.request_json = request
        try:
            result = openai_transport(
                "http://model.local/",
                "secret-token",
                "node2",
                node_payload,
                7.0,
            )
        finally:
            contract_model.request_json = original

        self.assertIn("sql", result)
        self.assertEqual("http://model.local/v1/chat/completions", captured["url"])
        self.assertEqual("secret-token", captured["token"])
        self.assertEqual(0, captured["payload"]["temperature"])
        self.assertEqual(1_500, captured["payload"]["max_tokens"])
        self.assertEqual(
            {"enable_thinking": False},
            captured["payload"]["chat_template_kwargs"],
        )
        self.assertEqual(node_payload, json.loads(captured["payload"]["messages"][1]["content"]))

    def test_fallback_is_rejected_as_product_result(self) -> None:
        client = ProductionModelClient(
            lambda _node, _payload, _timeout: (_ for _ in ()).throw(TimeoutError()),
            failure_threshold=1,
        )
        adapter = ContractModelAdapter(client)

        with self.assertRaisesRegex(TimeoutError, "fallback"):
            adapter._generate("node2", self._node2_payload())
        self.assertTrue(client.last_trace["fallback"])

        with self.assertRaisesRegex(TimeoutError, "fallback"):
            adapter._generate("node2", self._node2_payload())
        self.assertEqual("CIRCUIT_OPEN", client.last_trace["status"])

    @staticmethod
    def _node2_payload():
        return {
            "question_id": "request-1",
            "context_package": {
                "context_version": "CTX-v1",
                "policy_version": "POLICY-v1",
                "execution_time": {
                    "as_of": "2026-08-04T00:00:00+09:00",
                    "timezone": "Asia/Seoul",
                    "calendar_id": "gregorian-kr",
                    "period_start": "2026-08-01T00:00:00+09:00",
                    "period_end_exclusive": "2026-08-04T00:00:00+09:00",
                },
                "assets": [
                    {
                        "urn": "urn:li:dataset:pms",
                        "trino_fqn": "pms.public.pms_stays",
                        "columns": ["room_revenue", "actual_checkout_at"],
                    }
                ],
                "metrics": [
                    {
                        "id": "recognized_room_revenue_krw",
                        "field": "pms.public.pms_stays.room_revenue",
                        "aggregation": "sum",
                        "time_field": "pms.public.pms_stays.actual_checkout_at",
                    }
                ],
                "joins": [],
            },
        }


if __name__ == "__main__":
    unittest.main()
