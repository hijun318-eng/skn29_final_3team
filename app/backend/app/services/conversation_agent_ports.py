"""현재 Conversation workflow를 concrete AgentPort로 노출한다."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import os
from typing import Any

from app.context import ContextValidationError
from app.contracts import AnalysisStatus, ErrorCode
from app.ports.agent import AgentKind, AgentPortReadiness, AgentRequest, AgentResult
from app.services.agent_supervisor import AgentDispatchError
from app.services.analysis import analysis_progress
from app.services.execution_control import ConcurrentExecutionGate
from app.services.internal_manual_query import (
    InternalManualQuery,
    InternalManualQueryError,
    InternalManualQueryService,
)
from app.services.mcp_agent_tools import MCPMLPredictionExecutor


def analysis_agent_result(result: dict[str, Any]) -> AgentResult:
    """Conversation workflow 결과를 기존 분석 Agent 공개 계약으로 변환한다."""

    if result.get("status") in {"CONFLICT", "BUSY"}:
        raw_code = str(result.get("code") or "")
        code_map = {
            "CONVERSATION_CONFLICT": ErrorCode.CONVERSATION_CONFLICT,
            "CONVERSATION_BUSY": ErrorCode.CONVERSATION_BUSY,
            "CONVERSATION_ARCHIVED": ErrorCode.CONVERSATION_ARCHIVED,
            "IDEMPOTENCY_CONFLICT": ErrorCode.IDEMPOTENCY_CONFLICT,
            "IDEMPOTENCY_PAYLOAD_MISMATCH": ErrorCode.IDEMPOTENCY_CONFLICT,
            "RESOURCE_CONFLICT": ErrorCode.RESOURCE_CONFLICT,
            "PRODUCT_RELEASE_MISMATCH": ErrorCode.RESOURCE_CONFLICT,
            "ACCESS_DENIED": ErrorCode.ACCESS_DENIED,
            "PERMISSION_SNAPSHOT_MISMATCH": ErrorCode.ACCESS_DENIED,
            "RATE_LIMITED": ErrorCode.RATE_LIMITED,
        }
        public_code = code_map.get(raw_code, ErrorCode.RESOURCE_CONFLICT)
        status_code = (
            403
            if public_code is ErrorCode.ACCESS_DENIED
            else 429
            if public_code is ErrorCode.RATE_LIMITED
            else 409
        )
        raise ContextValidationError(
            public_code,
            str(result.get("message") or "현재 대화 상태와 요청이 충돌합니다."),
            status_code,
        )
    return AgentResult(
        agent=AgentKind.ANALYSIS_WORKFLOW,
        payload={"status": "SUCCESS", "data": result},
    )


def internal_guideline_agent_result(command_result: dict[str, Any]) -> AgentResult:
    """내부지침 command 결과를 기존 RAG Agent 공개 계약으로 변환한다."""

    if command_result.get("status") != "SUCCESS":
        status = str(command_result.get("status") or "FAILED")
        error_code = str(command_result.get("code") or "RAG_COMMAND_FAILED")
        raw_status_code = command_result.get("_http_status_code")
        status_code = (
            raw_status_code
            if isinstance(raw_status_code, int)
            else 403
            if error_code == ErrorCode.ACCESS_DENIED.value
            else 404
            if error_code == "CONVERSATION_NOT_FOUND"
            else 429
            if error_code == ErrorCode.RATE_LIMITED.value
            else 409
            if status in {"CONFLICT", "BUSY"}
            else 503
        )
        raise InternalManualQueryError(
            error_code,
            str(
                command_result.get("message")
                or "내부지침 명령을 완료하지 못했습니다."
            ),
            status_code,
        )
    return AgentResult(
        agent=AgentKind.INTERNAL_GUIDELINE,
        payload={
            "status": "SUCCESS",
            "data": {
                "status": "COMPLETED",
                "type": str(command_result.get("type") or "INTERNAL_GUIDELINE"),
                "turn": command_result.get("turn"),
                "conversation": command_result.get("conversation"),
                "rag_response": command_result.get("rag_response"),
                "ml_prediction": command_result.get("ml_prediction"),
                "composition": command_result.get("composition"),
            },
        },
    )


def ml_prediction_agent_result(command_result: dict[str, Any]) -> AgentResult:
    """ML command terminal 결과를 Conversation 공개 응답 계약으로 변환한다."""

    if command_result.get("status") != "SUCCESS":
        raise AgentDispatchError(
            str(command_result.get("code") or "ML_PREDICTION_COMMAND_FAILED"),
            str(command_result.get("message") or "ML 예측 명령을 완료하지 못했습니다."),
        )
    return AgentResult(
        agent=AgentKind.ML_PREDICTION,
        payload={
            "status": "SUCCESS",
            "data": {
                "status": "COMPLETED",
                "type": "ML_PREDICTION",
                "turn": command_result.get("turn"),
                "conversation": command_result.get("conversation"),
                "ml_prediction": command_result.get("ml_prediction"),
                "is_idempotent_replay": bool(
                    command_result.get("is_idempotent_replay", False)
                ),
            },
        },
    )


class AnalysisWorkflowAgentPort:
    """기존 거버넌스 Conversation workflow를 분석 Agent 경계로 실행한다."""

    agent = AgentKind.ANALYSIS_WORKFLOW

    def __init__(
        self,
        orchestrator: Any,
        execution_gate: ConcurrentExecutionGate,
        progress_tracker: Any = analysis_progress,
        admission: Any | None = None,
        composite_augmentation: Any | None = None,
    ) -> None:
        self._orchestrator = orchestrator
        self._execution_gate = execution_gate
        self._progress = progress_tracker
        self._admission = admission
        self._composite_augmentation = composite_augmentation

    async def readiness(self, request: AgentRequest) -> AgentPortReadiness:
        """공통 admission이 고정한 product·semantic release를 실행 근거로 사용한다."""

        context = request.context
        release_refs = tuple(
            f"{prefix}:{item}"
            for prefix, item in (
                ("product-release", context.product_release_id),
                ("semantic-release", context.semantic_release_id),
            )
            if isinstance(item, str) and item.strip()
        )
        if len(release_refs) != 2:
            return AgentPortReadiness(
                agent=self.agent,
                status="not_ready",
                capability_version="AnalysisWorkflowAgentPort.v1",
                reason="분석 release admission이 완료되지 않았습니다.",
            )
        return AgentPortReadiness(
            agent=self.agent,
            status="ready",
            capability_version="AnalysisWorkflowAgentPort.v1",
            release_refs=release_refs,
        )

    async def execute(self, request: AgentRequest) -> AgentResult:
        """기존 timeout·progress·충돌 변환을 유지해 단일 command를 실행한다."""

        context = request.context
        final_status = AnalysisStatus.FAILED
        self._progress.start(
            context.trace_id,
            context.user_id,
            context.role,
            context.request_id,
        )
        try:
            configured_timeout = float(
                os.getenv("CONVERSATION_COMMAND_TIMEOUT_SECONDS", "90")
            )
            recovery_stale = float(
                os.getenv("CONVERSATION_RECOVERY_STALE_SECONDS", "120")
            )
            command_timeout = max(
                1.0,
                min(configured_timeout, max(1.0, recovery_stale - 5.0)),
            )
            async with asyncio.timeout(command_timeout):
                execution_options: dict[str, Any] = {
                    "progress_sink": lambda stage, outcome: self._progress.record(
                        context.request_id,
                        stage,
                        outcome,
                    ),
                    "cancel_check": lambda: self._progress.cancelled(
                        context.request_id
                    ),
                    "analysis_gate": self._execution_gate,
                    "analysis_queue_wait_seconds": float(
                        os.getenv("ANALYSIS_QUEUE_WAIT_SECONDS", "0")
                    ),
                }
                if self._admission is not None:
                    execution_options["admission"] = self._admission
                if request.supervisor_plan_ref is not None:
                    execution_options.update(
                        supervisor_plan_ref=request.supervisor_plan_ref,
                        task_objective=request.task_objective,
                        task_analysis_route=request.task_analysis_route,
                        task_presentation_type=request.task_presentation_type,
                    )
                if self._composite_augmentation is not None:
                    execution_options["composite_augmentation"] = (
                        self._composite_augmentation
                    )
                result = await self._orchestrator.execute_command(
                    request.conversation_id,
                    request.command.model_dump(mode="python"),
                    context,
                    **execution_options,
                )
            final_status = {
                "SUCCESS": AnalysisStatus.SUCCEEDED,
                "PARTIAL": AnalysisStatus.PARTIAL,
                "BLOCKED": AnalysisStatus.BLOCKED,
                "CLARIFICATION_REQUIRED": AnalysisStatus.BLOCKED,
                "CANCELLED": AnalysisStatus.CANCELLED,
            }.get(str(result.get("status")), AnalysisStatus.FAILED)
            return analysis_agent_result(result)
        finally:
            self._progress.finish(context.request_id, final_status)


class InternalGuidelineAgentPort:
    """승인된 내부지침 use case를 Conversation 응답 계약으로 조립한다."""

    agent = AgentKind.INTERNAL_GUIDELINE

    def __init__(
        self,
        orchestrator: Any,
        query_service_factory: Callable[[], InternalManualQueryService],
        admission: Any | None = None,
        composite_augmentation: Any | None = None,
    ) -> None:
        self._orchestrator = orchestrator
        self._query_service_factory = query_service_factory
        self._query_service: InternalManualQueryService | None = None
        self._admission = admission
        self._composite_augmentation = composite_augmentation

    def _service(self) -> InternalManualQueryService:
        if self._query_service is None:
            self._query_service = self._query_service_factory()
        return self._query_service

    async def readiness(self, request: AgentRequest) -> AgentPortReadiness:
        """현재 요청 주체로 RAG Gateway release를 실행 직전에 확인한다."""

        try:
            readiness = await self._service().readiness(request.context)
        except Exception:
            return AgentPortReadiness(
                agent=self.agent,
                status="not_ready",
                capability_version="RagRuntimeReceipt.v1",
                reason="RAG 실행 서비스가 구성되지 않았습니다.",
            )
        if (
            not isinstance(readiness, AgentPortReadiness)
            or readiness.agent is not self.agent
        ):
            return AgentPortReadiness(
                agent=self.agent,
                status="not_ready",
                capability_version="RagRuntimeReceipt.v1",
                reason="RAG 실행 준비 상태 계약이 올바르지 않습니다.",
            )
        return readiness

    async def execute(self, request: AgentRequest) -> AgentResult:
        """명시 RAG 요청을 공통 command lifecycle로 실행하고 결과 Turn을 반환한다."""

        command = request.command

        async def _execute(admitted_context: Any) -> dict[str, Any]:
            return await self._service().execute(
                InternalManualQuery(
                    question=request.task_objective or command.user_message,
                    mode="DOCUMENT_ONLY",
                    conversation_id=request.conversation_id,
                    expected_head_turn_id=command.expected_head_turn_id,
                    # Turn commit은 orchestrator가 소유하므로 service의 legacy 저장은 끈다.
                    expected_head_turn_id_is_set=True,
                    inherit_previous_context=command.inherit_previous_context,
                ),
                admitted_context,
                persist_turn=False,
            )

        execution_options = {}
        if self._admission is not None:
            execution_options["admission"] = self._admission
        if request.supervisor_plan_ref is not None:
            execution_options["supervisor_plan_ref"] = request.supervisor_plan_ref
        if self._composite_augmentation is not None:
            execution_options["composite_augmentation"] = (
                self._composite_augmentation
            )
        command_result = await self._orchestrator.execute_internal_guideline_command(
            request.conversation_id,
            command.model_dump(mode="python"),
            request.context,
            _execute,
            **execution_options,
        )
        return internal_guideline_agent_result(command_result)


class MLPredictionAgentPort:
    """구조화된 ML invocation만 승인 runtime과 감사 DB 경계로 전달한다."""

    agent = AgentKind.ML_PREDICTION

    def __init__(
        self,
        orchestrator: Any,
        executor: MCPMLPredictionExecutor,
        admission: Any | None = None,
    ) -> None:
        self._orchestrator = orchestrator
        self._executor = executor
        self._admission = admission

    async def readiness(self, request: AgentRequest) -> AgentPortReadiness:
        """모델 release와 capability가 모두 검증된 서비스 영수증을 반환한다."""

        try:
            return await self._executor.readiness(request.context.role)
        except asyncio.CancelledError:
            raise
        except Exception:
            return AgentPortReadiness(
                agent=self.agent,
                status="not_ready",
                capability_version="MCPToolDescriptor.v1",
                reason="ML MCP Tool 또는 예측 runtime이 준비되지 않았습니다.",
            )

    async def execute(self, request: AgentRequest) -> AgentResult:
        """자연어 재해석 없이 승인 resolver의 구조화 invocation을 실행한다."""

        invocation = request.invocation
        if invocation is None or invocation.agent is not self.agent:
            raise ValueError("ML Agent에는 구조화된 prediction invocation이 필요합니다.")
        payload = {
            "property_id": invocation.property_id,
            "as_of": invocation.as_of.isoformat(),
            "horizon_days": invocation.horizon_days,
        }

        async def _generate(_context: Any) -> dict[str, Any]:
            try:
                return await self._executor.execute(
                    payload,
                    subject_id=request.context.user_id,
                    role=request.context.role,
                    trace_id=request.context.trace_id,
                )
            except ValueError as error:
                raise AgentDispatchError(
                    "AGENT_ROUTE_NOT_RESOLVED",
                    "요청한 ML 예측 범위는 현재 지원되지 않습니다.",
                ) from error
            except asyncio.CancelledError:
                raise
            except Exception as error:
                raise AgentDispatchError(
                    "AGENT_PORT_NOT_READY",
                    "ML 예측 실행 서비스를 확인하지 못했습니다.",
                ) from error

        execution_options = {}
        if self._admission is not None:
            execution_options["admission"] = self._admission
        if request.supervisor_plan_ref is not None:
            execution_options["supervisor_plan_ref"] = request.supervisor_plan_ref
        command_result = await self._orchestrator.execute_ml_prediction_command(
            request.conversation_id,
            request.command.model_dump(mode="python"),
            request.context,
            _generate,
            None,
            **execution_options,
        )
        return ml_prediction_agent_result(command_result)
