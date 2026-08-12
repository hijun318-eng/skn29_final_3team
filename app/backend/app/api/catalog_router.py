from __future__ import annotations

import os
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app.catalog_contracts import CatalogSourceListResponse
from app.context import analysis_context
from app.contracts import RequestContext


catalog_router = APIRouter(prefix="/catalog", tags=["catalog"])


def _catalog_adapter(context: RequestContext):
    if os.getenv("DATA_PLATFORM_MODE", "real") != "real":
        raise HTTPException(status_code=503, detail="실시간 DataHub 카탈로그가 필요합니다.")
    from app.adapters.i2_data_platform import I2DataPlatformAdapter
    from app.access_policy import resolve_access_profile

    try:
        profile = resolve_access_profile(context.user_id, context.role, context.access_profile)
        credential = profile.credential()
    except PermissionError as error:
        raise HTTPException(status_code=403, detail="요청한 접근 Profile을 사용할 수 없습니다.") from error
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail="DataHub Profile 자격증명을 사용할 수 없습니다.") from error

    adapter = I2DataPlatformAdapter(
        os.getenv("TRINO_URL", "http://trino:8080"),
        profile.trino_principal,
        os.getenv("DATAHUB_GMS_URL", "http://datahub-gms:8080"),
        credential,
        require_live_metadata=True,
    )
    return adapter, frozenset(profile.database_grants)


@catalog_router.get(
    "/sources",
    operation_id="catalogListSources",
    response_model=CatalogSourceListResponse,
    responses={
        403: {"description": "접근 Profile 또는 DB grant 거부"},
        503: {"description": "Profile 자격증명, DataHub 또는 Trino 카탈로그 미가용"},
    },
)
def list_catalog_sources(
    context: Annotated[RequestContext, Depends(analysis_context)],
) -> dict:
    try:
        adapter, database_grants = _catalog_adapter(context)
        items = adapter.catalog_sources(database_grants)
    except HTTPException:
        raise
    except (OSError, ValueError) as error:
        raise HTTPException(
            status_code=503,
            detail="DataHub 또는 Trino 카탈로그 상태를 확인할 수 없습니다.",
        ) from error
    if {item["source_id"] for item in items} != database_grants:
        raise HTTPException(status_code=503, detail="허용된 원천 카탈로그가 완전하지 않습니다.")
    return {"items": items}
