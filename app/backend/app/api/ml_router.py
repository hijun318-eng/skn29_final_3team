"""인증된 사용자에게 ML capability 조회와 객실 수요 예측 API를 제공한다."""

from __future__ import annotations

from datetime import date
import os
from typing import Annotated, Any
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_database_session
from app.context import session_context
from app.authorization import has_capability
from app.contracts import Capability, ContractModel, RequestContext
from app.services.ml_chat_request import MLChatRequestResolver
from app.services.ml_prediction_service import (
    MLDeploymentPolicyError,
    MLRoomDemandPrediction,
    MLRuntimeCapability,
    MLPredictionService,
)
from app.services.ml_actual_comparison import (
    MLActualComparison,
    MLActualComparisonService,
)


router = APIRouter(tags=["ml"])
service = MLPredictionService()
comparison_service = MLActualComparisonService()
ML_MAX_HORIZON_DAYS = 7


class RoomDemandRequest(ContractModel):
    """지원 대상·기준일·일 단위 horizon을 runtime capability 검증에 전달한다."""

    property_id: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9_-]+$",
    )
    as_of: date
    horizon_days: int = Field(
        default=7,
        ge=1,
        le=ML_MAX_HORIZON_DAYS,
    )


class MLChatQuestionRequest(ContractModel):
    """대화 화면에서 전달하는 자연어 객실 수요 질문이다."""

    question: str = Field(min_length=1, max_length=1000)


class MLRuntimeErrorDetail(ContractModel):
    """ML 기능·배포 정책·runtime 실패의 공개 가능한 코드와 안내 사유다."""

    code: str = Field(min_length=1, max_length=96, pattern=r"^[A-Z][A-Z0-9_]*$")
    reason: str = Field(min_length=1, max_length=500)


class MLRuntimeErrorResponse(ContractModel):
    """FastAPI HTTPException이 반환하는 ML 오류 envelope다."""

    detail: MLRuntimeErrorDetail


ML_RUNTIME_ERROR_RESPONSES = {
    502: {"model": MLRuntimeErrorResponse, "description": "ML runtime 응답 계약 오류"},
    503: {"model": MLRuntimeErrorResponse, "description": "ML 기능 또는 승인 runtime 사용 불가"},
}


def _require_ml_access(context: RequestContext) -> None:
    if not has_capability(context.role, Capability.RUN_ANALYSIS):
        raise HTTPException(status_code=403, detail="ML 예측 권한이 없습니다.")
    enabled = os.getenv("ML_FEATURE_ENABLED", "0").strip().lower() in {
        "1", "true", "yes"
    }
    if not enabled:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "ML_FEATURE_DISABLED",
                "reason": "ML 예측 기능이 비활성화되었습니다.",
            },
        )


@router.get(
    "/ml/capabilities",
    operation_id="getMlCapabilities",
    response_model=MLRuntimeCapability,
    responses=ML_RUNTIME_ERROR_RESPONSES,
)
async def ml_capabilities(
    context: Annotated[
        RequestContext,
        Depends(session_context),
    ],
) -> dict[str, Any]:
    """현재 역할과 feature flag를 확인한 뒤 runtime capability를 반환한다."""
    _require_ml_access(context)
    try:
        return await service.capabilities()
    except MLDeploymentPolicyError as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": exc.code, "reason": exc.reason},
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "ML_RUNTIME_UNAVAILABLE",
                "reason": "ML runtime is unavailable",
            },
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "code": "ML_RUNTIME_CAPABILITY_INVALID",
                "reason": "ML runtime capability contract is invalid",
            },
        ) from exc


@router.post("/analysis/ml/chat", operation_id="createMlChatAnalysis")
async def create_ml_chat_analysis(
    request: MLChatQuestionRequest,
    context: Annotated[RequestContext, Depends(session_context)],
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    """자연어 질문을 capability 범위 안의 구조화된 예측 요청으로 변환한다."""

    capabilities = await ml_capabilities(context)
    resolution = MLChatRequestResolver().resolve(
        request.question,
        capabilities,
        conversation_id=None,
    )
    if not resolution.ready:
        ml_response = resolution.clarification_response()
    else:
        payload = resolution.payload or {}
        ml_response = await create_ml_analysis(
            RoomDemandRequest(
                property_id=payload["property_id"],
                as_of=payload["as_of"],
                horizon_days=payload["horizon"],
            ),
            context,
            session,
        )
    return {"handled": True, "type": "FORECAST", "ml_response": ml_response}


@router.post(
    "/analysis/ml",
    operation_id="createMlAnalysis",
    response_model=MLRoomDemandPrediction,
    responses=ML_RUNTIME_ERROR_RESPONSES,
)
async def create_ml_analysis(
    request: RoomDemandRequest,
    context: Annotated[
        RequestContext,
        Depends(session_context),
    ],
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
    """허용된 사용자 요청만 예측하고 provenance 감사 이벤트를 저장한다."""
    _require_ml_access(context)
    try:
        return await service.predict(
            session,
            request.model_dump(mode="json", exclude_none=True),
        )
    except MLDeploymentPolicyError as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": exc.code, "reason": exc.reason},
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc
    except httpx.HTTPStatusError as exc:
        status = 404 if exc.response.status_code == 404 else 502
        raise HTTPException(
            status_code=status,
            detail=(
                "ML prediction request failed"
                if status == 404
                else {
                    "code": "ML_PREDICTION_REQUEST_FAILED",
                    "reason": "ML prediction request failed",
                }
            ),
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "ML_RUNTIME_UNAVAILABLE",
                "reason": "ML runtime is unavailable",
            },
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "code": "ML_PREDICTION_CONTRACT_INVALID",
                "reason": "ML prediction contract is invalid",
            },
        ) from exc


@router.get(
    "/analysis/ml/{execution_id}/comparison",
    operation_id="getMlActualComparison",
    response_model=MLActualComparison,
    responses=ML_RUNTIME_ERROR_RESPONSES,
)
async def get_ml_actual_comparison(
    execution_id: UUID,
    context: Annotated[RequestContext, Depends(session_context)],
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, object]:
    """저장된 예측을 이후 도착한 객실 실적과 자동 비교한다."""

    _require_ml_access(context)
    try:
        return await comparison_service.compare(session, execution_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "ML_ACTUALS_UNAVAILABLE",
                "reason": "ML 실제값을 조회하지 못했습니다.",
            },
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "code": "ML_ACTUAL_COMPARISON_INVALID",
                "reason": "ML 실제값 비교 계약이 올바르지 않습니다.",
            },
        ) from exc
