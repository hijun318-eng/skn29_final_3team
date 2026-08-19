"""Report router 계약 테스트에 명시적으로 주입하는 메모리 저장소 double이다."""

from __future__ import annotations

import hashlib
from datetime import datetime
from uuid import uuid4

from src.report.domain import (
    DefinitionStatus,
    ManualRunCommand,
    ReportBlock,
    ReportDefinitionVersion,
    ReportRun,
)


class InMemoryReportRepository:
    """외부 DB 없이 router 상태 전이만 검증하며 운영 코드에서는 import하지 않는다."""

    def __init__(self) -> None:
        self._versions: dict[tuple[str, int], ReportDefinitionVersion] = {}
        self._runs: dict[str, ReportRun] = {}
        self._commands: dict[str, ManualRunCommand] = {}
        self._idempotency: dict[tuple[str, int, str], str] = {}
        self._documents: dict[tuple[str, int], dict[str, object]] = {}

    def add_draft(self, draft: ReportDefinitionVersion) -> ReportDefinitionVersion:
        if draft.status is not DefinitionStatus.DRAFT:
            raise ValueError("draft만 저장할 수 있습니다.")
        key = (draft.definition_id, draft.version)
        existing = self._versions.get(key)
        if existing and existing.status is DefinitionStatus.APPROVED:
            raise ValueError("승인된 Report version은 덮어쓸 수 없습니다.")
        self._versions[key] = draft
        return draft

    def get_version(self, definition_id: str, version: int) -> ReportDefinitionVersion:
        try:
            return self._versions[(definition_id, version)]
        except KeyError as error:
            raise KeyError("Report definition version을 찾을 수 없습니다.") from error

    def list_definitions(self) -> tuple[ReportDefinitionVersion, ...]:
        return tuple(self._versions[key] for key in sorted(self._versions))

    def approve(
        self, definition_id: str, version: int, approved_at: datetime
    ) -> ReportDefinitionVersion:
        approved = self.get_version(definition_id, version).approve(approved_at)
        self._versions[(definition_id, version)] = approved
        return approved

    def create_next_draft(
        self, definition_id: str, approved_version: int
    ) -> ReportDefinitionVersion:
        draft = self.get_version(definition_id, approved_version).next_draft()
        return self.add_draft(draft)

    def get_document_source(self, definition_id: str, version: int) -> dict[str, object]:
        report = self.get_version(definition_id, version)
        if report.status is not DefinitionStatus.DRAFT:
            raise ValueError("Only a draft Report version can be finalized")
        if any(block.artifact_id for block in report.blocks):
            raise ValueError("The contract test repository has no Artifact snapshots")
        return {
            "definition_id": report.definition_id,
            "version": report.version,
            "title": report.title,
            "orientation": report.orientation,
            "currency_display_unit": report.currency_display_unit,
            "blocks": [
                {
                    "block_id": block.block_id,
                    "title": block.title,
                    "type": block.type.value,
                    "x": block.x,
                    "y": block.y,
                    "w": block.w,
                    "h": block.h,
                    "content": block.content,
                    "artifact": None,
                }
                for block in report.blocks
            ],
            "artifact_versions": [],
        }

    def approve_with_document(
        self,
        definition_id: str,
        version: int,
        approved_at: datetime,
        orientation: str,
        currency_display_unit: str,
        expected_source_checksum: str,
        html_snapshot: str,
        pdf_bytes: bytes,
    ) -> ReportDefinitionVersion:
        from app.services.report.document import canonical_source_checksum

        source = self.get_document_source(definition_id, version)
        if source["orientation"] != orientation:
            raise ValueError("Report orientation changed while the PDF was rendering")
        if source["currency_display_unit"] != currency_display_unit:
            raise ValueError("Report currency display unit changed while the PDF was rendering")
        if canonical_source_checksum(source, orientation) != expected_source_checksum:
            raise ValueError("Report content changed while the PDF was rendering")
        approved = self.get_version(definition_id, version).approve(approved_at)
        self._documents[(definition_id, version)] = {
            "definition_id": definition_id,
            "definition_version": version,
            "orientation": orientation,
            "currency_display_unit": currency_display_unit,
            "renderer_version": "weasyprint-69",
            "source_checksum": expected_source_checksum,
            "html_checksum": hashlib.sha256(html_snapshot.encode("utf-8")).hexdigest(),
            "pdf_checksum": hashlib.sha256(pdf_bytes).hexdigest(),
            "html_snapshot": html_snapshot,
            "pdf_bytes": pdf_bytes,
            "artifact_versions": source["artifact_versions"],
            "confirmed_at": approved_at,
        }
        self._versions[(definition_id, version)] = approved
        return approved

    def get_document(self, definition_id: str, version: int) -> dict[str, object]:
        try:
            return self._documents[(definition_id, version)]
        except KeyError as error:
            raise KeyError("Final Report document not found") from error

    def replace_draft_blocks(
        self,
        definition_id: str,
        version: int,
        blocks: tuple[ReportBlock, ...],
        *,
        orientation: str | None = None,
        currency_display_unit: str | None = None,
    ) -> ReportDefinitionVersion:
        replaced = self.get_version(definition_id, version).replace_blocks(
            blocks,
            orientation=orientation,
            currency_display_unit=currency_display_unit,
        )
        self._versions[(definition_id, version)] = replaced
        return replaced

    def add_run(self, run: ReportRun) -> ReportRun:
        version = self.get_version(run.definition_id, run.definition_version)
        if version.status is not DefinitionStatus.APPROVED:
            raise ValueError("승인된 Report definition version만 실행할 수 있습니다.")
        if run.run_id in self._runs:
            raise ValueError("같은 Report run_id를 다시 저장할 수 없습니다.")
        self._runs[run.run_id] = run
        return run

    def list_runs(self, definition_id: str | None = None) -> tuple[ReportRun, ...]:
        return tuple(
            run
            for run in self._runs.values()
            if definition_id is None or run.definition_id == definition_id
        )

    def get_run(self, run_id: str) -> ReportRun:
        try:
            return self._runs[run_id]
        except KeyError as error:
            raise KeyError("Report run을 찾을 수 없습니다.") from error

    def queue_manual_run(
        self,
        definition_id: str,
        version: int,
        as_of: datetime,
        idempotency_key: str,
    ) -> ManualRunCommand:
        if self.get_version(definition_id, version).status is not DefinitionStatus.APPROVED:
            raise ValueError("승인된 Report definition version만 실행할 수 있습니다.")
        key = (definition_id, version, idempotency_key)
        if command_id := self._idempotency.get(key):
            return self._commands[command_id]
        command = ManualRunCommand(
            str(uuid4()), definition_id, version, as_of, idempotency_key
        )
        self._commands[command.command_id] = command
        self._idempotency[key] = command.command_id
        return command
