"""승인 DataHub 후보 기반 Analysis capability probe의 fail-closed 계약을 검증한다."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "app" / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.authorization import permission_snapshot_id
from app.contracts import RequestContext, Role
from app.conversation_contracts import ConversationCommandRequest
from app.ports.agent import (
    AgentKind,
    AgentPreviousAnalysisContext,
    AgentRequest,
    MLPredictionInvocation,
)
from app.ports.data_platform import (
    AssetCandidateSet,
    MetadataUnavailableError,
    NoMetricMatchError,
)
from app.services.agent_capability_probes import (
    GovernedAnalysisCapabilityProbe,
    InternalGuidelineCapabilityProbe,
    MLPredictionCapabilityProbe,
)
from app.services.agent_supervisor import AgentDispatchError


class _CandidatePlatform:
    """테스트가 지정한 후보 또는 검색 거부를 반환하는 DataPlatform test double이다."""

    def __init__(
        self,
        candidates: AssetCandidateSet | None = None,
        error: Exception | None = None,
    ) -> None:
        self.candidates = candidates
        self.error = error
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def search_asset_candidates(self, query: str, context: dict[str, object]):
        self.calls.append((query, context))
        if self.error is not None:
            raise self.error
        assert self.candidates is not None
        return self.candidates


class _GuidelineSearcher:
    """원문 없는 RAG capability 후보를 반환하는 test double이다."""

    def __init__(self, candidate: dict[str, object]) -> None:
        self.candidate = candidate
        self.calls: list[tuple[str, str]] = []

    async def search_capability(
        self,
        query: str,
        app_role: str,
    ) -> dict[str, object]:
        self.calls.append((query, app_role))
        return self.candidate


class _MLCapabilityReader:
    def __init__(self, capability: dict[str, object]) -> None:
        self.capability = capability
        self.calls = 0

    async def capabilities(self) -> dict[str, object]:
        self.calls += 1
        return self.capability


def _request(
    *,
    question: str = "2026년 6월 객실 매출을 분석해줘",
    role: Role = Role.ANALYST,
    admitted: bool = True,
    invocation: MLPredictionInvocation | None = None,
) -> AgentRequest:
    conversation_id = uuid4()
    user_id = uuid4()
    context = RequestContext(
        conversation_id=conversation_id if admitted else None,
        user_id=user_id,
        role=role,
        permission_snapshot_id=(
            permission_snapshot_id(user_id, role) if admitted else None
        ),
        product_release_id="product-release-v1" if admitted else None,
        semantic_release_id="semantic-release-v1" if admitted else None,
        command_id=uuid4() if admitted else None,
    )
    return AgentRequest(
        conversation_id=conversation_id,
        command=ConversationCommandRequest(
            user_message=question,
            idempotency_key=uuid4().hex,
            expected_head_turn_id=None,
            requested_route=(
                "ML_PREDICTION" if invocation is not None else None
            ),
            ml_prediction=(
                {
                    "property_id": invocation.property_id,
                    "as_of": invocation.as_of,
                    "horizon_days": invocation.horizon_days,
                }
                if invocation is not None
                else None
            ),
        ),
        context=context,
        target_agent=(AgentKind.ML_PREDICTION if invocation is not None else None),
        invocation=invocation,
    )


def _candidates(
    *,
    product_release_id: str = "product-release-v1",
    semantic_release_id: str = "semantic-release-v1",
) -> AssetCandidateSet:
    return AssetCandidateSet(
        assets=(
            {
                "urn": "urn:li:dataset:(urn:li:dataPlatform:trino,hotel.room,PROD)",
                "fqn": "hotel.room",
                "metrics": [
                    {
                        "id": "room_revenue",
                        "visibility": "BUSINESS",
                        "candidate_selectable": True,
                    }
                ],
            },
        ),
        context_release=semantic_release_id,
        catalog_checksum="a" * 64,
        canonical_checksum="b" * 64,
        product_release_id=product_release_id,
        runtime_projection_checksum="c" * 64,
        source_authority="DATAHUB_NATIVE_METRIC_V1",
        retrieval_mode="datahub_lexical",
    )


def _rag_candidate(*, matched: bool = True) -> dict[str, object]:
    return {
        "schema_version": "RagCapabilityCandidate.v1",
        "matched": matched,
        "retrieval_request_id": str(uuid4()),
        "query_hash": "d" * 64,
        "tool_code": "internal-manual-search",
        "tool_version": "1.0.0-rc1",
        "model_revision": "text-embedding-3-large:d1024",
        "embedding_dimension": 1024,
        "evidence_ids": ["POL-PRIVACY-001:1.0:1:chunk-1"] if matched else [],
        "document_ids": ["POL-PRIVACY-001"] if matched else [],
        "maximum_score": 0.87 if matched else None,
    }


def _ml_capability(
    *,
    max_horizon_days: int = 90,
    approval: str = "APPROVED",
    approval_status: str = "APPROVED",
    synthetic_training_data: bool = False,
) -> dict[str, object]:
    return {
        "schema_version": "MLRuntimeCapability.v2",
        "prediction_contract_version": "MLRoomDemandPrediction.v1",
        "model_version": "approved-demand-release",
        "model_hash": "a" * 64,
        "feature_contract_sha256": "b" * 64,
        "model_type": "daily-demand-forecast",
        "estimator_type": "ApprovedRegressor",
        "approval": approval,
        "approval_status": approval_status,
        "min_horizon_days": 1,
        "max_horizon_days": max_horizon_days,
        "model_max_horizon_days": max_horizon_days,
        "properties": [
            {
                "property_id": "GRAND",
                "min_as_of": "2025-01-01",
                "max_as_of": "2026-12-31",
                "feature_max_as_of": "2026-08-28",
                "history_rows": 500,
            }
        ],
        "synthetic_training_data": synthetic_training_data,
        "history_source": {
            "table": "pms.ml_evaluation.approved_history",
            "row_count": 500,
            "property_count": 1,
            "series_count": 1,
            "min_date": "2024-01-01",
            "max_date": "2026-08-28",
            "synthetic_only": synthetic_training_data,
            "summary_query_id": "summary-query",
            "continuity_query_id": "continuity-query",
        },
        "query_id": "capability-query",
    }


class GovernedAnalysisCapabilityProbeTest(unittest.IsolatedAsyncioTestCase):
    """Probe가 모델 호출 없이 admission-bound 후보만 근거로 삼는지 확인한다."""

    async def test_matching_candidate_returns_release_bound_checksum_reference(self) -> None:
        request = _request()
        platform = _CandidatePlatform(_candidates())
        probe = GovernedAnalysisCapabilityProbe(platform)

        first = await probe.probe(request)
        second = await probe.probe(request)

        self.assertTrue(first.matched)
        self.assertEqual(first.agent, AgentKind.ANALYSIS_WORKFLOW)
        self.assertEqual(first.reason, "ANALYSIS_CAPABILITY_MATCH")
        self.assertEqual(first.evidence_refs, second.evidence_refs)
        self.assertRegex(
            first.evidence_refs[0],
            r"^agent-capability:v1:analysis-workflow:[0-9a-f]{64}$",
        )
        self.assertNotIn(request.command.user_message, first.evidence_refs[0])
        self.assertEqual(platform.calls[0][0], request.command.user_message)
        self.assertEqual(
            platform.calls[0][1]["permission_snapshot_id"],
            request.context.permission_snapshot_id,
        )

    async def test_question_changes_the_receipt_without_exposing_the_question(self) -> None:
        platform = _CandidatePlatform(_candidates())
        probe = GovernedAnalysisCapabilityProbe(platform)
        first_request = _request(question="객실 매출 분석")
        second_request = first_request.model_copy(
            update={
                "command": first_request.command.model_copy(
                    update={"user_message": "예약 취소율 분석"}
                )
            }
        )

        first = await probe.probe(first_request)
        second = await probe.probe(second_request)

        self.assertNotEqual(first.evidence_refs, second.evidence_refs)

    async def test_previous_analysis_uses_typed_metric_hint_without_rewriting_query(self) -> None:
        request = _request(question="3월부터 5월은?").model_copy(
            update={
                "previous_analysis": AgentPreviousAnalysisContext(
                    metric_ids=("room_revenue",),
                    period_start="2026-06-01",
                    period_end_exclusive="2026-07-01",
                )
            }
        )
        platform = _CandidatePlatform(_candidates())

        evidence = await GovernedAnalysisCapabilityProbe(platform).probe(request)

        self.assertTrue(evidence.matched)
        self.assertEqual(platform.calls[0][0], "3월부터 5월은?")
        self.assertEqual(
            platform.calls[0][1]["preferred_metric_ids"],
            ["room_revenue"],
        )

    async def test_no_governed_metric_is_a_receipted_non_match(self) -> None:
        platform = _CandidatePlatform(
            error=NoMetricMatchError("no governed metric")
        )
        evidence = await GovernedAnalysisCapabilityProbe(platform).probe(_request())

        self.assertFalse(evidence.matched)
        self.assertEqual(evidence.reason, "ANALYSIS_CAPABILITY_NOT_MATCHED")
        self.assertRegex(evidence.evidence_refs[0], r"[0-9a-f]{64}$")

    async def test_role_without_analysis_capability_does_not_search_catalog(self) -> None:
        platform = _CandidatePlatform(_candidates())
        evidence = await GovernedAnalysisCapabilityProbe(platform).probe(
            _request(role=Role.REPORT_ADMIN)
        )

        self.assertFalse(evidence.matched)
        self.assertEqual(platform.calls, [])

    async def test_unadmitted_request_is_rejected_before_catalog_search(self) -> None:
        platform = _CandidatePlatform(_candidates())

        with self.assertRaises(AgentDispatchError) as raised:
            await GovernedAnalysisCapabilityProbe(platform).probe(
                _request(admitted=False)
            )

        self.assertEqual(
            raised.exception.code,
            "AGENT_CAPABILITY_CONTEXT_INCOMPLETE",
        )
        self.assertEqual(platform.calls, [])

    async def test_candidate_release_drift_is_not_a_non_match(self) -> None:
        platform = _CandidatePlatform(
            _candidates(product_release_id="different-product-release")
        )

        with self.assertRaises(MetadataUnavailableError):
            await GovernedAnalysisCapabilityProbe(platform).probe(_request())

    async def test_unapproved_candidate_authority_is_rejected(self) -> None:
        candidates = _candidates()
        platform = _CandidatePlatform(
            replace(
                candidates,
                source_authority="UNAPPROVED_METADATA_SOURCE",
            )
        )

        with self.assertRaises(MetadataUnavailableError):
            await GovernedAnalysisCapabilityProbe(platform).probe(_request())


class InternalGuidelineCapabilityProbeTest(unittest.IsolatedAsyncioTestCase):
    """RAG probe가 답변 없이 승인 검색 후보만 receipt로 봉인하는지 확인한다."""

    async def test_matching_search_returns_deterministic_checksum_reference(self) -> None:
        request = _request(question="개인정보 유출 시 보고 절차를 알려줘")
        searcher = _GuidelineSearcher(_rag_candidate())
        probe = InternalGuidelineCapabilityProbe(searcher)

        first = await probe.probe(request)
        second = await probe.probe(request)

        self.assertTrue(first.matched)
        self.assertEqual(first.agent, AgentKind.INTERNAL_GUIDELINE)
        self.assertEqual(first.reason, "RAG_CAPABILITY_MATCH")
        self.assertEqual(first.evidence_refs, second.evidence_refs)
        self.assertRegex(
            first.evidence_refs[0],
            r"^agent-capability:v1:internal-guideline:[0-9a-f]{64}$",
        )
        self.assertNotIn(request.command.user_message, first.evidence_refs[0])
        self.assertEqual(
            searcher.calls[0],
            (request.command.user_message, "analyst"),
        )

    async def test_no_evidence_is_a_receipted_non_match(self) -> None:
        searcher = _GuidelineSearcher(_rag_candidate(matched=False))

        evidence = await InternalGuidelineCapabilityProbe(searcher).probe(
            _request(question="승인 문서에 없는 질문")
        )

        self.assertFalse(evidence.matched)
        self.assertEqual(evidence.reason, "RAG_CAPABILITY_NOT_MATCHED")
        self.assertRegex(evidence.evidence_refs[0], r"[0-9a-f]{64}$")

    async def test_role_without_capability_does_not_call_rag_search(self) -> None:
        searcher = _GuidelineSearcher(_rag_candidate())

        evidence = await InternalGuidelineCapabilityProbe(searcher).probe(
            _request(role=Role.REPORT_ADMIN)
        )

        self.assertFalse(evidence.matched)
        self.assertEqual(searcher.calls, [])

    async def test_candidate_with_unexpected_raw_field_is_rejected(self) -> None:
        candidate = _rag_candidate()
        candidate["content"] = "route receipt에 들어가면 안 되는 원문"

        with self.assertRaises(AgentDispatchError) as raised:
            await InternalGuidelineCapabilityProbe(
                _GuidelineSearcher(candidate)
            ).probe(_request())

        self.assertEqual(
            raised.exception.code,
            "AGENT_CAPABILITY_EVIDENCE_INVALID",
        )


class MLPredictionCapabilityProbeTest(unittest.IsolatedAsyncioTestCase):
    async def test_structured_ninety_day_invocation_matches_runtime_receipt(self) -> None:
        reader = _MLCapabilityReader(_ml_capability(max_horizon_days=90))
        request = _request(
            invocation=MLPredictionInvocation(
                property_id="GRAND",
                as_of="2026-08-28",
                horizon_days=90,
            )
        )

        evidence = await MLPredictionCapabilityProbe(reader).probe(request)

        self.assertTrue(evidence.matched)
        self.assertEqual(evidence.agent, AgentKind.ML_PREDICTION)
        self.assertRegex(
            evidence.evidence_refs[0],
            r"^agent-capability:v1:ml-prediction:[0-9a-f]{64}$",
        )
        self.assertEqual(reader.calls, 1)

    async def test_missing_structured_invocation_never_calls_ml_runtime(self) -> None:
        reader = _MLCapabilityReader(_ml_capability())

        evidence = await MLPredictionCapabilityProbe(reader).probe(_request())

        self.assertFalse(evidence.matched)
        self.assertEqual(reader.calls, 0)

    async def test_runtime_horizon_is_the_effective_probe_limit(self) -> None:
        reader = _MLCapabilityReader(_ml_capability(max_horizon_days=7))
        request = _request(
            invocation=MLPredictionInvocation(
                property_id="GRAND",
                as_of="2026-08-28",
                horizon_days=90,
            )
        )

        evidence = await MLPredictionCapabilityProbe(reader).probe(request)

        self.assertFalse(evidence.matched)
        self.assertEqual(reader.calls, 1)

    async def test_nonproduction_runtime_receipt_never_matches_registry_probe(self) -> None:
        request = _request(
            invocation=MLPredictionInvocation(
                property_id="GRAND",
                as_of="2026-08-28",
                horizon_days=7,
            )
        )
        candidates = (
            (
                _ml_capability(
                    approval="CONDITIONAL_PASS",
                    approval_status="VALIDATED",
                ),
                "ML_RELEASE_NOT_PRODUCTION_APPROVED",
            ),
            (
                _ml_capability(synthetic_training_data=True),
                "ML_SYNTHETIC_TRAINING_DATA_BLOCKED",
            ),
        )

        for capability, expected_reason in candidates:
            with self.subTest(expected_reason=expected_reason):
                reader = _MLCapabilityReader(capability)
                evidence = await MLPredictionCapabilityProbe(reader).probe(request)

                self.assertFalse(evidence.matched)
                self.assertEqual(evidence.reason, expected_reason)
                self.assertEqual(reader.calls, 1)

    async def test_explicitly_allowed_synthetic_candidate_matches_registry_probe(self) -> None:
        request = _request(
            invocation=MLPredictionInvocation(
                property_id="GRAND",
                as_of="2026-08-28",
                horizon_days=7,
            )
        )
        reader = _MLCapabilityReader(
            _ml_capability(
                approval="CONDITIONAL_PASS",
                approval_status="VALIDATED_SYNTHETIC",
                synthetic_training_data=True,
            )
        )

        with patch.dict("os.environ", {"ML_ALLOW_CONDITIONAL": "true"}):
            evidence = await MLPredictionCapabilityProbe(reader).probe(request)

        self.assertTrue(evidence.matched)
        self.assertEqual(evidence.agent, AgentKind.ML_PREDICTION)
        self.assertEqual(reader.calls, 1)

    async def test_missing_deployment_approval_field_is_invalid_evidence(self) -> None:
        capability = _ml_capability()
        capability.pop("approval_status")
        request = _request(
            invocation=MLPredictionInvocation(
                property_id="GRAND",
                as_of="2026-08-28",
                horizon_days=7,
            )
        )

        with self.assertRaises(AgentDispatchError) as raised:
            await MLPredictionCapabilityProbe(
                _MLCapabilityReader(capability)
            ).probe(request)

        self.assertEqual(
            raised.exception.code,
            "AGENT_CAPABILITY_EVIDENCE_INVALID",
        )

if __name__ == "__main__":
    unittest.main()
