"""인증된 사용자에게 ML capability 조회와 객실 수요 예측 API를 제공한다."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_database_session
from app.context import session_context
from app.authorization import has_capability
from app.contracts import Capability, ContractModel, RequestContext, RuntimeFeature
from app.runtime_features import runtime_feature_enabled
from app.ports.agent import ML_ABSOLUTE_MAX_HORIZON_DAYS
from app.services.ml_prediction_service import MLPredictionService


router = APIRouter(tags=["ml"])
service = MLPredictionService()


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
        le=ML_ABSOLUTE_MAX_HORIZON_DAYS,
    )


def _require_ml_access(context: RequestContext) -> None:
    if not has_capability(context.role, Capability.RUN_ANALYSIS):
        raise HTTPException(status_code=403, detail="ML 예측 권한이 없습니다.")
    if not runtime_feature_enabled(RuntimeFeature.ML_PREDICTION):
        raise HTTPException(status_code=503, detail="ML 예측 기능이 비활성화되었습니다.")


@router.get("/ml/capabilities", operation_id="getMlCapabilities")
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
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=503,
            detail="ML runtime is unavailable",
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=502,
            detail="ML runtime capability contract is invalid",
        ) from exc


@router.post("/analysis/ml", operation_id="createMlAnalysis")
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
    except RuntimeError as exc:
        raise HTTPException(
            status_code=502,
            detail="ML prediction contract is invalid",
        ) from exc
