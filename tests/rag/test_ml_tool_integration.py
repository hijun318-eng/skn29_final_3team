from __future__ import annotations

import unittest

from src.rag.integration.contracts import (
    DocumentEvidence,
    IntegrationContext,
    IntegrationStatus,
    ToolRegistration,
    ToolRoute,
)
from src.rag.integration.coordinator import EvidenceCoordinator
from src.rag.integration.routing import EvidenceRouter


class StubModelPort:
    def predict(self, question: str, context: IntegrationContext) -> dict[str, object]:
        return {
            "evidence_type": "MODEL_PREDICTION",
            "fact_status": "PREDICTION_NOT_OBSERVED",
            "no_show_probability": 0.72,
            "display_label": "모델 예측 · 합성 데이터 기반 예측",
        }


class StubDocumentPort:
    def search(
        self, question: str, context: IntegrationContext
    ) -> tuple[DocumentEvidence, ...]:
        return (
            DocumentEvidence(
                document_id="SOP-FRT-001",
                document_title="프런트 운영 절차",
                document_version="v1.2",
                citation="SOP-FRT-001#no-show",
                snippet="No-show 위험 예약은 담당자가 확인한다.",
                score=0.91,
            ),
        )


class MlToolIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.context = IntegrationContext(
            request_id="req-ml-1",
            trace_id="trace-ml-1",
            actor_id="actor-1",
            role="hotel_analyst",
            as_of="2026-08-04T18:00:00+09:00",
        )

    @staticmethod
    def registration(enabled: bool = True) -> ToolRegistration:
        return ToolRegistration(
            tool_code=EvidenceCoordinator.ML_TOOL,
            semantic_version="1.0.0",
            evidence_type="MODEL_PREDICTION",
            enabled=enabled,
            approval_status="APPROVED" if enabled else "NOT_APPROVED",
            required_roles=frozenset({"hotel_analyst"}),
            health_status="HEALTHY" if enabled else "INACTIVE_BY_GATE",
        )

    def test_approved_ml_route_returns_prediction_not_observed_fact(self) -> None:
        coordinator = EvidenceCoordinator(
            router=EvidenceRouter(),
            registrations={EvidenceCoordinator.ML_TOOL: self.registration()},
            model_port=StubModelPort(),
        )

        response = coordinator.execute("이 예약의 노쇼 위험을 예측해줘", self.context)

        self.assertEqual(ToolRoute.ML_ONLY, response.route)
        self.assertEqual(IntegrationStatus.SUCCEEDED, response.status)
        self.assertEqual((), response.observed_facts)
        self.assertEqual("MODEL_PREDICTION", response.model_predictions[0]["evidence_type"])

    def test_disabled_ml_registration_is_blocked(self) -> None:
        coordinator = EvidenceCoordinator(
            router=EvidenceRouter(),
            registrations={EvidenceCoordinator.ML_TOOL: self.registration(False)},
            model_port=StubModelPort(),
        )

        response = coordinator.execute("노쇼 가능성을 예측해줘", self.context)

        self.assertEqual(IntegrationStatus.BLOCKED, response.status)
        self.assertEqual("TOOL_NOT_APPROVED", response.tool_errors[EvidenceCoordinator.ML_TOOL])

    def test_ml_and_rag_keep_prediction_and_document_separate(self) -> None:
        registrations = {
            EvidenceCoordinator.ML_TOOL: self.registration(),
            EvidenceCoordinator.RAG_TOOL: ToolRegistration(
                tool_code=EvidenceCoordinator.RAG_TOOL,
                semantic_version="1.0.0",
                evidence_type="DOCUMENT",
                enabled=True,
                approval_status="APPROVED",
                required_roles=frozenset({"hotel_analyst"}),
                health_status="HEALTHY",
            ),
        }
        coordinator = EvidenceCoordinator(
            router=EvidenceRouter(),
            registrations=registrations,
            document_port=StubDocumentPort(),
            model_port=StubModelPort(),
        )

        response = coordinator.execute(
            "노쇼 위험 예측과 처리 절차를 같이 알려줘", self.context
        )

        self.assertEqual(ToolRoute.ML_AND_RAG, response.route)
        self.assertEqual(IntegrationStatus.SUCCEEDED, response.status)
        self.assertEqual("DOCUMENT", registrations[EvidenceCoordinator.RAG_TOOL].evidence_type)
        self.assertEqual("MODEL_PREDICTION", response.model_predictions[0]["evidence_type"])
        self.assertEqual("SOP-FRT-001", response.document_evidence[0].document_id)

    def test_room_demand_reference_model_is_not_routed_as_tool(self) -> None:
        plan = EvidenceRouter().decide("향후 7일 객실수요를 예측해줘")

        self.assertEqual(ToolRoute.GENERAL, plan.route)
        self.assertFalse(plan.use_ml)
        self.assertIsNone(plan.ml_tool_code)


if __name__ == "__main__":
    unittest.main()
