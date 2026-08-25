"""MCP Registry·ACL·typed 입력 검증을 실제 Analysis·RAG·ML 실행에 연결한다."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.adapters.analysis_repository import (
    AnalysisRepositoryUnavailable,
    PostgresAnalysisRepository,
)
from app.api.ml_router import ml_prediction_client
from app.authorization import has_capability
from app.contracts import Capability, RequestContext
from app.database import session_scope
from app.services.mcp_access_policy import is_mcp_tool_allowed
from app.services.mcp_audit_repository import McpAuditRepository, McpAuditUnavailable
from app.services.ml_prediction_service import MLAnalysisError, MLPredictionService
from app.services.rag_gateway import InternalManualAgent, RagToolError


class AnalysisGetRunInput(BaseModel):
    """소유권 검사를 거쳐 조회할 Analysis Run 식별자를 제한한다."""

    model_config = ConfigDict(extra="forbid")
    request_id: UUID


class RagAnswerInput(BaseModel):
    """내부 문서 근거 검색에 허용되는 질문 길이와 추가 필드 금지를 선언한다."""

    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=2, max_length=500, strict=True)


class MLPredictInput(BaseModel):
    """승인 예측 모델이 받는 호텔·지표·기간 범위를 엄격하게 제한한다."""

    model_config = ConfigDict(extra="forbid")
    hotel_scope: str = Field(
        pattern=r"^[A-Z0-9_]+$", min_length=1, max_length=32, strict=True
    )
    metric: Literal["OCCUPANCY_RATE"]
    horizon: int = Field(ge=1, le=7, strict=True)


@dataclass(frozen=True)
class McpToolSpec:
    """서버가 구현한 Tool 식별자와 capability, 입력 모델을 결합한다."""

    tool_id: UUID
    name: str
    title: str
    capability: Capability
    input_model: type[BaseModel]


class McpToolError(RuntimeError):
    """MCP 공개 오류 코드와 선택적 JSON-RPC 코드를 함께 전달한다."""

    def __init__(self, code: str, message: str, rpc_code: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.rpc_code = rpc_code


class McpToolService:
    """DB Registry와 서버 ACL이 모두 승인한 Tool만 조회·실행한다."""

    _SPECS = (
        McpToolSpec(
            UUID("c4454392-2f92-54a4-ad13-b8cdaba45732"),
            "analysis.get_run",
            "Get Analysis Run",
            Capability.READ_ANALYSIS,
            AnalysisGetRunInput,
        ),
        McpToolSpec(
            UUID("8edce655-e454-5b76-b56f-5e49aa2884d4"),
            "rag.answer",
            "Answer From Internal Manuals",
            Capability.RUN_ANALYSIS,
            RagAnswerInput,
        ),
        McpToolSpec(
            UUID("e3b9a137-8a4c-5a32-b6dc-41e7c324df72"),
            "ml.predict",
            "Run Approved ML Prediction",
            Capability.RUN_ANALYSIS,
            MLPredictInput,
        ),
    )

    def __init__(self, database_url: str) -> None:
        self._database_url = database_url
        self._by_name = {spec.name: spec for spec in self._SPECS}
        self._audit = McpAuditRepository(database_url)

    async def list_tools(self, context: RequestContext) -> list[dict[str, Any]]:
        """현재 주체가 호출 가능한 활성 Tool만 MCP schema와 함께 반환한다."""

        tools: list[dict[str, Any]] = []
        for spec in self._SPECS:
            row = await self._registry_row(spec)
            if row is None or not self._authorized(spec, row, context):
                continue
            tools.append(
                {
                    "name": spec.name,
                    "title": spec.title,
                    "description": row["description"],
                    "inputSchema": row["input_schema_json"],
                    "outputSchema": row["output_schema_json"],
                    "annotations": {
                        "readOnlyHint": True,
                        "destructiveHint": False,
                        "idempotentHint": True,
                        "openWorldHint": False,
                    },
                }
            )
        return tools

    async def call(
        self, name: Any, arguments: Any, context: RequestContext
    ) -> dict[str, Any]:
        """Tool 이름·입력·권한을 검증하고 거부와 실패까지 감사한 뒤 결과를 반환한다."""

        spec = self._by_name.get(name) if isinstance(name, str) else None
        if spec is None:
            raise McpToolError("TOOL_UNKNOWN", "Unknown or disabled tool", -32602)
        row = await self._registry_row(spec)
        if row is None:
            raise McpToolError("TOOL_DISABLED", "Unknown or disabled tool", -32602)
        validated = self._validate(spec, arguments)
        started = time.perf_counter()
        safe_arguments = validated.model_dump(mode="json")
        if not self._authorized(spec, row, context):
            await self._record(
                spec, context, safe_arguments, "DENIED", started, {}, "ACCESS_DENIED"
            )
            raise McpToolError("ACCESS_DENIED", "Tool access denied", -32001)
        if spec.name == "analysis.get_run":
            return await self._analysis_get_run(
                spec, validated, context, safe_arguments, started
            )
        if spec.name == "rag.answer":
            return await self._rag_answer(validated, context)
        return await self._ml_predict(
            spec, validated, context, safe_arguments, started
        )

    @staticmethod
    def _validate(spec: McpToolSpec, arguments: Any) -> BaseModel:
        if not isinstance(arguments, dict):
            raise McpToolError(
                "INVALID_ARGUMENTS", "Tool arguments must be an object", -32602
            )
        try:
            return spec.input_model.model_validate(arguments)
        except ValidationError as error:
            fields = ", ".join(
                sorted(
                    {
                        str(item["loc"][-1])
                        for item in error.errors()
                        if item.get("loc")
                    }
                )
            )
            raise McpToolError(
                "INVALID_ARGUMENTS",
                f"Invalid tool arguments: {fields or 'request'}",
                -32602,
            ) from error

    async def _analysis_get_run(
        self,
        spec: McpToolSpec,
        arguments: AnalysisGetRunInput,
        context: RequestContext,
        safe_arguments: dict[str, Any],
        started: float,
    ) -> dict[str, Any]:
        try:
            result = await PostgresAnalysisRepository(
                self._database_url, context.user_id
            ).get_run(str(arguments.request_id))
        except (ValueError, KeyError) as error:
            await self._record(
                spec, context, safe_arguments, "FAILED", started, {}, "RUN_NOT_FOUND"
            )
            raise McpToolError("RUN_NOT_FOUND", str(error)) from error
        except AnalysisRepositoryUnavailable as error:
            await self._record(
                spec,
                context,
                safe_arguments,
                "FAILED",
                started,
                {},
                "REPOSITORY_UNAVAILABLE",
            )
            raise McpToolError(
                "REPOSITORY_UNAVAILABLE", "Analysis repository is unavailable."
            ) from error
        output = json.loads(json.dumps(result, default=str))
        await self._record(
            spec,
            context,
            safe_arguments,
            "SUCCEEDED",
            started,
            {
                key: output.get(key)
                for key in ("request_id", "query_id", "artifact_id")
            },
        )
        return output

    async def _rag_answer(
        self, arguments: RagAnswerInput, context: RequestContext
    ) -> dict[str, Any]:
        try:
            return await InternalManualAgent(self._database_url).execute(
                arguments.query,
                context.user_id,
                context.role.value,
                context.trace_id,
            )
        except RagToolError as error:
            raise McpToolError(error.code, str(error)) from error

    async def _ml_predict(
        self,
        spec: McpToolSpec,
        arguments: MLPredictInput,
        context: RequestContext,
        safe_arguments: dict[str, Any],
        started: float,
    ) -> dict[str, Any]:
        try:
            async with session_scope(self._database_url) as session:
                output = await MLPredictionService(
                    ml_prediction_client()
                ).predict_approved_task(arguments.model_dump(), context, session)
        except MLAnalysisError as error:
            status = "DENIED" if error.code == "ML_ACCESS_DENIED" else "FAILED"
            await self._record(
                spec, context, safe_arguments, status, started, {}, error.code
            )
            raise McpToolError(error.code, error.message) from error
        except (ValueError, RuntimeError) as error:
            await self._record(
                spec,
                context,
                safe_arguments,
                "FAILED",
                started,
                {},
                "ML_RUNTIME_UNAVAILABLE",
            )
            raise McpToolError(
                "ML_RUNTIME_UNAVAILABLE", "ML runtime is unavailable."
            ) from error
        await self._record(
            spec,
            context,
            safe_arguments,
            "SUCCEEDED",
            started,
            {
                "request_id": output.get("request_id"),
                "execution_id": output.get("evidence", {}).get("execution_id"),
                "artifact_hash": output.get("evidence", {}).get("artifact_hash"),
                "trino_query_ids": output.get("evidence", {}).get(
                    "trino_query_ids"
                ),
            },
        )
        return output

    async def _registry_row(self, spec: McpToolSpec) -> dict[str, Any] | None:
        try:
            async with session_scope(self._database_url) as session:
                result = await session.execute(
                    text(
                        """
                        SELECT description, input_schema_json, output_schema_json,
                               required_roles_json
                        FROM tooling.tool_registry
                        WHERE tool_id = :tool_id
                          AND tool_code = :tool_code
                          AND is_enabled
                        """
                    ),
                    {"tool_id": spec.tool_id, "tool_code": spec.name},
                )
                row = result.mappings().first()
                return dict(row) if row else None
        except SQLAlchemyError as error:
            raise McpToolError(
                "REGISTRY_UNAVAILABLE",
                "MCP Tool Registry is unavailable.",
                -32000,
            ) from error

    @staticmethod
    def _authorized(
        spec: McpToolSpec, row: dict[str, Any], context: RequestContext
    ) -> bool:
        roles = row.get("required_roles_json")
        return is_mcp_tool_allowed(
            tool_name=spec.name,
            role=context.role,
            required_roles=roles if isinstance(roles, list) else (),
            capability_allowed=has_capability(context.role, spec.capability),
        )

    async def _record(
        self,
        spec: McpToolSpec,
        context: RequestContext,
        arguments: dict[str, Any],
        status: str,
        started: float,
        output_ref: dict[str, Any],
        error_code: str | None = None,
    ) -> None:
        try:
            await self._audit.record(
                spec.tool_id,
                context,
                arguments,
                status,
                started,
                output_ref,
                error_code,
            )
        except McpAuditUnavailable as error:
            raise McpToolError("AUDIT_FAILED", str(error)) from error
