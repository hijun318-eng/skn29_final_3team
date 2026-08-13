import importlib.util
import json
import sys
import unittest
from copy import deepcopy
from pathlib import Path
from urllib.parse import unquote, urlparse


ROOT = Path(__file__).resolve().parents[2]
CATALOG_PATH = ROOT / "src/data/serving_semantic_catalog.i4.v1.json"
CONTRACT_PATH = ROOT / "src/data/serving_analytics_contract.i4.v1.json"
PUBLISHER_PATH = ROOT / "infrastructure/database/datahub/publish_semantic_catalog.py"
VERIFIER_PATH = ROOT / "infrastructure/database/datahub/verify_semantic_catalog.py"
COMPOSE_PATH = ROOT / "infrastructure/database/datahub/compose.consumer.yml"
ACCESS_PATH = ROOT / "infrastructure/database/trino/etc/access-control-rules.json"
CRM_DDL_PATH = ROOT / "infrastructure/database/sql/ddl/03_hotel_crm_sqlserver.sql"


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


publisher = load_module("publish_semantic_catalog", PUBLISHER_PATH)
verifier = load_module("verify_semantic_catalog", VERIFIER_PATH)


class FakeResponse:
    def __init__(self, payload=b"{}"):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.payload


class FakeDataHub:
    def __init__(self):
        self.aspects = {}
        self.posts = []

    def __call__(self, request, timeout):
        self.assert_timeout(timeout)
        if request.get_method() == "POST":
            body = json.loads(request.data.decode("utf-8"))[0]
            urn = body["urn"]
            aspect_name = next(key for key in body if key != "urn")
            value = body[aspect_name]["value"]
            self.aspects.setdefault(urn, {})[aspect_name] = {
                "name": aspect_name,
                "version": 0,
                "value": value,
            }
            self.posts.append({"entityUrn": urn, "aspectName": aspect_name})
            return FakeResponse()
        urn = unquote(urlparse(request.full_url).path.rsplit("/", 1)[1])
        payload = json.dumps({"urn": urn, "aspects": self.aspects.get(urn, {})}).encode("utf-8")
        return FakeResponse(payload)

    @staticmethod
    def assert_timeout(timeout):
        if timeout <= 0:
            raise AssertionError("timeout must be positive")


class ServingSemanticCatalogTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
        cls.contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
        cls.compose = COMPOSE_PATH.read_text(encoding="utf-8")
        cls.access = json.loads(ACCESS_PATH.read_text(encoding="utf-8"))
        cls.crm_ddl = CRM_DDL_PATH.read_text(encoding="utf-8")

    def test_catalog_matches_frozen_eight_view_contract(self):
        views = self.contract["views"]
        fields = [field for view in views for field in view["columns"]]
        self.assertEqual(
            {"datasets": 8, "field_occurrences": 117, "unique_fields": 71},
            self.catalog["counts"],
        )
        self.assertEqual({view["fqn"] for view in views}, set(self.catalog["dataset_descriptions"]))
        self.assertEqual(set(fields), set(self.catalog["field_descriptions"]))
        self.assertEqual(self.catalog["catalog_sha256"], publisher.canonical_catalog_hash(self.catalog))
        self.assertEqual(
            self.contract["verification"]["trino_columns"]["canonical_sha256"],
            self.catalog["source_views_sha256"],
        )
        self.assertTrue(all(value.strip() for value in self.catalog["dataset_descriptions"].values()))
        self.assertTrue(all(value.strip() for value in self.catalog["field_descriptions"].values()))

    def test_publisher_is_idempotent_and_verifier_checks_exact_8_117(self):
        fake = FakeDataHub()
        first = publisher.publish("http://127.0.0.1:18081", opener=fake)
        first_state = deepcopy(fake.aspects)
        second = publisher.publish("http://127.0.0.1:18081/", opener=fake)
        self.assertEqual(first_state, fake.aspects)
        self.assertEqual(first, second)
        self.assertEqual(16, first["aspect_upserts"])
        self.assertEqual(32, len(fake.posts))
        self.assertEqual(
            {"editableDatasetProperties", "editableSchemaMetadata"},
            {post["aspectName"] for post in fake.posts},
        )
        result = verifier.verify("http://127.0.0.1:18081", opener=fake)
        self.assertEqual("VERIFIED", result["status"])
        self.assertEqual(8, result["dataset_descriptions"])
        self.assertEqual(117, result["column_descriptions"])
        self.assertEqual(self.catalog["catalog_version"], result["catalog_version"])
        self.assertEqual(self.catalog["catalog_sha256"], result["catalog_sha256"])

    def test_publisher_rejects_external_datahub_endpoint(self):
        with self.assertRaisesRegex(ValueError, "restricted to local"):
            publisher.publish("https://datahub.example.com", opener=FakeDataHub())

    def test_datahub_kafka_health_uses_real_cli(self):
        self.assertIn("kafka-topics --bootstrap-server broker:29092 --list", self.compose)
        self.assertNotIn("nc -z broker 29092", self.compose)

    def test_datahub_ingestion_gets_only_two_system_metadata_tables(self):
        catalog_rules = [rule for rule in self.access["catalogs"] if rule.get("user") == "datahub_ingestion"]
        self.assertEqual([{"user": "datahub_ingestion", "catalog": "system", "allow": "read-only"}], catalog_rules)
        table_rules = [rule for rule in self.access["tables"] if rule.get("user") == "datahub_ingestion"]
        self.assertEqual("metadata", table_rules[0]["schema"])
        self.assertEqual("(catalogs|table_comments)", table_rules[0]["table"])
        self.assertEqual(["SELECT"], table_rules[0]["privileges"])
        self.assertEqual([], table_rules[1]["privileges"])
        self.assertNotIn(".*", table_rules[0]["table"])

    def test_crm_fast_path_preserves_unique_and_interval_protection(self):
        for name in (
            "uq_crm_active_member",
            "uq_crm_active_pms",
            "uq_crm_active_pos",
            "uq_crm_active_facility",
            "uq_crm_active_banquet",
        ):
            self.assertEqual(2, self.crm_ddl.count(name))
        self.assertIn("trg_crm_grade_history_no_overlap", self.crm_ddl)
        self.assertIn("trg_crm_customer_map_no_overlap", self.crm_ddl)
        self.assertIn("i.mapping_status = 'ACTIVE' AND i.valid_to IS NULL", self.crm_ddl)
        self.assertIn("m.mapping_status = 'ACTIVE' AND m.valid_to IS NULL", self.crm_ddl)
        self.assertIn("i.valid_from < COALESCE(m.valid_to", self.crm_ddl)
        self.assertIn("m.valid_from < COALESCE(i.valid_to", self.crm_ddl)

    def test_contract_records_catalog_without_claiming_runtime_pass(self):
        semantic = self.contract["semantic_catalog"]
        self.assertEqual(self.catalog["catalog_sha256"], semantic["catalog_sha256"])
        self.assertEqual(8, semantic["dataset_description_count"])
        self.assertEqual(117, semantic["column_description_count"])
        self.assertEqual(71, semantic["unique_field_count"])
        self.assertEqual("VERIFIED", semantic["runtime_result"])
        self.assertNotEqual("PASS", semantic["status"])


if __name__ == "__main__":
    unittest.main()
