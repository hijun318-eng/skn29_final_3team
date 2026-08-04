from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Mapping

REPORT_CONTRACT_VERSION = "REPORT-v1.0.0"
REPORT_PROPOSAL_VERSION = "REPORT-v1.1.0-DRAFT"


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


class BlockType(StrEnum):
    TABLE = "table"
    CHART = "chart"
    TEXT = "text"


@dataclass(frozen=True, slots=True)
class ReportBlock:
    block_id: str
    title: str
    artifact_id: str | None
    columns: int
    query_id: str | None = None
    type: BlockType = BlockType.TABLE
    x: int = 0
    y: int = 0
    w: int | None = None
    h: int = 1
    content: str = ""

    def __post_init__(self) -> None:
        if not self.block_id or not self.title:
            raise ValueError("Report block은 block_id와 title이 필요합니다.")
        object.__setattr__(self, "type", BlockType(self.type))
        object.__setattr__(self, "w", self.columns if self.w is None else self.w)
        if not 1 <= self.columns <= 12:
            raise ValueError("Report block columns는 1~12 범위여야 합니다.")
        if self.columns != self.w:
            raise ValueError("Report block columns와 w는 같아야 합니다.")
        if self.x < 0 or self.y < 0 or self.w < 1 or self.h < 1 or self.x + self.w > 12:
            raise ValueError("Report block layout은 12-column bounds와 positive height를 지켜야 합니다.")
        if self.type in (BlockType.TABLE, BlockType.CHART) and not self.artifact_id:
            raise ValueError("table·chart block은 artifact_id가 필요합니다.")
        if self.type is BlockType.TEXT and not self.content.strip():
            raise ValueError("text block은 빈 content를 허용하지 않습니다.")


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

    def replace_blocks(self, blocks: tuple[ReportBlock, ...]) -> "ReportDefinitionVersion":
        if self.status is not DefinitionStatus.DRAFT:
            raise ValueError("draft Report version만 block layout을 교체할 수 있습니다.")
        return ReportDefinitionVersion(
            definition_id=self.definition_id,
            version=self.version,
            status=self.status,
            title=self.title,
            blocks=blocks,
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


@dataclass(frozen=True, slots=True)
class ManualRunCommand:
    command_id: str
    definition_id: str
    version: int
    as_of: datetime
    idempotency_key: str
    status: RunStatus = RunStatus.QUEUED

    def __post_init__(self) -> None:
        if not self.command_id or not self.definition_id or self.version < 1 or not self.idempotency_key:
            raise ValueError("manual run command 필드는 비어 있을 수 없습니다.")
        if self.status is not RunStatus.QUEUED:
            raise ValueError("manual run command는 queued 상태로만 생성합니다.")
