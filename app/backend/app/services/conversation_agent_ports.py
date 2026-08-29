"""현재 Conversation workflow를 concrete AgentPort로 노출한다."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import os
from typing import Any

from app.context import ContextValidationError
from app.contracts import AnalysisStatus, ErrorCode
from app.ports.agent import AgentKind, AgentRequest, AgentResult
from app.services.analysis import analysis_progress
from app.services.execution_control import ConcurrentExecutionGate
from app.services.internal_manual_query import (
    InternalManualQuery,
    InternalManualQueryError,
    InternalManualQueryService,
)


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
                "type": "INTERNAL_GUIDELINE",
                "turn": command_result.get("turn"),
                "conversation": command_result.get("conversation"),
                "rag_response": command_result.get("rag_response"),
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
    ) -> None:
        self._orchestrator = orchestrator
        self._execution_gate = execution_gate
        self._progress = progress_tracker
        self._admission = admission

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
    ) -> None:
        self._orchestrator = orchestrator
        self._query_service_factory = query_service_factory
        self._admission = admission

    async def execute(self, request: AgentRequest) -> AgentResult:
        """명시 RAG 요청을 공통 command lifecycle로 실행하고 결과 Turn을 반환한다."""

        command = request.command

        async def _execute(admitted_context: Any) -> dict[str, Any]:
            return await self._query_service_factory().execute(
                InternalManualQuery(
                    question=command.user_message,
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
        command_result = await self._orchestrator.execute_internal_guideline_command(
            request.conversation_id,
            command.model_dump(mode="python"),
            request.context,
            _execute,
            **execution_options,
        )
        return internal_guideline_agent_result(command_result)
