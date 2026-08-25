from __future__ import annotations

from typing import Annotated, Any
from uuid import uuid4

from fastapi import APIRouter, Depends, Request

from app.container import Container
from app.dependencies import container, current_admin
from app.schemas import ConnectionList


router = APIRouter(prefix="/admin-api/connections", tags=["admin-connections"])


@router.get("", response_model=ConnectionList)
async def connections(
    request: Request,
    services: Annotated[Container, Depends(container)],
    admin: Annotated[dict[str, Any], Depends(current_admin)],
) -> ConnectionList:
    return await services.connections.check(
        admin, request.headers.get("X-Request-ID") or uuid4().hex
    )
