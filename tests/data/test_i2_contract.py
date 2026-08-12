import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "src" / "data" / "i2_contract.v1.json"
I1_CONTRACT = ROOT / "src" / "data" / "r2_w1_contract.v1.json"
REGISTRY = ROOT / "src" / "data" / "source_registry.v1.json"


class I2ContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        cls.i1 = json.loads(I1_CONTRACT.read_text(encoding="utf-8"))
        cls.registry = json.loads(REGISTRY.read_text(encoding="utf-8"))

    def test_i1_versions_and_approved_join_are_reused(self):
        self.assertEqual("I2-v1.0.0", self.contract["contract_version"])
        self.assertEqual(self.i1["contract_version"], self.contract["input_contract_version"])
        for field in ("schema_version", "seed_version", "scenario_version"):
            self.assertEqual(self.i1[field], self.contract[field])
        self.assertEqual(
            self.registry["approved_joins"][0]["join_id"],
            self.contract["approved_join"]["join_id"],
        )
        self.assertEqual(1, self.contract["approved_join"]["amplification_limit"])

    def test_pms_crm_recipes_and_lineage_are_complete(self):
        recipes = self.contract["metadata"]["recipes"]
        env_names = {
            line.split("=", 1)[0]
            for line in (ROOT / "infrastructure/database/.env.example").read_text(
                encoding="utf-8"
            ).splitlines()
            if "=" in line and not line.startswith("#")
        }
        self.assertEqual({"pms", "crm"}, {recipe["source_id"] for recipe in recipes})
        for recipe in recipes:
            text = (ROOT / recipe["file"]).read_text(encoding="utf-8")
            self.assertIn("platform_instance:", text)
            self.assertIn("${", text)
            self.assertNotIn("CHANGE_ME", text)
            self.assertFalse(set(re.findall(r"\$\{([A-Z0-9_]+)\}", text)) - env_names)
            self.assertTrue(recipe["dataset_urn"].startswith("urn:li:dataset:"))
            self.assertEqual(3, len(recipe["fqn"].split(".")))
        upstream = self.contract["metadata"]["lineage"][0]["upstream"]
        self.assertEqual(5, len(upstream))
        self.assertTrue(any(name.startswith("pms.") for name in upstream))
        self.assertTrue(any(name.startswith("crm.") for name in upstream))

    def test_type_mapping_is_lossless_for_money_time_and_ids(self):
        mappings = self.contract["type_mappings"]
        self.assertTrue(all(mapping["lossless"] for mapping in mappings))
        joined = json.dumps(mappings)
        for token in ("decimal(18,2)", "timestamp(3)", "varchar"):
            self.assertIn(token, joined)

    def test_approved_join_sql_uses_fixed_period_and_complete_lineage(self):
        sql = (ROOT / self.contract["approved_join"]["sql_file"]).read_text(encoding="utf-8")
        self.assertNotIn("current_date", sql.lower())
        self.assertNotIn("now()", sql.lower())
        for table in self.contract["metadata"]["lineage"][0]["upstream"]:
            self.assertIn(table, sql)


if __name__ == "__main__":
    unittest.main()
