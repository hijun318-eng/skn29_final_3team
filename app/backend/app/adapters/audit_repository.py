from __future__ import annotations

from functools import lru_cache
from datetime import datetime
from uuid import UUID

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import SQLAlchemyError


@lru_cache(maxsize=None)
def _engine(database_url: str) -> Engine:
    return create_engine(database_url, pool_pre_ping=True)


def _uuid(value: str | UUID) -> UUID:
    try:
        return UUID(str(value))
    except (TypeError, ValueError, AttributeError) as error:
        raise ValueError("request_id는 UUID 형식이어야 합니다.") from error


class AuditRepositoryUnavailable(RuntimeError):
    pass


class PostgresAuditRepository:
    """요청 소유자에게 원문 payload를 제외한 실행 metadata만 제공한다."""

    def __init__(self, database_url: str, owner_id: UUID) -> None:
        self._engine = _engine(database_url)
        self._owner_id = owner_id

    def search(
        self,
        request_id: str | UUID | None = None,
        status: str | None = None,
        started_from: datetime | None = None,
        started_to: datetime | None = None,
    ) -> list[dict]:
        filters = []
        parameters = {"owner_id": self._owner_id}
        if request_id is not None:
            filters.append("r.request_id = :request_id")
            parameters["request_id"] = _uuid(request_id)
        if status:
            filters.append("r.status = :status")
            parameters["status"] = status
        if started_from is not None:
            filters.append("r.started_at >= :started_from")
            parameters["started_from"] = started_from
        if started_to is not None:
            filters.append("r.started_at <= :started_to")
            parameters["started_to"] = started_to
        where = "".join(f" AND {item}" for item in filters)
        try:
            with self._engine.connect() as connection:
                rows = connection.execute(
                    text(
                        f"""
                        SELECT r.request_id, r.user_id, r.user_role, r.request_type,
                               r.status, r.error_type, r.trace_id,
                               r.started_at, r.completed_at
                        FROM chat.analysis_requests r
                        WHERE r.user_id = :owner_id {where}
                        ORDER BY r.started_at DESC, r.request_id
                        LIMIT 100
                        """
                    ),
                    parameters,
                ).mappings()
                return [dict(row) for row in rows]
        except SQLAlchemyError as error:
            raise AuditRepositoryUnavailable("감사 저장소를 사용할 수 없습니다.") from error

    def get(self, request_id: str | UUID) -> dict:
        request_uuid = _uuid(request_id)
        try:
            with self._engine.connect() as connection:
                row = connection.execute(
                    text(
                        """
                        SELECT r.request_id, r.user_id, r.user_role, r.request_type,
                               r.status, r.error_type, r.trace_id,
                               r.started_at, r.completed_at,
                               d.definition_id, l.definition_version, d.status AS definition_status,
                               r.context_release_id, cr.release_key,
                               cr.version_no AS release_version, cr.release_hash,
                               r.context_package_id, cp.package_hash,
                               r.sql_policy_version,
                               ae.details_json_redacted AS access_details,
                               mv.model_version_id, mv.model_role, mv.model_name,
                               mv.model_revision, mv.runtime_name,
                               q.trino_query_id, q.generation_mode,
                               q.validation_status, q.execution_status, q.duration_ms,
                               q.source_urns_json,
                               a.artifact_id, a.artifact_type, a.freshness_status,
                               a.status AS artifact_status, a.artifact_checksum,
                               a.evidence_json
                        FROM chat.analysis_requests r
                        LEFT JOIN analysis_v1.analysis_run_links l
                          ON l.request_id = r.request_id
                        LEFT JOIN analysis_v1.analysis_definitions d
                          ON d.definition_id = l.definition_id
                         AND d.version = l.definition_version
                        LEFT JOIN context.context_releases cr
                          ON cr.context_release_id = r.context_release_id
                        LEFT JOIN context.context_packages cp
                          ON cp.context_package_id = r.context_package_id
                        LEFT JOIN LATERAL (
                            SELECT details_json_redacted
                            FROM governance.audit_events
                            WHERE request_id = r.request_id
                              AND action_code IN (
                                  'ANALYSIS_ACCESS_STARTED',
                                  'ANALYSIS_ACCESS_COMPLETED',
                                  'ANALYSIS_ACCESS_DENIED'
                              )
                            ORDER BY created_at DESC, audit_event_id DESC LIMIT 1
                        ) ae ON true
                        LEFT JOIN model.model_versions mv
                          ON mv.model_version_id = r.sql_generation_model_id
                        LEFT JOIN LATERAL (
                            SELECT trino_query_id, generation_mode, validation_status,
                                   execution_status, duration_ms, query_execution_id,
                                   source_urns_json
                            FROM query.query_executions
                            WHERE request_id = r.request_id
                            ORDER BY attempt_no DESC LIMIT 1
                        ) q ON true
                        LEFT JOIN LATERAL (
                            SELECT artifact_id, artifact_type, freshness_status,
                                   status, artifact_checksum, evidence_json
                            FROM artifact.analysis_artifacts
                            WHERE request_id = r.request_id
                            ORDER BY artifact_id LIMIT 1
                        ) a ON true
                        WHERE r.request_id = :request_id AND r.user_id = :owner_id
                        """
                    ),
                    {"request_id": request_uuid, "owner_id": self._owner_id},
                ).mappings().one_or_none()
                if row is None:
                    raise KeyError("감사 Trace를 찾을 수 없습니다.")

                transitions = connection.execute(
                    text(
                        """
                        SELECT sequence_no AS sequence, from_status, to_status, created_at
                        FROM chat.analysis_state_transitions
                        WHERE request_id = :request_id
                        ORDER BY sequence_no
                        """
                    ),
                    {"request_id": request_uuid},
                ).mappings()
                reports = connection.execute(
                    text(
                        """
                        SELECT rr.definition_id, rr.definition_version, rr.run_id, rr.status
                        FROM report_v1.report_block_runs br
                        JOIN report_v1.report_runs rr ON rr.run_id = br.run_id
                        JOIN report_v1.report_definitions rd
                          ON rd.definition_id = rr.definition_id
                        WHERE br.artifact_id = :artifact_id AND rd.owner_id = :owner_id
                        ORDER BY rr.created_at, rr.run_id
                        """
                    ),
                    {"artifact_id": row["artifact_id"], "owner_id": self._owner_id},
                ).mappings() if row["artifact_id"] else ()
                return self._detail(dict(row), transitions, reports)
        except KeyError:
            raise
        except SQLAlchemyError as error:
            raise AuditRepositoryUnavailable("감사 저장소를 사용할 수 없습니다.") from error

    @staticmethod
    def _detail(row: dict, transitions, reports) -> dict:
        result = {
            key: row[key]
            for key in (
                "request_id", "user_id", "user_role", "request_type", "status",
                "error_type", "trace_id", "started_at", "completed_at",
            )
        }
        result["transitions"] = [dict(item) for item in transitions]
        result["analysis_definition"] = None if row["definition_id"] is None else {
            "definition_id": row["definition_id"],
            "version": row["definition_version"],
            "status": row["definition_status"],
        }
        result["context"] = {
            "release_id": row["context_release_id"],
            "release_key": row["release_key"],
            "release_version": row["release_version"],
            "release_hash": row["release_hash"],
            "package_id": row["context_package_id"],
            "package_hash": row["package_hash"],
        }
        access = row.get("access_details") or {}
        result["policy"] = {
            "sql_policy_version": row["sql_policy_version"],
            "policy_version": access.get("policy_version") or row["sql_policy_version"],
            "entitlement_hash": access.get("entitlement_hash"),
        }
        result["access"] = {
            "access_profile": access.get("access_profile"),
            "allowed_domains": list(access.get("allowed_domains") or []),
            "datahub_actor": access.get("datahub_actor"),
            "allowed_urns": list(access.get("allowed_urns") or []),
            "trino_role": access.get("trino_role"),
            "datahub_search_attempted": bool(
                access.get("datahub_search_attempted", False)
            ),
            "trino_execution_attempted": bool(
                access.get("trino_execution_attempted", False)
            ),
        }
        result["model"] = None if row["model_version_id"] is None else {
            key: row[key]
            for key in (
                "model_version_id", "model_role", "model_name",
                "model_revision", "runtime_name",
            )
        }
        result["query"] = None if row["generation_mode"] is None else {
            "query_id": row["trino_query_id"],
            "generation_mode": row["generation_mode"],
            "validation_status": row["validation_status"],
            "execution_status": row["execution_status"],
            "duration_ms": row["duration_ms"],
            "source_urns": list(row["source_urns_json"] or []),
        }
        masking = (row.get("evidence_json") or {}).get("masking") or {}
        result["artifact"] = None if row["artifact_id"] is None else {
            "artifact_id": row["artifact_id"],
            "artifact_type": row["artifact_type"],
            "freshness_status": row["freshness_status"],
            "status": row["artifact_status"],
            "artifact_checksum": row["artifact_checksum"],
            "masking": {
                "applied": bool(masking.get("applied", False)),
                "fields": list(masking.get("fields") or []),
            },
        }
        result["reports"] = [dict(item) for item in reports]
        return result
