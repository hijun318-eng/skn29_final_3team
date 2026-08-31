"""보고서 정의·블록·실행·수동 명령의 불변 상태와 승인 전이를 프레임워크 없이 정의한다."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Mapping
import json
import re
import unicodedata

REPORT_CONTRACT_VERSION = "REPORT-v1.0.0"
REPORT_PROPOSAL_VERSION = "REPORT-v1.1.0-DRAFT"
REPORT_ORIENTATIONS = frozenset({"portrait", "landscape"})
CURRENCY_DISPLAY_UNITS = frozenset(
    {"auto", "one", "thousand", "million", "hundredMillion", "billion"}
)
MAX_REPORT_TITLE_LENGTH = 255
REPORT_ARTIFACT_VIEWS = frozenset({"summary", "kpi", "chart", "table"})


def normalize_report_block_content(block_type: "BlockType | str", content: str) -> str:
    """data block 설정을 정확히 한 원자 Artifact view로 정규화한다.

    legacy chart/table은 block type 자체가 view를 확정하므로 누락된 ``visibleViews``만
    안전하게 보완한다. artifact 합본·unknown·복수 view는 원본 DB를 변경하지 않고 새 저장을
    거부해 조용한 데이터 손실을 막는다.
    """

    resolved_type = BlockType(block_type)
    if resolved_type not in {BlockType.TABLE, BlockType.CHART, BlockType.ARTIFACT}:
        return content
    try:
        settings = json.loads(content or "{}")
    except (TypeError, ValueError) as error:
        raise ValueError("Report 분석 block 설정은 JSON 객체여야 합니다.") from error
    if not isinstance(settings, dict):
        raise ValueError("Report 분석 block 설정은 JSON 객체여야 합니다.")
    expected = (
        "chart" if resolved_type is BlockType.CHART
        else "table" if resolved_type is BlockType.TABLE
        else None
    )
    requested = settings.get("visibleViews")
    if requested is None and expected is not None:
        requested = [expected]
        settings["visibleViews"] = requested
    if (
        not isinstance(requested, list)
        or len(requested) != 1
        or requested[0] not in REPORT_ARTIFACT_VIEWS
    ):
        raise ValueError("Report 분석 block은 허용된 visibleViews 하나만 가져야 합니다.")
    view = requested[0]
    if (
        (expected is not None and view != expected)
        or (expected is None and view not in {"summary", "kpi"})
    ):
        raise ValueError("Report block type과 visibleViews가 일치하지 않습니다.")
    return json.dumps(
        settings, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def normalize_report_title(value: str) -> str:
    """사용자가 저장하는 보고서 제목을 단일 행의 bounded 문자열로 정규화한다."""

    if not isinstance(value, str):
        raise TypeError("보고서 제목은 문자열이어야 합니다.")
    if any(unicodedata.category(character) == "Cc" for character in value):
        raise ValueError("보고서 제목에는 줄바꿈이나 제어 문자를 사용할 수 없습니다.")
    normalized = value.strip()
    if not normalized:
        raise ValueError("보고서 제목은 비어 있을 수 없습니다.")
    if len(normalized) > MAX_REPORT_TITLE_LENGTH:
        raise ValueError(
            f"보고서 제목은 {MAX_REPORT_TITLE_LENGTH}자를 초과할 수 없습니다."
        )
    return normalized


class DefinitionStatus(StrEnum):
    """보고서 정의 버전이 편집 가능한 초안인지 변경 불가능한 승인본인지 구분한다."""
    DRAFT = "draft"
    APPROVED = "approved"


class RunStatus(StrEnum):
    """보고서 전체 실행 또는 수동 명령의 대기부터 종료까지 허용 상태를 열거한다."""
    QUEUED = "queued"
    RUNNING = "running"
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"


class BlockRunStatus(StrEnum):
    """개별 보고서 블록이 성공·부분 성공·실패·취소 중 어떻게 종료됐는지 표현한다."""
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"


class BlockFailureCode(StrEnum):
    """블록 재실행 실패를 인증·문맥·모델·SQL·쿼리·증거·계약 범주로 안정적으로 분류한다."""
    AUTHENTICATION_REQUIRED = "AUTHENTICATION_REQUIRED"
    ACCESS_DENIED = "ACCESS_DENIED"
    CONTEXT_INCOMPLETE = "CONTEXT_INCOMPLETE"
    CONTEXT_SOURCE_FAILED = "CONTEXT_SOURCE_FAILED"
    SEMANTIC_CONTRACT_INVALID = "SEMANTIC_CONTRACT_INVALID"
    DATA_ASSET_NOT_FOUND = "DATA_ASSET_NOT_FOUND"
    MODEL_CONTRACT_INVALID = "MODEL_CONTRACT_INVALID"
    MODEL_TIMEOUT = "MODEL_TIMEOUT"
    SQL_POLICY_BLOCKED = "SQL_POLICY_BLOCKED"
    SQL_REPAIR_FAILED = "SQL_REPAIR_FAILED"
    TRINO_CONNECTION_FAILED = "TRINO_CONNECTION_FAILED"
    QUERY_TIMEOUT = "QUERY_TIMEOUT"
    QUERY_SOURCE_FAILED = "QUERY_SOURCE_FAILED"
    RESULT_VALIDATION_FAILED = "RESULT_VALIDATION_FAILED"
    RESULT_EVIDENCE_MISSING = "RESULT_EVIDENCE_MISSING"
    ARTIFACT_PERSIST_FAILED = "ARTIFACT_PERSIST_FAILED"
    PARTIAL_FAILURE = "PARTIAL_FAILURE"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    RATE_LIMITED = "RATE_LIMITED"
    REQUEST_CANCELLED = "REQUEST_CANCELLED"
    CONTRACT_VERSION_MISMATCH = "CONTRACT_VERSION_MISMATCH"
    SCHEMA_VERSION_MISMATCH = "SCHEMA_VERSION_MISMATCH"
    DEFINITION_NOT_FOUND = "DEFINITION_NOT_FOUND"
    REPLAY_UNAVAILABLE = "REPLAY_UNAVAILABLE"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class BlockType(StrEnum):
    """보고서 격자 블록이 데이터·텍스트·명시적 페이지 경계 중 무엇인지 지정한다."""
    TABLE = "table"
    CHART = "chart"
    ARTIFACT = "artifact"
    TEXT = "text"
    PAGE_BREAK = "page_break"


@dataclass(frozen=True, slots=True)
class ReportBlock:
    """분석 산출물 또는 텍스트를 12열 격자의 유효한 위치와 크기에 배치하는 불변 값 객체다."""
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
    evidence_refs: tuple[str, ...] = ()
    view_spec_id: str | None = None

    def __post_init__(self) -> None:
        if not self.block_id or not self.title:
            raise ValueError("Report block은 block_id와 title이 필요합니다.")
        object.__setattr__(self, "type", BlockType(self.type))
        object.__setattr__(self, "w", self.columns if self.w is None else self.w)
        # Evidence aliases are a set-like lineage binding; canonical order prevents
        # the model from creating a no-op Revision by merely reordering aliases.
        object.__setattr__(self, "evidence_refs", tuple(sorted(self.evidence_refs)))
        if not 1 <= self.columns <= 12:
            raise ValueError("Report block columns는 1~12 범위여야 합니다.")
        if self.columns != self.w:
            raise ValueError("Report block columns와 w는 같아야 합니다.")
        if self.x < 0 or self.y < 0 or self.w < 1 or self.h < 1 or self.x + self.w > 12:
            raise ValueError("Report block layout은 12-column bounds와 positive height를 지켜야 합니다.")
        if self.type in (BlockType.TABLE, BlockType.CHART, BlockType.ARTIFACT) and not self.artifact_id:
            raise ValueError("table·chart·artifact block은 artifact_id가 필요합니다.")
        if self.type is BlockType.TEXT and not self.content.strip():
            raise ValueError("text block은 빈 content를 허용하지 않습니다.")
        if self.type is BlockType.PAGE_BREAK and (
            self.artifact_id is not None
            or self.query_id is not None
            or self.content
            or self.x != 0
            or self.w != 12
            or self.h != 1
        ):
            raise ValueError("page break block은 내용·Artifact 없이 12열 한 행이어야 합니다.")
        if (
            len(self.evidence_refs) > 16
            or len(set(self.evidence_refs)) != len(self.evidence_refs)
            or any(not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", ref) for ref in self.evidence_refs)
        ):
            raise ValueError("Report block 근거 별칭 계약이 올바르지 않습니다.")
        if self.type is not BlockType.TEXT and self.evidence_refs:
            raise ValueError("근거 별칭은 text block에만 저장할 수 있습니다.")


@dataclass(frozen=True, slots=True)
class ReportDefinitionVersion:
    """보고서 제목·블록·문서 표시 설정을 버전과 승인 상태에 결속하는 불변 정의다."""
    definition_id: str
    version: int
    status: DefinitionStatus
    title: str
    blocks: tuple[ReportBlock, ...]
    approved_at: datetime | None = None
    orientation: str = "portrait"
    currency_display_unit: str = "auto"
    product_release_id: str | None = None
    permission_snapshot_id: str | None = None
    semantic_release_id: str | None = None
    draft_revision: int = 1
    archived_at: datetime | None = None
    archived_by: str | None = None

    def __post_init__(self) -> None:
        if not self.definition_id or self.version < 1:
            raise ValueError("Report definition id와 version은 필수입니다.")
        object.__setattr__(self, "title", normalize_report_title(self.title))
        if (
            isinstance(self.draft_revision, bool)
            or not isinstance(self.draft_revision, int)
            or self.draft_revision < 1
        ):
            raise ValueError("Report draft revision은 1 이상의 정수여야 합니다.")
        if self.status is DefinitionStatus.APPROVED and self.approved_at is None:
            raise ValueError("승인 version은 approved_at이 필요합니다.")
        if self.status is DefinitionStatus.DRAFT and self.approved_at is not None:
            raise ValueError("draft version에는 approved_at을 기록하지 않습니다.")
        if self.orientation not in REPORT_ORIENTATIONS:
            raise ValueError("Report orientation must be portrait or landscape")
        if self.currency_display_unit not in CURRENCY_DISPLAY_UNITS:
            raise ValueError("Report currency display unit is invalid")
        receipt = (
            self.product_release_id,
            self.permission_snapshot_id,
            self.semantic_release_id,
        )
        if any(receipt) and not all(receipt):
            raise ValueError("Report definition release receipt must be complete")
        if (self.archived_at is None) != (self.archived_by is None):
            raise ValueError("Report archive timestamp and actor must be complete")
        if self.archived_at is not None and (
            self.archived_at.tzinfo is None or self.archived_at.utcoffset() is None
        ):
            raise ValueError("Report archive timestamp must include a timezone")
        if self.archived_by is not None and not self.archived_by.strip():
            raise ValueError("Report archive actor must not be blank")

    @property
    def is_archived(self) -> bool:
        """정의 전체가 비파괴 보관되어 읽기 전용인지 반환한다."""

        return self.archived_at is not None

    def approve(self, approved_at: datetime) -> "ReportDefinitionVersion":
        """초안만 지정 시각의 승인본으로 복제하며 이미 승인된 버전은 변경하지 않고 거부한다."""
        if self.is_archived:
            raise ValueError("보관된 Report definition은 승인할 수 없습니다.")
        if self.status is not DefinitionStatus.DRAFT:
            raise ValueError("draft Report version만 승인할 수 있습니다.")
        return ReportDefinitionVersion(
            definition_id=self.definition_id,
            version=self.version,
            status=DefinitionStatus.APPROVED,
            title=self.title,
            blocks=self.blocks,
            approved_at=approved_at,
            orientation=self.orientation,
            currency_display_unit=self.currency_display_unit,
            product_release_id=self.product_release_id,
            permission_snapshot_id=self.permission_snapshot_id,
            semantic_release_id=self.semantic_release_id,
            draft_revision=self.draft_revision,
        )

    def next_draft(self) -> "ReportDefinitionVersion":
        """승인본의 내용과 표시 설정을 복사해 버전을 하나 올린 편집 가능한 초안을 만든다."""
        if self.is_archived:
            raise ValueError("보관된 Report definition에서 새 draft를 만들 수 없습니다.")
        if self.status is not DefinitionStatus.APPROVED:
            raise ValueError("승인된 Report version만 다음 draft의 기준이 될 수 있습니다.")
        return ReportDefinitionVersion(
            definition_id=self.definition_id,
            version=self.version + 1,
            status=DefinitionStatus.DRAFT,
            title=self.title,
            blocks=self.blocks,
            orientation=self.orientation,
            currency_display_unit=self.currency_display_unit,
            product_release_id=self.product_release_id,
            permission_snapshot_id=self.permission_snapshot_id,
            semantic_release_id=self.semantic_release_id,
            draft_revision=1,
        )

    def replace_blocks(
        self,
        blocks: tuple[ReportBlock, ...],
        *,
        title: str | None = None,
        orientation: str | None = None,
        currency_display_unit: str | None = None,
    ) -> "ReportDefinitionVersion":
        """초안의 제목·블록·표시 설정을 교체한 새 값 객체를 반환하고 승인본 수정은 거부한다."""
        if self.is_archived:
            raise ValueError("보관된 Report definition은 편집할 수 없습니다.")
        if self.status is not DefinitionStatus.DRAFT:
            raise ValueError("draft Report version만 block layout을 교체할 수 있습니다.")
        return ReportDefinitionVersion(
            definition_id=self.definition_id,
            version=self.version,
            status=self.status,
            title=self.title if title is None else title,
            blocks=blocks,
            orientation=self.orientation if orientation is None else orientation,
            currency_display_unit=(
                self.currency_display_unit
                if currency_display_unit is None
                else currency_display_unit
            ),
            product_release_id=self.product_release_id,
            permission_snapshot_id=self.permission_snapshot_id,
            semantic_release_id=self.semantic_release_id,
            draft_revision=self.draft_revision,
        )


@dataclass(frozen=True, slots=True)
class ReportDefinitionLifecycle:
    """보고서 정의의 active·archived 전이를 actor와 시각에 결속한 공개 상태다."""

    definition_id: str
    archived_at: datetime | None
    archived_by: str | None

    def __post_init__(self) -> None:
        if not self.definition_id:
            raise ValueError("Report definition id는 필수입니다.")
        if (self.archived_at is None) != (self.archived_by is None):
            raise ValueError("Report archive timestamp and actor must be complete")
        if self.archived_at is not None and (
            self.archived_at.tzinfo is None or self.archived_at.utcoffset() is None
        ):
            raise ValueError("Report archive timestamp must include a timezone")

    @property
    def archived(self) -> bool:
        """현재 보고서가 보관 상태인지 반환한다."""

        return self.archived_at is not None


@dataclass(frozen=True, slots=True)
class ReportBlockRun:
    """블록 실행 상태를 성공 시 산출물 증거, 실패 시 공개 가능한 타입 오류와 결속한다."""
    block_id: str
    artifact_id: str | None
    query_id: str | None
    snapshot_checksum: str | None
    status: BlockRunStatus
    request_id: str | None = None
    failure_code: BlockFailureCode | None = None
    failure_message: str | None = None

    def __post_init__(self) -> None:
        if not self.block_id:
            raise ValueError("Report block run block_id is required")
        if self.status in {BlockRunStatus.SUCCESS, BlockRunStatus.PARTIAL} and not all(
            (self.request_id, self.artifact_id, self.query_id, self.snapshot_checksum)
        ):
            raise ValueError("successful Report block run requires Artifact evidence")
        if self.status in {BlockRunStatus.FAILED, BlockRunStatus.CANCELLED} and not all(
            (self.failure_code, self.failure_message)
        ):
            raise ValueError("failed Report block run requires a typed public failure")
        if self.status is BlockRunStatus.SUCCESS and (
            self.failure_code is not None or self.failure_message is not None
        ):
            raise ValueError("successful Report block run cannot include a failure")


@dataclass(frozen=True, slots=True)
class ReportRun:
    """정의 버전 실행을 기준 시각, 정책·문맥 해시, 소스 watermark와 블록 결과에 고정한다."""
    run_id: str
    definition_id: str
    definition_version: int
    as_of: datetime
    policy_version: str
    context_hash: str
    watermark: Mapping[str, str]
    status: RunStatus
    blocks: tuple[ReportBlockRun, ...] = ()
    product_release_id: str | None = None
    permission_snapshot_id: str | None = None
    semantic_release_id: str | None = None

    def __post_init__(self) -> None:
        if not self.run_id or not self.definition_id or self.definition_version < 1:
            raise ValueError("Report run은 run id와 definition version을 유지해야 합니다.")
        receipt = (
            self.product_release_id,
            self.permission_snapshot_id,
            self.semantic_release_id,
        )
        if any(receipt) and not all(receipt):
            raise ValueError("Report run release receipt must be complete")
        object.__setattr__(self, "watermark", MappingProxyType(dict(self.watermark)))


@dataclass(frozen=True, slots=True)
class ManualRunCommand:
    """멱등 키로 중복을 식별하는 특정 보고서 정의 버전의 수동 실행 명령을 표현한다."""
    command_id: str
    definition_id: str
    version: int
    as_of: datetime
    idempotency_key: str
    status: RunStatus = RunStatus.QUEUED

    def __post_init__(self) -> None:
        if not self.command_id or not self.definition_id or self.version < 1 or not self.idempotency_key:
            raise ValueError("manual run command 필드는 비어 있을 수 없습니다.")
        if self.status not in {
            RunStatus.QUEUED,
            RunStatus.RUNNING,
            RunStatus.SUCCESS,
            RunStatus.PARTIAL,
            RunStatus.FAILED,
            RunStatus.CANCELLED,
        }:
            raise ValueError("manual run command status is invalid")
