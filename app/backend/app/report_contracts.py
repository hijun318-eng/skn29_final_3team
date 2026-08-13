from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.contracts import ChartSpec, Evidence, TableResult


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


class CreateReportFromArtifactRequest(ReportContractModel):
    artifact_id: UUID
    title: str = Field(min_length=1, max_length=255)


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


class ReportArtifactResponse(ReportContractModel):
    contract_version: str
    artifact_id: UUID
    query_id: str
    title: str
    summary: str
    table: TableResult
    chart: ChartSpec | None = None
    evidence: Evidence
    artifact_checksum: str = Field(pattern=r"^[0-9a-f]{64}$")


class ReportBlockRunResponse(ReportContractModel):
    block_id: str
    artifact_id: str | None
    query_id: str | None
    snapshot_checksum: str | None
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


class CreateReportScheduleRequest(ReportContractModel):
    schedule_id: UUID
    definition_id: UUID
    version: int = Field(ge=1)
    cadence: Literal["daily", "weekly", "monthly"]
    next_run_at: datetime
    timezone: Literal["Asia/Seoul"] = "Asia/Seoul"

    @field_validator("next_run_at")
    @classmethod
    def require_aware_next_run_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("next_run_at에는 timezone offset이 필요합니다.")
        return value


class ReportScheduleResponse(ReportContractModel):
    schedule_id: UUID
    definition_id: UUID
    version: int
    cadence: Literal["daily", "weekly", "monthly"]
    next_run_at: datetime
    timezone: Literal["Asia/Seoul"]
    enabled: bool
    last_run_id: UUID | None = None


class ReportScheduleListResponse(ReportContractModel):
    items: list[ReportScheduleResponse]


class UpdateReportScheduleRequest(ReportContractModel):
    enabled: bool


class RunDueReportScheduleResponse(ReportContractModel):
    schedule: ReportScheduleResponse
    executed: bool
    run: ReportRunResponse | None = None


class CreateReportAssistantDraftRequest(ReportContractModel):
    artifact_id: UUID
    instruction: str = Field(default="경영 검토용 보고서 초안을 구성해 줘", min_length=1, max_length=500)

    @field_validator("instruction")
    @classmethod
    def reject_blank_instruction(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("instruction은 비어 있을 수 없습니다.")
        return value.strip()


class ReportAssistantTraceResponse(ReportContractModel):
    model_version: str
    prompt_id: str
    prompt_version: str
    prompt_hash: str
    attempts: int
    duration_ms: float


class ReportAssistantDraftResponse(ReportContractModel):
    assistant_request_id: UUID
    status: Literal["success"]
    definition: ReportDefinitionResponse
    trace: ReportAssistantTraceResponse


class ManualRunCommandResponse(ReportContractModel):
    contract_version: str
    command_id: str
    definition_id: str
    version: int
    as_of: datetime
    idempotency_key: str
    status: Literal["queued", "success", "partial", "failed"]
    run_id: str | None = None
