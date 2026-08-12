import json
import unittest
from pathlib import Path


class ModelDecisionTests(unittest.TestCase):
    def test_node2_and_repair_use_qwen35_sql_lora_only(self):
        path = Path("src/modelops/model_decision.v0.1.json")
        decision = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(decision["decision_version"], "MODEL-v1.0.0")
        self.assertEqual(decision["product_default"], "answervice-sql-lora-qwen3.5-4b")
        self.assertEqual(decision["release_candidate_status"], "SERVERLESS_SMOKE_VERIFIED")
        self.assertEqual(decision["release_readiness"], "ENDPOINT_ADVERTISES_ALIAS")
        self.assertEqual(decision["external_actions"]["deployment"], "workers_min_0")
        self.assertEqual(
            decision["scope"]["excluded_until_i5_followup"],
            ["mcp", "document_rag", "ml_as_a_tool", "customer_360"],
        )
        self.assertFalse(decision["runtime_boundary"]["all_nodes_use_base_model"])
        self.assertEqual(decision["runtime_boundary"]["base_model_version"], "Qwen/Qwen3.5-4B")
        self.assertEqual(
            decision["runtime_boundary"]["node2_model_alias"],
            "answervice-sql-lora-qwen3.5-4b",
        )
        self.assertEqual(
            decision["runtime_boundary"]["sql_lora_enabled_nodes"],
            ["node2", "node2_repair"],
        )
        self.assertFalse(decision["runtime_boundary"]["node1_or_node3_sql_lora"])
        self.assertFalse(decision["runtime_boundary"]["model_may_decide_authorization"])
        self.assertFalse(decision["runtime_boundary"]["model_may_decide_sql_execution"])
        self.assertFalse(decision["runtime_boundary"]["model_may_decide_gates"])


if __name__ == "__main__":
    unittest.main()
