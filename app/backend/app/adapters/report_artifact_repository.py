"""보고서가 참조할 승인 분석 artifact·snapshot·chart·checksum을 소유권 범위에서 조회한다."""

from __future__ import annotations

from sqlalchemy import text

from app.adapters.report_repository_common import _uuid


class ReportArtifactRepositoryMixin:
    """승인 분석 artifact 조회와 보고서 assistant request 상태 기록을 제공한다.

    조회는 현재 소유자의 성공·부분 성공 request에 속한 승인 artifact만 허용하고 보고서
    조회는 해당 version block 참조까지 확인한다. assistant 완료·실패 갱신도 같은
    ``_owner_id``와 ``running`` 상태를 조건으로 제한한다.
    """
    async def get_assistant_artifact(self, artifact_id: str) -> dict[str, object]:
        """assistant 입력용 승인 artifact의 narrative·chart·evidence·checksum을 반환한다.

        현재 소유자의 성공 또는 부분 성공 분석에 속하지 않으면 존재하지 않는 경우와 같은
        ``KeyError``로 감춘다. 잘못된 artifact UUID는 ``ValueError``로 거부한다.
        """
        artifact_uuid = _uuid(artifact_id, "artifact_id")
        async with self._sessionmaker() as session:
            row = (await session.execute(
                text(
                    """
                    SELECT a.artifact_id, a.title, a.narrative_markdown,
                           a.evidence_json, a.chart_spec_json, a.artifact_checksum,
                           q.trino_query_id
                    FROM artifact.analysis_artifacts a
                    JOIN query.query_executions q
                      ON q.query_execution_id = a.query_execution_id
                    JOIN chat.analysis_requests r ON r.request_id = a.request_id
                    WHERE a.artifact_id = :artifact_id
                      AND a.status = 'APPROVED'
                      AND r.status IN ('SUCCEEDED', 'PARTIAL')
                      AND r.user_id = :owner_id
                    """
                ),
                {"artifact_id": artifact_uuid, "owner_id": self._owner_id},
            )).mappings().one_or_none()
        if row is None:
            raise KeyError("승인된 Analysis Artifact를 찾을 수 없습니다.")
        return dict(row)

    async def get_transfer_artifact(self, artifact_id: str) -> dict[str, object]:
        """보고서 전송용 승인 artifact의 snapshot·chart·evidence·query ID를 반환한다.

        현재 소유자의 성공 또는 부분 성공 분석이라는 조건을 만족하지 않으면 ``KeyError``를
        발생시켜 타인 artifact의 존재를 노출하지 않는다. UUID 형식 오류는 ``ValueError``다.
        """
        artifact_uuid = _uuid(artifact_id, "artifact_id")
        async with self._sessionmaker() as session:
            row = (await session.execute(
                text(
                    """
                    SELECT a.artifact_id, a.title, a.narrative_markdown,
                           a.data_snapshot_json, a.evidence_json, a.chart_spec_json,
                           a.artifact_checksum,
                           q.trino_query_id
                    FROM artifact.analysis_artifacts a
                    JOIN query.query_executions q
                      ON q.query_execution_id = a.query_execution_id
                    JOIN chat.analysis_requests r ON r.request_id = a.request_id
                    WHERE a.artifact_id = :artifact_id
                      AND a.status = 'APPROVED'
                      AND r.status IN ('SUCCEEDED', 'PARTIAL')
                      AND r.user_id = :owner_id
                    """
                ),
                {"artifact_id": artifact_uuid, "owner_id": self._owner_id},
            )).mappings().one_or_none()
        if row is None:
            raise KeyError("본인의 승인된 Analysis Artifact를 찾을 수 없습니다.")
        return dict(row)

    async def get_report_artifact(
        self,
        definition_id: str,
        version: int,
        artifact_id: str,
    ) -> dict[str, object]:
        """보고서 version이 실제 참조하는 현재 소유자의 승인 artifact를 반환한다.

        먼저 접근 가능한 definition version의 block 참조를 확인한 뒤 artifact 소유권과 분석
        성공 상태를 검증한다. 잘못된 UUID는 ``ValueError``이며 누락·비참조·비소유·미승인은
        모두 ``KeyError``로 반환한다.
        """
        artifact_uuid = _uuid(artifact_id, "artifact_id")
        definition = await self.get_version(definition_id, version)
        if not any(block.artifact_id == str(artifact_uuid) for block in definition.blocks):
            raise KeyError("보고서에 연결된 Analysis Artifact를 찾을 수 없습니다.")
        async with self._sessionmaker() as session:
            row = (await session.execute(
                text(
                    """
                    SELECT a.artifact_id, a.title, a.narrative_markdown,
                           a.data_snapshot_json, a.evidence_json,
                           a.chart_spec_json, a.artifact_checksum,
                           q.trino_query_id
                    FROM artifact.analysis_artifacts a
                    JOIN query.query_executions q
                      ON q.query_execution_id = a.query_execution_id
                    JOIN chat.analysis_requests r ON r.request_id = a.request_id
                    WHERE a.artifact_id = :artifact_id
                      AND a.status = 'APPROVED'
                      AND r.status IN ('SUCCEEDED', 'PARTIAL')
                      AND r.user_id = :owner_id
                    """
                ),
                {"artifact_id": artifact_uuid, "owner_id": self._owner_id},
            )).mappings().one_or_none()
        if row is None:
            raise KeyError("승인된 Analysis Artifact를 찾을 수 없습니다.")
        return dict(row)

    async def start_assistant_request(
        self,
        assistant_request_id: str,
        artifact_id: str,
        instruction_hash: str,
        prompt_id: str,
        prompt_version: str,
        prompt_hash: str,
    ) -> None:
        """어시스턴트 요청 처리를 중복 실행 방지 조건과 함께 시작한다."""
        async with self._sessionmaker.begin() as session:
            await session.execute(
                text(
                    """
                    INSERT INTO report_v1.report_assistant_requests
                        (assistant_request_id, owner_id, artifact_id, instruction_hash,
                         status, prompt_id, prompt_version, prompt_hash)
                    VALUES (:request_id, :owner_id, :artifact_id, :instruction_hash,
                            'running', :prompt_id, :prompt_version, :prompt_hash)
                    """
                ),
                {
                    "request_id": _uuid(assistant_request_id, "assistant_request_id"),
                    "owner_id": self._owner_id,
                    "artifact_id": _uuid(artifact_id, "artifact_id"),
                    "instruction_hash": instruction_hash,
                    "prompt_id": prompt_id,
                    "prompt_version": prompt_version,
                    "prompt_hash": prompt_hash,
                },
            )

    async def complete_assistant_request(
        self,
        assistant_request_id: str,
        definition_id: str,
        version: int,
        model_version: str,
        output_hash: str,
    ) -> None:
        """현재 소유자의 running assistant request에 성공 output lineage를 기록한다.

        definition version·model version·output hash와 완료 시각을 한 transaction에서
        갱신한다. 일치하는 running 행이 없으면 멱등적인 no-op이며 UUID 형식 오류는
        ``ValueError``로 전달된다. 성공 반환값은 ``None``이다.
        """
        async with self._sessionmaker.begin() as session:
            await session.execute(
                text(
                    """
                    UPDATE report_v1.report_assistant_requests
                    SET status = 'success', definition_id = :definition_id,
                        definition_version = :version, model_version = :model_version,
                        output_hash = :output_hash, completed_at = now()
                    WHERE assistant_request_id = :request_id AND owner_id = :owner_id
                      AND status = 'running'
                    """
                ),
                {
                    "definition_id": _uuid(definition_id, "definition_id"),
                    "version": version,
                    "model_version": model_version,
                    "output_hash": output_hash,
                    "request_id": _uuid(assistant_request_id, "assistant_request_id"),
                    "owner_id": self._owner_id,
                },
            )

    async def fail_assistant_request(self, assistant_request_id: str, error_code: str) -> None:
        """현재 소유자의 running assistant request를 실패 code와 완료 시각으로 종결한다.

        이미 종결됐거나 소유 범위 밖인 식별자는 상태를 바꾸지 않는 no-op이다. 잘못된 request
        UUID는 ``ValueError``로 전달되고 DB 오류가 나면 transaction이 rollback된다. 성공
        반환값은 ``None``이다.
        """
        async with self._sessionmaker.begin() as session:
            await session.execute(
                text(
                    """
                    UPDATE report_v1.report_assistant_requests
                    SET status = 'failed', error_code = :error_code, completed_at = now()
                    WHERE assistant_request_id = :request_id AND owner_id = :owner_id
                      AND status = 'running'
                    """
                ),
                {
                    "error_code": error_code,
                    "request_id": _uuid(assistant_request_id, "assistant_request_id"),
                    "owner_id": self._owner_id,
                },
            )
