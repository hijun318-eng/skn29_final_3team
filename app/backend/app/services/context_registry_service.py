from __future__ import annotations

from uuid import UUID

from app.context_registry_contracts import (
    ContextPackage,
    ContextRecord,
    ContextRelease,
    CreateContextPackage,
    CreateContextRecord,
    CreateContextRelease,
)


class ContextRegistryService:
    """Context Registry의 유일한 application service 진입점."""

    def __init__(self, repository: object) -> None:
        self._repository = repository

    def create_record(self, command: CreateContextRecord) -> ContextRecord:
        return self._repository.create_record(command)

    def approve_record(self, record_id: UUID, approved_by: UUID) -> ContextRecord:
        return self._repository.approve_record(record_id, approved_by)

    def deprecate_record(self, record_id: UUID) -> ContextRecord:
        return self._repository.deprecate_record(record_id)

    def create_release(self, command: CreateContextRelease) -> ContextRelease:
        return self._repository.create_release(command)

    def publish_release(self, release_id: UUID, published_by: UUID) -> ContextRelease:
        return self._repository.publish_release(release_id, published_by)

    def retire_release(self, release_id: UUID) -> ContextRelease:
        return self._repository.retire_release(release_id)

    def create_package(self, command: CreateContextPackage) -> ContextPackage:
        return self._repository.create_package(command)
