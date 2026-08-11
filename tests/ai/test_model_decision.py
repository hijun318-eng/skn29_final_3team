import json
import unittest
from pathlib import Path


class ModelDecisionTests(unittest.TestCase):
    def test_wave1_scope_keeps_p2_and_sql_lora_out(self):
        path = Path("src/modelops/model_decision.v0.1.json")
        decision = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(decision["decision_version"], "MODEL-v1.0.0")
        self.assertEqual(decision["product_default"], "Base")
        self.assertEqual(decision["release_candidate_status"], "DRAFT")
        self.assertEqual(decision["release_readiness"], "NOT_READY")
        self.assertEqual(
            decision["scope"]["excluded_until_i5_followup"],
            ["mcp", "document_rag", "ml_as_a_tool", "customer_360"],
        )
        self.assertTrue(decision["runtime_boundary"]["all_nodes_use_base_model"])
        self.assertEqual(decision["runtime_boundary"]["base_model_version"], "DRAFT-BASE-v0.1")
        self.assertEqual(decision["runtime_boundary"]["sql_lora_enabled_nodes"], [])
        self.assertFalse(decision["runtime_boundary"]["node1_or_node3_sql_lora"])
        self.assertFalse(decision["runtime_boundary"]["model_may_decide_authorization"])
        self.assertFalse(decision["runtime_boundary"]["model_may_decide_sql_execution"])
        self.assertFalse(decision["runtime_boundary"]["model_may_decide_gates"])


if __name__ == "__main__":
    unittest.main()
