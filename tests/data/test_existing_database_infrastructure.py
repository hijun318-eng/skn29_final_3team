import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class ExistingDatabaseInfrastructureTest(unittest.TestCase):
    def test_datahub_kafka_health_uses_real_cli(self):
        compose = (
            ROOT / "infrastructure/database/datahub/compose.consumer.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("kafka-topics --bootstrap-server broker:29092 --list", compose)
        self.assertNotIn("nc -z broker 29092", compose)

    def test_ingestion_system_metadata_access_is_narrow(self):
        access = json.loads(
            (
                ROOT / "infrastructure/database/trino/etc/access-control-rules.json"
            ).read_text(encoding="utf-8")
        )
        catalogs = [
            rule for rule in access["catalogs"]
            if rule.get("user") == "datahub_ingestion"
        ]
        self.assertEqual(
            [
                {
                    "user": "datahub_ingestion",
                    "catalog": "system",
                    "allow": "read-only",
                },
                {
                    "user": "datahub_ingestion",
                    "catalog": "(serving|pms|pos|crm|facility|banquet)",
                    "allow": "read-only",
                },
            ],
            catalogs,
        )
        tables = [
            rule for rule in access["tables"]
            if rule.get("user") == "datahub_ingestion"
        ]
        self.assertEqual("metadata", tables[0]["schema"])
        self.assertEqual("(catalogs|table_comments)", tables[0]["table"])
        self.assertEqual(["SELECT"], tables[0]["privileges"])
        self.assertEqual([], tables[1]["privileges"])

    def test_trino_catalog_allows_are_bound_to_authenticated_principals(self):
        access = json.loads(
            (
                ROOT / "infrastructure/database/trino/etc/access-control-rules.json"
            ).read_text(encoding="utf-8")
        )
        for rule in access["catalogs"]:
            if rule["allow"] != "none":
                self.assertIn("user", rule)
        self.assertEqual({"catalog": ".*", "allow": "none"}, access["catalogs"][-1])
        self.assertEqual({"allow": []}, access["queries"][-1])


if __name__ == "__main__":
    unittest.main()
