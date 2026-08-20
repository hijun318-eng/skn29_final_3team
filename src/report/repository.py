"""보고서 router가 저장 방식에 결합되지 않도록 정의·실행·수동 명령 영속 연산을 선언한다."""

from collections.abc import Awaitable
from datetime import datetime
from typing import Protocol

from .domain import ManualRunCommand, ReportBlock, ReportDefinitionVersion, ReportRun


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
    ) -> tuple[ReportDefinitionVersion, ...] | Awaitable[tuple[ReportDefinitionVersion, ...]]:
        """호출자 권한 범위에서 저장된 보고서 정의 버전들을 안정된 tuple로 반환한다."""
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
    ) -> ReportDefinitionVersion | Awaitable[ReportDefinitionVersion]:
        """초안의 제목·블록 전체·선택적 문서 표시 설정을 한 transaction에서 교체한다."""
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
