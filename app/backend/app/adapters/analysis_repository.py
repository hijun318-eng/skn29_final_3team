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
from app.contracts import AnalysisResponse, AnalysisStatus, PipelineStage, RequestContext


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
                             question_text_redacted, parameters_json, parameter_hash)
                        VALUES (:definition_id, 1, :owner_id, :title,
                                :question, CAST(:parameters AS jsonb), :parameter_hash)
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
                        WHERE definition_id = :definition_id AND owner_id = :owner_id
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
                        WHERE owner_id = :owner_id
                        ORDER BY created_at, definition_id
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
                self._insert_access_audit(connection, context)
                connection.execute(
                    text(
                        """
                        INSERT INTO analysis_v1.analysis_run_links
                            (definition_id, definition_version, request_id,
                             idempotency_key, as_of, timezone_name)
                        VALUES (:definition_id, :version, :request_id,
                                :idempotency_key, :as_of, :timezone)
                        """
                    ),
                    {
                        "definition_id": definition_id,
                        "version": definition["version"],
                        "request_id": context.request_id,
                        "idempotency_key": idempotency_key,
                        "as_of": as_of,
                        "timezone": context.timezone,
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
                             question_text_redacted, parameters_json, parameter_hash)
                        VALUES (:definition_id, 1, :owner_id, :title,
                                :question, CAST(:parameters AS jsonb), :parameter_hash)
                        """
                    ),
                    {
                        "definition_id": definition_id,
                        "owner_id": self._owner_id,
                        "title": redacted[:200],
                        "question": redacted,
                        "parameters": json.dumps(parameters, ensure_ascii=False),
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
                self._insert_access_audit(connection, context)
                connection.execute(
                    text(
                        """
                        INSERT INTO analysis_v1.analysis_run_links
                            (definition_id, definition_version, request_id,
                             idempotency_key, as_of, timezone_name)
                        VALUES (:definition_id, 1, :request_id,
                                :idempotency_key, :as_of, :timezone)
                        """
                    ),
                    {
                        "definition_id": definition_id,
                        "request_id": context.request_id,
                        "idempotency_key": f"chat:{context.request_id}",
                        "as_of": context.as_of,
                        "timezone": context.timezone,
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
                self._update_access_audit(connection, request_id, response, execution)
                if execution and response.data.artifact and response.data.result:
                    self._link_execution_metadata(connection, request_id, execution)
                    self._save_evidence(connection, request_id, response, execution)
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
                        UPDATE governance.audit_events
                        SET action_code = 'ANALYSIS_ACCESS_DENIED',
                            details_json_redacted = details_json_redacted ||
                                CAST(:status AS jsonb)
                        WHERE request_id = :request_id
                          AND action_code = 'ANALYSIS_ACCESS_STARTED'
                        """
                    ),
                    {
                        "request_id": request_id,
                        "status": json.dumps({"request_status": "DENIED"}),
                    },
                )
        except SQLAlchemyError as error:
            raise AnalysisRepositoryUnavailable("Analysis 실행 실패를 저장할 수 없습니다.") from error

    @staticmethod
    def _insert_access_audit(connection, context: RequestContext) -> None:
        from app.access_policy import resolve_access_profile

        profile = resolve_access_profile(
            context.user_id, context.role, context.access_profile
        )
        trino_role = context.trino_principal or f"answervice_{profile.name.replace('-', '_')}"
        details = {
            "access_profile": profile.name,
            "allowed_domains": list(context.allowed_domains),
            "datahub_actor": context.datahub_principal or profile.datahub_principal,
            "allowed_urns": [],
            "policy_version": context.access_policy_version or profile.policy_version,
            "entitlement_hash": context.entitlement_hash or profile.entitlement_hash,
            "trino_role": trino_role,
            "datahub_search_attempted": False,
            "trino_execution_attempted": False,
            "request_status": "RECEIVED",
        }
        connection.execute(
            text(
                """
                INSERT INTO governance.audit_events
                    (request_id, actor_user_id, actor_role, action_code,
                     object_type, object_id, sql_policy_version,
                     details_json_redacted, trace_id)
                VALUES (:request_id, :actor_user_id, :actor_role,
                        'ANALYSIS_ACCESS_STARTED', 'ANALYSIS_REQUEST',
                        :object_id, :policy_version, CAST(:details AS jsonb),
                        :trace_id)
                """
            ),
            {
                "request_id": context.request_id,
                "actor_user_id": context.user_id,
                "actor_role": context.role.value,
                "object_id": str(context.request_id),
                "policy_version": details["policy_version"],
                "details": json.dumps(details, ensure_ascii=True, sort_keys=True),
                "trace_id": context.trace_id,
            },
        )

    @staticmethod
    def _update_access_audit(
        connection,
        request_id: UUID,
        response: AnalysisResponse,
        execution: dict[str, Any],
    ) -> None:
        stages = {item.stage for item in response.data.trace}
        package = execution.get("package")
        allowed_urns = sorted({item.urn for item in package.assets}) if package else []
        details = {
            "allowed_urns": allowed_urns,
            "datahub_search_attempted": any(
                stage not in {PipelineStage.ROUTER, PipelineStage.CONTROLLER}
                for stage in stages
            ),
            "trino_execution_attempted": PipelineStage.QUERY in stages,
            "request_status": response.data.status.value,
        }
        action = (
            "ANALYSIS_ACCESS_DENIED"
            if response.data.status is AnalysisStatus.BLOCKED
            else "ANALYSIS_ACCESS_COMPLETED"
        )
        connection.execute(
            text(
                """
                UPDATE governance.audit_events
                SET action_code = :action,
                    details_json_redacted = details_json_redacted ||
                        CAST(:details AS jsonb)
                WHERE request_id = :request_id
                  AND action_code = 'ANALYSIS_ACCESS_STARTED'
                """
            ),
            {
                "request_id": request_id,
                "action": action,
                "details": json.dumps(details, ensure_ascii=True, sort_keys=True),
            },
        )

    @staticmethod
    def _link_execution_metadata(connection, request_id, execution) -> None:
        plan = execution["plan"]
        package = execution["package"]
        release_id = connection.execute(
            text(
                """
                SELECT context_release_id
                FROM context.context_releases
                WHERE status = 'PUBLISHED'
                  AND (release_key = :release OR release_hash = :release)
                ORDER BY version_no DESC
                LIMIT 1
                """
            ),
            {"release": package.context_release},
        ).scalar_one_or_none()
        package_id = None
        if release_id is not None:
            package_id = uuid4()
            connection.execute(
                text(
                    """
                    INSERT INTO context.context_packages
                        (context_package_id, request_id, context_release_id,
                         user_scope_json, assets_json, metrics_json, joins_json,
                         policies_json, dataset_count, column_count, token_count,
                         package_hash)
                    VALUES (:package_id, :request_id, :release_id,
                            CAST(:user_scope AS jsonb), CAST(:assets AS jsonb),
                            CAST(:metrics AS jsonb), CAST(:joins AS jsonb),
                            CAST(:policies AS jsonb), :dataset_count, :column_count,
                            :token_count, :package_hash)
                    ON CONFLICT (request_id) DO NOTHING
                    """
                ),
                {
                    "package_id": package_id,
                    "request_id": request_id,
                    "release_id": release_id,
                    "user_scope": json.dumps(
                        {"entitlement_hash": package.entitlement_hash}
                    ),
                    "assets": json.dumps(
                        [
                            {
                                "urn": item.urn,
                                "fqn": item.fqn,
                                "columns": list(item.columns),
                            }
                            for item in package.assets
                        ]
                    ),
                    "metrics": json.dumps([item.id for item in package.metrics]),
                    "joins": json.dumps(list(package.approved_join_ids)),
                    "policies": json.dumps(
                        {
                            "sql_policy_version": package.policy_version,
                            "time_version": package.time_version,
                        }
                    ),
                    "dataset_count": package.dataset_count,
                    "column_count": package.column_count,
                    "token_count": package.token_count,
                    "package_hash": package.package_hash,
                },
            )
            package_id = connection.execute(
                text(
                    "SELECT context_package_id FROM context.context_packages "
                    "WHERE request_id = :request_id"
                ),
                {"request_id": request_id},
            ).scalar_one()

        model_version = str(plan.get("model_version", ""))
        model_id = None
        if model_version and not model_version.startswith("TEMPLATE"):
            model_id = connection.execute(
                text(
                    """
                    SELECT model_version_id
                    FROM model.model_versions
                    WHERE model_role = 'SQL_GENERATION'
                      AND status IN ('APPROVED', 'DEPLOYED')
                      AND (model_revision = :version OR model_name = :version
                           OR checkpoint_ref = :version)
                    ORDER BY CASE status WHEN 'DEPLOYED' THEN 0 ELSE 1 END,
                             model_version_id
                    LIMIT 1
                    """
                ),
                {"version": model_version},
            ).scalar_one_or_none()
        connection.execute(
            text(
                """
                UPDATE chat.analysis_requests
                SET context_release_id = :release_id,
                    context_package_id = :package_id,
                    sql_generation_model_id = :model_id,
                    sql_policy_version = :policy_version
                WHERE request_id = :request_id
                """
            ),
            {
                "request_id": request_id,
                "release_id": release_id,
                "package_id": package_id,
                "model_id": model_id,
                "policy_version": package.policy_version,
            },
        )

    @staticmethod
    def _save_evidence(connection, request_id, response, execution) -> None:
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
                    "TEMPLATE" if str(plan.get("model_version", "")).startswith("TEMPLATE") else "SLLM"
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
                request_ids = connection.execute(
                    text(
                        """
                        SELECT l.request_id
                        FROM analysis_v1.analysis_run_links l
                        JOIN analysis_v1.analysis_definitions d
                          ON d.definition_id = l.definition_id
                         AND d.version = l.definition_version
                        WHERE d.owner_id = :owner_id
                        ORDER BY l.created_at, l.request_id
                        """
                    ),
                    {"owner_id": self._owner_id},
                ).scalars()
                return [self.get_run(request_id) for request_id in request_ids]
        except SQLAlchemyError as error:
            raise AnalysisRepositoryUnavailable("Analysis 저장소를 사용할 수 없습니다.") from error
