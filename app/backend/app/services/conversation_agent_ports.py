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
    InternalManualQueryService,
)


class AnalysisWorkflowAgentPort:
    """기존 거버넌스 Conversation workflow를 분석 Agent 경계로 실행한다."""

    agent = AgentKind.ANALYSIS_WORKFLOW

    def __init__(
        self,
        orchestrator: Any,
        execution_gate: ConcurrentExecutionGate,
        progress_tracker: Any = analysis_progress,
    ) -> None:
        self._orchestrator = orchestrator
        self._execution_gate = execution_gate
        self._progress = progress_tracker

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
                result = await self._orchestrator.execute_command(
                    request.conversation_id,
                    request.command.model_dump(mode="python"),
                    context,
                    progress_sink=lambda stage, outcome: self._progress.record(
                        context.request_id,
                        stage,
                        outcome,
                    ),
                    cancel_check=lambda: self._progress.cancelled(
                        context.request_id
                    ),
                    analysis_gate=self._execution_gate,
                    analysis_queue_wait_seconds=float(
                        os.getenv("ANALYSIS_QUEUE_WAIT_SECONDS", "0")
                    ),
                )
            final_status = {
                "SUCCESS": AnalysisStatus.SUCCEEDED,
                "PARTIAL": AnalysisStatus.PARTIAL,
                "BLOCKED": AnalysisStatus.BLOCKED,
                "CLARIFICATION_REQUIRED": AnalysisStatus.BLOCKED,
                "CANCELLED": AnalysisStatus.CANCELLED,
            }.get(str(result.get("status")), AnalysisStatus.FAILED)
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
                public_code = code_map.get(
                    raw_code,
                    ErrorCode.RESOURCE_CONFLICT,
                )
                status_code = (
                    403
                    if public_code is ErrorCode.ACCESS_DENIED
                    else 429
                    if public_code is ErrorCode.RATE_LIMITED
                    else 409
                )
                raise ContextValidationError(
                    public_code,
                    str(
                        result.get("message")
                        or "현재 대화 상태와 요청이 충돌합니다."
                    ),
                    status_code,
                )
            return AgentResult(
                agent=self.agent,
                payload={"status": "SUCCESS", "data": result},
            )
        finally:
            self._progress.finish(context.request_id, final_status)


class InternalGuidelineAgentPort:
    """승인된 내부지침 use case를 Conversation 응답 계약으로 조립한다."""

    agent = AgentKind.INTERNAL_GUIDELINE

    def __init__(
        self,
        orchestrator: Any,
        query_service_factory: Callable[[], InternalManualQueryService],
    ) -> None:
        self._orchestrator = orchestrator
        self._query_service_factory = query_service_factory

    async def execute(self, request: AgentRequest) -> AgentResult:
        """명시 RAG 요청을 실행하고 저장된 Turn·Conversation을 함께 반환한다."""

        command = request.command
        rag_result = await self._query_service_factory().execute(
            InternalManualQuery(
                question=command.user_message,
                mode="DOCUMENT_ONLY",
                conversation_id=request.conversation_id,
                expected_head_turn_id=command.expected_head_turn_id,
                # 기존 API helper는 이 필드를 항상 명시해 CAS를 활성화했다.
                expected_head_turn_id_is_set=True,
                inherit_previous_context=command.inherit_previous_context,
            ),
            request.context,
        )
        turns = await self._orchestrator.list_turns(request.conversation_id)
        payload = {
            "status": "SUCCESS",
            "data": {
                "status": "COMPLETED",
                "type": "INTERNAL_GUIDELINE",
                "turn": next(
                    (
                        item
                        for item in turns
                        if str(item["turn_id"]) == str(rag_result.get("turn_id"))
                    ),
                    None,
                ),
                "conversation": await self._orchestrator.get_conversation(
                    request.conversation_id,
                    request.context.user_id,
                ),
                "rag_response": rag_result,
            },
        }
        return AgentResult(agent=self.agent, payload=payload)
