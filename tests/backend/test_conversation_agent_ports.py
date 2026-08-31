"""concrete Conversation AgentPort와 내부지침 use case 경계를 검증한다."""

from __future__ import annotations

from pathlib import Path
import sys
import unittest
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "app" / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.contracts import AnalysisStatus, RequestContext
from app.conversation_contracts import ConversationCommandRequest
from app.ports.agent import (
    AgentKind,
    AgentPortReadiness,
    AgentRequest,
    MLPredictionInvocation,
)
from app.services.conversation_agent_ports import (
    AnalysisWorkflowAgentPort,
    InternalGuidelineAgentPort,
    MLPredictionAgentPort,
)
from app.services.execution_control import ConcurrentExecutionGate
from app.services.internal_manual_query import (
    InternalManualQuery,
    InternalManualQueryError,
    InternalManualQueryService,
)


def _agent_request(
    route: str | None = None,
    *,
    inherit_previous_context: bool = False,
) -> AgentRequest:
    conversation_id = uuid4()
    return AgentRequest(
        conversation_id=conversation_id,
        command=ConversationCommandRequest(
            user_message="승인된 범위에서 처리해줘",
            idempotency_key=uuid4().hex,
            expected_head_turn_id=None,
            requested_route=route,
            inherit_previous_context=inherit_previous_context,
        ),
        context=RequestContext(conversation_id=conversation_id),
    )


class _ProgressTracker:
    def __init__(self) -> None:
        self.started: list[object] = []
        self.finished: list[tuple[object, AnalysisStatus]] = []

    def start(self, *values: object) -> None:
        self.started.append(values)

    def record(self, *values: object) -> None:
        return None

    def cancelled(self, request_id: object) -> bool:
        return False

    def finish(self, request_id: object, status: AnalysisStatus) -> None:
        self.finished.append((request_id, status))


