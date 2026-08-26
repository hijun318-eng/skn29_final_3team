from __future__ import annotations

from datetime import date
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_database_session
from app.context import session_context
from app.contracts import RequestContext
from app.services.ml_prediction_service import MLPredictionService


router = APIRouter(tags=["ml"])
service = MLPredictionService()


class RoomDemandRequest(BaseModel):
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


@router.get("/ml/capabilities")
async def ml_capabilities(
    _context: Annotated[
        RequestContext,
        Depends(session_context),
    ],
) -> dict[str, Any]:
    try:
        return await service.capabilities()
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=503,
            detail="ML runtime is unavailable",
        ) from exc


@router.post("/analysis/ml")
async def create_ml_analysis(
    request: RoomDemandRequest,
    _context: Annotated[
        RequestContext,
        Depends(session_context),
    ],
    session: AsyncSession = Depends(get_database_session),
) -> dict[str, Any]:
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
