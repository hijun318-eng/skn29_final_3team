from __future__ import annotations

import runpy
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
MIGRATION = (
    ROOT
    / "app"
    / "backend"
    / "migrations"
    / "versions"
    / "20260831_70_report_assistant_external_transfer.py"
)

TRANSFER_TABLES = (
    "REPORT_ASSISTANT_TRANSFER_DISCLOSURES",
    "REPORT_ASSISTANT_EXTERNAL_CONSENTS",
    "REPORT_ASSISTANT_TRANSFER_RECEIPTS",
)


def _normalized(statement: str) -> str:
    return " ".join(statement.upper().split())


def _captured_sql(direction: str) -> tuple[str, ...]:
    statements: list[str] = []
    with patch.dict("os.environ", {"APP_DB_USER": "app_user"}, clear=True):
        namespace = runpy.run_path(str(MIGRATION))
        with patch.object(namespace["op"], "execute", side_effect=statements.append):
            namespace[direction]()
    return tuple(_normalized(statement) for statement in statements)


class ReportAssistantExternalTransferMigrationTest(unittest.TestCase):
    def test_revision_is_linear_child_of_69_and_attempts_are_bounded(self) -> None:
        namespace = runpy.run_path(str(MIGRATION))
        self.assertEqual("20260831_70", namespace["revision"])
        self.assertEqual("20260831_69", namespace["down_revision"])

        upgrade = " ".join(_captured_sql("upgrade"))
        self.assertIn(
            "ATTEMPT SMALLINT NOT NULL CHECK (ATTEMPT BETWEEN 1 AND 4)",
            upgrade,
        )
        self.assertIn("MODEL_EXECUTION_ID UUID NOT NULL", upgrade)
        self.assertIn(
            "UNIQUE (ASSISTANT_REQUEST_ID, MODEL_EXECUTION_ID, ATTEMPT)",
            upgrade,
        )
        self.assertIn("CONTENT_WARNING VARCHAR(500) NOT NULL", upgrade)
        self.assertIn(
            "CREATE TRIGGER REPORT_ASSISTANT_MODEL_EXECUTION_GUARD BEFORE UPDATE",
            upgrade,
        )

    def test_runtime_role_has_insert_read_only_and_rows_are_append_only(self) -> None:
        statements = _captured_sql("upgrade")
        grants = tuple(statement for statement in statements if statement.startswith("GRANT "))
        self.assertEqual(
            tuple(
                f'GRANT SELECT, INSERT ON REPORT_V1.{table} TO "APP_USER"'
                for table in TRANSFER_TABLES
            ),
            grants,
        )
        self.assertNotIn("UPDATE", " ".join(grants))
        self.assertNotIn("DELETE", " ".join(grants))
        self.assertNotIn("ON ALL TABLES", " ".join(grants))

        program = " ".join(statements)
        for table in TRANSFER_TABLES:
            with self.subTest(table=table):
                self.assertIn(
                    f"CREATE TRIGGER {table}_OWNER_GUARD BEFORE INSERT "
                    f"ON REPORT_V1.{table} FOR EACH ROW EXECUTE FUNCTION "
                    "REPORT_V1.REQUIRE_ASSISTANT_TRANSFER_OWNER()",
                    program,
                )
                self.assertIn(
                    f"CREATE TRIGGER {table}_IMMUTABLE BEFORE UPDATE OR DELETE "
                    f"ON REPORT_V1.{table} FOR EACH ROW EXECUTE FUNCTION "
                    "REPORT_V1.REJECT_ASSISTANT_TRANSFER_RECEIPT_MUTATION()",
                    program,
                )
        self.assertIn(
            "RAISE EXCEPTION 'REPORT ASSISTANT TRANSFER RECEIPTS ARE APPEND-ONLY'",
            program,
        )

    def test_external_receipt_guard_exactly_binds_consent_disclosure_and_route(self) -> None:
        statements = _captured_sql("upgrade")
        guard = next(
            statement
            for statement in statements
            if "CREATE FUNCTION REPORT_V1.REQUIRE_ASSISTANT_TRANSFER_OWNER()" in statement
        )
        common_guard, table_guards = guard.split(
            "IF TG_TABLE_NAME = 'REPORT_ASSISTANT_EXTERNAL_CONSENTS' THEN",
            1,
        )
        consent_guard, receipt_guard = table_guards.split(
            "ELSIF TG_TABLE_NAME = 'REPORT_ASSISTANT_TRANSFER_RECEIPTS'",
            1,
        )

        for predicate in (
            "REQUEST.ASSISTANT_REQUEST_ID = NEW.ASSISTANT_REQUEST_ID",
            "REQUEST.OWNER_ID = NEW.OWNER_ID",
        ):
            with self.subTest(common_predicate=predicate):
                self.assertIn(predicate, common_guard)

        for predicate in (
            "DISCLOSURE.ASSISTANT_REQUEST_ID = NEW.ASSISTANT_REQUEST_ID",
            "DISCLOSURE.OWNER_ID = NEW.OWNER_ID",
            "DISCLOSURE.POLICY_VERSION = NEW.POLICY_VERSION",
            "DISCLOSURE.DISCLOSURE_HASH = NEW.DISCLOSURE_HASH",
            "DISCLOSURE.ROUTE_FINGERPRINT = NEW.ROUTE_FINGERPRINT",
            "DISCLOSURE.BINDING_HASH = NEW.BINDING_HASH",
            "DISCLOSURE.SCOPE_HASH = NEW.SCOPE_HASH",
            "DISCLOSURE.EXPIRES_AT > NOW()",
        ):
            with self.subTest(consent_predicate=predicate):
                self.assertIn(predicate, consent_guard)

        for predicate in (
            "JOIN REPORT_V1.REPORT_ASSISTANT_TRANSFER_DISCLOSURES DISCLOSURE "
            "ON DISCLOSURE.DISCLOSURE_ID = CONSENT.DISCLOSURE_ID",
            "CONSENT.CONSENT_ID = NEW.CONSENT_ID",
            "DISCLOSURE.DISCLOSURE_ID = NEW.DISCLOSURE_ID",
            "CONSENT.ASSISTANT_REQUEST_ID = NEW.ASSISTANT_REQUEST_ID",
            "CONSENT.OWNER_ID = NEW.OWNER_ID",
            "CONSENT.POLICY_VERSION = NEW.POLICY_VERSION",
            "CONSENT.ROUTE_FINGERPRINT = NEW.ROUTE_FINGERPRINT",
            "CONSENT.BINDING_HASH = NEW.BINDING_HASH",
            "CONSENT.SCOPE_HASH = NEW.SCOPE_HASH",
            "CONSENT.ACCEPTED",
            "NEW.NODE = DISCLOSURE.NODE",
            "NEW.DATA_SCOPES_JSON = DISCLOSURE.DATA_SCOPES_JSON",
            "NEW.DATA_BOUNDARY = 'EXTERNAL'",
            "NEW.MANIFEST_VERSION = DISCLOSURE.ROUTE_JSON->>'MANIFEST_VERSION'",
            "PROVIDER_ROUTE->>'NODE' = NEW.NODE",
            "PROVIDER_ROUTE->>'ROUTE_ID' = NEW.ROUTE_ID",
            "PROVIDER_ROUTE->>'PROVIDER' = NEW.PROVIDER",
            "PROVIDER_ROUTE->>'MODEL' = NEW.MODEL",
            "PROVIDER_ROUTE->>'DATA_BOUNDARY' = NEW.DATA_BOUNDARY",
            "NEW.ENDPOINT LIKE (PROVIDER_ROUTE->>'DESTINATION_ORIGIN') || '/%'",
            "REQUEST.MODEL_EXECUTION_ID = NEW.MODEL_EXECUTION_ID",
            "REQUEST.MODEL_EXECUTION_NODE = NEW.NODE",
            "REQUEST.MODEL_EXECUTION_MESSAGE_REVISION = REQUEST.MESSAGE_REVISION",
            "REQUEST.MODEL_EXECUTION_EXPIRES_AT > NOW()",
            "VERSION.REVISION = REQUEST.BASE_REVISION",
        ):
            with self.subTest(receipt_predicate=predicate):
                self.assertIn(predicate, receipt_guard)

        self.assertIn(
            "FROM JSONB_ARRAY_ELEMENTS( DISCLOSURE.ROUTE_JSON->'PROVIDER_ROUTES' ) "
            "AS PROVIDER_ROUTE",
            receipt_guard,
        )

    def test_downgrade_refuses_to_destroy_any_preserved_transfer_evidence(self) -> None:
        statements = _captured_sql("downgrade")
        program = " ".join(statements)
        lock = statements[0]
        self.assertEqual(
            "LOCK TABLE REPORT_V1.REPORT_ASSISTANT_REQUESTS, "
            "REPORT_V1.REPORT_ASSISTANT_TRANSFER_DISCLOSURES, "
            "REPORT_V1.REPORT_ASSISTANT_EXTERNAL_CONSENTS, "
            "REPORT_V1.REPORT_ASSISTANT_TRANSFER_RECEIPTS IN ACCESS EXCLUSIVE MODE",
            lock,
        )

        guard = statements[1]
        self.assertIn(
            "SELECT 1 FROM REPORT_V1.REPORT_ASSISTANT_REQUESTS "
            "WHERE MODEL_EXECUTION_ID IS NOT NULL",
            guard,
        )
        self.assertIn(
            "OR EXISTS (SELECT 1 FROM REPORT_V1.REPORT_ASSISTANT_TRANSFER_DISCLOSURES)",
            guard,
        )
        self.assertIn(
            "OR EXISTS (SELECT 1 FROM REPORT_V1.REPORT_ASSISTANT_EXTERNAL_CONSENTS)",
            guard,
        )
        self.assertIn(
            "OR EXISTS (SELECT 1 FROM REPORT_V1.REPORT_ASSISTANT_TRANSFER_RECEIPTS)",
            guard,
        )
        self.assertIn(
            "RAISE EXCEPTION 'REPORT ASSISTANT EXTERNAL TRANSFER RECEIPTS MUST BE PRESERVED'",
            guard,
        )

        for table in reversed(TRANSFER_TABLES):
            with self.subTest(table=table):
                revoke_at = program.index(
                    f'REVOKE SELECT, INSERT ON REPORT_V1.{table} FROM "APP_USER"'
                )
                drop_at = program.index(f"DROP TABLE REPORT_V1.{table}")
                self.assertLess(program.index(lock), program.index(guard))
                self.assertLess(program.index(guard), revoke_at)
                self.assertLess(revoke_at, drop_at)


if __name__ == "__main__":
    unittest.main()