class _AnalysisOrchestrator:
    def __init__(self, result: dict) -> None:
        self.result = result
        self.calls: list[tuple] = []

    async def execute_command(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.result


class _RagOrchestrator:
    def __init__(self, turn_id) -> None:
        self.turn_id = turn_id

    async def execute_internal_guideline_command(
        self,
        conversation_id,
        payload,
        context,
        executor,
    ):
        rag_response = await executor(context)
        return {
            "status": "SUCCESS",
            "turn": {"turn_id": self.turn_id, "route": "INTERNAL_GUIDELINE"},
            "conversation": {
                "conversation_id": conversation_id,
                "owner_id": context.user_id,
            },
            "rag_response": rag_response,
        }


class _RagRepository:
    def __init__(self, conversation_id, turn_id) -> None:
        self.conversation_id = conversation_id
        self.turn_id = turn_id
        self.appended: tuple | None = None

    async def get_conversation(self, conversation_id, user_id):
        if conversation_id != self.conversation_id:
            return None
        return {"conversation_id": conversation_id, "owner_id": user_id}

    async def list_turns(self, conversation_id):
        return [
            {
                "route": "INTERNAL_GUIDELINE",
                "resolved_slots": {
                    "rag": {
                        "routing": {
                            "snapshot_question": "승인된 시설 안전 절차",
                            "selected_document_ids": ["MANUAL-SAFETY"],
                        }
                    }
                },
            }
        ]

    async def append_rag_turn(self, *args):
        self.appended = args
        return self.turn_id


class _RagExecutor:
    def __init__(self) -> None:
        self.kwargs: dict = {}

    async def execute(self, **kwargs):
        self.kwargs = kwargs
        return {
            "status": "ANSWER",
            "routing": {"snapshot_question": kwargs["query"]},
            "processing_steps": ["DOCUMENT_SEARCHED", "ANSWERED"],
            "document": {"body": "승인된 시설 안전 절차"},
        }

    async def runtime_receipt(self, app_role: str):
        return {
            "schema_version": "RagRuntimeReceipt.v1",
            "tool_code": "internal-manual-search",
            "tool_version": "1.0.0",
            "model_revision": "embedding-release:d1536",
            "embedding_dimension": 1536,
            "corpus_manifest_sha256": "b" * 64,
            "processing_profile_sha256": "c" * 64,
            "capability_hash": "a" * 64,
        }


class ConversationAgentPortTest(unittest.IsolatedAsyncioTestCase):
    async def test_analysis_port_forwards_pre_admission_without_reacquiring_it(self) -> None:
        request = _agent_request("ANALYSIS")
        admission = object()
        orchestrator = _AnalysisOrchestrator(
            {"status": "SUCCESS", "turn": {"route": "ANALYSIS"}}
        )
        port = AnalysisWorkflowAgentPort(
            orchestrator,
            ConcurrentExecutionGate(),
            _ProgressTracker(),
            admission=admission,
        )

        await port.execute(request)

        self.assertIs(orchestrator.calls[0][1]["admission"], admission)

    async def test_analysis_port_preserves_result_and_progress_contract(self) -> None:
        request = _agent_request("ANALYSIS")
        orchestrator = _AnalysisOrchestrator(
            {"status": "SUCCESS", "turn": {"route": "ANALYSIS"}}
        )
        progress = _ProgressTracker()
        port = AnalysisWorkflowAgentPort(
            orchestrator,
            ConcurrentExecutionGate(),
            progress,
        )

        result = await port.execute(request)

        self.assertEqual(result.agent, AgentKind.ANALYSIS_WORKFLOW)
        self.assertEqual(result.payload["data"]["status"], "SUCCESS")
        self.assertEqual(len(orchestrator.calls), 1)
        self.assertEqual(
            progress.finished,
            [(request.context.request_id, AnalysisStatus.SUCCEEDED)],
        )

    async def test_internal_guideline_port_uses_service_and_public_reader(self) -> None:
        request = _agent_request("INTERNAL_GUIDELINE")
        turn_id = uuid4()
        repository = _RagRepository(request.conversation_id, turn_id)
        executor = _RagExecutor()
        service = InternalManualQueryService(
            repository,
            lambda: executor,
            enabled=True,
        )
        port = InternalGuidelineAgentPort(
            _RagOrchestrator(turn_id),
            lambda: service,
        )

        result = await port.execute(request)

        self.assertEqual(result.agent, AgentKind.INTERNAL_GUIDELINE)
        self.assertEqual(result.payload["data"]["type"], "INTERNAL_GUIDELINE")
        self.assertEqual(result.payload["data"]["turn"]["turn_id"], turn_id)
        rag_response = result.payload["data"]["rag_response"]
        self.assertEqual(
            rag_response["routing"]["snapshot_question"],
            request.command.user_message,
        )
        self.assertEqual(
            rag_response["processing_steps"],
            ["DOCUMENT_SEARCHED", "ANSWERED"],
        )
        self.assertEqual(
            rag_response["document"],
            {"body": "승인된 시설 안전 절차"},
        )
        self.assertIsNone(repository.appended)

    async def test_internal_guideline_readiness_is_runtime_receipted(self) -> None:
        request = _agent_request("INTERNAL_GUIDELINE")
        service = InternalManualQueryService(
            _RagRepository(request.conversation_id, uuid4()),
            lambda: _RagExecutor(),
            enabled=True,
        )
        port = InternalGuidelineAgentPort(
            _RagOrchestrator(uuid4()),
            lambda: service,
        )

        readiness = await port.readiness(request)

        self.assertEqual(readiness.status, "ready")
        self.assertTrue(
            any(ref.startswith("rag-capability:sha256:") for ref in readiness.release_refs)
        )
        self.assertIn("rag-corpus:sha256:" + "b" * 64, readiness.release_refs)
        self.assertIn("rag-processing:sha256:" + "c" * 64, readiness.release_refs)

    async def test_ml_port_executes_only_the_structured_invocation(self) -> None:
        class MLService:
            async def readiness(self):
                return AgentPortReadiness(
                    agent=AgentKind.ML_PREDICTION,
                    status="ready",
                    capability_version="MLRuntimeCapability.v1",
                    release_refs=("ml-model:sha256:" + "a" * 64,),
                )

            async def generate_prediction(self, payload):
                self.payload = payload
                return {"status": "SUCCEEDED", "horizon_days": payload["horizon_days"]}

            async def persist_prediction(self, session, prediction):
                self.session = session
                self.persisted = prediction

        class MLOrchestrator:
            async def execute_ml_prediction_command(
                self,
                conversation_id,
                payload,
                context,
                executor,
                persister,
            ):
                prediction = await executor(context)
                await persister(object(), prediction)
                return {
                    "status": "SUCCESS",
                    "turn": {"turn_id": uuid4(), "route": "ML_PREDICTION"},
                    "conversation": {"conversation_id": conversation_id},
                    "ml_prediction": prediction,
                    "is_idempotent_replay": False,
                }

        conversation_id = uuid4()
        invocation = MLPredictionInvocation(
            property_id="GRAND",
            as_of="2026-08-28",
            horizon_days=90,
        )
        request = AgentRequest(
            conversation_id=conversation_id,
            command=ConversationCommandRequest(
                user_message="90일 객실 수요를 예측해줘",
                idempotency_key=uuid4().hex,
                expected_head_turn_id=None,
                requested_route="ML_PREDICTION",
                ml_prediction={
                    "property_id": invocation.property_id,
                    "as_of": invocation.as_of,
                    "horizon_days": invocation.horizon_days,
                },
            ),
            context=RequestContext(conversation_id=conversation_id),
            target_agent=AgentKind.ML_PREDICTION,
            invocation=invocation,
        )
        service = MLService()
        port = MLPredictionAgentPort(
            MLOrchestrator(),
            service,  # type: ignore[arg-type]
        )

        result = await port.execute(request)

        self.assertEqual(result.agent, AgentKind.ML_PREDICTION)
        self.assertEqual(service.payload["horizon_days"], 90)
        self.assertEqual(service.persisted, result.payload["data"]["ml_prediction"])

    async def test_internal_guideline_port_forwards_pre_admission(self) -> None:
        request = _agent_request("INTERNAL_GUIDELINE")
        admission = object()
        captured: dict = {}

        class Orchestrator:
            async def execute_internal_guideline_command(
                self,
                conversation_id,
                payload,
                context,
                executor,
                **kwargs,
            ):
                captured.update(kwargs)
                return {
                    "status": "SUCCESS",
                    "turn": {"turn_id": uuid4(), "route": "INTERNAL_GUIDELINE"},
                    "conversation": {"conversation_id": conversation_id},
                    "rag_response": {"status": "ANSWER"},
                }

        port = InternalGuidelineAgentPort(
            Orchestrator(),
            lambda: None,
            admission=admission,
        )

        await port.execute(request)

        self.assertIs(captured["admission"], admission)

    async def test_internal_guideline_port_preserves_admission_error_status(self) -> None:
        """공통 admission의 권한 오류를 일반 409로 뭉개지 않는다."""

        class RejectedOrchestrator:
            async def execute_internal_guideline_command(self, *args):
                return {
                    "status": "CONFLICT",
                    "code": "ACCESS_DENIED",
                    "message": "Conversation 권한 snapshot이 변경되었습니다.",
                }

        port = InternalGuidelineAgentPort(
            RejectedOrchestrator(),
            lambda: None,
        )

        with self.assertRaises(InternalManualQueryError) as raised:
            await port.execute(_agent_request("INTERNAL_GUIDELINE"))

        self.assertEqual(raised.exception.code, "ACCESS_DENIED")
        self.assertEqual(raised.exception.status_code, 403)

    async def test_internal_guideline_replay_does_not_construct_gateway_service(self) -> None:
        """저장된 terminal replay는 현재 RAG Gateway 구성에 의존하지 않는다."""

        turn_id = uuid4()

        class ReplayOrchestrator:
            async def execute_internal_guideline_command(self, *args):
                return {
                    "status": "SUCCESS",
                    "turn": {"turn_id": turn_id, "route": "INTERNAL_GUIDELINE"},
                    "conversation": {"conversation_id": args[0]},
                    "rag_response": {"status": "ANSWER"},
                    "is_idempotent_replay": True,
                }

        def unavailable_factory():
            raise AssertionError("terminal replay에서 Gateway service를 만들면 안 됩니다.")

        port = InternalGuidelineAgentPort(
            ReplayOrchestrator(),
            unavailable_factory,
        )
        result = await port.execute(_agent_request("INTERNAL_GUIDELINE"))

        self.assertEqual(result.payload["data"]["turn"]["turn_id"], turn_id)

    async def test_internal_manual_followup_uses_only_approved_snapshot(self) -> None:
        conversation_id = uuid4()
        repository = _RagRepository(conversation_id, uuid4())
        executor = _RagExecutor()
        service = InternalManualQueryService(
            repository,
            lambda: executor,
            enabled=True,
        )

        result = await service.execute(
            InternalManualQuery(
                question="그 절차를 더 설명해줘",
                mode="DOCUMENT_ONLY",
                conversation_id=conversation_id,
                inherit_previous_context=True,
            ),
            RequestContext(),
        )

        self.assertEqual(
            executor.kwargs["recent_utterances"],
            ("승인된 시설 안전 절차",),
        )
        self.assertEqual(
            executor.kwargs["selected_document_ids"],
            ("MANUAL-SAFETY",),
        )
        self.assertEqual(result["routing"]["context_source"], "APPROVED_RAG_SNAPSHOT")
        self.assertIsNotNone(repository.appended)

    async def test_internal_manual_followup_without_snapshot_fails_closed(self) -> None:
        conversation_id = uuid4()
        repository = _RagRepository(conversation_id, uuid4())

        async def no_turns(target_conversation_id):
            return []

        repository.list_turns = no_turns
        service = InternalManualQueryService(
            repository,
            lambda: _RagExecutor(),
            enabled=True,
        )

        with self.assertRaises(InternalManualQueryError) as raised:
            await service.execute(
                InternalManualQuery(
                    question="그 절차를 더 설명해줘",
                    mode="DOCUMENT_ONLY",
                    conversation_id=conversation_id,
                    inherit_previous_context=True,
                ),
                RequestContext(),
            )

        self.assertEqual(raised.exception.code, "RAG_APPROVED_CONTEXT_MISSING")
        self.assertEqual(raised.exception.status_code, 409)


if __name__ == "__main__":
    unittest.main()
