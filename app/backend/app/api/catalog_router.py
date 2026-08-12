from __future__ import annotations

import os
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app.catalog_contracts import CatalogSourceListResponse
from app.context import analysis_context
from app.contracts import RequestContext


catalog_router = APIRouter(prefix="/catalog", tags=["catalog"])


def _catalog_adapter():
    if os.getenv("DATA_PLATFORM_MODE", "real") != "real":
        raise HTTPException(status_code=503, detail="실시간 DataHub 카탈로그가 필요합니다.")
    from app.adapters.i2_data_platform import I2DataPlatformAdapter

    return I2DataPlatformAdapter(
        os.getenv("TRINO_URL", "http://trino:8080"),
        os.getenv("TRINO_USER", "answervice"),
        os.getenv("DATAHUB_GMS_URL", "http://datahub-gms:8080"),
        os.getenv("DATAHUB_API_TOKEN"),
        require_live_metadata=True,
    )


@catalog_router.get(
    "/sources",
    operation_id="catalogListSources",
    response_model=CatalogSourceListResponse,
    responses={503: {"description": "DataHub 또는 Trino 카탈로그 미가용"}},
)
def list_catalog_sources(
    _context: Annotated[RequestContext, Depends(analysis_context)],
) -> dict:
    try:
        items = _catalog_adapter().catalog_sources()
    except HTTPException:
        raise
    except (OSError, ValueError) as error:
        raise HTTPException(
            status_code=503,
            detail="DataHub 또는 Trino 카탈로그 상태를 확인할 수 없습니다.",
        ) from error
    if len(items) != 5:
        raise HTTPException(status_code=503, detail="5개 원천 카탈로그가 완전하지 않습니다.")
    return {"items": items}
