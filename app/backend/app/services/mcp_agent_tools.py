"""RAG·HGBR ML runtime을 공용 MCP descriptor·handler 계약으로 조립한다."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Mapping
from typing import Any
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from app.contracts import Capability, Role
from app.database import DatabaseConfigurationError, session_scope
from app.ports.mcp_tool import (
    MCPToolDescriptor,
    MCPToolDispatchError,
    MCPToolErrorPolicy,
    MCPToolInfrastructureError,
    MCPToolInvocation,
)
from app.services.ml_prediction_service import (
    MLPredictionRequest,
    MLPredictionService,
    MLRoomDemandPrediction,
)
from app.services.governed_mcp_execution import (
    GovernedMCPToolExecutor,
    MCPToolRateLimitedError,
    MCPToolUnavailableError,
)
from app.services.rag_gateway import (
    InternalManualAgent,
    RAG_TOOL_ANNOTATIONS,
    RAG_TOOL_CODE,
    RAG_TOOL_DESCRIPTION,
    RAG_TOOL_ID,
    RAG_TOOL_INPUT_SCHEMA,
    RAG_TOOL_OUTPUT_SCHEMA,
    RAG_TOOL_ROLES,
    RAG_TOOL_SEMANTIC_VERSION,
    RAG_TOOL_TIMEOUT_SECONDS,
    RAG_TOOL_TITLE,
    RagToolError,
)


DatabaseUrlFactory = Callable[[], str]
MLPredictionServiceFactory = Callable[[], MLPredictionService]

ML_PREDICT_TOOL_ID = UUID("3002d1d6-f681-5b5d-b0b6-0de795fb4c5c")
ML_PREDICT_NAME = "ml.predict"
ML_PREDICT_SEMANTIC_VERSION = "1.0.0"
ML_PREDICT_TITLE = "Predict Room Demand"
ML_PREDICT_DESCRIPTION = (
    "Predict governed room demand for a typed property and date horizon."
)
ML_PREDICT_TIMEOUT_SECONDS = 30
READ_ONLY_ANNOTATIONS = {
    "readOnlyHint": True,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": False,
}
ML_PREDICT_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "property_id": {
            "type": "string",
            "minLength": 1,
            "maxLength": 64,
            "pattern": "^[A-Za-z0-9_-]+$",
        },
        "as_of": {"type": "string", "format": "date"},
        "horizon_days": {"type": "integer", "minimum": 1, "maximum": 366},
    },
    "required": ["property_id", "as_of", "horizon_days"],
    "additionalProperties": False,
}
_DAILY_FORECAST_SCHEMA = {
    "type": "object",
    "properties": {
        "target_date": {"type": "string", "format": "date"},
        "total_available_rooms": {"type": "number", "exclusiveMinimum": 0},
        "predicted_occupied_rooms": {"type": "number", "minimum": 0},
        "predicted_available_rooms": {"type": "number", "minimum": 0},
        "predicted_occupancy_rate": {
            "type": "number",
            "minimum": 0,
            "maximum": 1,
        },
    },
    "required": [
        "target_date",
        "total_available_rooms",
        "predicted_occupied_rooms",
        "predicted_available_rooms",
        "predicted_occupancy_rate",
    ],
    "additionalProperties": False,
}
_ROOM_TYPE_FORECAST_SCHEMA = {
    "type": "object",
    "properties": {
        "target_date": {"type": "string", "format": "date"},
        "room_type_code": {"type": "string", "minLength": 1, "maxLength": 64},
        "available_rooms": {"type": "number", "exclusiveMinimum": 0},
        "predicted_rooms_raw": {"type": "number"},
        "predicted_rooms": {"type": "number", "minimum": 0},
        "occupancy_rate": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": [
        "target_date",
        "room_type_code",
        "available_rooms",
        "predicted_rooms_raw",
        "predicted_rooms",
        "occupancy_rate",
    ],
    "additionalProperties": False,
}
_ML_PROVENANCE_SCHEMA = {
    "type": "object",
    "properties": {
        "source": {"type": "string", "const": "TRINO_HISTORICAL_DAILY_FACTS"},
        "history_table": {
            "type": "string",
            "minLength": 5,
            "maxLength": 256,
            "pattern": (
                "^[A-Za-z_][A-Za-z0-9_]*\\."
                "[A-Za-z_][A-Za-z0-9_]*\\."
                "[A-Za-z_][A-Za-z0-9_]*$"
            ),
        },
        "trino_query_id": {"type": "string", "minLength": 1, "maxLength": 256},
        "feature_as_of": {"type": "string", "format": "date"},
        "request_as_of": {"type": "string", "format": "date"},
        "rag_called": {"type": "boolean", "const": False},
    },
    "required": [
        "source",
        "history_table",
        "trino_query_id",
        "feature_as_of",
        "request_as_of",
        "rag_called",
    ],
    "additionalProperties": False,
}
ML_PREDICT_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "schema_version": {"type": "string", "const": "MLRoomDemandPrediction.v1"},
        "status": {"type": "string", "const": "SUCCEEDED"},
        "execution_id": {"type": "string", "format": "uuid"},
        "property_id": {
            "type": "string",
            "minLength": 1,
            "maxLength": 64,
            "pattern": "^[A-Za-z0-9_-]+$",
        },
        "as_of": {"type": "string", "format": "date"},
        "feature_as_of": {"type": "string", "format": "date"},
        "horizon_days": {"type": "integer", "minimum": 1, "maximum": 366},
        "model_version": {"type": "string", "minLength": 1, "maxLength": 160},
        "model_hash": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "feature_contract_sha256": {
            "type": "string",
            "pattern": "^[0-9a-f]{64}$",
        },
        "daily_forecasts": {
            "type": "array",
            "minItems": 1,
            "items": _DAILY_FORECAST_SCHEMA,
        },
        "room_type_forecasts": {
            "type": "array",
            "minItems": 1,
            "items": _ROOM_TYPE_FORECAST_SCHEMA,
        },
        "provenance": _ML_PROVENANCE_SCHEMA,
    },
    "required": [
        "schema_version",
        "status",
        "execution_id",
        "property_id",
        "as_of",
        "feature_as_of",
        "horizon_days",
        "model_version",
        "model_hash",
        "feature_contract_sha256",
        "daily_forecasts",
        "room_type_forecasts",
        "provenance",
    ],
    "additionalProperties": False,
}


def _strict_mapping(arguments: Any, allowed: frozenset[str]) -> dict[str, Any]:
    if not isinstance(arguments, Mapping) or set(arguments) - allowed:
        raise MCPToolDispatchError(
            "INVALID_ARGUMENT",
            "Tool arguments do not match the declared input schema.",
            protocol_error=True,
        )
    try:
        normalized = json.loads(
            json.dumps(dict(arguments), sort_keys=True, separators=(",", ":"), allow_nan=False)
        )
    except (TypeError, ValueError) as error:
        raise MCPToolDispatchError(
            "INVALID_ARGUMENT",
            "Tool arguments must be valid JSON.",
            protocol_error=True,
        ) from error
    return normalized


def _rag_input(arguments: Any) -> Mapping[str, Any]:
    return _strict_mapping(
        arguments,
        frozenset({"query", "selected_document_ids", "recent_utterances"}),
    )


def _rag_output(raw: Mapping[str, Any]) -> Mapping[str, Any]:
    status = raw.get("status")
    output: dict[str, Any] = {
        "status": status,
        "trace_id": raw.get("trace_id"),
        "evidence_bundle": [
            {
                key: item.get(key)
                for key in (
                    "evidence_id",
                    "document_id",
                    "document_name",
                    "section",
                    "snippet",
                    "score",
                )
            }
            for item in raw.get("evidence_bundle", [])
            if isinstance(item, Mapping)
        ],
    }
    if status in {"ANSWER", "NO_EVIDENCE"}:
        output["answer"] = {"text": str((raw.get("answer") or {}).get("text") or "")}
        output["citations"] = [
            {
                "evidence_id": item.get("evidence_id"),
                "citation": item.get("citation"),
            }
            for item in raw.get("citations", [])
            if isinstance(item, Mapping)
        ]
    elif status == "CONFLICT":
        output["conflicts"] = [
            {
                "description": item.get("description"),
                "evidence_ids": list(item.get("evidence_ids") or []),
            }
            for item in raw.get("conflicts", [])
            if isinstance(item, Mapping)
        ]
    return output


def _rag_audit(output: Mapping[str, Any]) -> Mapping[str, Any]:
    return {
        "status": output.get("status"),
        "trace_id": output.get("trace_id"),
        "evidence_ids": [
            item.get("evidence_id")
            for item in output.get("evidence_bundle", [])
            if isinstance(item, Mapping)
        ],
    }


def rag_answer_descriptor(database_url_factory: DatabaseUrlFactory) -> MCPToolDescriptor:
    """서명된 RAG Gateway를 단일 ``rag.answer`` MCP Tool로 조립한다."""

    async def _handler(invocation: MCPToolInvocation) -> Mapping[str, Any]:
        arguments = invocation.arguments
        try:
            return await InternalManualAgent(database_url_factory()).execute_mcp_handler(
                query=str(arguments["query"]),
                actor_id=invocation.subject_id,
                app_role=invocation.role.value,
                trace_id=invocation.trace_id,
                recent_utterances=tuple(arguments.get("recent_utterances", ())),
                selected_document_ids=tuple(arguments.get("selected_document_ids", ())),
            )
        except asyncio.CancelledError:
            raise
        except RagToolError as error:
            raise MCPToolDispatchError(error.code, str(error)) from error

    return MCPToolDescriptor(
        tool_id=RAG_TOOL_ID,
        name=RAG_TOOL_CODE,
        semantic_version=RAG_TOOL_SEMANTIC_VERSION,
        title=RAG_TOOL_TITLE,
        description=RAG_TOOL_DESCRIPTION,
        input_schema=RAG_TOOL_INPUT_SCHEMA,
        output_schema=RAG_TOOL_OUTPUT_SCHEMA,
        handler=_handler,
        input_adapter=_rag_input,
        output_adapter=_rag_output,
        audit_adapter=_rag_audit,
        timeout_seconds=RAG_TOOL_TIMEOUT_SECONDS,
        capability=Capability.RUN_ANALYSIS,
        roles=tuple(Role(role) for role in RAG_TOOL_ROLES),
        annotations=RAG_TOOL_ANNOTATIONS,
        error_policy=MCPToolErrorPolicy(
            timeout_code="RAG_TOOL_TIMEOUT",
            timeout_message="내부 문서 검색 시간이 초과되었습니다.",
            output_code="RAG_OUTPUT_INVALID",
            output_message="내부 문서 답변 계약이 올바르지 않습니다.",
            unexpected_code="RAG_TOOL_FAILED",
            unexpected_message="내부 문서 검색을 완료하지 못했습니다.",
        ),
    )


def _ml_input(arguments: Any) -> Mapping[str, Any]:
    normalized = _strict_mapping(
        arguments,
        frozenset({"property_id", "as_of", "horizon_days"}),
    )
    try:
        return MLPredictionRequest.model_validate(normalized).model_dump(mode="json")
    except ValidationError as error:
        raise MCPToolDispatchError(
            "INVALID_ARGUMENT",
            "ML prediction arguments are invalid.",
            protocol_error=True,
        ) from error


def _ml_output(raw: Mapping[str, Any]) -> Mapping[str, Any]:
    return MLRoomDemandPrediction.model_validate(raw).model_dump(mode="json")


def _ml_audit(output: Mapping[str, Any]) -> Mapping[str, Any]:
    return {
        "status": output.get("status"),
        "execution_id": output.get("execution_id"),
        "model_hash": output.get("model_hash"),
        "feature_contract_sha256": output.get("feature_contract_sha256"),
    }


def ml_predict_descriptor(
    database_url_factory: DatabaseUrlFactory,
    service_factory: MLPredictionServiceFactory = MLPredictionService,
) -> MCPToolDescriptor:
    """승인 HGBR runtime과 ML 감사 저장을 ``ml.predict`` MCP Tool로 조립한다."""

    async def _handler(invocation: MCPToolInvocation) -> Mapping[str, Any]:
        service = service_factory()
        try:
            result = await service.generate_prediction(dict(invocation.arguments))
        except asyncio.CancelledError:
            raise
        except ValueError as error:
            raise MCPToolDispatchError(
                "ML_REQUEST_UNSUPPORTED",
                "요청한 ML 예측 범위는 현재 지원되지 않습니다.",
            ) from error
        try:
            async with session_scope(database_url_factory()) as session:
                await service.persist_prediction(session, result)
        except asyncio.CancelledError:
            raise
        except (DatabaseConfigurationError, SQLAlchemyError, RuntimeError) as error:
            raise MCPToolInfrastructureError("MCP_AUDIT_UNAVAILABLE") from error
        return result

    return MCPToolDescriptor(
        tool_id=ML_PREDICT_TOOL_ID,
        name=ML_PREDICT_NAME,
        semantic_version=ML_PREDICT_SEMANTIC_VERSION,
        title=ML_PREDICT_TITLE,
        description=ML_PREDICT_DESCRIPTION,
        input_schema=ML_PREDICT_INPUT_SCHEMA,
        output_schema=ML_PREDICT_OUTPUT_SCHEMA,
        handler=_handler,
        input_adapter=_ml_input,
        output_adapter=_ml_output,
        audit_adapter=_ml_audit,
        timeout_seconds=ML_PREDICT_TIMEOUT_SECONDS,
        capability=Capability.RUN_ANALYSIS,
        roles=(Role.ANALYST,),
        annotations=READ_ONLY_ANNOTATIONS,
        error_policy=MCPToolErrorPolicy(
            timeout_code="ML_TOOL_TIMEOUT",
            timeout_message="ML 예측 시간이 초과되었습니다.",
            output_code="ML_OUTPUT_INVALID",
            output_message="ML 예측 결과 계약이 올바르지 않습니다.",
            unexpected_code="ML_TOOL_FAILED",
            unexpected_message="ML 예측을 완료하지 못했습니다.",
        ),
    )


class MCPInternalManualExecutor:
    """InternalManualQueryService를 실제 ``rag.answer`` MCP 호출에 연결한다."""

    def __init__(
        self,
        database_url: str,
        *,
        governed_executor: GovernedMCPToolExecutor | None = None,
    ) -> None:
        normalized = database_url.strip()
        if not normalized:
            raise ValueError("APP runtime database URL is required")
        self._database_url = normalized
        self._database_url_factory = lambda: self._database_url
        self._executor = (
            governed_executor
            or GovernedMCPToolExecutor(
                (rag_answer_descriptor(self._database_url_factory),),
                self._database_url_factory,
            )
        )

    async def execute(
        self,
        query: str,
        actor_id: UUID,
        app_role: str,
        trace_id: str,
        recent_utterances: tuple[str, ...] = (),
        resolved_question: str | None = None,
        domains: tuple[str, ...] = (),
        intent: str = "REGULATION_CHECK",
        selected_document_ids: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        """기존 RAG use case 입력을 닫힌 MCP 인자로 바꾸고 broker receipt를 보존한다."""

        if resolved_question is not None or domains or intent != "REGULATION_CHECK":
            raise RagToolError(
                "RAG_MCP_ARGUMENT_UNSUPPORTED",
                "현재 MCP RAG 계약에서 지원하지 않는 검색 옵션입니다.",
                422,
            )
        try:
            role = Role(app_role)
        except ValueError as error:
            raise RagToolError("RAG_ACCESS_DENIED", "RAG 검색 권한이 없습니다.", 403) from error
        arguments = {
            "query": query,
            "recent_utterances": list(recent_utterances),
            "selected_document_ids": list(selected_document_ids),
        }
        try:
            receipt = await self._executor.execute(
                RAG_TOOL_CODE,
                subject_id=actor_id,
                role=role,
                trace_id=trace_id,
                arguments=arguments,
            )
        except asyncio.CancelledError:
            raise
        except MCPToolRateLimitedError as error:
            raise RagToolError(
                "RAG_RATE_LIMITED",
                "RAG Tool 호출 한도를 초과했습니다.",
                429,
            ) from error
        except MCPToolUnavailableError as error:
            raise RagToolError(
                "RAG_REGISTRY_UNAVAILABLE",
                "RAG Tool Registry를 사용할 수 없습니다.",
            ) from error
        except MCPToolInfrastructureError as error:
            raise RagToolError(error.code, "RAG Tool 실행 기반을 사용할 수 없습니다.") from error
        except MCPToolDispatchError as error:
            status_code = 422 if error.protocol_error else 503
            raise RagToolError(error.code, str(error), status_code) from error

        result = dict(receipt.structured_content)
        evidence_document_ids = [
            item.get("document_id")
            for item in result.get("evidence_bundle", [])
            if isinstance(item, Mapping) and isinstance(item.get("document_id"), str)
        ]
        approved_document_ids = list(
            dict.fromkeys([*selected_document_ids, *evidence_document_ids])
        )[:2]
        context_question = "\n".join(
            [
                *(f"이전 질문: {item}" for item in recent_utterances[-3:]),
                f"현재 질문: {query.strip()}",
            ]
        )[-500:].strip()
        result["routing"] = {
            "domains": [],
            "intent": "REGULATION_CHECK",
            "resolved_with_context": bool(recent_utterances),
            "context_question": context_question,
            "snapshot_question": query.strip(),
            "selected_document_ids": approved_document_ids,
        }
        result["mcp_tool_run_id"] = str(receipt.tool_run_id)
        return result

    async def runtime_receipt(self, app_role: str) -> dict[str, Any]:
        """MCP registry 권한과 서명 RAG runtime release를 함께 확인한다."""

        try:
            role = Role(app_role)
            await self._executor.resolve_descriptor(RAG_TOOL_CODE, role)
        except (ValueError, MCPToolUnavailableError) as error:
            raise RagToolError(
                "RAG_REGISTRY_UNAVAILABLE",
                "RAG Tool Registry를 사용할 수 없습니다.",
            ) from error
        return await InternalManualAgent(self._database_url).runtime_receipt(app_role)


class MCPMLPredictionExecutor:
    """승인 HGBR runtime을 ``ml.predict`` MCP Tool로만 실행한다."""

    def __init__(
        self,
        database_url: str,
        service: MLPredictionService | None = None,
        *,
        governed_executor: GovernedMCPToolExecutor | None = None,
    ) -> None:
        normalized = database_url.strip()
        if not normalized:
            raise ValueError("APP runtime database URL is required")
        self._database_url = normalized
        self._service = service or MLPredictionService()
        database_url_factory = lambda: self._database_url
        self._executor = (
            governed_executor
            or GovernedMCPToolExecutor(
                (
                    ml_predict_descriptor(
                        database_url_factory,
                        service_factory=lambda: self._service,
                    ),
                ),
                database_url_factory,
            )
        )

    async def readiness(self, role: Role) -> Any:
        """MCP registry와 HGBR runtime receipt가 모두 유효한지 확인한다."""

        await self._executor.resolve_descriptor(ML_PREDICT_NAME, role)
        return await self._service.readiness()

    async def execute(
        self,
        payload: Mapping[str, Any],
        *,
        subject_id: UUID,
        role: Role,
        trace_id: str,
    ) -> dict[str, Any]:
        """구조화 ML 인자를 governed MCP 경계에서 실행한다."""

        receipt = await self._executor.execute(
            ML_PREDICT_NAME,
            subject_id=subject_id,
            role=role,
            trace_id=trace_id,
            arguments=dict(payload),
        )
        result = dict(receipt.structured_content)
        result["mcp_tool_run_id"] = str(receipt.tool_run_id)
        return result
