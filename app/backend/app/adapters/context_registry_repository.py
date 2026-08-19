"""Context record·package·release를 checksum·idempotency·상태 전이와 함께 PostgreSQL에 저장한다."""

from __future__ import annotations

import hashlib
import json
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from app.context_registry_contracts import (
    ContextPackage,
    ContextRecord,
    ContextRelease,
    CreateContextPackage,
    CreateContextRecord,
    CreateContextRelease,
)
from app.database import get_sessionmaker
class ContextRegistryConflict(RuntimeError):
    """409에 대응하는 Context Registry 도메인 충돌."""

class ContextRegistryUnavailable(RuntimeError):
    """Context Registry DB가 응답하지 않아 record·package·release를 확정할 수 없음을 알린다."""
    pass

def canonical_checksum(value: object) -> str:
    """입력 계약을 표준 JSON으로 직렬화한 뒤 재현 가능한 SHA-256 체크섬을 계산한다."""
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()

def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)

class PostgresContextRegistryRepository:
    """Checksum과 상태 전이를 서버에서 통제하는 PostgreSQL 저장소."""
    def __init__(
        self,
        database_url: str,
        *,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        self._sessionmaker = session_factory or get_sessionmaker(database_url)

    @staticmethod
    def _same_or_conflict(row, checksum_field: str, checksum: str, kind: str):
        if row[checksum_field] != checksum:
            raise ContextRegistryConflict(f"같은 idempotency key의 {kind} payload가 다릅니다.")
        return row

    async def create_record(self, command: CreateContextRecord) -> ContextRecord:
        """payload checksum과 idempotency key를 묶어 DRAFT Context record를 원자적으로 생성한다.

        같은 key의 기존 행은 checksum이 같을 때만 재사용하며 내용이 달라지면 충돌로 거부한다.
        """
        checksum = canonical_checksum(command.payload)
        record_id = uuid4()
        try:
            async with self._sessionmaker.begin() as session:
                row = (await session.execute(
                    text(
                        """
                        INSERT INTO context.context_records
                            (context_record_id, record_type, record_key, version_no,
                             payload_json, status, owner_role, valid_from, valid_to,
                             checksum, idempotency_key)
                        VALUES (:id, :type, :key, :version, CAST(:payload AS jsonb),
                                'DRAFT', :owner, :valid_from, :valid_to, :checksum,
                                :idempotency_key)
                        ON CONFLICT (idempotency_key) DO NOTHING
                        RETURNING *
                        """
                    ),
                    {
                        "id": record_id,
                        "type": command.record_type.value,
                        "key": command.record_key,
                        "version": command.version_no,
                        "payload": _json(command.payload),
                        "owner": command.owner_role,
                        "valid_from": command.valid_from,
                        "valid_to": command.valid_to,
                        "checksum": checksum,
                        "idempotency_key": command.idempotency_key,
                    },
                )).mappings().one_or_none()
                if row is None:
                    row = (await session.execute(
                        text("SELECT * FROM context.context_records WHERE idempotency_key = :key"),
                        {"key": command.idempotency_key},
                    )).mappings().one()
                    row = self._same_or_conflict(row, "checksum", checksum, "record")
                return ContextRecord.from_row(row)
        except ContextRegistryConflict:
            raise
        except IntegrityError as error:
            raise ContextRegistryConflict("같은 Context record version이 이미 존재합니다.") from error
        except SQLAlchemyError as error:
            raise ContextRegistryUnavailable("Context Registry 저장소를 사용할 수 없습니다.") from error

    async def approve_record(self, record_id: UUID, approved_by: UUID) -> ContextRecord:
        """DRAFT record를 APPROVED로 비교 갱신하고 승인자와 승인 시각을 기록한다.

        actor 권한 판정은 호출 service의 책임이며 이 계층은 전달받은 ``approved_by``를
        감사 속성으로 보존한다. 갱신된 :class:`ContextRecord`를 반환하며 누락·상태 불일치는
        :class:`ContextRegistryConflict`, DB 장애는 :class:`ContextRegistryUnavailable`이다.
        """
        return await self._transition_record(record_id, "DRAFT", "APPROVED", approved_by)
    async def deprecate_record(self, record_id: UUID) -> ContextRecord:
        """APPROVED record만 DEPRECATED로 비교 갱신하고 기존 승인 귀속은 보존한다.

        호출 service가 폐기 권한을 확인해야 하며 갱신된 :class:`ContextRecord`를 반환한다. 누락·상태 경합은
        :class:`ContextRegistryConflict`, DB 장애는 :class:`ContextRegistryUnavailable`로
        구분한다.
        """
        return await self._transition_record(record_id, "APPROVED", "DEPRECATED", None)

    async def _transition_record(
        self, record_id: UUID, expected: str, target: str, approved_by: UUID | None
    ) -> ContextRecord:
        try:
            async with self._sessionmaker.begin() as session:
                row = (await session.execute(
                    text(
                        """
                        UPDATE context.context_records
                        SET status = CAST(:target AS varchar),
                            approved_by = COALESCE(:approved_by, approved_by),
                            approved_at = CASE WHEN CAST(:target AS varchar) = 'APPROVED'
                                               THEN now() ELSE approved_at END
                        WHERE context_record_id = :id
                          AND status = CAST(:expected AS varchar)
                        RETURNING *
                        """
                    ),
                    {
                        "id": record_id,
                        "expected": expected,
                        "target": target,
                        "approved_by": approved_by,
                    },
                )).mappings().one_or_none()
                if row is None:
                    raise ContextRegistryConflict(f"record 상태는 {expected}여야 합니다.")
                return ContextRecord.from_row(row)
        except ContextRegistryConflict:
            raise
        except SQLAlchemyError as error:
            raise ContextRegistryUnavailable("Context Registry 저장소를 사용할 수 없습니다.") from error

    async def create_release(self, command: CreateContextRelease) -> ContextRelease:
        """승인 record UUID·checksum 집합을 정확히 검증해 DRAFT release를 생성한다.

        정렬 가능한 canonical 참조로 release hash를 계산하며 같은 idempotency key와 같은
        hash는 기존 행을, 새 입력은 DRAFT :class:`ContextRelease`를 반환한다. 참조 불일치·key 재사용·version 중복은
        :class:`ContextRegistryConflict`, DB 장애는 :class:`ContextRegistryUnavailable`이다.
        """
        refs = [item.model_dump(mode="json") for item in command.included_records]
        checksum = canonical_checksum(refs)
        try:
            async with self._sessionmaker.begin() as session:
                approved = (await session.execute(
                    text(
                        """
                        SELECT context_record_id::text, checksum
                        FROM context.context_records
                        WHERE status = 'APPROVED'
                          AND context_record_id = ANY(CAST(:ids AS uuid[]))
                        """
                    ),
                    {"ids": [str(item.context_record_id) for item in command.included_records]},
                )).all()
                actual = {(str(item[0]), item[1]) for item in approved}
                expected = {(str(item.context_record_id), item.checksum) for item in command.included_records}
                if actual != expected:
                    raise ContextRegistryConflict("승인된 record와 checksum이 정확히 일치해야 합니다.")
                row = (await session.execute(
                    text(
                        """
                        INSERT INTO context.context_releases
                            (context_release_id, release_key, version_no,
                             included_record_refs_json, status, release_hash,
                             rollback_release_id, idempotency_key)
                        VALUES (:id, :key, :version, CAST(:refs AS jsonb), 'DRAFT',
                                :checksum, :rollback_id, :idempotency_key)
                        ON CONFLICT (idempotency_key) DO NOTHING
                        RETURNING *
                        """
                    ),
                    {
                        "id": uuid4(),
                        "key": command.release_key,
                        "version": command.version_no,
                        "refs": _json(refs),
                        "checksum": checksum,
                        "rollback_id": command.rollback_release_id,
                        "idempotency_key": command.idempotency_key,
                    },
                )).mappings().one_or_none()
                if row is None:
                    row = (await session.execute(
                        text("SELECT * FROM context.context_releases WHERE idempotency_key = :key"),
                        {"key": command.idempotency_key},
                    )).mappings().one()
                    row = self._same_or_conflict(row, "release_hash", checksum, "release")
                return ContextRelease.from_row(row)
        except ContextRegistryConflict:
            raise
        except IntegrityError as error:
            raise ContextRegistryConflict("같은 Context release version이 이미 존재합니다.") from error
        except SQLAlchemyError as error:
            raise ContextRegistryUnavailable("Context Registry 저장소를 사용할 수 없습니다.") from error

    async def publish_release(self, release_id: UUID, published_by: UUID) -> ContextRelease:
        """DRAFT release를 PUBLISHED로 비교 갱신하고 발행자와 발행 시각을 기록한다.

        actor 권한 판정은 호출 service가 끝낸 ``published_by``를 받는다는 계약이다. 누락이나
        상태 경합은 :class:`ContextRegistryConflict`, DB 장애는
        :class:`ContextRegistryUnavailable`로 구분한다.
        성공하면 갱신된 :class:`ContextRelease`를 반환한다.
        """
        return await self._transition_release(release_id, "DRAFT", "PUBLISHED", published_by)

    async def retire_release(self, release_id: UUID) -> ContextRelease:
        """PUBLISHED release만 RETIRED로 비교 갱신하고 기존 발행 귀속을 보존한다.

        호출 service가 폐기 권한을 확인해야 하며 갱신된 :class:`ContextRelease`를 반환한다. 누락이나 상태 경합은
        :class:`ContextRegistryConflict`, DB 장애는 :class:`ContextRegistryUnavailable`로
        구분한다.
        """
        return await self._transition_release(release_id, "PUBLISHED", "RETIRED", None)

    async def _transition_release(
        self, release_id: UUID, expected: str, target: str, published_by: UUID | None
    ) -> ContextRelease:
        try:
            async with self._sessionmaker.begin() as session:
                row = (await session.execute(
                    text(
                        """
                        UPDATE context.context_releases
                        SET status = CAST(:target AS varchar),
                            published_by = COALESCE(:published_by, published_by),
                            published_at = CASE WHEN CAST(:target AS varchar) = 'PUBLISHED'
                                                THEN now() ELSE published_at END
                        WHERE context_release_id = :id
                          AND status = CAST(:expected AS varchar)
                        RETURNING *
                        """
                    ),
                    {
                        "id": release_id,
                        "expected": expected,
                        "target": target,
                        "published_by": published_by,
                    },
                )).mappings().one_or_none()
                if row is None:
                    raise ContextRegistryConflict(f"release 상태는 {expected}여야 합니다.")
                return ContextRelease.from_row(row)
        except ContextRegistryConflict:
            raise
        except SQLAlchemyError as error:
            raise ContextRegistryUnavailable("Context Registry 저장소를 사용할 수 없습니다.") from error

    async def create_package(self, command: CreateContextPackage) -> ContextPackage:
        """PUBLISHED release에 runtime scope·semantic 자산을 묶은 Context package를 생성한다.

        payload 전체의 canonical checksum으로 idempotency 재시도를 검증한다. 미발행 release,
        같은 key의 다른 payload, request별 package 중복은
        :class:`ContextRegistryConflict`, DB 장애는 :class:`ContextRegistryUnavailable`로
        반환한다. 성공하면 새 항목 또는 동일 checksum의 기존 :class:`ContextPackage`를 반환한다.
        """
        payload = {
            "user_scope": command.user_scope,
            "assets": command.assets,
            "metrics": command.metrics,
            "joins": command.joins,
            "policies": command.policies,
            "dataset_count": command.dataset_count,
            "column_count": command.column_count,
            "token_count": command.token_count,
        }
        checksum = canonical_checksum(payload)
        try:
            async with self._sessionmaker.begin() as session:
                release_status = (await session.execute(
                    text(
                        "SELECT status FROM context.context_releases "
                        "WHERE context_release_id = :id"
                    ),
                    {"id": command.context_release_id},
                )).scalar_one_or_none()
                if release_status != "PUBLISHED":
                    raise ContextRegistryConflict("PUBLISHED release만 package에 연결할 수 있습니다.")
                row = (await session.execute(
                    text(
                        """
                        INSERT INTO context.context_packages
                            (context_package_id, request_id, context_release_id,
                             user_scope_json, assets_json, metrics_json, joins_json,
                             policies_json, dataset_count, column_count, token_count,
                             package_hash, idempotency_key)
                        VALUES (:id, :request_id, :release_id, CAST(:scope AS jsonb),
                                CAST(:assets AS jsonb), CAST(:metrics AS jsonb),
                                CAST(:joins AS jsonb), CAST(:policies AS jsonb),
                                :datasets, :columns, :tokens, :checksum, :idempotency_key)
                        ON CONFLICT (idempotency_key) DO NOTHING
                        RETURNING *
                        """
                    ),
                    {
                        "id": uuid4(),
                        "request_id": command.request_id,
                        "release_id": command.context_release_id,
                        "scope": _json(command.user_scope),
                        "assets": _json(command.assets),
                        "metrics": _json(command.metrics),
                        "joins": _json(command.joins),
                        "policies": _json(command.policies),
                        "datasets": command.dataset_count,
                        "columns": command.column_count,
                        "tokens": command.token_count,
                        "checksum": checksum,
                        "idempotency_key": command.idempotency_key,
                    },
                )).mappings().one_or_none()
                if row is None:
                    row = (await session.execute(
                        text("SELECT * FROM context.context_packages WHERE idempotency_key = :key"),
                        {"key": command.idempotency_key},
                    )).mappings().one()
                    row = self._same_or_conflict(row, "package_hash", checksum, "package")
                return ContextPackage.from_row(row)
        except ContextRegistryConflict:
            raise
        except IntegrityError as error:
            raise ContextRegistryConflict("request에는 Context package 하나만 연결할 수 있습니다.") from error
        except SQLAlchemyError as error:
            raise ContextRegistryUnavailable("Context Registry 저장소를 사용할 수 없습니다.") from error
