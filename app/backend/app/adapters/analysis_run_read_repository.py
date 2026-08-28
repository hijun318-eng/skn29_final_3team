"""인증 소유자 범위에서 분석 run 목록·상세·artifact를 정해진 최신순으로 조회한다."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.adapters.analysis_repository_common import (
    AnalysisRepositoryUnavailable,
    _uuid,
)
from app.analysis_contracts import ANALYSIS_PERSISTENCE_VERSION


class AnalysisRunReadRepositoryMixin:
    """현재 소유자의 분석 run과 승인 artifact를 관계 테이블에서 읽는 조회 기능을 제공한다.

    run에는 최신 Trino query와 artifact 시간 증거를 결합하고, artifact 조회에는 승인 상태와
    성공 query를 함께 요구한다. DB 오류는 :class:`AnalysisRepositoryUnavailable`로
    변환한다.
    """

    @staticmethod
    def _run(row) -> dict[str, Any]:
        status = {"DENIED": "BLOCKED"}.get(
            row["status"], row["status"]
        )
        query_cutoff = dict(row.get("query_cutoff") or {})
        period = dict(
            row["artifact_period"]
            or (query_cutoff if query_cutoff.get("start") else {})
        )
        snapshot = dict(
            row.get("artifact_snapshot")
            or (query_cutoff if query_cutoff.get("cutoff") else {})
        )
        parameters = dict(row["parameters"] or {})
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
            "question": row["question"],
            "period_start": period.get("start") or parameters.get("period_start"),
            "period_end_exclusive": period.get("end_exclusive") or parameters.get("period_end_exclusive"),
            "snapshot_cutoff": snapshot.get("cutoff"),
            "snapshot_selection": snapshot.get("selection"),
        }

    async def get_run(self, request_id: str | UUID) -> dict[str, Any]:
        """``request_id``와 현재 소유자가 일치하는 run의 상태·lineage·기간을 반환한다.

        잘못된 UUID는 ``ValueError``이고, 누락된 run과 타인 run은 모두 ``KeyError``로
        감춰 객체 존재 여부를 노출하지 않는다. DB 장애는
        :class:`AnalysisRepositoryUnavailable`로 전달한다.
        """
        try:
            async with self._sessionmaker() as session:
                row = (await session.execute(
                    text(
                        """
                        SELECT l.request_id, l.definition_id, l.definition_version,
                               l.as_of, l.timezone_name, l.parameters_json AS parameters,
                               d.question_text_redacted AS question, r.status, r.error_type,
                               r.trace_id, r.started_at, r.completed_at,
                               q.trino_query_id AS query_id,
                               q.source_cutoff_json AS query_cutoff, a.artifact_id,
                               a.evidence_json->'period' AS artifact_period,
                               a.evidence_json->'snapshot' AS artifact_snapshot
                        FROM analysis_v1.analysis_run_links l
                        JOIN analysis_v1.analysis_definitions d
                          ON d.definition_id = l.definition_id
                         AND d.version = l.definition_version
                        JOIN chat.analysis_requests r ON r.request_id = l.request_id
                        LEFT JOIN LATERAL (
                            SELECT trino_query_id, source_cutoff_json
                            FROM query.query_executions
                            WHERE request_id = r.request_id
                            ORDER BY attempt_no DESC LIMIT 1
                        ) q ON true
                        LEFT JOIN LATERAL (
                            SELECT artifact_id, evidence_json FROM artifact.analysis_artifacts
                            WHERE request_id = r.request_id LIMIT 1
                        ) a ON true
                        WHERE l.request_id = :request_id AND d.owner_id = :owner_id
                        """
                    ),
                    {
                        "request_id": _uuid(request_id, "request_id"),
                        "owner_id": self._owner_id,
                    },
                )).mappings().one_or_none()
        except SQLAlchemyError as error:
            raise AnalysisRepositoryUnavailable("Analysis 저장소를 사용할 수 없습니다.") from error
        if row is None:
            raise KeyError("Analysis Run을 찾을 수 없습니다.")
        return self._run(row)

    async def list_runs(self) -> list[dict[str, Any]]:
        """현재 owner의 run에 최신 query ID와 artifact 시간 증거를 결합해 시작 시각 역순으로 반환한다."""
        try:
            async with self._sessionmaker() as session:
                rows = (await session.execute(
                    text(
                        """
                        SELECT l.request_id, l.definition_id, l.definition_version,
                               l.as_of, l.timezone_name, l.parameters_json AS parameters,
                               d.question_text_redacted AS question, r.status, r.error_type,
                               r.trace_id, r.started_at, r.completed_at,
                               q.trino_query_id AS query_id,
                               q.source_cutoff_json AS query_cutoff, a.artifact_id,
                               a.evidence_json->'period' AS artifact_period,
                               a.evidence_json->'snapshot' AS artifact_snapshot
                        FROM analysis_v1.analysis_run_links l
                        JOIN analysis_v1.analysis_definitions d
                          ON d.definition_id = l.definition_id
                         AND d.version = l.definition_version
                        JOIN chat.analysis_requests r ON r.request_id = l.request_id
                        LEFT JOIN LATERAL (
                            SELECT trino_query_id, source_cutoff_json
                            FROM query.query_executions
                            WHERE request_id = r.request_id
                            ORDER BY attempt_no DESC LIMIT 1
                        ) q ON true
                        LEFT JOIN LATERAL (
                            SELECT artifact_id, evidence_json FROM artifact.analysis_artifacts
                            WHERE request_id = r.request_id LIMIT 1
                        ) a ON true
                        WHERE d.owner_id = :owner_id
                        ORDER BY l.created_at DESC, l.request_id DESC
                        """
                    ),
                    {"owner_id": self._owner_id},
                )).mappings()
                return [self._run(row) for row in rows]
        except SQLAlchemyError as error:
            raise AnalysisRepositoryUnavailable("Analysis 저장소를 사용할 수 없습니다.") from error

    async def get_run_artifact(self, request_id: str | UUID) -> dict[str, Any]:
        """현재 소유자 run에 연결된 승인 artifact와 성공한 Trino query 근거를 반환한다.

        반환 dict에는 snapshot·chart·evidence·checksum·query ID가 포함된다. UUID가 잘못되면
        ``ValueError``, 소유권·승인·query 성공 조건 중 하나라도 충족하지 않으면
        ``KeyError``, DB 장애면 :class:`AnalysisRepositoryUnavailable`을 발생시킨다.
        """
        try:
            async with self._sessionmaker() as session:
                row = (await session.execute(
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
                )).mappings().one_or_none()
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
            "metrics": (row["evidence"] or {}).get("metric_values", []),
            "table": row["table_data"],
            "chart": row["chart_data"] or None,
            "evidence": row["evidence"],
            "artifact_id": row["artifact_id"],
            "query_id": row["query_id"],
            "artifact_checksum": row["artifact_checksum"],
        }
