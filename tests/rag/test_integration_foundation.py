from __future__ import annotations

import unittest
from dataclasses import dataclass, replace
from datetime import date
from enum import Enum

from src.rag.integration.adapters import (
    AnswerviceContextAdapter,
    ApprovedRoleMapper,
    RoleMappingError,
)
from src.rag.integration.contracts import (
    DocumentEvidence,
    IntegrationContext,
    IntegrationStatus,
    SqlEvidence,
    ToolRegistration,
    ToolRoute,
)
from src.rag.integration.coordinator import EvidenceCoordinator, ToolCallError
from src.rag.integration.routing import EvidenceRouter


class FakeSqlPort:
    def query(self, question: str, context: IntegrationContext) -> SqlEvidence:
        return SqlEvidence(
            query_id="query-1",
            as_of=context.as_of,
            observed_facts=({"metric_id": "revenue", "value": 100},),
            source_refs=("urn:dataset:revenue",),
        )


class FakeDocumentPort:
    def search(
        self, question: str, context: IntegrationContext
    ) -> tuple[DocumentEvidence, ...]:
        return (
            DocumentEvidence(
                document_id="POL-001",
                document_title="프로모션 정책",
                document_version="1.0",
                citation="[POL-001 v1.0 p.2-2 적용 조건]",
                snippet="승인된 채널에 적용한다.",
                score=0.9,
                effective_from="2026-01-01",
            ),
        )


class FailingDocumentPort:
    def search(
        self, question: str, context: IntegrationContext
    ) -> tuple[DocumentEvidence, ...]:
        raise ToolCallError("RAG_SOURCE_FAILED")


class EmptyDocumentPort:
    def search(
        self, question: str, context: IntegrationContext
    ) -> tuple[DocumentEvidence, ...]:
        return ()


class IntegrationFoundationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.router = EvidenceRouter()
        self.context = IntegrationContext(
            request_id="00000000-0000-0000-0000-000000000001",
            trace_id="trace-1",
            actor_id="00000000-0000-0000-0000-000000000002",
            role="hotel_analyst",
            as_of="2026-08-04",
            approved_route=ToolRoute.SQL_AND_RAG,
            router_decision_id="approved-route-sql-rag",
        )
        self.registrations = {
            EvidenceCoordinator.SQL_TOOL: self._registration(
                EvidenceCoordinator.SQL_TOOL, "SQL_EVIDENCE"
            ),
            EvidenceCoordinator.RAG_TOOL: self._registration(
                EvidenceCoordinator.RAG_TOOL, "DOCUMENT_EVIDENCE"
            ),
        }

    def test_router_uses_only_the_approved_route_receipt(self) -> None:
        plan = self.router.decide(ToolRoute.SQL_AND_RAG, "decision-1")
        self.assertEqual(plan.route, ToolRoute.SQL_AND_RAG)
        self.assertTrue(plan.use_sql)
        self.assertTrue(plan.use_rag)
        self.assertFalse(plan.use_ml)
        with self.assertRaisesRegex(ValueError, "ROUTER_DECISION_REQUIRED"):
            self.router.decide(ToolRoute.RAG_ONLY, None)

    def test_mixed_response_separates_observation_document_and_interpretation(self) -> None:
        response = EvidenceCoordinator(
            self.router,
            self.registrations,
            FakeSqlPort(),
            FakeDocumentPort(),
        ).execute("매출 감소 원인과 관련 프로모션 정책", self.context)
        self.assertEqual(response.status, IntegrationStatus.SUCCEEDED)
        self.assertEqual(len(response.sql_evidence), 1)
        self.assertEqual(len(response.document_evidence), 1)
        self.assertEqual(response.interpretations, ())
        self.assertEqual(response.observed_facts[0]["metric_id"], "revenue")

    def test_one_tool_failure_returns_partial_evidence(self) -> None:
        response = EvidenceCoordinator(
            self.router,
            self.registrations,
            FakeSqlPort(),
            FailingDocumentPort(),
        ).execute("매출 감소 원인과 관련 프로모션 정책", self.context)
        self.assertEqual(response.status, IntegrationStatus.PARTIAL)
        self.assertEqual(len(response.sql_evidence), 1)
        self.assertEqual(response.document_evidence, ())
        self.assertEqual(
            response.tool_errors[EvidenceCoordinator.RAG_TOOL],
            "RAG_SOURCE_FAILED",
        )

    def test_unapproved_registry_blocks_tool_call(self) -> None:
        blocked = dict(self.registrations)
        blocked[EvidenceCoordinator.RAG_TOOL] = self._registration(
            EvidenceCoordinator.RAG_TOOL,
            "DOCUMENT_EVIDENCE",
            enabled=False,
            approval="NOT_APPROVED",
        )
        response = EvidenceCoordinator(
            self.router, blocked, document_port=FakeDocumentPort()
        ).execute(
            "승인된 문서 요청",
            replace(
                self.context,
                approved_route=ToolRoute.RAG_ONLY,
                router_decision_id="approved-route-rag",
            ),
        )
        self.assertEqual(response.status, IntegrationStatus.BLOCKED)
        self.assertEqual(response.document_evidence, ())

    def test_empty_document_search_is_explicit_partial_failure(self) -> None:
        response = EvidenceCoordinator(
            self.router,
            self.registrations,
            FakeSqlPort(),
            EmptyDocumentPort(),
        ).execute("매출 감소 원인과 관련 프로모션 정책", self.context)
        self.assertEqual(response.status, IntegrationStatus.PARTIAL)
        self.assertEqual(
            response.tool_errors[EvidenceCoordinator.RAG_TOOL],
            "RAG_NO_EVIDENCE",
        )

    def test_role_mapping_requires_explicit_approval(self) -> None:
        mapper = ApprovedRoleMapper({"hotel_analyst": "STAFF"}, approved=False)
        with self.assertRaisesRegex(RoleMappingError, "ROLE_MAPPING_NOT_APPROVED"):
            mapper.map("hotel_analyst")
        approved = ApprovedRoleMapper({"hotel_analyst": "STAFF"}, approved=True)
        self.assertEqual(approved.map("hotel_analyst"), "STAFF")

    def test_current_dev_context_fields_are_preserved(self) -> None:
        class Role(str, Enum):
            HOTEL_ANALYST = "hotel_analyst"

        @dataclass
        class DevContext:
            request_id: str = "request-1"
            trace_id: str = "trace-1"
            user_id: str = "actor-1"
            role: Role = Role.HOTEL_ANALYST
            as_of: date = date(2026, 8, 4)
            conversation_id: str = "conversation-1"

        converted = AnswerviceContextAdapter.convert(DevContext())
        self.assertEqual(converted.role, "hotel_analyst")
        self.assertEqual(converted.as_of, "2026-08-04")
        self.assertEqual(converted.session_id, "conversation-1")

    def _registration(
        self,
        code: str,
        evidence_type: str,
        enabled: bool = True,
        approval: str = "APPROVED",
    ) -> ToolRegistration:
        return ToolRegistration(
            tool_code=code,
            semantic_version="1.0.0-test",
            evidence_type=evidence_type,
            enabled=enabled,
            approval_status=approval,
            required_roles=frozenset({"hotel_analyst"}),
            health_status="HEALTHY",
        )


if __name__ == "__main__":
    unittest.main()
