"""Analysis Artifact의 owner별 비파괴 보관·복원과 감사 전이를 저장한다."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.adapters.analysis_repository_common import (
    AnalysisRepositoryUnavailable,
    _uuid,
)
from src.analysis.domain import AnalysisArtifactLifecycle


class AnalysisArtifactLifecycleRepositoryMixin:
    """승인 Artifact 원본을 바꾸지 않고 현재 owner의 보관 상태만 전이한다."""

    @staticmethod
    def _validate_lifecycle_actor(actor_role: str, trace_id: str | None) -> None:
        """감사 ledger column 범위를 lifecycle transaction 전에 검증한다."""

        if not actor_role.strip() or len(actor_role) > 64:
            raise ValueError("Analysis Artifact lifecycle actor role이 유효하지 않습니다.")
        if trace_id is not None and (not trace_id.strip() or len(trace_id) > 128):
            raise ValueError("Analysis Artifact lifecycle trace ID가 유효하지 않습니다.")

    @staticmethod
    def _artifact_lifecycle(row: Mapping[str, Any]) -> AnalysisArtifactLifecycle:
        return AnalysisArtifactLifecycle(
            artifact_id=str(row["artifact_id"]),
            archived_at=row.get("archived_at"),
            archived_by=(
                str(row["archived_by"]) if row.get("archived_by") is not None else None
            ),
        )

    async def _lock_owned_artifact(
        self,
        session,
        artifact_id: UUID,
    ) -> Mapping[str, Any]:
        """승인·종단·소유 조건을 만족하는 owner request를 잠그고 lifecycle을 읽는다."""

        row = (await session.execute(
            text(
                """
                SELECT a.artifact_id, a.request_id,
                       lifecycle.archived_at, lifecycle.archived_by
                FROM artifact.analysis_artifacts a
                JOIN chat.analysis_requests r ON r.request_id = a.request_id
                LEFT JOIN artifact.user_artifact_lifecycle lifecycle
                  ON lifecycle.owner_id = r.user_id
                 AND lifecycle.artifact_id = a.artifact_id
                WHERE a.artifact_id = :artifact_id
                  AND a.status = 'APPROVED'
                  AND r.status IN ('SUCCEEDED', 'PARTIAL')
                  AND r.user_id = :owner_id
                FOR UPDATE OF r
                """
            ),
            {"artifact_id": artifact_id, "owner_id": self._owner_id},
        )).mappings().one_or_none()
        if row is None:
            # 관리 역할도 owner 우회 범위를 받지 않는다. 미존재와 비소유를 같은 404로 닫는다.
            raise KeyError("승인된 Analysis Artifact를 찾을 수 없습니다.")
        return row

    async def archive_artifact(
        self,
        artifact_id: str | UUID,
        *,
        actor_role: str,
        trace_id: str | None = None,
    ) -> AnalysisArtifactLifecycle:
        """현재 owner의 Artifact를 멱등 보관하고 진행 중 Assistant와 충돌하면 거부한다.

        불변 source Artifact가 속한 owner request row의 exclusive lock은 신규
        Report·Assistant의 key-share lock과 직렬화된다. 먼저 완료된 결속은
        기존 참조로 보존되고, 보관이 먼저면 뒤따르는 active-only 결속이 실패한다.
        """

        self._validate_lifecycle_actor(actor_role, trace_id)
        artifact_uuid = _uuid(artifact_id, "artifact_id")
        try:
            async with self._sessionmaker.begin() as session:
                current = await self._lock_owned_artifact(session, artifact_uuid)
                if current.get("archived_at") is not None:
                    return self._artifact_lifecycle(current)

                assistant_active = (await session.execute(
                    text(
                        """
                        SELECT EXISTS (
                            SELECT 1
                            FROM report_v1.report_assistant_requests assistant
                            LEFT JOIN report_v1.report_assistant_artifact_bindings binding
                              ON binding.assistant_request_id = assistant.assistant_request_id
                            WHERE assistant.owner_id = :owner_id
                              AND assistant.status = 'running'
                              AND (
                                  assistant.artifact_id = :artifact_id
                                  OR assistant.result_artifact_id = :artifact_id
                                  OR binding.artifact_id = :artifact_id
                              )
                        )
                        """
                    ),
                    {"artifact_id": artifact_uuid, "owner_id": self._owner_id},
                )).scalar_one()
                if assistant_active:
                    raise ValueError("ARTIFACT_ARCHIVE_IN_PROGRESS")

                archived = (await session.execute(
                    text(
                        """
                        INSERT INTO artifact.user_artifact_lifecycle (
                            owner_id, artifact_id, archived_at, archived_by, updated_at
                        ) VALUES (
                            :owner_id, :artifact_id, now(), :owner_id, now()
                        )
                        ON CONFLICT (owner_id, artifact_id) DO UPDATE
                        SET archived_at = now(), archived_by = EXCLUDED.archived_by,
                            updated_at = now()
                        WHERE user_artifact_lifecycle.archived_at IS NULL
                        RETURNING artifact_id, archived_at, archived_by
                        """
                    ),
                    {"artifact_id": artifact_uuid, "owner_id": self._owner_id},
                )).mappings().one_or_none()
                if archived is None:
                    # READ COMMITTED에서 source row lock을 기다리던 동시 요청은
                    # INSERT의 conflict predicate를 다시 평가한 뒤 RETURNING row를
                    # 받지 못할 수 있다. 이미 전이된 receipt를 다시 읽어 audit을
                    # 중복 기록하지 않고 같은 멱등 응답을 반환한다.
                    archived = (await session.execute(
                        text(
                            """
                            SELECT artifact_id, archived_at, archived_by
                            FROM artifact.user_artifact_lifecycle
                            WHERE owner_id = :owner_id AND artifact_id = :artifact_id
                              AND archived_at IS NOT NULL
                            """
                        ),
                        {"artifact_id": artifact_uuid, "owner_id": self._owner_id},
                    )).mappings().one()
                    return self._artifact_lifecycle(archived)
                await session.execute(
                    text(
                        """
                        INSERT INTO governance.audit_events (
                            request_id, actor_user_id, actor_role, action_code,
                            object_type, object_id, artifact_id,
                            details_json_redacted, trace_id
                        ) VALUES (
                            :request_id, :owner_id, :actor_role, 'ANALYSIS_ARTIFACT_ARCHIVED',
                            'ANALYSIS_ARTIFACT', :object_id, :artifact_id,
                            '{}'::jsonb, :trace_id
                        )
                        """
                    ),
                    {
                        "request_id": current["request_id"],
                        "owner_id": self._owner_id,
                        "actor_role": actor_role,
                        "object_id": str(artifact_uuid),
                        "artifact_id": artifact_uuid,
                        "trace_id": trace_id,
                    },
                )
                return self._artifact_lifecycle(archived)
        except SQLAlchemyError as error:
            raise AnalysisRepositoryUnavailable(
                "Analysis Artifact 보관 저장소를 사용할 수 없습니다."
            ) from error

    async def restore_artifact(
        self,
        artifact_id: str | UUID,
        *,
        actor_role: str,
        trace_id: str | None = None,
    ) -> AnalysisArtifactLifecycle:
        """현재 owner의 Artifact를 멱등 복원하고 실제 전이에만 감사 이벤트를 남긴다."""

        self._validate_lifecycle_actor(actor_role, trace_id)
        artifact_uuid = _uuid(artifact_id, "artifact_id")
        try:
            async with self._sessionmaker.begin() as session:
                current = await self._lock_owned_artifact(session, artifact_uuid)
                if current.get("archived_at") is None:
                    return self._artifact_lifecycle(current)

                restored = (await session.execute(
                    text(
                        """
                        UPDATE artifact.user_artifact_lifecycle
                        SET archived_at = NULL, archived_by = NULL,
                            updated_at = now()
                        WHERE owner_id = :owner_id AND artifact_id = :artifact_id
                          AND archived_at IS NOT NULL
                        RETURNING artifact_id, archived_at, archived_by
                        """
                    ),
                    {"artifact_id": artifact_uuid, "owner_id": self._owner_id},
                )).mappings().one_or_none()
                if restored is None:
                    # archive와 같은 이유로 대기하던 복원 요청은 조건부 UPDATE의
                    # RETURNING row를 받지 않을 수 있다. 이미 복원된 receipt를
                    # 반환해 restore audit도 실제 전이에 한 번만 기록한다.
                    restored = (await session.execute(
                        text(
                            """
                            SELECT artifact_id, archived_at, archived_by
                            FROM artifact.user_artifact_lifecycle
                            WHERE owner_id = :owner_id AND artifact_id = :artifact_id
                            """
                        ),
                        {"artifact_id": artifact_uuid, "owner_id": self._owner_id},
                    )).mappings().one()
                    return self._artifact_lifecycle(restored)
                await session.execute(
                    text(
                        """
                        INSERT INTO governance.audit_events (
                            request_id, actor_user_id, actor_role, action_code,
                            object_type, object_id, artifact_id,
                            details_json_redacted, trace_id
                        ) VALUES (
                            :request_id, :owner_id, :actor_role, 'ANALYSIS_ARTIFACT_RESTORED',
                            'ANALYSIS_ARTIFACT', :object_id, :artifact_id,
                            '{}'::jsonb, :trace_id
                        )
                        """
                    ),
                    {
                        "request_id": current["request_id"],
                        "owner_id": self._owner_id,
                        "actor_role": actor_role,
                        "object_id": str(artifact_uuid),
                        "artifact_id": artifact_uuid,
                        "trace_id": trace_id,
                    },
                )
                return self._artifact_lifecycle(restored)
        except SQLAlchemyError as error:
            raise AnalysisRepositoryUnavailable(
                "Analysis Artifact 보관 저장소를 사용할 수 없습니다."
            ) from error
