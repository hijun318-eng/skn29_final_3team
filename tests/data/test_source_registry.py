import json
import hashlib
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / "src" / "data" / "source_registry.v1.json"
CONTRACT = ROOT / "src" / "data" / "r2_w1_contract.v1.json"


class SourceRegistryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
        cls.contract = json.loads(CONTRACT.read_text(encoding="utf-8"))

    def test_five_sources_four_engines_and_unique_connections(self):
        sources = self.registry["sources"]
        self.assertEqual(5, len(sources))
        self.assertEqual(4, len({source["engine"] for source in sources}))
        for field in ("source_id", "database_name", "query_account", "ingestion_account", "datahub_platform_instance", "trino_catalog"):
            values = [source[field] for source in sources]
            self.assertEqual(len(values), len(set(values)), field)

    def test_required_contract_and_grain_fields(self):
        required = {
            "source_id", "source_name", "domain", "engine", "database_name", "schema_name",
            "data_owner", "technical_owner", "synthetic_flag", "schema_version", "seed_version",
            "timezone", "query_account", "ingestion_account", "datahub_platform_instance",
            "trino_catalog", "watermark_rule", "active_status", "ddl_file", "entities",
        }
        sources = self.registry["sources"]
        self.assertEqual(18, sum(len(source["entities"]) for source in sources))
        registered = {
            f"{source['source_id']}.{entity['table']}"
            for source in sources
            for entity in source["entities"]
        }
        for source in sources:
            self.assertFalse(required - source.keys(), source["source_id"])
            self.assertTrue(source["synthetic_flag"])
            self.assertEqual("1.0.0", source["schema_version"])
            self.assertEqual("20260729", source["seed_version"])
            self.assertEqual("Asia/Seoul", source["timezone"])
            for entity in source["entities"]:
                self.assertTrue(entity["grain"])
                self.assertTrue(entity["primary_key"])
        for capability in self.registry["p0_capabilities"]:
            self.assertFalse(set(capability["entities"]) - registered, capability["id"])
        crm = next(source for source in sources if source["source_id"] == "crm")
        self.assertEqual(
            "crm_customer_map", crm["contract_aliases"]["customer_identity_map"]
        )

    def test_registered_entities_exist_in_owned_ddl(self):
        for source in self.registry["sources"]:
            ddl = (ROOT / source["ddl_file"]).read_text(encoding="utf-8")
            for entity in source["entities"]:
                table = re.escape(entity["table"])
                pattern = rf"CREATE TABLE(?: IF NOT EXISTS)? (?:\w+\.)?{table}\s*\("
                self.assertRegex(ddl, pattern, f"{source['source_id']}.{entity['table']}")

    def test_seed_manifest_is_fixed_and_current(self):
        self.assertEqual(5, len(self.contract["seed_manifest"]))
        for seed in self.contract["seed_manifest"]:
            path = ROOT / seed["file"]
            raw = path.read_bytes()
            text = raw.decode("utf-8").lower()
            self.assertEqual(seed["sha256"], hashlib.sha256(raw).hexdigest())
            self.assertIn("seed=20260729", text)
            self.assertIn("scenario_version=1.0.0", text)
            self.assertIn("synthetic=true", text)
            self.assertNotRegex(text, r"\b(now\(\)|current_date|current_timestamp)\b")
        states = self.contract["data_state_manifest"]
        self.assertEqual(18, len(states))
        self.assertEqual(18, len({state["entity"] for state in states}))
        self.assertTrue(all(state["row_count"] > 0 for state in states))
        self.assertTrue(all(state["checksum"] for state in states))
        for summary in self.contract["preprocessing_summary"]:
            self.assertEqual(
                summary["input_rows"],
                summary["accepted_rows"] + summary["rejected_rows"],
            )

    def test_crm_identity_and_event_time_guards(self):
        ddl = (
            ROOT / "infrastructure/database/sql/ddl/03_hotel_crm_sqlserver.sql"
        ).read_text(encoding="utf-8")
        required = (
            "CREATE OR ALTER VIEW dbo.customer_identity_map",
            "trg_crm_customer_map_no_overlap",
            "CRM_IDENTITY_PERIOD_OVERLAP",
            "trg_crm_grade_history_no_overlap",
            "CRM_GRADE_PERIOD_OVERLAP",
            "valid_to IS NULL OR valid_to > valid_from",
            "uq_crm_active_pms",
            "uq_crm_active_pos",
            "uq_crm_active_facility",
            "uq_crm_active_banquet",
        )
        for token in required:
            self.assertIn(token, ddl)

    def test_i1_room_revenue_metric_and_event_time_join_are_frozen(self):
        self.assertEqual("I1-v1.0.0", self.contract["contract_version"])
        self.assertEqual(self.contract["contract_version"], self.registry["contract_version"])

        metric = self.contract["metrics"][0]
        self.assertEqual(
            "지난달 GOLD 회원의 인식 객실 매출은 전월 대비 얼마나 변했어?",
            self.contract["representative_question"]["text"],
        )
        self.assertEqual("recognized_room_revenue", metric["id"])
        self.assertEqual("pms.public.pms_stays.room_revenue", metric["source_field"])
        self.assertEqual(("KRW", "SUM", "month"), (
            metric["unit"], metric["aggregation"], metric["time_grain"]
        ))
        self.assertEqual("pms.public.pms_stays.actual_checkout_at", metric["event_time_field"])
        self.assertEqual(
            "pms_stay_to_crm_membership_grade_event_time_v1",
            metric["approved_join_id"],
        )

        approved_join = self.registry["approved_joins"][0]
        self.assertEqual(metric["approved_join_id"], approved_join["join_id"])
        self.assertEqual("many_to_zero_or_one", approved_join["cardinality"])
        self.assertEqual(metric["event_time_field"], approved_join["event_time_field"])
        self.assertEqual(
            [
                "pms.public.pms_stays.reservation_id",
                "pms.public.pms_reservations.guest_id",
                "pms.public.pms_guests.guest_id",
                "crm.dbo.crm_customer_map.member_no",
            ],
            [step["from"] for step in approved_join["steps"]],
        )
        predicates = " ".join(approved_join["predicates"])
        self.assertIn("crm.dbo.crm_customer_map.valid_from <=", predicates)
        self.assertIn("actual_checkout_at < crm.dbo.crm_customer_map.valid_to", predicates)
        self.assertIn("crm.dbo.crm_member_grade_history.valid_from <=", predicates)
        self.assertIn("actual_checkout_at < crm.dbo.crm_member_grade_history.valid_to", predicates)
        self.assertNotIn("crm.dbo.crm_members.membership_grade", predicates)

        pms_ddl = (
            ROOT / "infrastructure/database/sql/ddl/01_hotel_pms_postgresql.sql"
        ).read_text(encoding="utf-8")
        crm_ddl = (
            ROOT / "infrastructure/database/sql/ddl/03_hotel_crm_sqlserver.sql"
        ).read_text(encoding="utf-8")
        for column in ("room_revenue numeric", "actual_checkout_at timestamptz"):
            self.assertIn(column, pms_ddl)
        for column in (
            "pms_guest_id varchar",
            "valid_from datetime2",
            "valid_to datetime2",
            "grade_code varchar",
        ):
            self.assertIn(column, crm_ddl)

    def test_trino_policy_is_read_only_and_hides_system(self):
        rules = json.loads(
            (
                ROOT
                / "infrastructure/database/trino/etc/access-control-rules.json"
            ).read_text(encoding="utf-8")
        )
        self.assertTrue(
            any(
                rule.get("catalog") == "system" and rule.get("allow") == "none"
                for rule in rules["catalogs"]
            )
        )
        self.assertTrue(
            any(rule.get("allow") == "read-only" for rule in rules["catalogs"])
        )
        self.assertEqual([{"privileges": []}], rules["procedures"])

    def test_direct_identifier_formats_are_absent(self):
        paths = [
            ROOT / source["ddl_file"] for source in self.registry["sources"]
        ] + [
            ROOT / seed["file"] for seed in self.contract["seed_manifest"]
        ]
        direct_columns = re.compile(
            r"\b(email|e_mail|phone|mobile|full_name|first_name|last_name|"
            r"resident_number|passport_number|credit_card_number)\b",
            re.IGNORECASE,
        )
        direct_values = re.compile(
            r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|"
            r"\b01[016789][ -]?\d{3,4}[ -]?\d{4}\b|"
            r"\b\d{6}-[1-4]\d{6}\b"
        )
        for path in paths:
            text = path.read_text(encoding="utf-8")
            self.assertIsNone(direct_columns.search(text), path)
            self.assertIsNone(direct_values.search(text), path)


if __name__ == "__main__":
    unittest.main()
