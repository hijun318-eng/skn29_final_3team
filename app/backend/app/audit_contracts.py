from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from typing import Literal


class AuditContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AuditRequestSummary(AuditContractModel):
    request_id: UUID
    user_id: UUID
    user_role: str
    request_type: str
    status: str
    error_type: str | None
    trace_id: str
    started_at: datetime
    completed_at: datetime | None


class AuditSearchResponse(AuditContractModel):
    items: list[AuditRequestSummary]


class EffectiveAccessResponse(AuditContractModel):
    policy_version: str
    subject: UUID
    role: Literal["hotel_analyst", "report_admin", "data_admin"]
    mapping_source: Literal["test_seed", "release_principal"]


class RetentionStatus(AuditContractModel):
    status: Literal["unknown", "not_run", "dry_run", "applied"]
    last_run_at: datetime | None


class BackupStatus(AuditContractModel):
    status: Literal["unknown", "not_run", "available"]
    created_at: datetime | None
    age_hours: float | None
    sha256: str | None
    rpo_target_hours: int
    rpo_passed: bool | None


class RestoreStatus(AuditContractModel):
    status: Literal["unknown", "not_run", "verified"]
    verified_at: datetime | None
    mode: Literal["unknown", "not_run", "archive-list-only", "isolated-restore"]
    backup_age_hours: float | None
    restore_duration_hours: float | None
    rpo_target_hours: int
    rpo_passed: bool | None
    rto_target_hours: int
    rto_passed: bool | None
    backup_sha256: str | None


class RecoveryStatusResponse(AuditContractModel):
    generated_at: datetime
    retention: RetentionStatus
    backup: BackupStatus
    restore: RestoreStatus


class AuditTransition(AuditContractModel):
    sequence: int
    from_status: str | None
    to_status: str
    created_at: datetime


class AnalysisDefinitionTrace(AuditContractModel):
    definition_id: UUID
    version: int
    status: str


class ContextTrace(AuditContractModel):
    release_id: UUID | None
    release_key: str | None
    release_version: int | None
    release_hash: str | None
    package_id: UUID | None
    package_hash: str | None


class PolicyTrace(AuditContractModel):
    sql_policy_version: str
    policy_version: str
    entitlement_hash: str | None


class AccessExecutionTrace(AuditContractModel):
    access_profile: str | None
    allowed_domains: list[str]
    datahub_actor: str | None
    allowed_urns: list[str]
    trino_role: str | None
    datahub_search_attempted: bool
    trino_execution_attempted: bool


class ModelTrace(AuditContractModel):
    model_version_id: UUID
    model_role: str
    model_name: str
    model_revision: str
    runtime_name: str


class QueryTrace(AuditContractModel):
    query_id: str | None
    generation_mode: str
    validation_status: str
    execution_status: str
    duration_ms: int | None
    source_urns: list[str]


class MaskingTrace(AuditContractModel):
    applied: bool
    fields: list[str]


class ArtifactTrace(AuditContractModel):
    artifact_id: UUID
    artifact_type: str
    freshness_status: str
    status: str
    artifact_checksum: str
    masking: MaskingTrace


class ReportTrace(AuditContractModel):
    definition_id: UUID
    definition_version: int
    run_id: UUID
    status: str


class AuditTraceResponse(AuditRequestSummary):
    transitions: list[AuditTransition]
    analysis_definition: AnalysisDefinitionTrace | None
    context: ContextTrace
    policy: PolicyTrace
    access: AccessExecutionTrace
    model: ModelTrace | None
    query: QueryTrace | None
    artifact: ArtifactTrace | None
    reports: list[ReportTrace]
