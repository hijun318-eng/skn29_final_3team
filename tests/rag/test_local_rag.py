from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.rag.application import LocalRagApplication
from src.rag.access_policy import AccessDeniedError, SearchAccessPolicy
from src.rag.api import create_app
from src.rag.pdf_ingestion import MANUAL_ID_PATTERN
from src.rag.quality_evaluation import SyntheticQualitySuite
from src.rag.request_auth import (
    GatewayAuthenticationError,
    GatewayRequestAuthenticator,
    canonical_search_request,
    canonical_answer_request,
)
from src.rag.text_processing import SecurityScanner
from src.rag.vector_settings import VectorSettings
from src.rag.vector_application import VectorRagApplication
from src.rag.p2_contracts import (
    EvidenceType,
    P2GateStatus,
    RagToolContract,
    build_retrieval_envelope,
)


class LocalRagApplicationTest(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.root = Path(self._temporary.name)
        (self.root / "config").mkdir()
        source_directory = self.root / "data" / "rag" / "source_documents"
        source_directory.mkdir(parents=True)
        source_directory.joinpath("manual.md").write_text(
            """# 테스트 업무 매뉴얼

## 1. 장애 보고

장애가 발생하면 담당자는 관리자에게 즉시 보고한다.

## 2. 접근 권한

권한이 없는 사용자는 제한 문서를 검색할 수 없다.
""",
            encoding="utf-8",
        )
        allowlist = {
            "documents": [
                {
                    "manual_id": "TEST-001",
                    "title": "테스트 업무 매뉴얼",
                    "version": "1.0",
                    "source_path": "data/rag/source_documents/manual.md",
                    "role_scope": ["MANAGER"],
                }
            ]
        }
        (self.root / "config" / "document_allowlist.json").write_text(
            json.dumps(allowlist, ensure_ascii=False), encoding="utf-8"
        )
        self.application = LocalRagApplication(self.root)

    def tearDown(self) -> None:
        self._temporary.cleanup()

    def test_ingestion_is_idempotent(self) -> None:
        first = self.application.ingest()
        second = self.application.ingest()
        self.assertGreater(first["created_chunks"], 0)
        self.assertEqual(second["created_chunks"], 0)
        self.assertEqual(second["database_counts"]["documents"], 1)

    def test_unresolved_document_requires_explicit_option(self) -> None:
        self.application.ingest()
        blocked = self.application.search("장애 보고", "MANAGER")
        allowed = self.application.search(
            "장애 보고", "MANAGER", allow_unresolved_validity=True
        )
        self.assertEqual(blocked, [])
        self.assertGreater(len(allowed), 0)

    def test_unauthorized_role_cannot_retrieve(self) -> None:
        self.application.ingest()
        results = self.application.search(
            "접근 권한", "STAFF", allow_unresolved_validity=True
        )
        self.assertEqual(results, [])

    def test_result_contains_citation(self) -> None:
        self.application.ingest()
        result = self.application.search(
            "관리자에게 보고", "MANAGER", allow_unresolved_validity=True
        )[0]
        self.assertIn("TEST-001", result.citation_label)
        self.assertEqual(result.manual_version, "1.0")

    def test_personal_information_is_masked(self) -> None:
        status, text = SecurityScanner().inspect("연락처는 010-1234-5678입니다.")
        self.assertEqual(status, "MASKED_PII")
        self.assertNotIn("010-1234-5678", text)

    def test_secret_is_rejected(self) -> None:
        status, _ = SecurityScanner().inspect("api_key=do-not-index")
        self.assertEqual(status, "REJECTED_SECRET")

    def test_manual_id_patterns_are_not_confused(self) -> None:
        text = "INDEX-001 다음 참조 문서는 POL-COM-001이다."
        matches = MANUAL_ID_PATTERN.findall(text)
        self.assertEqual(matches, ["INDEX-001", "POL-COM-001"])


class OperationalControlTest(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = SearchAccessPolicy.load(PROJECT_ROOT / "config" / "rag" / "access_policy.json")

    def test_unresolved_validity_is_decided_by_server_policy(self) -> None:
        self.assertFalse(self.policy.decide("STAFF").allow_unresolved_validity)
        self.assertTrue(self.policy.decide("MANAGER").allow_unresolved_validity)

    def test_unregistered_role_is_rejected_before_search(self) -> None:
        with self.assertRaises(AccessDeniedError):
            self.policy.decide("GUEST")

    def test_top_k_is_bounded_by_server_policy(self) -> None:
        self.assertEqual(self.policy.decide("SYSTEM_ADMIN", 999).top_k, 10)

    def test_approved_two_document_snapshot_wins_over_new_vector_rank(self) -> None:
        self.assertEqual(
            2,
            VectorRagApplication.answer_document_limit(
                "REGULATION_CHECK",
                ("MANUAL-FACILITY", "MANUAL-SAFETY"),
            ),
        )
        self.assertEqual(
            ("MANUAL-FACILITY", "MANUAL-SAFETY"),
            VectorRagApplication.answer_document_ids(
                ("MANUAL-FACILITY", "MANUAL-SAFETY"),
                ("MANUAL-FACILITY",),
                2,
            ),
        )

    def test_quality_suite_has_more_than_80_positive_queries(self) -> None:
        sources = [
            {
                "manual_id": f"SOP-TEST-{index:03d}",
                "title": f"테스트 업무 {index}",
                "content": "현장 상황을 확인하고 관리자에게 즉시 보고한 뒤 처리 내용을 기록한다.",
            }
            for index in range(1, 37)
        ]
        queries = SyntheticQualitySuite().build(sources)
        positive_count = sum(item.expected_manual_id is not None for item in queries)
        self.assertEqual(positive_count, 108)
        self.assertEqual(len(queries) - positive_count, 12)

    @patch.dict(os.environ, {"RAG_DATABASE_URL": "postgresql://rag_test@localhost/rag_test"})
    def test_api_does_not_expose_unresolved_override(self) -> None:
        schema = create_app(PROJECT_ROOT).openapi()
        properties = schema["components"]["schemas"]["ManualSearchRequest"]["properties"]
        self.assertNotIn("allow_unresolved_validity", properties)
        self.assertNotIn("role", properties)
        self.assertIn("recent_utterances", properties)
        self.assertIn("selected_document_ids", properties)

    def test_search_signature_covers_context_and_document_selection(self) -> None:
        base = canonical_search_request("그 다음은?", 3, ("예약 확인",), ())
        changed_context = canonical_search_request("그 다음은?", 3, ("결제 확인",), ())
        changed_selection = canonical_search_request(
            "그 다음은?", 3, ("예약 확인",), ("SOP-FRT-003",)
        )
        self.assertNotEqual(base, changed_context)
        self.assertNotEqual(base, changed_selection)

    def test_answer_signature_covers_evidence_content_and_order(self) -> None:
        base = canonical_answer_request(
            "예약금 처리 기준",
            (
                {"evidence_id": "E1", "text": "내용 A", "page": 1},
                {"text": "내용 B", "evidence_id": "E2"},
            ),
        )
        changed_text = canonical_answer_request(
            "예약금 처리 기준", ({"evidence_id": "E1", "text": "내용 C"},)
        )
        reordered = canonical_answer_request(
            "예약금 처리 기준",
            (
                {"text": "내용 B", "evidence_id": "E2"},
                {"evidence_id": "E1", "text": "내용 A", "page": 1},
            ),
        )
        self.assertNotEqual(base, changed_text)
        self.assertNotEqual(base, reordered)

    def test_signed_gateway_request_is_verified_once(self) -> None:
        secret = "local-test-secret-with-at-least-32-characters"
        request_id = "1c38b5e3-0ca0-4d20-8b3e-46319d94ac69"
        timestamp = "1000"
        query = "객실 소음 대응"
        authenticator = GatewayRequestAuthenticator(secret, clock=lambda: 1000.0)
        signature = authenticator.build_signature(
            secret, timestamp, request_id, "MANAGER", query
        )
        self.assertEqual(
            authenticator.verify("MANAGER", timestamp, request_id, signature, query),
            "MANAGER",
        )
        with self.assertRaises(GatewayAuthenticationError):
            authenticator.verify("MANAGER", timestamp, request_id, signature, query)

    def test_tampered_role_and_expired_signature_are_rejected(self) -> None:
        secret = "local-test-secret-with-at-least-32-characters"
        request_id = "cf8d8199-cf86-47c8-8645-479150980e89"
        query = "객실 소음 대응"
        signature = GatewayRequestAuthenticator.build_signature(
            secret, "1000", request_id, "STAFF", query
        )
        authenticator = GatewayRequestAuthenticator(secret, clock=lambda: 1000.0)
        with self.assertRaises(GatewayAuthenticationError):
            authenticator.verify("MANAGER", "1000", request_id, signature, query)
        expired_authenticator = GatewayRequestAuthenticator(secret, clock=lambda: 2000.0)
        with self.assertRaises(GatewayAuthenticationError):
            expired_authenticator.verify("STAFF", "1000", request_id, signature, query)

    def test_weak_or_missing_gateway_secret_fails_closed(self) -> None:
        authenticator = GatewayRequestAuthenticator("too-short")
        self.assertFalse(authenticator.configured)
        with self.assertRaises(GatewayAuthenticationError) as context:
            authenticator.verify(None, None, None, None, "질문")
        self.assertEqual(context.exception.status_code, 503)

    @patch.dict(os.environ, {"RAG_DATABASE_URL": "postgresql://rag_test@localhost/rag_test"})
    def test_integrated_paths_follow_repository_layout(self) -> None:
        settings = VectorSettings.load(PROJECT_ROOT)
        self.assertEqual(settings.config_dir, PROJECT_ROOT / "config" / "rag")
        self.assertEqual(
            settings.migrations_dir,
            PROJECT_ROOT / "infrastructure" / "rag" / "db" / "init",
        )
        self.assertEqual(settings.manuals_dir, PROJECT_ROOT / "data" / "rag" / "manuals")
        self.assertEqual(
            settings.smoke_queries_path,
            PROJECT_ROOT / "evals" / "testsets" / "rag" / "smoke_queries.json",
        )

    @patch.dict(os.environ, {}, clear=True)
    def test_database_url_is_required(self) -> None:
        with self.assertRaisesRegex(ValueError, "RAG_DATABASE_URL is required"):
            VectorSettings.load(PROJECT_ROOT)

    def test_p2_gate_and_tool_registration_fail_closed(self) -> None:
        gate = P2GateStatus()
        tool = RagToolContract()
        self.assertEqual(gate.implementation_state, "ISOLATED_POC")
        self.assertEqual(gate.p2_gate, "NOT_APPROVED")
        self.assertFalse(gate.affects_p0_p1_completion)
        self.assertFalse(tool.enabled)
        self.assertEqual(tool.approval_status, "NOT_APPROVED")

    def test_retrieval_contract_keeps_sql_and_document_evidence_separate(self) -> None:
        result = {
            "manual_id": "POL-001",
            "title": "테스트 정책",
            "version": "1.0",
            "citation": "[POL-001 v1.0 p.1-1 테스트]",
            "score": 0.9,
            "snippet": "정책 내용",
            "warning": None,
            "effective_from": "2026-01-01",
            "expires_at": None,
        }
        envelope = build_retrieval_envelope("request-1", None, [result])
        self.assertEqual(envelope["sql_evidence"], [])
        self.assertEqual(
            envelope["document_evidence"][0]["evidence_type"],
            EvidenceType.DOCUMENT,
        )
        self.assertEqual(envelope["interpretations"], [])

    def test_p2_migration_keeps_registry_disabled(self) -> None:
        migration = PROJECT_ROOT / "infrastructure" / "rag" / "db" / "init" / "004_p2_contract_foundation.sql"
        sql = migration.read_text(encoding="utf-8")
        self.assertIn("CHECK (NOT enabled OR approval_status = 'APPROVED')", sql)
        self.assertIn("FALSE, 'NOT_APPROVED'", sql)
        self.assertIn("ALTER TABLE document_versions", sql)
        self.assertIn(
            "INSERT INTO tool_runs",
            (PROJECT_ROOT / "src" / "rag" / "pgvector_observability.py").read_text(
                encoding="utf-8"
            ),
        )
        self.assertIn("d.expires_at", (PROJECT_ROOT / "src" / "rag" / "pgvector_repository.py").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
