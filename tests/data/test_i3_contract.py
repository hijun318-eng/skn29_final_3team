import hashlib
import json
import re
import unittest
from pathlib import Path

from src.data.i3_watermarks import watermark_fingerprint


ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "src/data/i3_contract.v1.json"
REGISTRY = ROOT / "src/data/source_registry.v1.json"


class I3ContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        cls.registry = json.loads(REGISTRY.read_text(encoding="utf-8"))

    def test_five_recipes_have_stable_identity_and_known_env(self):
        recipes = self.contract["metadata"]["recipes"]
        self.assertEqual({"pms", "pos", "crm", "facility", "banquet"}, {item["source_id"] for item in recipes})
        self.assertEqual(5, len({item["ingestion_id"] for item in recipes}))
        env_names = {
            line.split("=", 1)[0]
            for line in (ROOT / "infrastructure/database/.env.example").read_text(encoding="utf-8").splitlines()
            if "=" in line and not line.startswith("#")
        }
        for item in recipes:
            recipe = (ROOT / item["file"]).read_text(encoding="utf-8")
            self.assertEqual("CONFIG_VALIDATED", item["status"])
            self.assertIn(f"platform_instance: {item['platform_instance']}", recipe)
            self.assertFalse(set(re.findall(r"\$\{([A-Z0-9_]+)\}", recipe)) - env_names)
            self.assertTrue(item["dataset_urn"].startswith("urn:li:dataset:"))
            self.assertGreaterEqual(len(item["fqn"].split(".")), 3)
            source = next(source for source in self.registry["sources"] if source["source_id"] == item["source_id"])
            self.assertIn("type: simple_add_ownership", recipe)
            self.assertIn(f"urn:li:corpuser:{source['data_owner']}", recipe)

    def test_catalog_hashes_and_type_mappings_are_lossless(self):
        checks = self.contract["catalog_checks"]
        self.assertEqual(5, len(checks))
        for item in checks:
            digest = hashlib.sha256((item["canonical_row"] + "\n").encode()).hexdigest()
            self.assertEqual(item["sha256"], digest)
            self.assertTrue(item["query"].startswith("SELECT"))
        self.assertTrue(all(item["lossless"] for item in self.contract["type_mappings"]))
        semantic_types = {item["semantic_type"] for item in self.contract["type_mappings"]}
        self.assertTrue({"money_krw", "event_time", "source_local_id", "watermark_utc"} <= semantic_types)

    def test_approved_two_and_three_source_joins_are_read_only_and_complete(self):
        joins = self.contract["approved_joins"]
        self.assertEqual([2, 3], [len(item["sources"]) for item in joins])
        for item in joins:
            self.assertEqual(1, item["amplification_limit"])
            sql = (ROOT / item["sql_file"]).read_text(encoding="utf-8").lower()
            self.assertNotIn("current_date", sql)
            self.assertNotIn("now()", sql)
            for source in item["sources"]:
                self.assertIn(f"{source}.", sql)

    def test_watermark_contract_is_complete(self):
        watermark = self.contract["watermark_set"]
        self.assertEqual(5, len(watermark["values"]))
        self.assertEqual(watermark["sha256"], watermark_fingerprint(watermark["values"]))


if __name__ == "__main__":
    unittest.main()
