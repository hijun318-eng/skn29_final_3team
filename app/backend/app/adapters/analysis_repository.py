from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timezone
from functools import lru_cache
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.analysis_contracts import ANALYSIS_PERSISTENCE_VERSION
from app.contracts import AnalysisResponse, AnalysisStatus, RequestContext


_EMAIL = re.compile(r"\b[^\s@]+@[^\s@]+\.[^\s@]+\b")
_PHONE = re.compile(r"(?<!\d)(?:\d[ -]?){9,12}(?!\d)")


@lru_cache(maxsize=None)
def _engine(database_url: str) -> Engine:
    return create_engine(database_url, pool_pre_ping=True)


def _uuid(value: str | UUID, field: str) -> UUID:
    try:
        return UUID(str(value))
    except (TypeError, ValueError, AttributeError) as error:
        raise ValueError(f"{field}는 UUID 형식이어야 합니다.") from error


def _redact_question(question: str) -> str:
    return _PHONE.sub("[REDACTED_PHONE]", _EMAIL.sub("[REDACTED_EMAIL]", question)).strip()


def _hash(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def _parameter_types(parameters: dict[str, object]) -> dict[str, str]:
    types = {}
    for name, value in parameters.items():
        if value is None:
            types[name] = "null"
        elif isinstance(value, bool):
            types[name] = "boolean"
        elif isinstance(value, (int, float)):
            types[name] = "number"
        else:
            types[name] = "string"
    return types


class AnalysisRepositoryUnavailable(RuntimeError):
    pass


class PostgresAnalysisRepository:
    """User-owned Definition과 기존 request→query→artifact를 연결한다."""

    def __init__(self, database_url: str, owner_id: UUID) -> None:
        self._engine = _engine(database_url)
        self._owner_id = owner_id

    @staticmethod
    def _definition(row, *, replay: bool = False) -> dict[str, Any]:
        parameters = dict(row["parameters"])
        definition = {
            "contract_version": ANALYSIS_PERSISTENCE_VERSION,
            "definition_id": row["definition_id"],
            "version": row["version"],
            "status": "approved",
            "title": row["title"],
            "parameter_types": _parameter_types(parameters),
            "created_at": row["created_at"],
        }
        if replay:
            definition.update(question=row["question_text_redacted"], parameters=parameters)
        return definition

    def create_definition(
        self,
        title: str,
        question: str,
        parameters: dict[str, object],
    ) -> dict[str, Any]:
        definition_id = uuid4()
        redacted = _redact_question(question)
        if not redacted:
            raise ValueError("redacted question은 비어 있을 수 없습니다.")
        try:
            with self._engine.begin() as connection:
                row = connection.execute(
                    text(
                        """
                        INSERT INTO analysis_v1.analysis_definitions
                            (definition_id, version, owner_id, title,
                             question_text_redacted, parameters_json, parameter_hash,
                             is_saved)
                        VALUES (:definition_id, 1, :owner_id, :title,
                                :question, CAST(:parameters AS jsonb), :parameter_hash,
                                true)
                        RETURNING definition_id, version, title, question_text_redacted,
                                  parameters_json AS parameters, created_at
                        """
                    ),
                    {
                        "definition_id": definition_id,
                        "owner_id": self._owner_id,
                        "title": title.strip(),
                        "question": redacted,
                        "parameters": json.dumps(parameters, ensure_ascii=False),
                        "parameter_hash": _hash(parameters),
                    },
                ).mappings().one()
        except SQLAlchemyError as error:
            raise AnalysisRepositoryUnavailable("Analysis 저장소를 사용할 수 없습니다.") from error
        return self._definition(row)

    def get_definition(
        self, definition_id: str | UUID, *, replay: bool = False
    ) -> dict[str, Any]:
        try:
            with self._engine.connect() as connection:
                row = connection.execute(
                    text(
                        """
                        SELECT definition_id, version, title, question_text_redacted,
                               parameters_json AS parameters, created_at
                        FROM analysis_v1.analysis_definitions
                        WHERE definition_id = :definition_id
                          AND owner_id = :owner_id
                          AND is_saved
                        ORDER BY version DESC LIMIT 1
                        """
                    ),
                    {
                        "definition_id": _uuid(definition_id, "definition_id"),
                        "owner_id": self._owner_id,
                    },
                ).mappings().one_or_none()
        except SQLAlchemyError as error:
            raise AnalysisRepositoryUnavailable("Analysis 저장소를 사용할 수 없습니다.") from error
        if row is None:
            raise KeyError("Analysis Definition을 찾을 수 없습니다.")
        return self._definition(row, replay=replay)

    def list_definitions(self) -> list[dict[str, Any]]:
        try:
            with self._engine.connect() as connection:
                rows = connection.execute(
                    text(
                        """
                        SELECT definition_id, version, title, question_text_redacted,
                               parameters_json AS parameters, created_at
                        FROM analysis_v1.analysis_definitions
                        WHERE owner_id = :owner_id AND is_saved
                        ORDER BY created_at DESC, definition_id DESC
                        """
                    ),
                    {"owner_id": self._owner_id},
                ).mappings()
                return [self._definition(row) for row in rows]
        except SQLAlchemyError as error:
            raise AnalysisRepositoryUnavailable("Analysis 저장소를 사용할 수 없습니다.") from error

    def begin_run(
        self,
        definition: dict[str, Any],
        context: RequestContext,
        as_of: date,
        idempotency_key: str,
        parameters: dict[str, object] | None = None,
    ) -> tuple[UUID, bool]:
        definition_id = _uuid(definition["definition_id"], "definition_id")
        try:
            with self._engine.begin() as connection:
                existing = connection.execute(
                    text(
                        """
                        SELECT l.request_id
                        FROM analysis_v1.analysis_run_links l
                        JOIN analysis_v1.analysis_definitions d
                          ON d.definition_id = l.definition_id
                         AND d.version = l.definition_version
                        WHERE l.definition_id = :definition_id
                          AND l.definition_version = :version
                          AND l.idempotency_key = :idempotency_key
                          AND d.owner_id = :owner_id
                        """
                    ),
                    {
                        "definition_id": definition_id,
                        "version": definition["version"],
                        "idempotency_key": idempotency_key,
                        "owner_id": self._owner_id,
                    },
                ).scalar_one_or_none()
                if existing:
                    return UUID(str(existing)), False
                connection.execute(
                    text(
                        """
                        INSERT INTO chat.analysis_requests
                            (request_id, request_type, user_id, user_role,
                             question_text_redacted, question_hash, ambiguity_status,
                             sql_policy_version, status, trace_id, started_at)
                        VALUES (:request_id, 'CHAT', :user_id, :user_role,
                                :question, :question_hash, 'CLEAR',
                                'policy-v1', 'RECEIVED', :trace_id, :started_at)
                        """
                    ),
                    {
                        "request_id": context.request_id,
                        "user_id": self._owner_id,
                        "user_role": context.role.value,
                        "question": definition["question"],
                        "question_hash": _hash(definition["question"]),
                        "trace_id": context.trace_id,
                        "started_at": datetime.now(timezone.utc),
                    },
                )
                connection.execute(
                    text(
                        """
                        INSERT INTO analysis_v1.analysis_run_links
                            (definition_id, definition_version, request_id,
                             idempotency_key, as_of, timezone_name,
                             parameters_json, parameter_hash)
                        VALUES (:definition_id, :version, :request_id,
                                :idempotency_key, :as_of, :timezone,
                                CAST(:parameters AS jsonb), :parameter_hash)
                        """
                    ),
                    {
                        "definition_id": definition_id,
                        "version": definition["version"],
                        "request_id": context.request_id,
                        "idempotency_key": idempotency_key,
                        "as_of": as_of,
                        "timezone": context.timezone,
                        "parameters": json.dumps(
                            parameters if parameters is not None else definition["parameters"],
                            ensure_ascii=False,
                        ),
                        "parameter_hash": _hash(
                            parameters if parameters is not None else definition["parameters"]
                        ),
                    },
                )
                return context.request_id, True
        except IntegrityError as error:
            try:
                existing = self._existing_run(definition_id, definition["version"], idempotency_key)
            except (KeyError, SQLAlchemyError) as lookup_error:
                raise AnalysisRepositoryUnavailable(
                    "Analysis 실행을 예약할 수 없습니다."
                ) from lookup_error
            return existing, False
        except SQLAlchemyError as error:
            raise AnalysisRepositoryUnavailable("Analysis 저장소를 사용할 수 없습니다.") from error

    def begin_request(
        self,
        question: str,
        parameters: dict[str, object],
        context: RequestContext,
    ) -> UUID:
        redacted = _redact_question(question)
        if not redacted:
            raise ValueError("redacted question은 비어 있을 수 없습니다.")
        definition_id = uuid4()
        try:
            with self._engine.begin() as connection:
                connection.execute(
                    text(
                        """
                        INSERT INTO analysis_v1.analysis_definitions
                            (definition_id, version, owner_id, title,
                             question_text_redacted, parameters_json, parameter_hash,
                             is_saved)
                        VALUES (:definition_id, 1, :owner_id, :title,
                                :question, CAST(:parameters AS jsonb), :parameter_hash,
                                false)
                        """
                    ),
                    {
                        "definition_id": definition_id,
                        "owner_id": self._owner_id,
                        "title": "Analysis request",
                        "question": redacted,
                        "parameters": json.dumps(parameters),
                        "parameter_hash": _hash(parameters),
                    },
                )
                connection.execute(
                    text(
                        """
                        INSERT INTO chat.analysis_requests
                            (request_id, request_type, user_id, user_role,
                             question_text_redacted, question_hash, ambiguity_status,
                             sql_policy_version, status, trace_id, started_at)
                        VALUES (:request_id, 'CHAT', :user_id, :user_role,
                                :question, :question_hash, 'CLEAR',
                                'policy-v1', 'RECEIVED', :trace_id, :started_at)
                        """
                    ),
                    {
                        "request_id": context.request_id,
                        "user_id": self._owner_id,
                        "user_role": context.role.value,
                        "question": redacted,
                        "question_hash": _hash(redacted),
                        "trace_id": context.trace_id,
                        "started_at": datetime.now(timezone.utc),
                    },
                )
                connection.execute(
                    text(
                        """
                        INSERT INTO analysis_v1.analysis_run_links
                            (definition_id, definition_version, request_id,
                             idempotency_key, as_of, timezone_name,
                             parameters_json, parameter_hash)
                        VALUES (:definition_id, 1, :request_id,
                                :idempotency_key, :as_of, :timezone,
                                CAST(:parameters AS jsonb), :parameter_hash)
                        """
                    ),
                    {
                        "definition_id": definition_id,
                        "request_id": context.request_id,
                        "idempotency_key": str(context.request_id),
                        "as_of": context.as_of,
                        "timezone": context.timezone,
                        "parameters": json.dumps(parameters, ensure_ascii=False),
                        "parameter_hash": _hash(parameters),
                    },
                )
            return context.request_id
        except IntegrityError as error:
            raise ValueError("같은 Analysis request가 이미 존재합니다.") from error
        except SQLAlchemyError as error:
            raise AnalysisRepositoryUnavailable("Analysis 요청을 저장할 수 없습니다.") from error

    def _existing_run(
        self,
        definition_id: UUID,
        version: int,
        idempotency_key: str,
    ) -> UUID:
        with self._engine.connect() as connection:
            request_id = connection.execute(
                text(
                    """
                    SELECT l.request_id
                    FROM analysis_v1.analysis_run_links l
                    JOIN analysis_v1.analysis_definitions d
                      ON d.definition_id = l.definition_id
                     AND d.version = l.definition_version
                    WHERE l.definition_id = :definition_id
                      AND l.definition_version = :version
                      AND l.idempotency_key = :idempotency_key
                      AND d.owner_id = :owner_id
                    """
                ),
                {
                    "definition_id": definition_id,
                    "version": version,
                    "idempotency_key": idempotency_key,
                    "owner_id": self._owner_id,
                },
            ).scalar_one_or_none()
        if request_id is None:
            raise KeyError("idempotent Analysis Run을 찾을 수 없습니다.")
        return UUID(str(request_id))

    def finish_run(
        self,
        request_id: UUID,
        response: AnalysisResponse,
        execution: dict[str, Any],
    ) -> None:
        status = {
            AnalysisStatus.BLOCKED: "DENIED",
            AnalysisStatus.CANCELLED: "FAILED",
        }.get(response.data.status, response.data.status.value)
        error_type = {
            "ACCESS_DENIED": "PERMISSION",
            "CONTEXT_INCOMPLETE": "AMBIGUOUS",
            "SQL_POLICY_BLOCKED": "UNSUPPORTED",
            "PARTIAL_FAILURE": "PARTIAL",
            "RESULT_EVIDENCE_MISSING": "INSUFFICIENT_EVIDENCE",
        }.get(response.error.code.value if response.error else "")
        try:
            with self._engine.begin() as connection:
                connection.execute(
                    text(
                        """
                        UPDATE chat.analysis_requests
                        SET status = :status, error_type = :error_type,
                            completed_at = :completed_at
                        WHERE request_id = :request_id
                        """
                    ),
                    {
                        "request_id": request_id,
                        "status": status,
                        "error_type": error_type,
                        "completed_at": datetime.now(timezone.utc),
                    },
                )
                previous = None
                for sequence, transition in enumerate(response.data.transitions, 1):
                    connection.execute(
                        text(
                            """
                            INSERT INTO chat.analysis_state_transitions
                                (request_id, sequence_no, from_status, to_status)
                            VALUES (:request_id, :sequence, :from_status, :to_status)
                            """
                        ),
                        {
                            "request_id": request_id,
                            "sequence": sequence,
                            "from_status": previous,
                            "to_status": transition.value,
                        },
                    )
                    previous = transition.value
                if execution and response.data.artifact and response.data.result:
                    query_execution_id, artifact_id = self._save_evidence(
                        connection, request_id, response, execution
                    )
                else:
                    query_execution_id, artifact_id = None, None
                self._save_audit(
                    connection,
                    request_id,
                    response,
                    query_execution_id,
                    artifact_id,
                )
        except SQLAlchemyError as error:
            raise AnalysisRepositoryUnavailable("Analysis 실행 결과를 저장할 수 없습니다.") from error

    def fail_run(self, request_id: UUID, error_type: str = "UNSUPPORTED") -> None:
        try:
            with self._engine.begin() as connection:
                connection.execute(
                    text(
                        """
                        UPDATE chat.analysis_requests
                        SET status = 'DENIED', error_type = :error_type,
                            completed_at = :completed_at
                        WHERE request_id = :request_id AND status = 'RECEIVED'
                        """
                    ),
                    {
                        "request_id": request_id,
                        "error_type": error_type,
                        "completed_at": datetime.now(timezone.utc),
                    },
                )
                connection.execute(
                    text(
                        """
                        INSERT INTO governance.audit_events
                            (request_id, actor_user_id, actor_role, action_code,
                             object_type, object_id, sql_policy_version,
                             details_json_redacted, trace_id)
                        SELECT request_id, user_id, user_role, 'ANALYSIS_DENIED',
                               'ANALYSIS_REQUEST', request_id::text,
                               sql_policy_version,
                               CAST(:details AS jsonb), trace_id
                        FROM chat.analysis_requests
                        WHERE request_id = :request_id
                          AND NOT EXISTS (
                              SELECT 1 FROM governance.audit_events
                              WHERE request_id = :request_id
                                AND action_code = 'ANALYSIS_DENIED'
                          )
                        """
                    ),
                    {
                        "request_id": request_id,
                        "details": json.dumps(
                            {
                                "status": "DENIED",
                                "error_type": error_type,
                                "persistence_version": ANALYSIS_PERSISTENCE_VERSION,
                            },
                            sort_keys=True,
                        ),
                    },
                )
        except SQLAlchemyError as error:
            raise AnalysisRepositoryUnavailable("Analysis 실행 실패를 저장할 수 없습니다.") from error

    @staticmethod
    def _save_evidence(connection, request_id, response, execution) -> tuple[UUID, UUID]:
        plan = execution["plan"]
        query = execution["query"]
        package = execution["package"]
        query_execution_id = uuid4()
        result = response.data.result
        snapshot = result.table.model_dump(mode="json") if result.table else {}
        chart = result.chart.model_dump(mode="json") if result.chart else {}
        evidence = result.evidence.model_dump(mode="json")
        connection.execute(
            text(
                """
                INSERT INTO query.query_executions
                    (query_execution_id, request_id, attempt_no, generation_mode,
                     generated_sql_redacted, sql_hash, ast_validation_json,
                     join_validation_json, permission_validation_json, explain_json,
                     validation_status, trino_query_id, execution_status, row_count,
                     scan_bytes, result_checksum, source_urns_json, source_cutoff_json)
                VALUES (:query_execution_id, :request_id, 1, :generation_mode,
                        '[REDACTED]', :sql_hash, CAST(:ast AS jsonb),
                        CAST(:joins AS jsonb), CAST(:permission AS jsonb),
                        CAST(:explain AS jsonb), 'ALLOWED', :query_id, 'SUCCEEDED',
                        :row_count, :scan_bytes, :result_checksum,
                        CAST(:sources AS jsonb), CAST(:cutoff AS jsonb))
                """
            ),
            {
                "query_execution_id": query_execution_id,
                "request_id": request_id,
                "generation_mode": (
                    "TEMPLATE" if str(plan.get("model_version", "")).startswith("TEMPLATE") else "LLM"
                ),
                "sql_hash": _hash(str(plan["sql"])),
                "ast": json.dumps({"status": "PASSED"}),
                "joins": json.dumps({"status": "PASSED"}),
                "permission": json.dumps({"status": "PASSED"}),
                "explain": json.dumps({"status": "NOT_RECORDED"}),
                "query_id": query["query_id"],
                "row_count": len(query.get("rows", ())),
                "scan_bytes": int(query.get("scan_bytes", 0)),
                "result_checksum": _hash(snapshot),
                "sources": json.dumps([item.urn for item in package.assets]),
                "cutoff": json.dumps(evidence.get("period") or {}),
            },
        )
        artifact = response.data.artifact
        connection.execute(
            text(
                """
                INSERT INTO artifact.analysis_artifacts
                    (artifact_id, request_id, query_execution_id, artifact_type,
                     title, data_snapshot_json, chart_spec_json, narrative_markdown,
                     evidence_json, freshness_status, status, artifact_checksum)
                VALUES (:artifact_id, :request_id, :query_execution_id, 'COMPOSITE',
                        'Analysis result', CAST(:snapshot AS jsonb), CAST(:chart AS jsonb),
                        :narrative, CAST(:evidence AS jsonb), :freshness,
                        'APPROVED', :checksum)
                """
            ),
            {
                "artifact_id": artifact.artifact_id,
                "request_id": request_id,
                "query_execution_id": query_execution_id,
                "snapshot": json.dumps(snapshot, ensure_ascii=False),
                "chart": json.dumps(chart, ensure_ascii=False),
                "narrative": result.summary,
                "evidence": json.dumps(evidence, ensure_ascii=False),
                "freshness": (
                    "PARTIAL" if response.data.status is AnalysisStatus.PARTIAL else "FRESH"
                ),
                "checksum": _hash({"snapshot": snapshot, "chart": chart, "evidence": evidence}),
            },
        )
        return query_execution_id, artifact.artifact_id

    @staticmethod
    def _save_audit(
        connection,
        request_id: UUID,
        response: AnalysisResponse,
        query_execution_id: UUID | None,
        artifact_id: UUID | None,
    ) -> None:
        result = response.data.result
        evidence = result.evidence if result else None
        details = {
            "status": response.data.status.value,
            "transitions": [item.value for item in response.data.transitions],
            "route": response.data.route.value if response.data.route else None,
            "template_id": response.data.template_id,
            "repair_count": response.data.repair_count,
            "trace": [step.model_dump(mode="json") for step in response.data.trace],
            "error_code": response.error.code.value if response.error else None,
            "query_id": evidence.query_id if evidence else None,
            "context_release": evidence.context_release if evidence else None,
            "policy_version": evidence.policy_version if evidence else None,
            "model_version": evidence.model_version if evidence else None,
            "persistence_version": ANALYSIS_PERSISTENCE_VERSION,
        }
        action = f"ANALYSIS_{response.data.status.value}"
        object_type = "ANALYSIS_ARTIFACT" if artifact_id else "ANALYSIS_REQUEST"
        object_id = artifact_id or request_id
        connection.execute(
            text(
                """
                INSERT INTO governance.audit_events
                    (request_id, actor_user_id, actor_role, action_code,
                     object_type, object_id, sql_policy_version,
                     query_execution_id, artifact_id, details_json_redacted,
                     trace_id)
                SELECT request_id, user_id, user_role, :action_code,
                       :object_type, :object_id, COALESCE(:policy_version, sql_policy_version),
                       :query_execution_id, :artifact_id, CAST(:details AS jsonb),
                       trace_id
                FROM chat.analysis_requests
                WHERE request_id = :request_id
                """
            ),
            {
                "request_id": request_id,
                "action_code": action,
                "object_type": object_type,
                "object_id": str(object_id),
                "policy_version": evidence.policy_version if evidence else None,
                "query_execution_id": query_execution_id,
                "artifact_id": artifact_id,
                "details": json.dumps(details, ensure_ascii=False, sort_keys=True),
            },
        )

    @staticmethod
    def _run(row) -> dict[str, Any]:
        status = {"DENIED": "BLOCKED", "CANCELLED": "FAILED"}.get(
            row["status"], row["status"]
        )
        return {
            "contract_version": ANALYSIS_PERSISTENCE_VERSION,
            "request_id": row["request_id"],
            "definition_id": row["definition_id"],
            "definition_version": row["definition_version"],
            "status": status,
            "as_of": row["as_of"],
            "timezone": row["timezone_name"],
            "trace_id": row["trace_id"],
            "query_id": row["query_id"],
            "artifact_id": row["artifact_id"],
            "error_type": row["error_type"],
            "started_at": row["started_at"],
            "completed_at": row["completed_at"],
        }

    def get_run(self, request_id: str | UUID) -> dict[str, Any]:
        try:
            with self._engine.connect() as connection:
                row = connection.execute(
                    text(
                        """
                        SELECT l.request_id, l.definition_id, l.definition_version,
                               l.as_of, l.timezone_name, r.status, r.error_type,
                               r.trace_id, r.started_at, r.completed_at,
                               q.trino_query_id AS query_id, a.artifact_id
                        FROM analysis_v1.analysis_run_links l
                        JOIN analysis_v1.analysis_definitions d
                          ON d.definition_id = l.definition_id
                         AND d.version = l.definition_version
                        JOIN chat.analysis_requests r ON r.request_id = l.request_id
                        LEFT JOIN LATERAL (
                            SELECT trino_query_id FROM query.query_executions
                            WHERE request_id = r.request_id
                            ORDER BY attempt_no DESC LIMIT 1
                        ) q ON true
                        LEFT JOIN LATERAL (
                            SELECT artifact_id FROM artifact.analysis_artifacts
                            WHERE request_id = r.request_id LIMIT 1
                        ) a ON true
                        WHERE l.request_id = :request_id AND d.owner_id = :owner_id
                        """
                    ),
                    {
                        "request_id": _uuid(request_id, "request_id"),
                        "owner_id": self._owner_id,
                    },
                ).mappings().one_or_none()
        except SQLAlchemyError as error:
            raise AnalysisRepositoryUnavailable("Analysis 저장소를 사용할 수 없습니다.") from error
        if row is None:
            raise KeyError("Analysis Run을 찾을 수 없습니다.")
        return self._run(row)

    def list_runs(self) -> list[dict[str, Any]]:
        try:
            with self._engine.connect() as connection:
                rows = connection.execute(
                    text(
                        """
                        SELECT l.request_id, l.definition_id, l.definition_version,
                               l.as_of, l.timezone_name, r.status, r.error_type,
                               r.trace_id, r.started_at, r.completed_at,
                               q.trino_query_id AS query_id, a.artifact_id
                        FROM analysis_v1.analysis_run_links l
                        JOIN analysis_v1.analysis_definitions d
                          ON d.definition_id = l.definition_id
                         AND d.version = l.definition_version
                        JOIN chat.analysis_requests r ON r.request_id = l.request_id
                        LEFT JOIN LATERAL (
                            SELECT trino_query_id FROM query.query_executions
                            WHERE request_id = r.request_id
                            ORDER BY attempt_no DESC LIMIT 1
                        ) q ON true
                        LEFT JOIN LATERAL (
                            SELECT artifact_id FROM artifact.analysis_artifacts
                            WHERE request_id = r.request_id LIMIT 1
                        ) a ON true
                        WHERE d.owner_id = :owner_id
                        ORDER BY l.created_at DESC, l.request_id DESC
                        """
                    ),
                    {"owner_id": self._owner_id},
                ).mappings()
                return [self._run(row) for row in rows]
        except SQLAlchemyError as error:
            raise AnalysisRepositoryUnavailable("Analysis 저장소를 사용할 수 없습니다.") from error

    def get_run_artifact(self, request_id: str | UUID) -> dict[str, Any]:
        try:
            with self._engine.connect() as connection:
                row = connection.execute(
                    text(
                        """
                        SELECT r.request_id, r.trace_id, r.status,
                               d.question_text_redacted AS question,
                               a.narrative_markdown AS summary,
                               a.data_snapshot_json AS table_data,
                               a.chart_spec_json AS chart_data,
                               a.evidence_json AS evidence,
                               a.artifact_id, a.artifact_checksum,
                               q.trino_query_id AS query_id
                        FROM analysis_v1.analysis_run_links l
                        JOIN analysis_v1.analysis_definitions d
                          ON d.definition_id = l.definition_id
                         AND d.version = l.definition_version
                        JOIN chat.analysis_requests r ON r.request_id = l.request_id
                        JOIN artifact.analysis_artifacts a
                          ON a.request_id = r.request_id
                         AND a.status = 'APPROVED'
                        JOIN query.query_executions q
                          ON q.query_execution_id = a.query_execution_id
                         AND q.execution_status = 'SUCCEEDED'
                        WHERE l.request_id = :request_id
                          AND d.owner_id = :owner_id
                        LIMIT 1
                        """
                    ),
                    {
                        "request_id": _uuid(request_id, "request_id"),
                        "owner_id": self._owner_id,
                    },
                ).mappings().one_or_none()
        except SQLAlchemyError as error:
            raise AnalysisRepositoryUnavailable("Analysis 저장소를 사용할 수 없습니다.") from error
        if row is None:
            raise KeyError("승인된 Analysis Artifact를 찾을 수 없습니다.")
        return {
            "contract_version": ANALYSIS_PERSISTENCE_VERSION,
            "request_id": row["request_id"],
            "trace_id": row["trace_id"],
            "status": row["status"],
            "question": row["question"],
            "summary": row["summary"],
            "table": row["table_data"],
            "chart": row["chart_data"] or None,
            "evidence": row["evidence"],
            "artifact_id": row["artifact_id"],
            "query_id": row["query_id"],
            "artifact_checksum": row["artifact_checksum"],
        }
