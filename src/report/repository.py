"""보고서 router가 저장 방식에 결합되지 않도록 정의·실행·수동 명령 영속 연산을 선언한다."""

from collections.abc import Awaitable
from datetime import datetime
from typing import Protocol

from .domain import (
    ManualRunCommand,
    ReportBlock,
    ReportDefinitionLifecycle,
    ReportDefinitionVersion,
    ReportRun,
)


class ReportRevisionConflict(ValueError):
    """저장 요청의 기준 revision이 현재 draft와 달라 안전하게 적용할 수 없음을 나타낸다."""

    def __init__(self, current_revision: int) -> None:
        super().__init__("REPORT_REVISION_CONFLICT")
        self.current_revision = current_revision


class ReportLifecycleConflict(ValueError):
    """진행 중 실행이나 Assistant 때문에 보관 전이를 안전하게 수행할 수 없음을 나타낸다."""


class ReportRepository(Protocol):
    """정의 승인 전이, 실행 이력과 멱등 수동 명령을 보존해야 하는 저장소 연산을 규정한다."""

    def add_draft(
        self, draft: ReportDefinitionVersion
    ) -> ReportDefinitionVersion | Awaitable[ReportDefinitionVersion]:
        """검증된 첫 초안을 저장하며 식별자·버전 충돌은 adapter의 타입 오류로 노출한다."""
        ...

    def get_version(
        self, definition_id: str, version: int
    ) -> ReportDefinitionVersion | Awaitable[ReportDefinitionVersion]:
        """정의 식별자와 양의 버전으로 단일 정의를 조회하며 미존재 결과는 숨기지 않는다."""
        ...

    def list_definitions(
        self,
        *,
        archived: bool = False,
    ) -> tuple[ReportDefinitionVersion, ...] | Awaitable[tuple[ReportDefinitionVersion, ...]]:
        """호출자 범위에서 active 또는 명시한 archived 보고서 버전들을 반환한다."""
        ...

    def archive_definition(
        self,
        definition_id: str,
        *,
        actor_role: str,
        trace_id: str | None = None,
    ) -> ReportDefinitionLifecycle | Awaitable[ReportDefinitionLifecycle]:
        """소유 보고서를 멱등 보관하고 안전하지 않은 진행 상태가 있으면 전이를 거부한다."""
        ...

    def restore_definition(
        self,
        definition_id: str,
        *,
        actor_role: str,
        trace_id: str | None = None,
    ) -> ReportDefinitionLifecycle | Awaitable[ReportDefinitionLifecycle]:
        """소유 보고서를 멱등 복원하되 이전 schedule을 자동 재활성화하지 않는다."""
        ...

    def permanently_delete_definition(
        self,
        definition_id: str,
        *,
        actor_role: str,
        trace_id: str | None = None,
    ) -> bool | Awaitable[bool]:
        """휴지통에 있는 소유 보고서 데이터를 복원 불가능하게 제거하고 감사 기록만 보존한다."""
        ...

    def approve(
        self, definition_id: str, version: int, approved_at: datetime
    ) -> ReportDefinitionVersion | Awaitable[ReportDefinitionVersion]:
        """지정 초안을 승인 시각과 함께 원자적으로 전이하며 중복·비초안 승인은 거부한다."""
        ...

    def create_next_draft(
        self, definition_id: str, approved_version: int
    ) -> ReportDefinitionVersion | Awaitable[ReportDefinitionVersion]:
        """승인본을 기준으로 내용이 복사된 다음 번호 초안을 원자적으로 생성한다."""
        ...

    def replace_draft_blocks(
        self,
        definition_id: str,
        version: int,
        blocks: tuple[ReportBlock, ...],
        *,
        title: str | None = None,
        orientation: str | None = None,
        currency_display_unit: str | None = None,
        expected_draft_revision: int | None = None,
    ) -> ReportDefinitionVersion | Awaitable[ReportDefinitionVersion]:
        """초안 전체를 원자 교체하고 선택적 revision token으로 동시 저장을 차단한다."""
        ...

    def add_run(self, run: ReportRun) -> ReportRun | Awaitable[ReportRun]:
        """정의 버전과 증거가 검증된 보고서 실행을 저장하고 영속 상태를 반환한다."""
        ...

    def list_runs(
        self, definition_id: str | None = None
    ) -> tuple[ReportRun, ...] | Awaitable[tuple[ReportRun, ...]]:
        """선택적 정의 ID로 실행 이력을 제한하고 결과를 변경 불가능한 tuple로 반환한다."""
        ...

    def get_run(self, run_id: str) -> ReportRun | Awaitable[ReportRun]:
        """실행 식별자로 단일 실행과 블록 증거를 조회하며 미존재 상태는 호출자에게 전달한다."""
        ...

    def queue_manual_run(
        self,
        definition_id: str,
        version: int,
        as_of: datetime,
        idempotency_key: str,
    ) -> ManualRunCommand | Awaitable[ManualRunCommand]:
        """정의 버전·기준 시각·멱등 키를 원자적으로 등록하고 같은 키에는 기존 명령을 반환한다."""
        ...
