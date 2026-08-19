"""PostgreSQL 레지스트리 기반 Context 레코드/릴리즈/패키지 생명주기 관리 서비스 모듈.

[핵심 목적]
컨텍스트 레코드(ContextRecord)의 상태 전이(DRAFT -> APPROVED -> DEPRECATED),
릴리즈(ContextRelease)의 발행(DRAFT -> PUBLISHED -> RETIRED),
그리고 런타임 패키지(ContextPackage)의 멱등 저장 및 감사 로그 영속화를 관리합니다.
"""

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
    """Context Registry 영속성 계층과 상호작용하는 애플리케이션 서비스 클래스."""

    def __init__(self, repository: object) -> None:
        self._repository = repository

    async def create_record(self, command: CreateContextRecord) -> ContextRecord:
        """신규 ContextRecord를 DRAFT 상태로 생성합니다."""
        return await self._repository.create_record(command)

    async def approve_record(self, record_id: UUID, approved_by: UUID) -> ContextRecord:
        """DRAFT 상태의 레코드를 APPROVED 상태로 전이합니다."""
        return await self._repository.approve_record(record_id, approved_by)

    async def deprecate_record(self, record_id: UUID) -> ContextRecord:
        """APPROVED 상태의 레코드를 DEPRECATED 상태로 전이합니다."""
        return await self._repository.deprecate_record(record_id)

    async def create_release(self, command: CreateContextRelease) -> ContextRelease:
        """승인된 레코드 참조들을 묶어 DRAFT 릴리즈를 생성합니다."""
        return await self._repository.create_release(command)

    async def publish_release(self, release_id: UUID, published_by: UUID) -> ContextRelease:
        """DRAFT 상태의 릴리즈를 PUBLISHED 상태로 전이하여 프로덕션에 배포합니다."""
        return await self._repository.publish_release(release_id, published_by)

    async def retire_release(self, release_id: UUID) -> ContextRelease:
        """PUBLISHED 상태의 릴리즈를 RETIRED 상태로 퇴역 처리합니다."""
        return await self._repository.retire_release(release_id)

    async def create_package(self, command: CreateContextPackage) -> ContextPackage:
        """게시된 릴리즈를 기반으로 런타임 ContextPackage를 레지스트리에 영속화합니다."""
        return await self._repository.create_package(command)
