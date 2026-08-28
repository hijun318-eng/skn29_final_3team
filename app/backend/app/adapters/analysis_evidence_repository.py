"""Trino query·artifact·lineage evidence를 분석 run과 원자적으로 연결해 저장한다."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.analysis_repository_common import AnalysisRepositoryUnavailable, _hash
from app.analysis_contracts import ANALYSIS_PERSISTENCE_VERSION
from app.contracts import AnalysisResponse, AnalysisStatus

logger = logging.getLogger("uvicorn.error")

_FAILURE_TERMINALS = {
    "AMBIGUOUS": ("DENIED", "ANALYSIS_DENIED"),
    "UNSUPPORTED": ("DENIED", "ANALYSIS_DENIED"),
    "PERMISSION": ("DENIED", "ANALYSIS_DENIED"),
    "QUERY": ("FAILED", "ANALYSIS_FAILED"),
    "INSUFFICIENT_EVIDENCE": ("FAILED", "ANALYSIS_FAILED"),
    "PERSISTENCE": ("FAILED", "ANALYSIS_FAILED"),
    "RECOVERY": ("FAILED", "ANALYSIS_FAILED"),
}


class AnalysisEvidenceRepositoryMixin:
    """분석 run의 terminal 상태와 query·artifact·audit evidence를 원자적으로 기록한다.

    response에 실행 근거가 있으면 query 행을 만들고, 승인 결과가 있을 때만 artifact를
    추가해 audit에 식별자를 연결한다. 모든 SQL 쓰기는 한 transaction이며 DB 오류는
    :class:`AnalysisRepositoryUnavailable`로 변환한다.
    """
    async def finish_run(
        self,
        request_id: UUID,
        response: AnalysisResponse,
        execution: dict[str, Any],
    ) -> None:
        """검증된 ``response``와 선택적 ``execution`` 근거로 분석 run을 종결한다.

        request 상태·오류 유형·전이 이력을 갱신하고, 실행 근거가 있으면 query를, 승인 결과가
        있으면 artifact를 저장한 뒤 같은 transaction에서 audit event를 연결한다. 어느 SQL 단계든 실패하면
        전체 쓰기를 rollback하고 :class:`AnalysisRepositoryUnavailable`을 발생시키며, 성공
        반환값은 ``None``이다.
        """
        try:
            async with self._sessionmaker.begin() as session:
                await self.finish_run_in_session(session, request_id, response, execution)
        except SQLAlchemyError as error:
            logger.error("finish_run DB error: %s", error, exc_info=True)
            raise AnalysisRepositoryUnavailable("Analysis 실행 결과를 저장할 수 없습니다.") from error

    async def finish_run_in_session(
        self,
        session: AsyncSession,
        request_id: UUID,
        response: AnalysisResponse,
        execution: dict[str, Any],
    ) -> None:
        """호출자가 소유한 transaction 안에서 run terminal·evidence·audit를 저장한다."""

        status = {
            AnalysisStatus.BLOCKED: "DENIED",
            AnalysisStatus.CLARIFICATION_REQUIRED: "CLARIFYING",
        }.get(response.data.status, response.data.status.value)
        error_type = {
            "ACCESS_DENIED": "PERMISSION",
            "CONTEXT_INCOMPLETE": "AMBIGUOUS",
            "SQL_POLICY_BLOCKED": "UNSUPPORTED",
            "PARTIAL_FAILURE": "PARTIAL",
            "RESULT_EVIDENCE_MISSING": "INSUFFICIENT_EVIDENCE",
            "ARTIFACT_PERSIST_FAILED": "PERSISTENCE",
        }.get(response.error.code.value if response.error else "")
        result = await session.execute(
            text(
                """
                UPDATE chat.analysis_requests
                SET status = :status, error_type = :error_type,
                    completed_at = :completed_at
                WHERE request_id = :request_id
                  AND status IN ('RECEIVED','ROUTED','RUNNING')
                RETURNING request_id
                """
            ),
            {
                "request_id": request_id,
                "status": status,
                "error_type": error_type,
                "completed_at": datetime.now(timezone.utc),
            },
        )
        if result.scalar_one_or_none() is None:
            raise ValueError("Analysis run terminal 전이가 중복되었거나 시작 상태가 아닙니다.")
        previous = None
        for sequence, transition in enumerate(response.data.transitions, 1):
            await session.execute(
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
        terminal_evidence = (
            response.data.result.evidence
            if response.data.result is not None
            else response.data.evidence
        )
        if execution and terminal_evidence is not None:
            query_execution_id, artifact_id = await self._save_evidence(
                session, request_id, response, execution
            )
        else:
            query_execution_id, artifact_id = None, None
        await self._save_audit(
            session,
            request_id,
            response,
            query_execution_id,
            artifact_id,
        )

    async def fail_run(self, request_id: UUID, error_type: str = "RECOVERY") -> None:
        """nonterminal request를 승인된 영속 실패 유형으로 종결하고 감사한다.

        거부 유형은 ``DENIED``, 실행·복구 실패 유형은 ``FAILED``로 저장한다. 동일 action
        audit는 중복 삽입하지 않으며 두 쓰기는 한 transaction으로 처리된다. DB 오류는
        :class:`AnalysisRepositoryUnavailable`로 변환하고 성공하면 ``None``을 반환한다.
        """
        try:
            async with self._sessionmaker.begin() as session:
                await self.fail_run_in_session(session, request_id, error_type)
        except SQLAlchemyError as error:
            raise AnalysisRepositoryUnavailable("Analysis 실행 실패를 저장할 수 없습니다.") from error

    async def fail_run_in_session(
        self,
        session: AsyncSession,
        request_id: UUID,
        error_type: str = "RECOVERY",
    ) -> None:
        """호출자 transaction 안에서 nonterminal run과 audit를 실패 상태로 함께 닫는다."""

        try:
            stored_status, action_code = _FAILURE_TERMINALS[error_type]
        except KeyError as error:
            raise ValueError(
                f"Analysis Run 영속 실패 유형이 유효하지 않습니다: {error_type}"
            ) from error
        stored_error_type = error_type
        await session.execute(
            text(
                """
                UPDATE chat.analysis_requests
                SET status = :status, error_type = :error_type,
                    completed_at = :completed_at
                WHERE request_id = :request_id
                  AND status IN ('RECEIVED','ROUTED','RUNNING')
                """
            ),
            {
                "request_id": request_id,
                "status": stored_status,
                "error_type": stored_error_type,
                "completed_at": datetime.now(timezone.utc),
            },
        )
        await session.execute(
            text(
                """
                INSERT INTO governance.audit_events
                    (request_id, actor_user_id, actor_role, action_code,
                     object_type, object_id, sql_policy_version,
                     details_json_redacted, trace_id)
                SELECT request_id, user_id, user_role,
                       CAST(:action_code AS varchar(96)),
                       'ANALYSIS_REQUEST', request_id::text,
                       sql_policy_version,
                       CAST(:details AS jsonb), trace_id
                FROM chat.analysis_requests
                WHERE request_id = :request_id
                  AND NOT EXISTS (
                      SELECT 1 FROM governance.audit_events
                      WHERE request_id = :request_id
                        AND action_code = CAST(:action_code AS varchar(96))
                  )
                """
            ),
            {
                "request_id": request_id,
                "action_code": action_code,
                "details": json.dumps(
                    {
                        "status": stored_status,
                        "error_type": stored_error_type,
                        "persistence_version": ANALYSIS_PERSISTENCE_VERSION,
                    },
                    sort_keys=True,
                ),
            },
        )

    async def record_query_lifecycle(
        self,
        request_id: UUID,
        event: dict[str, Any],
    ) -> None:
        """외부 query가 진행 중인 동안 ID와 exact cancel URI를 독립 transaction으로 보존한다."""

        event_type = str(event.get("event_type") or "")
        query_id = str(event.get("query_id") or "")
        if event_type not in {"SUBMITTED", "HEARTBEAT", "TERMINAL"}:
            raise ValueError("query lifecycle event type이 유효하지 않습니다.")
        if not query_id or len(query_id) > 128:
            raise ValueError("query lifecycle query ID가 유효하지 않습니다.")
        try:
            async with self._sessionmaker.begin() as session:
                owned = (
                    await session.execute(
                        text(
                            "SELECT request_id FROM chat.analysis_requests "
                            "WHERE request_id = :request_id AND user_id = :owner_id FOR UPDATE"
                        ),
                        {"request_id": request_id, "owner_id": self._owner_id},
                    )
                ).scalar_one_or_none()
                if owned is None:
                    raise ValueError("query lifecycle run을 찾을 수 없습니다.")

                rows = (
                    await session.execute(
                        text(
                            "SELECT query_execution_id, trino_query_id, sql_hash, "
                            "execution_status, trino_cancel_uri "
                            "FROM query.query_executions WHERE request_id = :request_id "
                            "ORDER BY attempt_no FOR UPDATE"
                        ),
                        {"request_id": request_id},
                    )
                ).mappings().all()
                if len(rows) > 1:
                    raise ValueError("한 Conversation command에서 query가 중복 실행되었습니다.")

                if event_type == "SUBMITTED":
                    cancel_uri = str(event.get("cancel_uri") or "")
                    sql_hash = str(event.get("sql_hash") or "")
                    if not cancel_uri or len(cancel_uri) > 4096:
                        raise ValueError("RUNNING query의 durable cancel URI가 없습니다.")
                    if not re.fullmatch(r"[0-9a-f]{64}", sql_hash):
                        raise ValueError("RUNNING query SQL hash가 유효하지 않습니다.")
                    if not rows:
                        query_execution_id = uuid4()
                        await session.execute(
                            text(
                                """
                                INSERT INTO query.query_executions (
                                    query_execution_id, request_id, attempt_no,
                                    generation_mode, generated_sql_redacted, sql_hash,
                                    ast_validation_json, join_validation_json,
                                    permission_validation_json, explain_json,
                                    validation_status, trino_query_id, trino_cancel_uri,
                                    execution_status, row_count, scan_bytes,
                                    source_urns_json, source_cutoff_json
                                ) VALUES (
                                    :query_execution_id, :request_id, 1, 'LLM',
                                    '[REDACTED]', :sql_hash,
                                    '{"status":"CAPABILITY_BOUND"}'::jsonb,
                                    '{"status":"PENDING_TERMINAL_EVIDENCE"}'::jsonb,
                                    '{"status":"CAPABILITY_BOUND"}'::jsonb,
                                    '{"status":"NOT_RECORDED"}'::jsonb,
                                    'ALLOWED', :query_id, :cancel_uri, 'RUNNING', 0, 0,
                                    '[]'::jsonb, '{}'::jsonb
                                )
                                """
                            ),
                            {
                                "query_execution_id": query_execution_id,
                                "request_id": request_id,
                                "sql_hash": sql_hash,
                                "query_id": query_id,
                                "cancel_uri": cancel_uri,
                            },
                        )
                    else:
                        row = rows[0]
                        if row["trino_query_id"] != query_id or row["sql_hash"] != sql_hash:
                            raise ValueError("동일 command에서 다른 query submission을 감지했습니다.")
                        if row["execution_status"] == "RUNNING":
                            await session.execute(
                                text(
                                    "UPDATE query.query_executions SET trino_cancel_uri = :cancel_uri "
                                    "WHERE query_execution_id = :query_execution_id"
                                ),
                                {
                                    "cancel_uri": cancel_uri,
                                    "query_execution_id": row["query_execution_id"],
                                },
                            )
                    return

                if not rows:
                    # nextUri 없이 첫 page에서 끝난 query는 orphan이 될 수 없으며 최종
                    # evidence transaction이 완전한 행을 생성한다.
                    if event_type == "TERMINAL":
                        return
                    raise ValueError("heartbeat 대상 RUNNING query를 찾을 수 없습니다.")
                row = rows[0]
                if row["trino_query_id"] != query_id:
                    raise ValueError("query lifecycle ID가 durable submission과 다릅니다.")

                if event_type == "HEARTBEAT":
                    cancel_uri = str(event.get("cancel_uri") or "")
                    if not cancel_uri or len(cancel_uri) > 4096:
                        raise ValueError("query heartbeat cancel URI가 유효하지 않습니다.")
                    if row["execution_status"] != "RUNNING":
                        raise ValueError("terminal query에는 heartbeat를 기록할 수 없습니다.")
                    await session.execute(
                        text(
                            "UPDATE query.query_executions SET trino_cancel_uri = :cancel_uri "
                            "WHERE query_execution_id = :query_execution_id "
                            "AND execution_status = 'RUNNING'"
                        ),
                        {
                            "cancel_uri": cancel_uri,
                            "query_execution_id": row["query_execution_id"],
                        },
                    )
                    return

                status = str(event.get("status") or "")
                if status not in {
                    "SUCCEEDED", "PARTIAL", "FINISHED", "CANCELLED", "FAILED"
                }:
                    raise ValueError("query terminal status가 유효하지 않습니다.")
                terminal_status = (
                    "SUCCEEDED"
                    if status in {"SUCCEEDED", "PARTIAL", "FINISHED"}
                    else "CANCELLED"
                    if status == "CANCELLED"
                    else "FAILED"
                )
                if row["execution_status"] != "RUNNING":
                    if row["execution_status"] == terminal_status:
                        return
                    raise ValueError("query terminal 상태를 다시 쓸 수 없습니다.")
                row_count = int(event.get("row_count", 0))
                scan_bytes = int(event.get("scan_bytes", 0))
                if row_count < 0 or scan_bytes < 0:
                    raise ValueError("query terminal count evidence가 유효하지 않습니다.")
                error_code = str(event.get("error_code") or "")[:64] or None
                await session.execute(
                    text(
                        """
                        UPDATE query.query_executions
                        SET execution_status = CAST(:status AS varchar(16)),
                            row_count = :row_count,
                            scan_bytes = :scan_bytes, trino_cancel_uri = NULL,
                            error_code = :error_code,
                            error_message_redacted = CASE
                                WHEN CAST(:status AS varchar(16)) = 'FAILED'
                                THEN 'Query execution failed'
                                ELSE NULL
                            END
                        WHERE query_execution_id = :query_execution_id
                          AND execution_status = 'RUNNING'
                        """
                    ),
                    {
                        "status": terminal_status,
                        "row_count": row_count,
                        "scan_bytes": scan_bytes,
                        "error_code": error_code,
                        "query_execution_id": row["query_execution_id"],
                    },
                )
        except SQLAlchemyError as error:
            raise AnalysisRepositoryUnavailable(
                "Query lifecycle evidence를 저장할 수 없습니다."
            ) from error

    @staticmethod
    async def _save_evidence(
        session: AsyncSession, request_id, response, execution
    ) -> tuple[UUID, UUID | None]:
        plan = execution["plan"]
        query = execution["query"]
        package = execution["package"]
        query_id = str(query["query_id"])
        executable_sql = plan.get("executable_sql")
        if not isinstance(executable_sql, str) or not executable_sql.strip():
            raise ValueError("terminal query의 exact executable SQL이 없습니다.")
        # lifecycle SUBMITTED receipt는 parameter binding까지 끝난 exact SQL을
        # 해시한다. placeholder가 남은 canonical plan SQL과 비교하면 정상 실행도
        # 서로 다른 submission으로 오인한다.
        sql_hash = _hash(executable_sql)
        result = response.data.result
        artifact = response.data.artifact
        if (result is None) != (artifact is None):
            raise ValueError("Analysis 결과와 Artifact 참조는 함께 있어야 합니다.")
        terminal_evidence = result.evidence if result is not None else response.data.evidence
        if terminal_evidence is None:
            raise ValueError("terminal query 실행 근거가 없습니다.")
        snapshot = (
            result.table.model_dump(mode="json")
            if result is not None and result.table is not None
            else {}
        )
        chart = (
            result.chart.model_dump(mode="json")
            if result is not None and result.chart is not None
            else {}
        )
        evidence = terminal_evidence.model_dump(mode="json")
        receipt = (
            await session.execute(
                text(
                    """
                    SELECT product_release_id, permission_snapshot_id, semantic_release_id
                    FROM chat.analysis_requests WHERE request_id = :request_id
                    """
                ),
                {"request_id": request_id},
            )
        ).mappings().one()
        if (
            receipt["product_release_id"] is not None
            and evidence.get("product_release_id") != receipt["product_release_id"]
        ):
            raise ValueError("실행 근거의 product release가 admitted run과 일치하지 않습니다.")
        existing_queries = (
            await session.execute(
                text(
                    "SELECT query_execution_id, trino_query_id, sql_hash, execution_status "
                    "FROM query.query_executions WHERE request_id = :request_id "
                    "ORDER BY attempt_no FOR UPDATE"
                ),
                {"request_id": request_id},
            )
        ).mappings().all()
        if len(existing_queries) > 1:
            raise ValueError("한 Conversation command에서 query가 중복 실행되었습니다.")
        source_cutoff = dict(
            evidence.get("period") or evidence.get("snapshot") or {}
        )
        if evidence.get("comparison_period") is not None:
            source_cutoff["comparison_period"] = evidence["comparison_period"]
        query_values = {
            "request_id": request_id,
            "generation_mode": (
                "TEMPLATE" if str(plan.get("model_version", "")).startswith("TEMPLATE") else "LLM"
            ),
            "sql_hash": sql_hash,
            "ast": json.dumps({"status": "PASSED"}),
            "joins": json.dumps({"status": "PASSED"}),
            "permission": json.dumps({"status": "PASSED"}),
            "explain": json.dumps({"status": "NOT_RECORDED"}),
            "query_id": query_id,
            "row_count": len(query.get("rows", ())),
            "scan_bytes": int(query.get("scan_bytes", 0)),
            "result_checksum": _hash(
                snapshot if result is not None else {"rows": query.get("rows", ())}
            ),
            "sources": json.dumps([item.urn for item in package.assets]),
            "cutoff": json.dumps(source_cutoff),
        }
        if existing_queries:
            existing = existing_queries[0]
            if existing["trino_query_id"] != query_id or existing["sql_hash"] != sql_hash:
                raise ValueError("terminal query evidence가 durable submission과 다릅니다.")
            if existing["execution_status"] not in {"RUNNING", "SUCCEEDED"}:
                raise ValueError("실패 또는 취소된 query에 terminal evidence를 연결할 수 없습니다.")
            query_execution_id = UUID(str(existing["query_execution_id"]))
            await session.execute(
                text(
                    """
                    UPDATE query.query_executions
                    SET generation_mode = :generation_mode,
                        ast_validation_json = CAST(:ast AS jsonb),
                        join_validation_json = CAST(:joins AS jsonb),
                        permission_validation_json = CAST(:permission AS jsonb),
                        explain_json = CAST(:explain AS jsonb), validation_status = 'ALLOWED',
                        execution_status = 'SUCCEEDED', trino_cancel_uri = NULL,
                        row_count = :row_count, scan_bytes = :scan_bytes,
                        result_checksum = :result_checksum,
                        source_urns_json = CAST(:sources AS jsonb),
                        source_cutoff_json = CAST(:cutoff AS jsonb),
                        error_code = NULL, error_message_redacted = NULL
                    WHERE query_execution_id = :query_execution_id
                    """
                ),
                {**query_values, "query_execution_id": query_execution_id},
            )
        else:
            query_execution_id = uuid4()
            await session.execute(
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
                {**query_values, "query_execution_id": query_execution_id},
            )
        if result is None:
            return query_execution_id, None

        await session.execute(
            text(
                """
                INSERT INTO artifact.analysis_artifacts
                    (artifact_id, request_id, query_execution_id, artifact_type,
                     title, data_snapshot_json, chart_spec_json, narrative_markdown,
                     evidence_json, freshness_status, status, artifact_checksum,
                     product_release_id, permission_snapshot_id, semantic_release_id)
                VALUES (:artifact_id, :request_id, :query_execution_id, 'COMPOSITE',
                        'Analysis result', CAST(:snapshot AS jsonb), CAST(:chart AS jsonb),
                        :narrative, CAST(:evidence AS jsonb), :freshness,
                        'APPROVED', :checksum, :product_release_id,
                        :permission_snapshot_id, :semantic_release_id)
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
                "product_release_id": receipt["product_release_id"],
                "permission_snapshot_id": receipt["permission_snapshot_id"],
                "semantic_release_id": receipt["semantic_release_id"],
            },
        )
        if receipt["product_release_id"] is not None:
            await session.execute(
                text(
                    """
                    INSERT INTO governance.product_release_bindings (
                        object_kind, object_id, product_release_id,
                        permission_snapshot_id, semantic_release_id,
                        capability_release_vector_json, evidence_refs_json
                    ) VALUES (
                        'ARTIFACT', :object_id, :product_release_id,
                        :permission_snapshot_id, :semantic_release_id,
                        '{"analysis.run":"1.0.0"}'::jsonb, '[]'::jsonb
                    )
                    """
                ),
                {
                    "object_id": str(artifact.artifact_id),
                    "product_release_id": receipt["product_release_id"],
                    "permission_snapshot_id": receipt["permission_snapshot_id"],
                    "semantic_release_id": receipt["semantic_release_id"],
                },
            )
        return query_execution_id, artifact.artifact_id

    @staticmethod
    async def _save_audit(
        session: AsyncSession,
        request_id: UUID,
        response: AnalysisResponse,
        query_execution_id: UUID | None,
        artifact_id: UUID | None,
    ) -> None:
        result = response.data.result
        evidence = result.evidence if result else response.data.evidence
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
        if response.data.evidence is not None:
            details["run_evidence"] = response.data.evidence.model_dump(mode="json")
        action = f"ANALYSIS_{response.data.status.value}"
        object_type = "ANALYSIS_ARTIFACT" if artifact_id else "ANALYSIS_REQUEST"
        object_id = artifact_id or request_id
        await session.execute(
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
