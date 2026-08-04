from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Mapping

REPORT_CONTRACT_VERSION = "REPORT-v1.0.0"


class DefinitionStatus(StrEnum):
    DRAFT = "draft"
    APPROVED = "approved"


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"


class BlockRunStatus(StrEnum):
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class ReportBlock:
    block_id: str
    title: str
    artifact_id: str
    columns: int
    query_id: str | None = None

    def __post_init__(self) -> None:
        if not self.block_id or not self.artifact_id:
            raise ValueError("Report block은 block_id와 artifact_id가 필요합니다.")
        if not 1 <= self.columns <= 12:
            raise ValueError("Report block columns는 1~12 범위여야 합니다.")


@dataclass(frozen=True, slots=True)
class ReportDefinitionVersion:
    definition_id: str
    version: int
    status: DefinitionStatus
    title: str
    blocks: tuple[ReportBlock, ...]
    approved_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.definition_id or self.version < 1 or not self.title:
            raise ValueError("Report definition id, version, title은 필수입니다.")
        if self.status is DefinitionStatus.APPROVED and self.approved_at is None:
            raise ValueError("승인 version은 approved_at이 필요합니다.")
        if self.status is DefinitionStatus.DRAFT and self.approved_at is not None:
            raise ValueError("draft version에는 approved_at을 기록하지 않습니다.")

    def approve(self, approved_at: datetime) -> "ReportDefinitionVersion":
        if self.status is not DefinitionStatus.DRAFT:
            raise ValueError("draft Report version만 승인할 수 있습니다.")
        return ReportDefinitionVersion(
            definition_id=self.definition_id,
            version=self.version,
            status=DefinitionStatus.APPROVED,
            title=self.title,
            blocks=self.blocks,
            approved_at=approved_at,
        )

    def next_draft(self) -> "ReportDefinitionVersion":
        if self.status is not DefinitionStatus.APPROVED:
            raise ValueError("승인된 Report version만 다음 draft의 기준이 될 수 있습니다.")
        return ReportDefinitionVersion(
            definition_id=self.definition_id,
            version=self.version + 1,
            status=DefinitionStatus.DRAFT,
            title=self.title,
            blocks=self.blocks,
        )


@dataclass(frozen=True, slots=True)
class ReportBlockRun:
    block_id: str
    artifact_id: str
    query_id: str
    snapshot_checksum: str
    status: BlockRunStatus

    def __post_init__(self) -> None:
        if not all((self.block_id, self.artifact_id, self.query_id, self.snapshot_checksum)):
            raise ValueError("Report block run은 artifact·query·snapshot checksum을 유지해야 합니다.")


@dataclass(frozen=True, slots=True)
class ReportRun:
    run_id: str
    definition_id: str
    definition_version: int
    as_of: datetime
    policy_version: str
    context_hash: str
    watermark: Mapping[str, str]
    status: RunStatus
    blocks: tuple[ReportBlockRun, ...] = ()

    def __post_init__(self) -> None:
        if not self.run_id or not self.definition_id or self.definition_version < 1:
            raise ValueError("Report run은 run id와 definition version을 유지해야 합니다.")
        object.__setattr__(self, "watermark", MappingProxyType(dict(self.watermark)))