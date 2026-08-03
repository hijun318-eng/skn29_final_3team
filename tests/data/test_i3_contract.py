import hashlib
import json
import re
import unittest
from collections import Counter, defaultdict
from pathlib import Path

from src.data.i3_watermarks import watermark_fingerprint


ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "src/data/i3_contract.v1.json"
MANIFEST = ROOT / "src/data/evaluation_fixture_manifest.i3.v1.json"


class I3ContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        cls.manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

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

    def test_approved_two_and_three_source_joins_have_fixed_hashes(self):
        joins = self.contract["approved_joins"]
        self.assertEqual([2, 3], [len(item["sources"]) for item in joins])
        for item in joins:
            self.assertEqual(1, item["amplification_limit"])
            sql = (ROOT / item["sql_file"]).read_text(encoding="utf-8").lower()
            self.assertNotIn("current_date", sql)
            self.assertNotIn("now()", sql)
            for source in item["sources"]:
                self.assertIn(f"{source}.", sql)
        for fixture in self.contract["gold_fixtures"]:
            canonical = "".join("|".join(row) + "\n" for row in fixture["rows"])
            self.assertEqual(fixture["sha256"], hashlib.sha256(canonical.encode()).hexdigest())

    def test_watermark_and_failure_contract_are_complete(self):
        watermark = self.contract["watermark_set"]
        self.assertEqual(5, len(watermark["values"]))
        self.assertEqual(watermark["sha256"], watermark_fingerprint(watermark["values"]))
        errors = {item["expected_error"] for item in self.contract["failure_fixtures"]}
        self.assertTrue({"UNAPPROVED_JOIN", "CARDINALITY_AMPLIFICATION", "TYPE_LOSS", "WATERMARK_DRIFT", "NOT_FOUND", "FORBIDDEN", "TIMEOUT", "CANCELLED", "PARTIAL"} <= errors)

    def test_required30_and_gold_partial_follow_case_schema(self):
        required_fields = {
            "case_id", "set", "category", "paraphrase_group", "split", "question",
            "role_policy", "time_context", "expected_outcome", "expected_state_error",
            "sources", "versions", "reviewers", "evidence", "status",
        }
        cases = self.manifest["cases"]
        self.assertEqual(len(cases), len({item["case_id"] for item in cases}))
        counts = Counter(item["set"] for item in cases)
        self.assertEqual({"required30": 30, "gold120": 5}, dict(counts))
        categories = Counter(item["category"] for item in cases if item["set"] == "required30")
        self.assertEqual({"단일 source": 10, "cross-source": 10, "모호성·근거 부족": 5, "권한·금지 요청": 5}, dict(categories))
        splits = defaultdict(set)
        for item in cases:
            self.assertFalse(required_fields - item.keys())
            if item["expected_outcome"] == "성공":
                self.assertIn("expected_query_result", item)
            splits[item["paraphrase_group"]].add(item["split"])
            self.assertTrue(item["evidence"])
            self.assertEqual("REVIEW", item["status"])
        self.assertTrue(all(len(value) == 1 for value in splits.values()))


if __name__ == "__main__":
    unittest.main()
