"""승인 DataHub 후보 기반 Analysis capability probe의 fail-closed 계약을 검증한다."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sys
import unittest
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "app" / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.authorization import permission_snapshot_id
from app.contracts import RequestContext, Role
from app.conversation_contracts import ConversationCommandRequest
from app.ports.agent import AgentKind, AgentRequest
from app.ports.data_platform import (
    AssetCandidateSet,
    MetadataUnavailableError,
    NoMetricMatchError,
)
from app.services.agent_capability_probes import (
    GovernedAnalysisCapabilityProbe,
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


def _request(
    *,
    question: str = "2026년 6월 객실 매출을 분석해줘",
    role: Role = Role.ANALYST,
    admitted: bool = True,
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
        ),
        context=context,
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


if __name__ == "__main__":
    unittest.main()
