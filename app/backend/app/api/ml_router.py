"""인증된 분석가의 ML 예측 요청을 내부 runtime에 전달하고 PostgreSQL 감사 증거를 남긴다."""

from __future__ import annotations

import json
import os
from datetime import date
from functools import lru_cache
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text

from app.adapters.ml_prediction_client import MLPredictionClient, MLPredictionRejected, MLPredictionUnavailable
from app.authorization import has_capability
from app.context import DatabaseSession, session_context
from app.contracts import Capability, RequestContext
from app.services.mcp_access_policy import is_ml_allowed
from app.services.ml_prediction_service import MLAnalysisError, MLPredictionService


class MLPredictionRequest(BaseModel):
    """승인된 객실 점유율 모델이 허용하는 요청 scope를 검증한다."""

    model_config = ConfigDict(extra="forbid")
    metric: Literal["OCCUPANCY_RATE"]
    hotel_scope: str = Field(pattern=r"^[A-Z0-9_]+$", min_length=1, max_length=32)
    horizon: int = Field(ge=1, le=7)
    as_of: date


@lru_cache
def ml_prediction_client() -> MLPredictionClient:
    """환경에 선언된 내부 runtime용 shared async client를 생성한다."""

    endpoint = os.getenv("ML_RUNTIME_URL", "")
    if not endpoint:
        raise MLPredictionUnavailable("ML_RUNTIME_URL is not configured")
    return MLPredictionClient(
        endpoint,
        float(os.getenv("ML_RUNTIME_TIMEOUT_SECONDS", "90")),
    )


router = APIRouter(prefix="/ml", tags=["ml"])
analysis_router = APIRouter(tags=["ml"])


class MLAnalysisRequest(BaseModel):
    """대화형 ML 통합 실행 입력이다."""

    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1, max_length=1000)
    conversation_id: UUID | None = None
    expected_head_turn_id: UUID | None = None


@analysis_router.post("/analysis/ml", operation_id="createMLAnalysis", response_model=None)
async def create_ml_analysis(
    payload: MLAnalysisRequest,
    context: Annotated[RequestContext, Depends(session_context)],
    session: DatabaseSession,
) -> dict[str, object] | JSONResponse:
    """자연어 요청을 권한 검증된 실제 ML 예측과 Backend 집계 응답으로 변환한다."""

    try:
        return await MLPredictionService(ml_prediction_client()).predict_from_query(
            payload.query,
            context,
            session,
            payload.conversation_id,
            payload.expected_head_turn_id,
        )
    except MLAnalysisError as error:
        return JSONResponse(
            status_code=error.status_code,
            content={
                "status": "FAILED",
                "error": {
                    "code": error.code,
                    "message": error.message,
                    "retryable": error.retryable,
                    "required_action": error.required_action,
                    "trace_id": context.trace_id,
                },
            },
        )


@router.get("/capability", operation_id="getMLPredictionCapability")
async def get_ml_prediction_capability(
    context: Annotated[RequestContext, Depends(session_context)],
) -> dict[str, object]:
    """현재 READY인 승인 모델의 서버 검증 scope를 채팅 화면에 제공한다."""

    if not is_ml_allowed(
        role=context.role,
        capability_allowed=has_capability(context.role, Capability.RUN_ANALYSIS),
    ):
        raise HTTPException(status_code=403, detail="분석 실행 권한이 필요합니다.")
    try:
        capability = await ml_prediction_client().capability(context.trace_id)
    except (MLPredictionUnavailable, ValueError) as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    return {"status": "SUCCESS", "data": capability}


@router.post("/predictions", operation_id="createMLPrediction")
async def create_ml_prediction(
    payload: MLPredictionRequest,
    context: Annotated[RequestContext, Depends(session_context)],
    session: DatabaseSession,
) -> dict[str, object]:
    """실제 ML runtime 예측을 실행하고 모델 provenance를 audit event로 영속화한다."""

    if not is_ml_allowed(
        role=context.role,
        capability_allowed=has_capability(context.role, Capability.RUN_ANALYSIS),
    ):
        raise HTTPException(status_code=403, detail="분석 실행 권한이 필요합니다.")
    request = {
        "metric": payload.metric,
        "hotel_scope": payload.hotel_scope,
        "horizon": payload.horizon,
        "as_of": payload.as_of.isoformat(),
    }
    try:
        result = await ml_prediction_client().predict(
            request, context.trace_id, str(context.request_id)
        )
    except MLPredictionRejected as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except (MLPredictionUnavailable, ValueError) as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    execution_id = uuid4()
    details = {
        "execution_id": str(execution_id),
        "metric": result.get("metric"),
        "model_name": result.get("model_name"),
        "model_version": result.get("model_version"),
        "feature_source": result.get("feature_source"),
        "feature_as_of": result.get("feature_as_of"),
        "prediction_count": len(result.get("predictions") or ()),
    }
    async with session.begin():
        await session.execute(
            text(
                """
                INSERT INTO governance.audit_events
                    (audit_event_id, request_id, actor_user_id, actor_role,
                     action_code, object_type, object_id, details_json_redacted,
                     trace_id, created_at)
                VALUES (:audit_event_id, :request_id, :actor_user_id, :actor_role,
                        'ML_PREDICTION_SUCCEEDED', 'ML_MODEL', :object_id,
                        CAST(:details AS jsonb), :trace_id, now())
                """
            ),
            {
                "audit_event_id": uuid4(),
                "request_id": None,
                "actor_user_id": context.user_id,
                "actor_role": context.role.value,
                "object_id": str(result.get("model_version") or "unknown"),
                "details": json.dumps(details, ensure_ascii=False, sort_keys=True),
                "trace_id": context.trace_id,
            },
        )
    return {"status": "SUCCESS", "data": {**result, "execution_id": str(execution_id)}}
