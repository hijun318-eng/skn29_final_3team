from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from uuid import UUID, uuid4

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from app.context_registry_contracts import (
    ContextPackage,
    ContextRecord,
    ContextRelease,
    CreateContextPackage,
    CreateContextRecord,
    CreateContextRelease,
)
class ContextRegistryConflict(RuntimeError):
    """409에 대응하는 Context Registry 도메인 충돌."""

class ContextRegistryUnavailable(RuntimeError):
    pass

@dataclass(frozen=True)
class PublishedContextRelease:
    context_release_id: str
    release_key: str
    version_no: int
    release_hash: str
    time_policy_id: str
    timezone: str
    calendar_id: str

@lru_cache(maxsize=None)
def _engine(database_url: str) -> Engine:
    return create_engine(database_url, pool_pre_ping=True)

def canonical_checksum(value: object) -> str:
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
    def __init__(self, database_url: str) -> None:
        self._engine = _engine(database_url)

    def resolve_published_release(
        self, release_key: str, as_of: date
    ) -> PublishedContextRelease:
        """요청 시점에 유효한 PUBLISHED release와 단일 시간 정책을 반환한다."""
        if not release_key.strip():
            raise ContextRegistryConflict("CONTEXT_RELEASE_KEY가 필요합니다.")
        try:
            with self._engine.connect() as connection:
                release = connection.execute(
                    text(
                        """
                        SELECT context_release_id, release_key, version_no,
                               release_hash, included_record_refs_json
                        FROM context.context_releases
                        WHERE release_key = :key AND status = 'PUBLISHED'
                        ORDER BY version_no DESC
                        LIMIT 1
                        """
                    ),
                    {"key": release_key},
                ).mappings().one_or_none()
                if release is None:
                    raise ContextRegistryConflict("PUBLISHED Context release가 없습니다.")
                refs = release["included_record_refs_json"]
                if not isinstance(refs, list) or not refs:
                    raise ContextRegistryConflict("Context release record가 비어 있습니다.")
                records = connection.execute(
                    text(
                        """
                        SELECT context_record_id::text AS context_record_id,
                               record_type, record_key, version_no, payload_json,
                               checksum
                        FROM context.context_records
                        WHERE status = 'APPROVED'
                          AND valid_from <= :as_of
                          AND (valid_to IS NULL OR valid_to > :as_of)
                          AND context_record_id = ANY(CAST(:ids AS uuid[]))
                        """
                    ),
                    {
                        "as_of": as_of,
                        "ids": [str(item.get("context_record_id")) for item in refs],
                    },
                ).mappings().all()
                expected = {
                    (str(item.get("context_record_id")), str(item.get("checksum")))
                    for item in refs
                }
                actual = {(row["context_record_id"], row["checksum"]) for row in records}
                if actual != expected:
                    raise ContextRegistryConflict(
                        "승인된 Context record와 release checksum이 일치하지 않습니다."
                    )
                time_policies = [row for row in records if row["record_type"] == "TIME_POLICY"]
                if len(time_policies) != 1:
                    raise ContextRegistryConflict("유효한 TIME_POLICY가 정확히 하나 필요합니다.")
                policy = time_policies[0]
                payload = policy["payload_json"]
                timezone = payload.get("timezone") if isinstance(payload, dict) else None
                calendar_id = payload.get("calendar_id") if isinstance(payload, dict) else None
                if not isinstance(timezone, str) or not isinstance(calendar_id, str):
                    raise ContextRegistryConflict("TIME_POLICY timezone·calendar가 필요합니다.")
                return PublishedContextRelease(
                    context_release_id=str(release["context_release_id"]),
                    release_key=release["release_key"],
                    version_no=release["version_no"],
                    release_hash=release["release_hash"],
                    time_policy_id=(
                        f"{policy['record_key']}:v{policy['version_no']}:{policy['checksum']}"
                    ),
                    timezone=timezone,
                    calendar_id=calendar_id,
                )
        except ContextRegistryConflict:
            raise
        except SQLAlchemyError as error:
            raise ContextRegistryUnavailable("Context Registry 저장소를 사용할 수 없습니다.") from error

    @staticmethod
    def _same_or_conflict(row, checksum_field: str, checksum: str, kind: str):
        if row[checksum_field] != checksum:
            raise ContextRegistryConflict(f"같은 idempotency key의 {kind} payload가 다릅니다.")
        return row

    def create_record(self, command: CreateContextRecord) -> ContextRecord:
        checksum = canonical_checksum(command.payload)
        record_id = uuid4()
        try:
            with self._engine.begin() as connection:
                row = connection.execute(
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
                ).mappings().one_or_none()
                if row is None:
                    row = connection.execute(
                        text("SELECT * FROM context.context_records WHERE idempotency_key = :key"),
                        {"key": command.idempotency_key},
                    ).mappings().one()
                    row = self._same_or_conflict(row, "checksum", checksum, "record")
                return ContextRecord.from_row(row)
        except ContextRegistryConflict:
            raise
        except IntegrityError as error:
            raise ContextRegistryConflict("같은 Context record version이 이미 존재합니다.") from error
        except SQLAlchemyError as error:
            raise ContextRegistryUnavailable("Context Registry 저장소를 사용할 수 없습니다.") from error

    def approve_record(self, record_id: UUID, approved_by: UUID) -> ContextRecord:
        return self._transition_record(record_id, "DRAFT", "APPROVED", approved_by)
    def deprecate_record(self, record_id: UUID) -> ContextRecord:
        return self._transition_record(record_id, "APPROVED", "DEPRECATED", None)

    def _transition_record(
        self, record_id: UUID, expected: str, target: str, approved_by: UUID | None
    ) -> ContextRecord:
        try:
            with self._engine.begin() as connection:
                row = connection.execute(
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
                ).mappings().one_or_none()
                if row is None:
                    raise ContextRegistryConflict(f"record 상태는 {expected}여야 합니다.")
                return ContextRecord.from_row(row)
        except ContextRegistryConflict:
            raise
        except SQLAlchemyError as error:
            raise ContextRegistryUnavailable("Context Registry 저장소를 사용할 수 없습니다.") from error

    def create_release(self, command: CreateContextRelease) -> ContextRelease:
        refs = [item.model_dump(mode="json") for item in command.included_records]
        checksum = canonical_checksum(refs)
        try:
            with self._engine.begin() as connection:
                approved = connection.execute(
                    text(
                        """
                        SELECT context_record_id::text, checksum
                        FROM context.context_records
                        WHERE status = 'APPROVED'
                          AND context_record_id = ANY(CAST(:ids AS uuid[]))
                        """
                    ),
                    {"ids": [str(item.context_record_id) for item in command.included_records]},
                ).all()
                actual = {(str(item[0]), item[1]) for item in approved}
                expected = {(str(item.context_record_id), item.checksum) for item in command.included_records}
                if actual != expected:
                    raise ContextRegistryConflict("승인된 record와 checksum이 정확히 일치해야 합니다.")
                row = connection.execute(
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
                ).mappings().one_or_none()
                if row is None:
                    row = connection.execute(
                        text("SELECT * FROM context.context_releases WHERE idempotency_key = :key"),
                        {"key": command.idempotency_key},
                    ).mappings().one()
                    row = self._same_or_conflict(row, "release_hash", checksum, "release")
                return ContextRelease.from_row(row)
        except ContextRegistryConflict:
            raise
        except IntegrityError as error:
            raise ContextRegistryConflict("같은 Context release version이 이미 존재합니다.") from error
        except SQLAlchemyError as error:
            raise ContextRegistryUnavailable("Context Registry 저장소를 사용할 수 없습니다.") from error

    def publish_release(self, release_id: UUID, published_by: UUID) -> ContextRelease:
        return self._transition_release(release_id, "DRAFT", "PUBLISHED", published_by)

    def retire_release(self, release_id: UUID) -> ContextRelease:
        return self._transition_release(release_id, "PUBLISHED", "RETIRED", None)

    def _transition_release(
        self, release_id: UUID, expected: str, target: str, published_by: UUID | None
    ) -> ContextRelease:
        try:
            with self._engine.begin() as connection:
                row = connection.execute(
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
                ).mappings().one_or_none()
                if row is None:
                    raise ContextRegistryConflict(f"release 상태는 {expected}여야 합니다.")
                return ContextRelease.from_row(row)
        except ContextRegistryConflict:
            raise
        except SQLAlchemyError as error:
            raise ContextRegistryUnavailable("Context Registry 저장소를 사용할 수 없습니다.") from error

    def create_package(self, command: CreateContextPackage) -> ContextPackage:
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
            with self._engine.begin() as connection:
                release_status = connection.execute(
                    text(
                        "SELECT status FROM context.context_releases "
                        "WHERE context_release_id = :id"
                    ),
                    {"id": command.context_release_id},
                ).scalar_one_or_none()
                if release_status != "PUBLISHED":
                    raise ContextRegistryConflict("PUBLISHED release만 package에 연결할 수 있습니다.")
                row = connection.execute(
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
                ).mappings().one_or_none()
                if row is None:
                    row = connection.execute(
                        text("SELECT * FROM context.context_packages WHERE idempotency_key = :key"),
                        {"key": command.idempotency_key},
                    ).mappings().one()
                    row = self._same_or_conflict(row, "package_hash", checksum, "package")
                return ContextPackage.from_row(row)
        except ContextRegistryConflict:
            raise
        except IntegrityError as error:
            raise ContextRegistryConflict("request에는 Context package 하나만 연결할 수 있습니다.") from error
        except SQLAlchemyError as error:
            raise ContextRegistryUnavailable("Context Registry 저장소를 사용할 수 없습니다.") from error
