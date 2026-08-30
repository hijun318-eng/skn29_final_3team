"""소유자별 분석 정의의 생성·조회·재실행 snapshot을 PostgreSQL transaction으로 영속화한다."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.analysis_contracts import ANALYSIS_PERSISTENCE_VERSION
from app.adapters.analysis_repository_common import (
    AnalysisRepositoryUnavailable,
    _hash,
    _parameter_types,
    _uuid,
)
from app.services.analysis.semantic_request import (
    parse_approved_semantic_request_snapshot,
)


class AnalysisDefinitionRepositoryMixin:
    """조합 저장소의 ``_sessionmaker``와 ``_owner_id``로 소유자별 분석 정의를 영속화한다.

    성공한 run에서 정의를 만들고 저장된 최신본 또는 보고서가 고정한 승인 version을
    조회한다. DB 오류는 :class:`AnalysisRepositoryUnavailable`로 경계화한다.
    """

    @staticmethod
    def _public_semantic_summary(value: dict[str, Any]) -> dict[str, Any]:
        """내부 snapshot에서 사용자에게 필요한 비민감 분석 형태만 투영한다."""

        try:
            plan = parse_approved_semantic_request_snapshot(value).analysis_plan
        except (ValueError, TypeError):
            return {
                "schema_version": "ANALYSIS-SEMANTIC-SUMMARY-v1",
                "output_metric_ids": [],
                "operation": None,
                "time_mode": None,
                "time_bucket": None,
                "dimension_count": 0,
                "filter_count": 0,
                "comparison": False,
            }
        operation = str(plan["operation"])
        return {
            "schema_version": "ANALYSIS-SEMANTIC-SUMMARY-v1",
            "output_metric_ids": [str(item) for item in plan["output_metric_ids"]],
            "operation": operation,
            "time_mode": str(plan["time_mode"]),
            "time_bucket": plan["time_bucket"],
            "dimension_count": len(plan["dimension_fields"]),
            "filter_count": len(plan["filter_fields"]),
            "comparison": operation == "period_comparison",
        }

    @staticmethod
    def _definition(
        row,
        *,
        replay: bool = False,
    ) -> dict[str, Any]:
        parameters = dict(row["parameters"])
        semantic_request = dict(row["semantic_request"])
        definition = {
            "contract_version": ANALYSIS_PERSISTENCE_VERSION,
            "definition_id": row["definition_id"],
            "version": row["version"],
            "status": "approved",
            "title": row["title"],
            "question": row["question_text_redacted"],
            "parameter_types": _parameter_types(parameters),
            "semantic_request": AnalysisDefinitionRepositoryMixin._public_semantic_summary(
                semantic_request
            ),
            "parameter_schema": dict(row["parameter_schema"]),
            "created_at": row["created_at"],
        }
        if replay:
            snapshot = parse_approved_semantic_request_snapshot(
                row.get("approved_semantic_snapshot")
            )
            if (
                row.get("semantic_snapshot_id") != snapshot.snapshot_id
                or row.get("approved_snapshot_hash") != snapshot.snapshot_hash
                or semantic_request != snapshot.model_dump(mode="json")
            ):
                raise ValueError("Analysis Definition의 Semantic snapshot 결속이 일치하지 않습니다.")
            definition.update(
                question=row["question_text_redacted"],
                parameters=parameters,
                approved_semantic_snapshot=snapshot.model_dump(mode="json"),
            )
        return definition

    async def create_definition_from_run(self, source_request_id: str | UUID, title: str) -> dict[str, Any]:
        """실행 입력의 소유권과 필드를 검증해 정의 산출물을 생성한다."""
        definition_id = uuid4()
        try:
            async with self._sessionmaker.begin() as session:
                source = (await session.execute(
                    text(
                        """
                        SELECT d.question_text_redacted,
                               s.snapshot_id, s.snapshot_json, s.snapshot_hash,
                               q.query_execution_id, a.artifact_id
                        FROM analysis_v1.analysis_run_links l
                        JOIN analysis_v1.analysis_definitions d
                          ON d.definition_id = l.definition_id AND d.version = l.definition_version
                        JOIN chat.analysis_requests r ON r.request_id = l.request_id
                        JOIN artifact.analysis_artifacts a ON a.request_id = r.request_id
                         AND a.status = 'APPROVED'
                        JOIN analysis_v1.approved_semantic_request_snapshots s
                          ON s.source_request_id = l.request_id
                         AND s.owner_id = d.owner_id
                         AND s.artifact_id = a.artifact_id
                        JOIN query.query_executions q
                          ON q.query_execution_id = s.query_execution_id
                         AND q.request_id = r.request_id
                         AND a.query_execution_id = q.query_execution_id
                        WHERE l.request_id = :request_id AND d.owner_id = :owner_id
                          AND r.status IN ('SUCCEEDED', 'PARTIAL')
                        LIMIT 1
                        """
                    ),
                    {"request_id": _uuid(source_request_id, "source_request_id"), "owner_id": self._owner_id},
                )).mappings().one_or_none()
                if source is None:
                    raise ValueError("성공하거나 허용된 부분 성공 Analysis Artifact만 저장할 수 있습니다.")
                approved_snapshot = parse_approved_semantic_request_snapshot(
                    source["snapshot_json"]
                )
                if (
                    approved_snapshot.snapshot_id != source["snapshot_id"]
                    or approved_snapshot.snapshot_hash != source["snapshot_hash"]
                    or approved_snapshot.lineage.source_request_id
                    != _uuid(source_request_id, "source_request_id")
                    or approved_snapshot.lineage.query_execution_id
                    != source["query_execution_id"]
                    or approved_snapshot.lineage.artifact_id != source["artifact_id"]
                ):
                    raise ValueError("승인 Semantic Request lineage가 원본 run과 일치하지 않습니다.")
                parameters = approved_snapshot.parameters
                semantic_request = approved_snapshot.model_dump(mode="json")
                parameter_schema = {
                    item.name: item.value_type
                    for item in approved_snapshot.parameter_bindings
                }
                row = (await session.execute(
                    text(
                        """
                        INSERT INTO analysis_v1.analysis_definitions
                            (definition_id, version, owner_id, title,
                             question_text_redacted, parameters_json, parameter_hash,
                             semantic_request_json, parameter_schema_json,
                             semantic_snapshot_id, is_saved)
                        VALUES (:definition_id, 1, :owner_id, :title,
                                :question, CAST(:parameters AS jsonb), :parameter_hash,
                                CAST(:semantic_request AS jsonb), CAST(:parameter_schema AS jsonb),
                                :semantic_snapshot_id, true)
                        RETURNING definition_id, version, title, question_text_redacted,
                                  parameters_json AS parameters,
                                  semantic_request_json AS semantic_request,
                                  parameter_schema_json AS parameter_schema, created_at
                        """
                    ),
                    {
                        "definition_id": definition_id,
                        "owner_id": self._owner_id,
                        "title": title.strip(),
                        "question": source["question_text_redacted"],
                        "parameters": json.dumps(parameters, ensure_ascii=False),
                        "parameter_hash": _hash(parameters),
                        "semantic_request": json.dumps(semantic_request, ensure_ascii=False),
                        "parameter_schema": json.dumps(parameter_schema, ensure_ascii=False),
                        "semantic_snapshot_id": approved_snapshot.snapshot_id,
                    },
                )).mappings().one()
        except SQLAlchemyError as error:
            raise AnalysisRepositoryUnavailable("Analysis 저장소를 사용할 수 없습니다.") from error
        return self._definition(row)

    async def get_definition(
        self, definition_id: str | UUID, *, replay: bool = False
    ) -> dict[str, Any]:
        """현재 소유자가 저장한 ``definition_id``의 최신 version을 반환한다.

        ``replay=True``이면 재실행에 필요한 parameter 값도 포함한다. 잘못된 UUID는
        ``ValueError``, 존재하지 않거나 다른 소유자의 정의는 동일한 ``KeyError``, DB
        장애는 :class:`AnalysisRepositoryUnavailable`로 구분한다.
        """
        try:
            async with self._sessionmaker() as session:
                row = (await session.execute(
                    text(
                        """
                        SELECT definition_id, version, title, question_text_redacted,
                               parameters_json AS parameters,
                               d.semantic_request_json AS semantic_request,
                               d.parameter_schema_json AS parameter_schema, d.created_at,
                               d.semantic_snapshot_id,
                               s.snapshot_json AS approved_semantic_snapshot,
                               s.snapshot_hash AS approved_snapshot_hash
                        FROM analysis_v1.analysis_definitions d
                        LEFT JOIN analysis_v1.approved_semantic_request_snapshots s
                          ON s.snapshot_id = d.semantic_snapshot_id AND s.owner_id = d.owner_id
                        WHERE d.definition_id = :definition_id
                          AND d.owner_id = :owner_id
                          AND d.is_saved
                        ORDER BY version DESC LIMIT 1
                        """
                    ),
                    {
                        "definition_id": _uuid(definition_id, "definition_id"),
                        "owner_id": self._owner_id,
                    },
                )).mappings().one_or_none()
        except SQLAlchemyError as error:
            raise AnalysisRepositoryUnavailable("Analysis 저장소를 사용할 수 없습니다.") from error
        if row is None:
            raise KeyError("Analysis Definition을 찾을 수 없습니다.")
        return self._definition(row, replay=replay)

    async def get_definition_for_report(
        self,
        definition_id: str | UUID,
        version: int,
    ) -> dict[str, Any]:
        """보고서에 연결된 정확한 정의 레코드를 식별자와 버전으로 조회한다.

        Load the exact immutable Analysis version captured by a Report block.
        """
        try:
            async with self._sessionmaker() as session:
                row = (await session.execute(
                    text(
                        """
                        SELECT definition_id, version, title, question_text_redacted,
                               parameters_json AS parameters,
                               d.semantic_request_json AS semantic_request,
                               d.parameter_schema_json AS parameter_schema, d.created_at,
                               d.semantic_snapshot_id,
                               s.snapshot_json AS approved_semantic_snapshot,
                               s.snapshot_hash AS approved_snapshot_hash
                        FROM analysis_v1.analysis_definitions d
                        LEFT JOIN analysis_v1.approved_semantic_request_snapshots s
                          ON s.snapshot_id = d.semantic_snapshot_id AND s.owner_id = d.owner_id
                        WHERE d.definition_id = :definition_id
                          AND d.version = :version
                          AND d.owner_id = :owner_id
                          AND d.status = 'approved'
                        """
                    ),
                    {
                        "definition_id": _uuid(definition_id, "definition_id"),
                        "version": version,
                        "owner_id": self._owner_id,
                    },
                )).mappings().one_or_none()
        except SQLAlchemyError as error:
            raise AnalysisRepositoryUnavailable("Analysis repository is unavailable.") from error
        if row is None:
            raise KeyError("Analysis Definition not found")
        return self._definition(row, replay=True)

    async def list_definitions(self) -> list[dict[str, Any]]:
        """현재 owner가 명시적으로 저장한 분석 definition만 최신 생성 순서로 반환한다."""
        try:
            async with self._sessionmaker() as session:
                rows = (await session.execute(
                    text(
                        """
                        SELECT definition_id, version, title, question_text_redacted,
                               parameters_json AS parameters,
                               semantic_request_json AS semantic_request,
                               parameter_schema_json AS parameter_schema, created_at
                        FROM analysis_v1.analysis_definitions
                        WHERE owner_id = :owner_id AND is_saved
                        ORDER BY created_at DESC, definition_id DESC
                        """
                    ),
                    {"owner_id": self._owner_id},
                )).mappings()
                return [self._definition(row) for row in rows]
        except SQLAlchemyError as error:
            raise AnalysisRepositoryUnavailable("Analysis 저장소를 사용할 수 없습니다.") from error
