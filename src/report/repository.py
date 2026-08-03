from datetime import datetime

from .domain import DefinitionStatus, ReportDefinitionVersion, ReportRun


class InMemoryReportRepository:
    """R4 등록 전 contract test용 repository; production persistence가 아니다."""

    def __init__(self) -> None:
        self._versions: dict[tuple[str, int], ReportDefinitionVersion] = {}
        self._runs: dict[str, ReportRun] = {}

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

    def approve(self, definition_id: str, version: int, approved_at: datetime) -> ReportDefinitionVersion:
        approved = self.get_version(definition_id, version).approve(approved_at)
        self._versions[(definition_id, version)] = approved
        return approved

    def create_next_draft(self, definition_id: str, approved_version: int) -> ReportDefinitionVersion:
        draft = self.get_version(definition_id, approved_version).next_draft()
        return self.add_draft(draft)

    def add_run(self, run: ReportRun) -> ReportRun:
        version = self.get_version(run.definition_id, run.definition_version)
        if version.status is not DefinitionStatus.APPROVED:
            raise ValueError("승인된 Report definition version만 실행할 수 있습니다.")
        if run.run_id in self._runs:
            raise ValueError("같은 Report run_id를 다시 저장할 수 없습니다.")
        self._runs[run.run_id] = run
        return run