from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class CatalogContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CatalogSource(CatalogContractModel):
    source_id: Literal["pms", "pos", "crm", "facility", "banquet"]
    platform: str
    location: str
    dataset_urn: str
    owners: list[str]
    owner_status: Literal["AVAILABLE", "MISSING"]
    schema_status: Literal["AVAILABLE", "EMPTY"]
    column_count: int
    search_status: Literal["AVAILABLE"]
    connection_status: Literal["AVAILABLE"]


class CatalogSourceListResponse(CatalogContractModel):
    items: list[CatalogSource]
