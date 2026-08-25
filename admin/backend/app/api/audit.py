from __future__ import annotations

from math import ceil
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query

from app.container import Container
from app.dependencies import container, current_admin
from app.schemas import AuditPage


router = APIRouter(prefix="/admin-api/audit-events", tags=["admin-audit"])


@router.get("", response_model=AuditPage)
async def audit_events(
    services: Annotated[Container, Depends(container)],
    _: Annotated[dict[str, Any], Depends(current_admin)],
    page: Annotated[int, Query(ge=1)] = 1,
    search: Annotated[str, Query(max_length=100)] = "",
    result: Literal["", "SUCCESS", "BLOCKED", "FAILED"] = "",
) -> AuditPage:
    async with services.db.connection() as connection:
        total, items = await services.audit.page(connection, page, search.strip(), result)
    return AuditPage(
        page=page,
        page_size=20,
        total=total,
        total_pages=max(1, ceil(total / 20)),
        items=items,
    )
