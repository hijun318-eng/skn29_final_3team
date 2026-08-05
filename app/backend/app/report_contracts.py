from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ReportContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReportBlockRequest(ReportContractModel):
    block_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    artifact_id: str | None = None
    query_id: str | None = None
    columns: int | None = Field(default=None, ge=1, le=12)
    type: Literal["table", "chart", "text"] = "table"
    x: int = Field(default=0, ge=0, le=11)
    y: int = Field(default=0, ge=0)
    w: int | None = Field(default=None, ge=1, le=12)
    h: int = Field(default=1, ge=1)
    content: str = ""


class CreateReportDefinitionRequest(ReportContractModel):
    definition_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    blocks: list[ReportBlockRequest] = Field(default_factory=list)


class ReplaceReportBlocksRequest(ReportContractModel):
    blocks: list[ReportBlockRequest]


class ApproveReportVersionRequest(ReportContractModel):
    approved_at: datetime


class CreateManualRunRequest(ReportContractModel):
    definition_id: str = Field(min_length=1)
    version: int = Field(ge=1)
    as_of: datetime
    idempotency_key: str = Field(min_length=1)

    @field_validator("idempotency_key")
    @classmethod
    def reject_blank_idempotency_key(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("idempotency_key는 비어 있을 수 없습니다.")
        return value


class ReportBlockResponse(ReportContractModel):
    block_id: str
    title: str
    artifact_id: str | None
    columns: int
    query_id: str | None
    type: Literal["table", "chart", "text"]
    x: int
    y: int
    w: int
    h: int
    content: str


class ReportDefinitionResponse(ReportContractModel):
    contract_version: str
    definition_id: str
    version: int
    status: Literal["draft", "approved"]
    title: str
    blocks: list[ReportBlockResponse]
    approved_at: datetime | None


class ReportDefinitionListResponse(ReportContractModel):
    contract_version: str
    items: list[ReportDefinitionResponse]


class ReportBlockRunResponse(ReportContractModel):
    block_id: str
    artifact_id: str
    query_id: str
    snapshot_checksum: str
    status: Literal["success", "partial", "failed", "cancelled"]


class ReportRunResponse(ReportContractModel):
    contract_version: str
    run_id: str
    definition_id: str
    definition_version: int
    as_of: datetime
    policy_version: str
    context_hash: str
    watermark: dict[str, str]
    status: Literal["queued", "running", "success", "partial", "failed", "cancelled"]
    blocks: list[ReportBlockRunResponse]


class ReportRunListResponse(ReportContractModel):
    contract_version: str
    items: list[ReportRunResponse]


class ManualRunCommandResponse(ReportContractModel):
    contract_version: str
    command_id: str
    definition_id: str
    version: int
    as_of: datetime
    idempotency_key: str
    status: Literal["queued"]
