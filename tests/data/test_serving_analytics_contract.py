import ast
import hashlib
import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = ROOT / "src/data/serving_analytics_contract.i4.v1.json"
RECIPE_PATH = ROOT / "infrastructure/database/datahub/recipes/serving.i4.yml"
DATAHUB_COMPOSE_PATH = ROOT / "infrastructure/database/datahub/compose.consumer.yml"
ACCESS_PATH = ROOT / "infrastructure/database/trino/etc/access-control-rules.json"
TRAINING_PATH = ROOT / "src/ai/training/build_case_specs.py"


class ServingAnalyticsContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
        cls.views = {item["fqn"]: item for item in cls.contract["views"]}
        cls.recipe = RECIPE_PATH.read_text(encoding="utf-8")
        cls.datahub_compose = DATAHUB_COMPOSE_PATH.read_text(encoding="utf-8")
        cls.access = json.loads(ACCESS_PATH.read_text(encoding="utf-8"))

    def test_recipe_allowlists_exactly_eight_views(self):
        allowed = set(re.findall(r"'(serving\\\.analytics\\\.[a-z_]+)'", self.recipe))
        expected = {fqn.replace(".", r"\.") for fqn in self.views}
        self.assertEqual(expected, allowed)
        for setting in (
            "type: trino",
            "database: serving",
            "username: datahub_ingestion",
            "include_tables: false",
            "include_views: true",
            "include_view_lineage: true",
            "include_view_column_lineage: true",
        ):
            self.assertIn(setting, self.recipe)
        self.assertNotIn("platform_instance:", self.recipe)

    def test_datahub_uses_internal_schema_registry(self):
        for setting in (
            "KAFKA_SCHEMAREGISTRY_URL: http://datahub-gms:8080/schema-registry/api/",
            "DATAHUB_UPGRADE_HISTORY_KAFKA_CONSUMER_GROUP_ID: generic-duhe-consumer-job-client-gms",
            'KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR: "1"',
            'METADATA_SERVICE_AUTH_ENABLED: "false"',
            'MCP_CONSUMER_BATCH_ENABLED: "true"',
            'MCL_CONSUMER_BATCH_ENABLED: "true"',
            "SCHEMA_REGISTRY_TYPE: INTERNAL",
            'USE_CONFLUENT_SCHEMA_REGISTRY: "false"',
            "GRAPH_SERVICE_IMPL: elasticsearch",
            "ENTITY_REGISTRY_CONFIG_PATH: /datahub/datahub-gms/resources/entity-registry.yml",
            "EBEAN_DATASOURCE_URL: jdbc:mysql://mysql:3306/datahub?",
        ):
            self.assertIn(setting, self.datahub_compose)
        self.assertIn('system-update-quickstart:\n    <<: *datahub-service\n    restart: "no"', self.datahub_compose)

    def test_view_contract_has_stable_identity_columns_and_lineage(self):
        self.assertEqual("LIVE_DATAHUB", self.contract["context_source"])
        self.assertTrue(self.contract["validation_only"])
        self.assertEqual(8, len(self.views))
        self.assertEqual(116, sum(len(view["columns"]) for view in self.views.values()))
        for fqn, view in self.views.items():
            self.assertEqual(fqn.rsplit(".", 1)[1], view["name"])
            self.assertEqual(
                f"urn:li:dataset:(urn:li:dataPlatform:trino,{fqn},PROD)",
                view["urn"],
            )
            self.assertTrue(view["synthetic"])
            self.assertEqual(self.contract["schema_version"], view["schema_version"])
            self.assertEqual(self.contract["seed_version"], view["seed_version"])
            self.assertTrue(view["columns"])
            self.assertTrue(view["upstream_fqns"])

    def test_training_serving_context_is_a_contract_subset(self):
        tree = ast.parse(TRAINING_PATH.read_text(encoding="utf-8"))
        training = {}
        for node in tree.body:
            if not isinstance(node, ast.Assign):
                continue
            if not any(isinstance(target, ast.Name) and target.id == "SOURCES" for target in node.targets):
                continue
            for call in node.value.values:
                fqn = ast.literal_eval(call.args[0])
                training.setdefault(fqn, set()).update(ast.literal_eval(call.args[4]))
        self.assertEqual(
            {
                "serving.analytics.banquet_monthly_metrics",
                "serving.analytics.facility_daily_metrics",
                "serving.analytics.fnb_daypart_metrics",
                "serving.analytics.hotel_daily_metrics",
            },
            set(training),
        )
        for fqn, columns in training.items():
            self.assertLessEqual(columns, set(self.views[fqn]["columns"]))

    def test_setup_can_delegate_view_reads_without_runtime_escalation(self):
        catalogs = self.access["catalogs"]
        setup_source = next(
            item for item in catalogs
            if item.get("user") == "hotel_synthetic_setup" and item.get("catalog") == "(pms|pos|crm|facility|banquet)"
        )
        self.assertEqual("all", setup_source["allow"])
        setup_tables = [item for item in self.access["tables"] if item.get("user") == "hotel_synthetic_setup"]
        self.assertEqual(2, len(setup_tables))
        self.assertTrue(all("GRANT_SELECT" in item["privileges"] for item in setup_tables))
        self.assertTrue(all(
            "GRANT_SELECT" not in item["privileges"]
            for item in self.access["tables"] if "user" not in item
        ))
        runtime = next(
            item for item in self.access["catalogs"]
            if "user" not in item and item.get("catalog") == "(serving|pms|pos|crm|facility|banquet)"
        )
        self.assertEqual("read-only", runtime["allow"])

    def test_recorded_live_trino_evidence_matches_contract(self):
        verification = self.contract["verification"]
        column_lines = ["table_name\tcolumn_name\tdata_type\tordinal_position"]
        for view in self.contract["views"]:
            column_lines.extend(
                f"{view['name']}\t{name}\t{data_type}\t{ordinal}"
                for ordinal, (name, data_type) in enumerate(view["columns"].items(), 1)
            )
        column_hash = hashlib.sha256(("\n".join(column_lines) + "\n").encode()).hexdigest()
        self.assertEqual(verification["trino_columns"]["canonical_sha256"], column_hash)

        rows = verification["trino_select"]["row_counts"]
        row_text = "view_name\trow_count\n" + "".join(f"{name}\t{count}\n" for name, count in rows.items())
        self.assertEqual(
            verification["trino_select"]["canonical_sha256"],
            hashlib.sha256(row_text.encode()).hexdigest(),
        )
        self.assertEqual("PASS", verification["read_only_policy"]["status"])
        self.assertEqual(
            verification["read_only_policy"]["sha256"],
            hashlib.sha256(ACCESS_PATH.read_bytes()).hexdigest(),
        )
        datahub = verification["datahub_live"]
        self.assertEqual("PASS", datahub["status"])
        self.assertEqual("v1.6.0", datahub["datahub_version"])
        self.assertEqual(len(self.views), datahub["view_count"])
        self.assertEqual(sum(len(view["columns"]) for view in self.views.values()), datahub["column_count"])
        self.assertGreater(datahub["upstream_edge_count"], 0)
        self.assertGreater(datahub["fine_grained_lineage_count"], 0)
        self.assertRegex(datahub["canonical_sha256"], r"^[0-9a-f]{64}$")
        self.assertFalse(datahub["required_before_gate_pass"])


if __name__ == "__main__":
    unittest.main()
