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


class AnalysisDefinitionRepositoryMixin:
    """조합 저장소의 ``_sessionmaker``와 ``_owner_id``로 소유자별 분석 정의를 영속화한다.

    성공한 run에서 정의를 만들고 저장된 최신본 또는 보고서가 고정한 승인 version을
    조회한다. DB 오류는 :class:`AnalysisRepositoryUnavailable`로 경계화한다.
    """

    @staticmethod
    def _definition(row, *, replay: bool = False) -> dict[str, Any]:
        parameters = dict(row["parameters"])
        definition = {
            "contract_version": ANALYSIS_PERSISTENCE_VERSION,
            "definition_id": row["definition_id"],
            "version": row["version"],
            "status": "approved",
            "title": row["title"],
            "question": row["question_text_redacted"],
            "parameter_types": _parameter_types(parameters),
            "semantic_request": dict(row["semantic_request"]),
            "parameter_schema": dict(row["parameter_schema"]),
            "created_at": row["created_at"],
        }
        if replay:
            definition.update(question=row["question_text_redacted"], parameters=parameters)
        return definition

    async def create_definition_from_run(self, source_request_id: str | UUID, title: str) -> dict[str, Any]:
        """실행 입력의 소유권과 필드를 검증해 정의 산출물을 생성한다."""
        definition_id = uuid4()
        try:
            async with self._sessionmaker.begin() as session:
                source = (await session.execute(
                    text(
                        """
                        SELECT d.question_text_redacted, a.evidence_json
                        FROM analysis_v1.analysis_run_links l
                        JOIN analysis_v1.analysis_definitions d
                          ON d.definition_id = l.definition_id AND d.version = l.definition_version
                        JOIN chat.analysis_requests r ON r.request_id = l.request_id
                        JOIN artifact.analysis_artifacts a ON a.request_id = r.request_id
                         AND a.status = 'APPROVED'
                        WHERE l.request_id = :request_id AND d.owner_id = :owner_id
                          AND r.status IN ('SUCCEEDED', 'PARTIAL')
                        LIMIT 1
                        """
                    ),
                    {"request_id": _uuid(source_request_id, "source_request_id"), "owner_id": self._owner_id},
                )).mappings().one_or_none()
                if source is None:
                    raise ValueError("성공하거나 허용된 부분 성공 Analysis Artifact만 저장할 수 있습니다.")
                evidence = dict(source["evidence_json"])
                period = dict(evidence.get("period") or {})
                parameters = {
                    "period_start": period.get("start"),
                    "period_end_exclusive": period.get("end_exclusive"),
                }
                parameters = {key: value for key, value in parameters.items() if value is not None}
                semantic_request = {
                    "question": source["question_text_redacted"],
                    "metric_ids": [item.get("metric_id") for item in evidence.get("metrics", [])],
                    "filters": evidence.get("filters", {}),
                    "period": period,
                    "context_release": evidence.get("context_release"),
                    "policy_version": evidence.get("policy_version"),
                    "source_request_id": str(source_request_id),
                }
                parameter_schema = {key: "date" for key in parameters}
                row = (await session.execute(
                    text(
                        """
                        INSERT INTO analysis_v1.analysis_definitions
                            (definition_id, version, owner_id, title,
                             question_text_redacted, parameters_json, parameter_hash,
                             semantic_request_json, parameter_schema_json, is_saved)
                        VALUES (:definition_id, 1, :owner_id, :title,
                                :question, CAST(:parameters AS jsonb), :parameter_hash,
                                CAST(:semantic_request AS jsonb), CAST(:parameter_schema AS jsonb), true)
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
                               semantic_request_json AS semantic_request,
                               parameter_schema_json AS parameter_schema, created_at
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
                               semantic_request_json AS semantic_request,
                               parameter_schema_json AS parameter_schema, created_at
                        FROM analysis_v1.analysis_definitions
                        WHERE definition_id = :definition_id
                          AND version = :version
                          AND owner_id = :owner_id
                          AND status = 'approved'
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
