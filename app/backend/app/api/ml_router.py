from __future__ import annotations

from datetime import date
import os
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_database_session
from app.context import session_context
from app.authorization import has_capability
from app.contracts import Capability, ContractModel, RequestContext
from app.services.ml_chat_request import MLChatRequestResolver
from app.services.ml_prediction_service import MLPredictionService


router = APIRouter(tags=["ml"])
service = MLPredictionService()


class RoomDemandRequest(ContractModel):
    property_id: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9_-]+$",
    )
    as_of: date
    horizon: int = Field(default=7, ge=1, le=7)
    conversation_id: str | None = Field(
        default=None,
        max_length=128,
    )


class MLChatQuestionRequest(ContractModel):
    question: str = Field(min_length=1, max_length=1000)


def _require_ml_access(context: RequestContext) -> None:
    if not has_capability(context.role, Capability.RUN_ANALYSIS):
        raise HTTPException(status_code=403, detail="ML 예측 권한이 없습니다.")
    enabled = os.getenv("ML_FEATURE_ENABLED", "0").strip().lower() in {
        "1", "true", "yes"
    }
    if not enabled:
        raise HTTPException(status_code=503, detail="ML 예측 기능이 비활성화되었습니다.")


@router.get("/ml/capabilities")
async def ml_capabilities(
    context: Annotated[
        RequestContext,
        Depends(session_context),
    ],
) -> dict[str, Any]:
    _require_ml_access(context)
    try:
        return await service.capabilities()
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=503,
            detail="ML runtime is unavailable",
        ) from exc


@router.post("/analysis/ml/chat", operation_id="createMlChatAnalysis")
async def create_ml_chat_analysis(
    request: MLChatQuestionRequest,
    context: Annotated[RequestContext, Depends(session_context)],
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    """명시적으로 선택된 ML 대화 요청을 capability 기반 입력으로 변환한다."""
    capabilities = await ml_capabilities(context)
    resolution = MLChatRequestResolver().resolve(
        request.question,
        capabilities,
        conversation_id=None,
    )
    ml_response = (
        await create_ml_analysis(RoomDemandRequest(**resolution.payload), context, session)
        if resolution.ready
        else resolution.clarification_response()
    )
    return {"handled": True, "type": "FORECAST", "ml_response": ml_response}


@router.post("/analysis/ml")
async def create_ml_analysis(
    request: RoomDemandRequest,
    context: Annotated[
        RequestContext,
        Depends(session_context),
    ],
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    _require_ml_access(context)
    try:
        return await service.predict(
            session,
            request.model_dump(mode="json", exclude_none=True),
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc
    except httpx.HTTPStatusError as exc:
        status = 404 if exc.response.status_code == 404 else 502
        raise HTTPException(
            status_code=status,
            detail="ML prediction request failed",
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=503,
            detail="ML runtime is unavailable",
        ) from exc
