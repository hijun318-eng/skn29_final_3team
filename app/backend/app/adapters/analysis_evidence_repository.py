"""Trino query·artifact·lineage evidence를 분석 run과 원자적으로 연결해 저장한다."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.analysis_repository_common import AnalysisRepositoryUnavailable, _hash
from app.analysis_contracts import ANALYSIS_PERSISTENCE_VERSION
from app.contracts import AnalysisResponse, AnalysisStatus


class AnalysisEvidenceRepositoryMixin:
    """분석 run의 terminal 상태와 query·artifact·audit evidence를 원자적으로 기록한다.

    response에 실행 근거와 결과 artifact가 있을 때만 query와 artifact 행을 만들고 audit에
    그 식별자를 연결한다. 모든 SQL 쓰기는 한 transaction이며 DB 오류는
    :class:`AnalysisRepositoryUnavailable`로 변환한다.
    """
    async def finish_run(
        self,
        request_id: UUID,
        response: AnalysisResponse,
        execution: dict[str, Any],
    ) -> None:
        """검증된 ``response``와 선택적 ``execution`` 근거로 분석 run을 종결한다.

        request 상태·오류 유형·전이 이력을 갱신하고, 결과가 있으면 query 및 승인 artifact를
        저장한 뒤 같은 transaction에서 audit event를 연결한다. 어느 SQL 단계든 실패하면
        전체 쓰기를 rollback하고 :class:`AnalysisRepositoryUnavailable`을 발생시키며, 성공
        반환값은 ``None``이다.
        """
        status = {
            AnalysisStatus.BLOCKED: "DENIED",
        }.get(response.data.status, response.data.status.value)
        error_type = {
            "ACCESS_DENIED": "PERMISSION",
            "CONTEXT_INCOMPLETE": "AMBIGUOUS",
            "SQL_POLICY_BLOCKED": "UNSUPPORTED",
            "PARTIAL_FAILURE": "PARTIAL",
            "RESULT_EVIDENCE_MISSING": "INSUFFICIENT_EVIDENCE",
        }.get(response.error.code.value if response.error else "")
        try:
            async with self._sessionmaker.begin() as session:
                await session.execute(
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
                if execution and response.data.artifact and response.data.result:
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
        except SQLAlchemyError as error:
            raise AnalysisRepositoryUnavailable("Analysis 실행 결과를 저장할 수 없습니다.") from error

    async def fail_run(self, request_id: UUID, error_type: str = "UNSUPPORTED") -> None:
        """아직 ``RECEIVED``인 request를 거부 또는 영속화 실패 상태로 종결하고 감사한다.

        ``ARTIFACT_PERSIST_FAILED``는 ``FAILED/PERSISTENCE``로, 나머지는
        ``DENIED/<error_type>``으로 저장한다. 동일 action audit는 중복 삽입하지 않으며 두
        쓰기는 한 transaction으로 처리된다. DB 오류는
        :class:`AnalysisRepositoryUnavailable`로 변환하고 성공하면 ``None``을 반환한다.
        """
        persistence_failure = error_type == "ARTIFACT_PERSIST_FAILED"
        stored_status = "FAILED" if persistence_failure else "DENIED"
        stored_error_type = "PERSISTENCE" if persistence_failure else error_type
        action_code = "ANALYSIS_FAILED" if persistence_failure else "ANALYSIS_DENIED"
        try:
            async with self._sessionmaker.begin() as session:
                await session.execute(
                    text(
                        """
                        UPDATE chat.analysis_requests
                        SET status = :status, error_type = :error_type,
                            completed_at = :completed_at
                        WHERE request_id = :request_id AND status = 'RECEIVED'
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
                        SELECT request_id, user_id, user_role, :action_code,
                               'ANALYSIS_REQUEST', request_id::text,
                               sql_policy_version,
                               CAST(:details AS jsonb), trace_id
                        FROM chat.analysis_requests
                        WHERE request_id = :request_id
                          AND NOT EXISTS (
                              SELECT 1 FROM governance.audit_events
                              WHERE request_id = :request_id
                                AND action_code = :action_code
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
        except SQLAlchemyError as error:
            raise AnalysisRepositoryUnavailable("Analysis 실행 실패를 저장할 수 없습니다.") from error

    @staticmethod
    async def _save_evidence(
        session: AsyncSession, request_id, response, execution
    ) -> tuple[UUID, UUID]:
        plan = execution["plan"]
        query = execution["query"]
        package = execution["package"]
        query_execution_id = uuid4()
        result = response.data.result
        snapshot = result.table.model_dump(mode="json") if result.table else {}
        chart = result.chart.model_dump(mode="json") if result.chart else {}
        evidence = result.evidence.model_dump(mode="json")
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
        await session.execute(
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
    async def _save_audit(
        session: AsyncSession,
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
