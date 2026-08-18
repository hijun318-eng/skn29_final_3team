"""Context record·release·package 명령을 PostgreSQL registry의 idempotency·checksum·상태 전이 경계에 전달하고 충돌·장애를 typed 예외로 보존한다."""

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

    async def create_record(self, command: CreateContextRecord) -> ContextRecord:
        """검증된 create command를 registry의 원자적 record 생성 경계에 전달한다.

        checksum·idempotency key·version uniqueness의 권위는 repository transaction에 두며,
        동일 key의 다른 payload 충돌과 저장소 장애를 typed 예외로 그대로 전파한다.
        """
        return await self._repository.create_record(command)

    async def approve_record(self, record_id: UUID, approved_by: UUID) -> ContextRecord:
        """DRAFT record를 APPROVED로 전이하고 승인 주체·시각이 기록된 결과를 반환한다.

        상태 선행 조건과 원자성은 repository transaction이 판정하며, 충돌이나 저장소 장애는
        application service에서 완화하지 않고 typed 예외로 전파한다.
        """
        return await self._repository.approve_record(record_id, approved_by)

    async def deprecate_record(self, record_id: UUID) -> ContextRecord:
        """APPROVED record를 DEPRECATED로 원자 전이하고 갱신된 record를 반환한다.

        미존재와 잘못된 현재 상태를 repository의 충돌 계약에 맡기며 이전 승인 증거는
        보존한다.
        """
        return await self._repository.deprecate_record(record_id)

    async def create_release(self, command: CreateContextRelease) -> ContextRelease:
        """승인 record 참조·checksum을 포함한 command로 DRAFT context release를 생성한다.

        repository가 모든 참조의 APPROVED 상태와 checksum 일치, version 고유성 및
        idempotency payload 동일성을 한 transaction에서 검증한다.
        """
        return await self._repository.create_release(command)

    async def publish_release(self, release_id: UUID, published_by: UUID) -> ContextRelease:
        """DRAFT release를 PUBLISHED로 전이하고 게시 주체·시각이 기록된 결과를 반환한다.

        repository의 비교 갱신이 동시 게시와 잘못된 상태를 충돌로 닫으며, 서비스는 해당
        typed 실패를 그대로 호출자에게 전달한다.
        """
        return await self._repository.publish_release(release_id, published_by)

    async def retire_release(self, release_id: UUID) -> ContextRelease:
        """PUBLISHED release를 RETIRED로 원자 전이하고 기존 게시 증거를 보존한다.

        대상이 없거나 현재 상태가 PUBLISHED가 아니면 repository의 충돌 예외가 전파된다.
        """
        return await self._repository.retire_release(release_id)

    async def create_package(self, command: CreateContextPackage) -> ContextPackage:
        """게시된 release와 요청별 scope·asset·metric·join·policy를 context package로 저장한다.

        repository가 PUBLISHED 선행 조건, package checksum과 idempotency 동일성을 검증하며,
        성공 시 영속 식별자와 package hash가 포함된 계약 객체를 반환한다.
        """
        return await self._repository.create_package(command)
