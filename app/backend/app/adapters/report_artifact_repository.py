"""보고서가 참조할 승인 분석 artifact·snapshot·chart·checksum을 소유권 범위에서 조회한다."""

from __future__ import annotations

import json
import hashlib
import re

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.adapters.report_repository_common import _uuid
from src.report.domain import DefinitionStatus, ReportDefinitionVersion


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

    async def fail_assistant_request(
        self,
        assistant_request_id: str,
        error_code: str,
        data_request_id: str | None = None,
    ) -> None:
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
                    SET status = 'failed', error_code = :error_code, completed_at = now(),
                        phase = CASE WHEN phase IS NULL THEN NULL ELSE 'failed' END
                    WHERE assistant_request_id = :request_id AND owner_id = :owner_id
                      AND status = 'running'
                      AND (CAST(:data_request_id AS uuid) IS NULL
                           OR data_request_id = CAST(:data_request_id AS uuid))
                    """
                ),
                {
                    "error_code": error_code,
                    "request_id": _uuid(assistant_request_id, "assistant_request_id"),
                    "owner_id": self._owner_id,
                    "data_request_id": (
                        _uuid(data_request_id, "data_request_id")
                        if data_request_id is not None else None
                    ),
                },
            )

    async def start_assistant_session(
        self,
        assistant_request_id: str,
        definition_id: str,
        definition_version: int,
        artifact_id: str,
        instruction_hash: str,
        prompt_id: str,
        prompt_version: str,
        prompt_hash: str,
    ) -> dict[str, object]:
        """접근 가능한 draft와 그 block의 승인 artifact를 ``ready`` 세션으로 저장한다."""

        definition = await self.get_version(definition_id, definition_version)
        if definition.status != DefinitionStatus.DRAFT:
            raise ValueError("draft Report version만 Assistant 세션을 시작할 수 있습니다.")
        artifact_uuid = _uuid(artifact_id, "artifact_id")
        if not any(block.artifact_id == str(artifact_uuid) for block in definition.blocks):
            raise KeyError("보고서에 연결된 Analysis Artifact를 찾을 수 없습니다.")
        await self.get_assistant_artifact(artifact_id)
        async with self._sessionmaker.begin() as session:
            base_revision = (await session.execute(
                text(
                    """
                    SELECT v.revision
                    FROM report_v1.report_definition_versions v
                    JOIN report_v1.report_definitions d USING (definition_id)
                    WHERE v.definition_id = :definition_id AND v.version = :definition_version
                      AND d.owner_id = :owner_id AND v.status = 'draft'
                      AND EXISTS (
                          SELECT 1 FROM report_v1.report_blocks b
                          WHERE b.definition_id = v.definition_id
                            AND b.definition_version = v.version
                            AND b.artifact_id = :artifact_id
                      )
                    FOR SHARE
                    """
                ),
                {
                    "definition_id": _uuid(definition_id, "definition_id"),
                    "definition_version": definition_version,
                    "owner_id": self._owner_id,
                    "artifact_id": artifact_uuid,
                },
            )).scalar_one_or_none()
            if base_revision is None:
                raise ValueError("Report Assistant 기준 draft가 변경되었습니다.")
            row = (await session.execute(
                text(
                    """
                    INSERT INTO report_v1.report_assistant_requests
                        (assistant_request_id, owner_id, artifact_id, instruction_hash,
                         status, prompt_id, prompt_version, prompt_hash, phase,
                         session_definition_id, session_definition_version, base_revision)
                    VALUES (:request_id, :owner_id, :artifact_id, :instruction_hash,
                            'running', :prompt_id, :prompt_version, :prompt_hash, 'ready',
                            :definition_id, :definition_version, :base_revision)
                    RETURNING assistant_request_id, phase, session_definition_id,
                              session_definition_version, base_revision, artifact_id,
                              analysis_plan_json, result_artifact_id, result_revision,
                              error_code
                    """
                ),
                {
                    "request_id": _uuid(assistant_request_id, "assistant_request_id"),
                    "owner_id": self._owner_id,
                    "artifact_id": artifact_uuid,
                    "instruction_hash": instruction_hash,
                    "prompt_id": prompt_id,
                    "prompt_version": prompt_version,
                    "prompt_hash": prompt_hash,
                    "definition_id": _uuid(definition_id, "definition_id"),
                    "definition_version": definition_version,
                    "base_revision": int(base_revision),
                },
            )).mappings().one()
        return dict(row)

    async def get_assistant_session(self, assistant_request_id: str) -> dict[str, object]:
        """현재 소유자의 대화형 Assistant 세션을 조회하고 타인·미존재 대상은 숨긴다."""

        async with self._sessionmaker() as session:
            row = (await session.execute(
                text(
                    """
                    SELECT assistant_request_id, phase, session_definition_id,
                           session_definition_version, base_revision, artifact_id,
                           analysis_plan_json, result_artifact_id, result_revision,
                           error_code, data_request_id, patch_request_id,
                           report_patch_json, status, instruction_hash,
                           decision_hash, model_version, prompt_id,
                           prompt_version, prompt_hash,
                           approved_at, rejected_at
                    FROM report_v1.report_assistant_requests
                    WHERE assistant_request_id = :request_id AND owner_id = :owner_id
                      AND phase IS NOT NULL
                    """
                ),
                {
                    "request_id": _uuid(assistant_request_id, "assistant_request_id"),
                    "owner_id": self._owner_id,
                },
            )).mappings().one_or_none()
        if row is None:
            raise KeyError("Report Assistant 세션을 찾을 수 없습니다.")
        return dict(row)

    async def record_existing_assistant_patch_proposal(
        self,
        assistant_request_id: str,
        patch_request_id: str,
        instruction_hash: str,
        decision_hash: str,
        model_version: str,
        prompt_id: str,
        prompt_version: str,
        prompt_hash: str,
        patch: dict[str, object],
        instruction_text: str,
        assistant_message: str,
    ) -> dict[str, object]:
        """검증·dry-run된 기존 근거 patch를 적용하지 않고 사용자 승인 대기로 저장한다."""

        async with self._sessionmaker.begin() as session:
            row = (await session.execute(
                text(
                    """
                    UPDATE report_v1.report_assistant_requests
                    SET phase = 'waiting_patch_approval',
                        patch_request_id = :patch_request_id,
                        report_patch_json = CAST(:patch AS jsonb),
                        instruction_hash = :instruction_hash,
                        decision_hash = :decision_hash,
                        model_version = :model_version,
                        prompt_id = :prompt_id,
                        prompt_version = :prompt_version,
                        prompt_hash = :prompt_hash,
                        analysis_plan_json = NULL,
                        data_request_id = NULL,
                        approved_at = NULL,
                        rejected_at = NULL,
                        result_artifact_id = NULL,
                        result_query_id = NULL,
                        result_artifact_checksum = NULL,
                        result_revision = NULL,
                        error_code = NULL
                    WHERE assistant_request_id = :request_id AND owner_id = :owner_id
                      AND phase = 'ready' AND status = 'running'
                    RETURNING assistant_request_id, phase, session_definition_id,
                              session_definition_version, base_revision, artifact_id,
                              analysis_plan_json, patch_request_id, report_patch_json,
                              result_artifact_id, result_revision, error_code
                    """
                ),
                {
                    "patch_request_id": _uuid(patch_request_id, "patch_request_id"),
                    "patch": json.dumps(patch, ensure_ascii=False, sort_keys=True),
                    "instruction_hash": instruction_hash,
                    "decision_hash": decision_hash,
                    "model_version": model_version,
                    "prompt_id": prompt_id,
                    "prompt_version": prompt_version,
                    "prompt_hash": prompt_hash,
                    "request_id": _uuid(assistant_request_id, "assistant_request_id"),
                    "owner_id": self._owner_id,
                },
            )).mappings().one_or_none()
            if row is not None:
                await self._append_assistant_turn(
                    session,
                    request_uuid=_uuid(assistant_request_id, "assistant_request_id"),
                    instruction_text=instruction_text,
                    assistant_message=assistant_message,
                    change_kind="existing_artifact",
                )
        if row is None:
            raise ValueError("ready Report Assistant 세션만 patch 제안을 저장할 수 있습니다.")
        return dict(row)

    async def decide_existing_assistant_patch(
        self,
        assistant_request_id: str,
        patch_request_id: str,
        approved: bool,
    ) -> tuple[dict[str, object], bool]:
        """owner·session·patch 요청·phase를 한 CAS로 확인해 최초 결정만 claim한다."""

        request_uuid = _uuid(assistant_request_id, "assistant_request_id")
        patch_uuid = _uuid(patch_request_id, "patch_request_id")
        target_phase = "saving_revision" if approved else "ready"
        async with self._sessionmaker.begin() as session:
            claimed = (await session.execute(
                text(
                    """
                    UPDATE report_v1.report_assistant_requests
                    SET phase = :target_phase,
                        approved_at = CASE WHEN :approved THEN now() ELSE approved_at END,
                        rejected_at = CASE WHEN :approved THEN rejected_at ELSE now() END
                    WHERE assistant_request_id = :request_id AND owner_id = :owner_id
                      AND patch_request_id = :patch_request_id
                      AND phase = 'waiting_patch_approval' AND status = 'running'
                    RETURNING assistant_request_id
                    """
                ),
                {
                    "target_phase": target_phase,
                    "approved": approved,
                    "request_id": request_uuid,
                    "owner_id": self._owner_id,
                    "patch_request_id": patch_uuid,
                },
            )).scalar_one_or_none()
        current = await self.get_assistant_session(assistant_request_id)
        same_request = str(current.get("patch_request_id")) == str(patch_uuid)
        already_decided = (
            current.get("approved_at") is not None
            if approved else current.get("rejected_at") is not None
        )
        if claimed is None and (not same_request or not already_decided):
            raise ValueError("현재 승인 대기 중인 patch 요청과 일치하지 않습니다.")
        return current, claimed is not None

    async def recover_stale_assistant_session(
        self,
        assistant_request_id: str,
        stale_seconds: int,
    ) -> None:
        """중단 뒤 재실행할 수 없는 분석 phase만 owner 범위에서 typed 실패로 종결한다.

        ``saving_revision``은 고정 Artifact로 안전하게 재개할 수 있으므로 제외한다. 분석을
        다시 호출하면 중복 query가 될 수 있는 두 phase만 승인 시각 기준 timeout 뒤 실패시킨다.
        """

        if not 60 <= stale_seconds <= 86400:
            raise ValueError("Assistant stale timeout은 60~86400초여야 합니다.")
        async with self._sessionmaker.begin() as session:
            await session.execute(
                text(
                    """
                    UPDATE report_v1.report_assistant_requests
                    SET phase = 'failed', status = 'failed',
                        error_code = 'ASSISTANT_EXECUTION_INTERRUPTED',
                        completed_at = now()
                    WHERE assistant_request_id = :request_id AND owner_id = :owner_id
                      AND status = 'running'
                      AND phase IN ('running_data_agent', 'waiting_artifact')
                      AND approved_at < now() - make_interval(secs => :stale_seconds)
                    """
                ),
                {
                    "request_id": _uuid(assistant_request_id, "assistant_request_id"),
                    "owner_id": self._owner_id,
                    "stale_seconds": stale_seconds,
                },
            )

    async def record_assistant_proposal(
        self,
        assistant_request_id: str,
        instruction_hash: str,
        decision_hash: str,
        model_version: str,
        prompt_id: str,
        prompt_version: str,
        prompt_hash: str,
        analysis_plan: dict[str, object] | None,
        instruction_text: str,
        assistant_message: str,
        change_kind: str,
    ) -> dict[str, object]:
        """ready 세션에 검증된 모델 제안을 기록하고 새 데이터 계획만 승인 대기로 전이한다."""

        phase = "waiting_approval" if analysis_plan is not None else "ready"
        data_request_id = analysis_plan.get("request_id") if analysis_plan else None
        async with self._sessionmaker.begin() as session:
            row = (await session.execute(
                text(
                    """
                    UPDATE report_v1.report_assistant_requests
                    SET phase = :phase,
                        instruction_hash = :instruction_hash,
                        decision_hash = :decision_hash,
                        model_version = :model_version,
                        prompt_id = :prompt_id,
                        prompt_version = :prompt_version,
                        prompt_hash = :prompt_hash,
                        analysis_plan_json = CAST(:analysis_plan AS jsonb),
                        data_request_id = :data_request_id,
                        patch_request_id = NULL,
                        report_patch_json = NULL,
                        approved_at = NULL,
                        rejected_at = NULL,
                        result_artifact_id = NULL,
                        result_query_id = NULL,
                        result_artifact_checksum = NULL,
                        result_revision = NULL,
                        error_code = NULL
                    WHERE assistant_request_id = :request_id AND owner_id = :owner_id
                      AND phase = 'ready' AND status = 'running'
                    RETURNING assistant_request_id, phase, session_definition_id,
                              session_definition_version, base_revision, artifact_id,
                              analysis_plan_json, result_artifact_id, result_revision,
                              error_code
                    """
                ),
                {
                    "phase": phase,
                    "instruction_hash": instruction_hash,
                    "decision_hash": decision_hash,
                    "model_version": model_version,
                    "prompt_id": prompt_id,
                    "prompt_version": prompt_version,
                    "prompt_hash": prompt_hash,
                    "analysis_plan": (
                        json.dumps(analysis_plan, ensure_ascii=False, sort_keys=True)
                        if analysis_plan is not None else None
                    ),
                    "data_request_id": (
                        _uuid(str(data_request_id), "data_request_id")
                        if data_request_id is not None else None
                    ),
                    "request_id": _uuid(assistant_request_id, "assistant_request_id"),
                    "owner_id": self._owner_id,
                },
            )).mappings().one_or_none()
            if row is not None:
                await self._append_assistant_turn(
                    session,
                    request_uuid=_uuid(assistant_request_id, "assistant_request_id"),
                    instruction_text=instruction_text,
                    assistant_message=assistant_message,
                    change_kind=change_kind,
                )
        if row is None:
            raise ValueError("ready Report Assistant 세션만 변경안을 저장할 수 있습니다.")
        return dict(row)

    async def finalize_existing_assistant_patch(
        self,
        assistant_request_id: str,
        instruction_hash: str | None,
        decision_hash: str,
        model_version: str,
        prompt_id: str,
        prompt_version: str,
        prompt_hash: str,
        patch: dict[str, object],
        patched: ReportDefinitionVersion,
        *,
        instruction_text: str | None = None,
        assistant_message: str | None = None,
        change_kind: str = "existing_artifact",
        data_request_id: str | None = None,
        expected_phase: str = "ready",
    ) -> dict[str, object]:
        """검증된 Artifact patch를 기준 draft의 다음 version으로 CAS 저장한다.

        모델은 이 함수에 SQL이나 식별자를 제공하지 않는다. 서버에서 복원·검증한 불변
        ``ReportDefinitionVersion``만 저장하며 owner·session·phase·선택적 data request·base
        revision과 최신 version을 한 transaction에서 확인한다.
        """

        if patched.status is not DefinitionStatus.DRAFT:
            raise ValueError("Report Assistant patch 결과는 draft여야 합니다.")
        request_uuid = _uuid(assistant_request_id, "assistant_request_id")
        data_uuid = (
            _uuid(data_request_id, "data_request_id")
            if data_request_id is not None else None
        )
        if expected_phase not in {"ready", "saving_revision"}:
            raise ValueError("ASSISTANT_STATE_CONFLICT")
        patch_json = json.dumps(patch, ensure_ascii=False, sort_keys=True)
        output_hash = hashlib.sha256(patch_json.encode("utf-8")).hexdigest()
        try:
            async with self._sessionmaker.begin() as session:
                assistant = (await session.execute(
                    text(
                        """
                        SELECT session_definition_id, session_definition_version,
                               base_revision, artifact_id
                        FROM report_v1.report_assistant_requests
                        WHERE assistant_request_id = :request_id AND owner_id = :owner_id
                          AND phase = :expected_phase AND status = 'running'
                          AND (CAST(:data_request_id AS uuid) IS NULL
                               OR data_request_id = CAST(:data_request_id AS uuid))
                        FOR UPDATE
                        """
                    ),
                    {
                        "request_id": request_uuid,
                        "owner_id": self._owner_id,
                        "expected_phase": expected_phase,
                        "data_request_id": data_uuid,
                    },
                )).mappings().one_or_none()
                if assistant is None:
                    raise ValueError("REPORT_REVISION_CONFLICT")
                source_version = int(assistant["session_definition_version"])
                definition_id = assistant["session_definition_id"]
                if (
                    patched.definition_id != str(definition_id)
                    or patched.version != source_version
                ):
                    raise ValueError("REPORT_REVISION_CONFLICT")
                source = (await session.execute(
                    text(
                        """
                        SELECT v.revision
                        FROM report_v1.report_definition_versions v
                        JOIN report_v1.report_definitions d USING (definition_id)
                        WHERE v.definition_id = :definition_id AND v.version = :source_version
                          AND v.revision = :base_revision AND v.status = 'draft'
                          AND d.owner_id = :owner_id
                          AND NOT EXISTS (
                              SELECT 1 FROM report_v1.report_definition_versions newer
                              WHERE newer.definition_id = v.definition_id
                                AND newer.version > v.version
                          )
                        FOR UPDATE
                        """
                    ),
                    {
                        "definition_id": definition_id,
                        "source_version": source_version,
                        "base_revision": assistant["base_revision"],
                        "owner_id": self._owner_id,
                    },
                )).scalar_one_or_none()
                if source is None:
                    raise ValueError("REPORT_REVISION_CONFLICT")
                target_version = source_version + 1
                await session.execute(
                    text(
                        """
                        INSERT INTO report_v1.report_definition_versions
                            (definition_id, version, status, title,
                             orientation, currency_display_unit)
                        VALUES (:definition_id, :version, 'draft', :title,
                                :orientation, :currency_display_unit)
                        """
                    ),
                    {
                        "definition_id": definition_id,
                        "version": target_version,
                        "title": patched.title,
                        "orientation": patched.orientation,
                        "currency_display_unit": patched.currency_display_unit,
                    },
                )
                for block in patched.blocks:
                    block_artifact_id = (
                        _uuid(block.artifact_id, "artifact_id") if block.artifact_id else None
                    )
                    lineage = None
                    if block_artifact_id is not None:
                        lineage = await self._require_owned_artifact(
                            session, block_artifact_id, block.query_id
                        )
                    await session.execute(
                        text(
                            """
                            INSERT INTO report_v1.report_blocks
                                (definition_id, definition_version, block_id, title,
                                 artifact_id, query_id, columns, block_type, x, y, w, h,
                                 content, analysis_definition_id, analysis_definition_version)
                            VALUES (:definition_id, :version, :block_id, :title,
                                    :artifact_id, :query_id, :columns, :block_type,
                                    :x, :y, :w, :h, :content,
                                    :analysis_definition_id, :analysis_definition_version)
                            """
                        ),
                        {
                            "definition_id": definition_id,
                            "version": target_version,
                            "block_id": _uuid(block.block_id, "block_id"),
                            "title": block.title,
                            "artifact_id": block_artifact_id,
                            "query_id": block.query_id,
                            "columns": block.columns,
                            "block_type": block.type.value,
                            "x": block.x,
                            "y": block.y,
                            "w": block.w,
                            "h": block.h,
                            "content": block.content,
                            "analysis_definition_id": lineage[0] if lineage else None,
                            "analysis_definition_version": lineage[1] if lineage else None,
                        },
                    )
                completed = (await session.execute(
                    text(
                        """
                        UPDATE report_v1.report_assistant_requests
                        SET phase = 'completed', status = 'success',
                            definition_id = :definition_id,
                            definition_version = :target_version,
                            result_revision = :target_version,
                            instruction_hash = COALESCE(:instruction_hash, instruction_hash),
                            decision_hash = :decision_hash,
                            model_version = :model_version,
                            prompt_id = :prompt_id, prompt_version = :prompt_version,
                            prompt_hash = :prompt_hash, report_patch_json = CAST(:patch AS jsonb),
                            output_hash = :output_hash, error_code = NULL, completed_at = now()
                        WHERE assistant_request_id = :request_id AND owner_id = :owner_id
                          AND phase = :expected_phase AND status = 'running'
                          AND (CAST(:data_request_id AS uuid) IS NULL
                               OR data_request_id = CAST(:data_request_id AS uuid))
                          AND session_definition_id = :definition_id
                          AND session_definition_version = :source_version
                          AND base_revision = :base_revision
                        RETURNING assistant_request_id
                        """
                    ),
                    {
                        "definition_id": definition_id,
                        "source_version": source_version,
                        "target_version": target_version,
                        "base_revision": assistant["base_revision"],
                        "expected_phase": expected_phase,
                        "data_request_id": data_uuid,
                        "instruction_hash": instruction_hash,
                        "decision_hash": decision_hash,
                        "model_version": model_version,
                        "prompt_id": prompt_id,
                        "prompt_version": prompt_version,
                        "prompt_hash": prompt_hash,
                        "patch": patch_json,
                        "output_hash": output_hash,
                        "request_id": request_uuid,
                        "owner_id": self._owner_id,
                    },
                )).scalar_one_or_none()
                if completed is None:
                    raise ValueError("REPORT_REVISION_CONFLICT")
                if instruction_text is not None and assistant_message is not None:
                    await self._append_assistant_turn(
                        session,
                        request_uuid=request_uuid,
                        instruction_text=instruction_text,
                        assistant_message=assistant_message,
                        change_kind=change_kind,
                    )
        except IntegrityError as error:
            raise ValueError("REPORT_REVISION_CONFLICT") from error
        return await self.get_assistant_session(assistant_request_id)

    async def get_assistant_turn_history(
        self,
        assistant_request_id: str,
        limit: int = 6,
    ) -> tuple[dict[str, str], ...]:
        """owner 세션의 최근 상호작용을 시간순 role/content 메시지로 bounded 반환한다."""

        if not 1 <= limit <= 6:
            raise ValueError("Assistant history limit은 1~6이어야 합니다.")
        async with self._sessionmaker() as session:
            rows = (await session.execute(
                text(
                    """
                    SELECT t.user_instruction, t.assistant_message
                    FROM report_v1.report_assistant_turns t
                    JOIN report_v1.report_assistant_requests r
                      ON r.assistant_request_id = t.assistant_request_id
                    WHERE t.assistant_request_id = :request_id AND r.owner_id = :owner_id
                    ORDER BY t.turn_number DESC
                    LIMIT :limit
                    """
                ),
                {
                    "request_id": _uuid(assistant_request_id, "assistant_request_id"),
                    "owner_id": self._owner_id,
                    "limit": limit,
                },
            )).mappings().all()
        messages: list[dict[str, str]] = []
        for row in reversed(rows):
            messages.extend((
                {"role": "user", "content": str(row["user_instruction"])},
                {"role": "assistant", "content": str(row["assistant_message"])},
            ))
        return tuple(messages)

    async def _append_assistant_turn(
        self,
        session,
        *,
        request_uuid,
        instruction_text: str,
        assistant_message: str,
        change_kind: str,
    ) -> None:
        """잠긴 owner 세션 transaction에 다음 turn 번호를 충돌 없이 추가한다."""

        if change_kind not in {"clarification", "existing_artifact", "new_data"}:
            raise ValueError("지원하지 않는 Assistant change kind입니다.")
        inserted = (await session.execute(
            text(
                """
                INSERT INTO report_v1.report_assistant_turns
                    (assistant_request_id, turn_number, user_instruction,
                     assistant_message, change_kind)
                SELECT :request_id, COALESCE(MAX(t.turn_number), 0) + 1,
                       :instruction_text, :assistant_message, :change_kind
                FROM report_v1.report_assistant_turns t
                WHERE t.assistant_request_id = :request_id
                HAVING EXISTS (
                    SELECT 1 FROM report_v1.report_assistant_requests r
                    WHERE r.assistant_request_id = :request_id AND r.owner_id = :owner_id
                )
                RETURNING turn_number
                """
            ),
            {
                "request_id": request_uuid,
                "owner_id": self._owner_id,
                "instruction_text": instruction_text,
                "assistant_message": assistant_message,
                "change_kind": change_kind,
            },
        )).scalar_one_or_none()
        if inserted is None:
            raise ValueError("Report Assistant turn을 저장할 수 없습니다.")

    async def decide_assistant_plan(
        self,
        assistant_request_id: str,
        data_request_id: str,
        approved: bool,
    ) -> tuple[dict[str, object], bool]:
        """동일 owner·계획·대기 phase를 한 번만 claim하고 현재 세션과 claim 여부를 반환한다."""

        request_uuid = _uuid(assistant_request_id, "assistant_request_id")
        data_uuid = _uuid(data_request_id, "data_request_id")
        target_phase = "running_data_agent" if approved else "ready"
        async with self._sessionmaker.begin() as session:
            row = (await session.execute(
                text(
                    """
                    UPDATE report_v1.report_assistant_requests
                    SET phase = :target_phase,
                        approved_at = CASE WHEN :approved THEN now() ELSE approved_at END,
                        rejected_at = CASE WHEN :approved THEN rejected_at ELSE now() END
                    WHERE assistant_request_id = :request_id AND owner_id = :owner_id
                      AND data_request_id = :data_request_id
                      AND phase = 'waiting_approval' AND status = 'running'
                    RETURNING assistant_request_id
                    """
                ),
                {
                    "target_phase": target_phase,
                    "approved": approved,
                    "request_id": request_uuid,
                    "owner_id": self._owner_id,
                    "data_request_id": data_uuid,
                },
            )).scalar_one_or_none()
        current = await self.get_assistant_session(assistant_request_id)
        same_request = str(current.get("data_request_id")) == str(data_uuid)
        already_decided = (
            current.get("approved_at") is not None
            if approved else current.get("rejected_at") is not None
        )
        if row is None and (not same_request or not already_decided):
            raise ValueError("현재 승인 대기 중인 요청과 일치하지 않습니다.")
        return current, row is not None

    async def mark_assistant_waiting_artifact(
        self,
        assistant_request_id: str,
        data_request_id: str,
    ) -> dict[str, object]:
        """claim된 분석 실행을 동일 request ID의 Artifact 대기 phase로 전이한다."""

        await self._transition_assistant_phase(
            assistant_request_id,
            data_request_id,
            "running_data_agent",
            "waiting_artifact",
        )
        return await self.get_assistant_session(assistant_request_id)

    async def get_assistant_result_artifact(
        self,
        artifact_id: str,
        data_request_id: str,
        query_id: str,
    ) -> dict[str, object]:
        """승인 계획 request·owner·query에 결속된 승인 Artifact와 checksum만 반환한다."""

        async with self._sessionmaker() as session:
            row = (await session.execute(
                text(
                    """
                    SELECT a.artifact_id, a.artifact_checksum, q.trino_query_id
                    FROM artifact.analysis_artifacts a
                    JOIN query.query_executions q
                      ON q.query_execution_id = a.query_execution_id
                    JOIN chat.analysis_requests r ON r.request_id = a.request_id
                    WHERE a.artifact_id = :artifact_id
                      AND a.request_id = :data_request_id
                      AND a.status = 'APPROVED'
                      AND r.status IN ('SUCCEEDED', 'PARTIAL')
                      AND r.user_id = :owner_id
                    """
                ),
                {
                    "artifact_id": _uuid(artifact_id, "artifact_id"),
                    "data_request_id": _uuid(data_request_id, "data_request_id"),
                    "owner_id": self._owner_id,
                },
            )).mappings().one_or_none()
        if row is None:
            raise KeyError("승인 계획과 일치하는 Analysis Artifact를 찾을 수 없습니다.")
        result = dict(row)
        if str(result["trino_query_id"]) != query_id:
            raise ValueError("Analysis Artifact query lineage가 일치하지 않습니다.")
        if re.fullmatch(r"[0-9a-f]{64}", str(result["artifact_checksum"])) is None:
            raise ValueError("Analysis Artifact checksum이 유효하지 않습니다.")
        return result

    async def save_assistant_result_artifact(
        self,
        assistant_request_id: str,
        data_request_id: str,
        artifact: dict[str, object],
    ) -> dict[str, object]:
        """검증된 Artifact lineage를 저장하고 Revision 저장 대기 phase로 원자 전이한다."""

        async with self._sessionmaker.begin() as session:
            row = (await session.execute(
                text(
                    """
                    UPDATE report_v1.report_assistant_requests
                    SET phase = 'saving_revision', result_artifact_id = :artifact_id,
                        result_query_id = :query_id,
                        result_artifact_checksum = :artifact_checksum
                    WHERE assistant_request_id = :request_id AND owner_id = :owner_id
                      AND data_request_id = :data_request_id
                      AND phase = 'waiting_artifact' AND status = 'running'
                    RETURNING assistant_request_id
                    """
                ),
                {
                    "artifact_id": _uuid(str(artifact["artifact_id"]), "artifact_id"),
                    "query_id": str(artifact["trino_query_id"]),
                    "artifact_checksum": str(artifact["artifact_checksum"]),
                    "request_id": _uuid(assistant_request_id, "assistant_request_id"),
                    "owner_id": self._owner_id,
                    "data_request_id": _uuid(data_request_id, "data_request_id"),
                },
            )).scalar_one_or_none()
        if row is None:
            raise ValueError("Artifact를 저장할 Assistant phase가 일치하지 않습니다.")
        return await self.get_assistant_session(assistant_request_id)

    async def finalize_assistant_revision(
        self,
        assistant_request_id: str,
        data_request_id: str,
        output_hash: str,
    ) -> dict[str, object]:
        """검증된 Artifact를 새 draft version에 복사하고 세션을 한 transaction에서 완료한다.

        세션 owner·request·phase와 기준 draft revision을 잠근 뒤 기존 Artifact를 참조하는
        block만 새 lineage로 치환한다. 기준 revision 또는 다음 version이 바뀌면 전체
        transaction을 rollback하고 ``ValueError``로 CAS 충돌을 알린다.
        """

        request_uuid = _uuid(assistant_request_id, "assistant_request_id")
        data_uuid = _uuid(data_request_id, "data_request_id")
        try:
            async with self._sessionmaker.begin() as session:
                assistant = (await session.execute(
                    text(
                        """
                        SELECT session_definition_id, session_definition_version,
                               base_revision, artifact_id, result_artifact_id,
                               result_query_id, result_artifact_checksum
                        FROM report_v1.report_assistant_requests
                        WHERE assistant_request_id = :request_id AND owner_id = :owner_id
                          AND data_request_id = :data_request_id
                          AND phase = 'saving_revision' AND status = 'running'
                        FOR UPDATE
                        """
                    ),
                    {
                        "request_id": request_uuid,
                        "owner_id": self._owner_id,
                        "data_request_id": data_uuid,
                    },
                )).mappings().one_or_none()
                if assistant is None:
                    raise ValueError("완료할 Report Assistant 세션 상태가 일치하지 않습니다.")

                source_version = int(assistant["session_definition_version"])
                target_version = source_version + 1
                definition_id = assistant["session_definition_id"]
                source = (await session.execute(
                    text(
                        """
                        SELECT v.title, v.orientation, v.currency_display_unit
                        FROM report_v1.report_definition_versions v
                        JOIN report_v1.report_definitions d USING (definition_id)
                        WHERE v.definition_id = :definition_id AND v.version = :source_version
                          AND v.revision = :base_revision AND v.status = 'draft'
                          AND d.owner_id = :owner_id
                          AND NOT EXISTS (
                              SELECT 1 FROM report_v1.report_definition_versions newer
                              WHERE newer.definition_id = v.definition_id
                                AND newer.version > v.version
                          )
                        FOR UPDATE
                        """
                    ),
                    {
                        "definition_id": definition_id,
                        "source_version": source_version,
                        "base_revision": assistant["base_revision"],
                        "owner_id": self._owner_id,
                    },
                )).mappings().one_or_none()
                if source is None:
                    raise ValueError("REPORT_REVISION_CONFLICT")

                lineage = (await session.execute(
                    text(
                        """
                        SELECT l.definition_id, l.definition_version
                        FROM artifact.analysis_artifacts a
                        JOIN query.query_executions q
                          ON q.query_execution_id = a.query_execution_id
                        JOIN chat.analysis_requests r ON r.request_id = a.request_id
                        JOIN analysis_v1.analysis_run_links l ON l.request_id = r.request_id
                        WHERE a.artifact_id = :artifact_id
                          AND a.request_id = :data_request_id
                          AND a.artifact_checksum = :artifact_checksum
                          AND a.status = 'APPROVED'
                          AND r.status IN ('SUCCEEDED', 'PARTIAL')
                          AND r.user_id = :owner_id
                          AND q.trino_query_id = :query_id
                        """
                    ),
                    {
                        "artifact_id": assistant["result_artifact_id"],
                        "data_request_id": data_uuid,
                        "artifact_checksum": assistant["result_artifact_checksum"],
                        "owner_id": self._owner_id,
                        "query_id": assistant["result_query_id"],
                    },
                )).one_or_none()
                if lineage is None:
                    raise ValueError("ARTIFACT_LINEAGE_MISMATCH")

                replaced = (await session.execute(
                    text(
                        """
                        SELECT count(*)
                        FROM report_v1.report_blocks
                        WHERE definition_id = :definition_id
                          AND definition_version = :source_version
                          AND artifact_id = :source_artifact_id
                        """
                    ),
                    {
                        "definition_id": definition_id,
                        "source_version": source_version,
                        "source_artifact_id": assistant["artifact_id"],
                    },
                )).scalar_one()
                if int(replaced) < 1:
                    raise ValueError("REPORT_REVISION_CONFLICT")

                await session.execute(
                    text(
                        """
                        INSERT INTO report_v1.report_definition_versions
                            (definition_id, version, status, title,
                             orientation, currency_display_unit)
                        VALUES (:definition_id, :target_version, 'draft', :title,
                                :orientation, :currency_display_unit)
                        """
                    ),
                    {
                        "definition_id": definition_id,
                        "target_version": target_version,
                        "title": source["title"],
                        "orientation": source["orientation"],
                        "currency_display_unit": source["currency_display_unit"],
                    },
                )
                await session.execute(
                    text(
                        """
                        INSERT INTO report_v1.report_blocks
                            (definition_id, definition_version, block_id, title,
                             artifact_id, query_id, columns, block_type, x, y, w, h,
                             content, analysis_definition_id, analysis_definition_version)
                        SELECT b.definition_id, :target_version, b.block_id, b.title,
                               CASE WHEN b.artifact_id = :source_artifact_id
                                    THEN :result_artifact_id ELSE b.artifact_id END,
                               CASE WHEN b.artifact_id = :source_artifact_id
                                    THEN :result_query_id ELSE b.query_id END,
                               b.columns, b.block_type, b.x, b.y, b.w, b.h, b.content,
                               CASE WHEN b.artifact_id = :source_artifact_id
                                    THEN :analysis_definition_id
                                    ELSE b.analysis_definition_id END,
                               CASE WHEN b.artifact_id = :source_artifact_id
                                    THEN :analysis_definition_version
                                    ELSE b.analysis_definition_version END
                        FROM report_v1.report_blocks b
                        WHERE b.definition_id = :definition_id
                          AND b.definition_version = :source_version
                        """
                    ),
                    {
                        "definition_id": definition_id,
                        "source_version": source_version,
                        "target_version": target_version,
                        "source_artifact_id": assistant["artifact_id"],
                        "result_artifact_id": assistant["result_artifact_id"],
                        "result_query_id": assistant["result_query_id"],
                        "analysis_definition_id": lineage[0],
                        "analysis_definition_version": lineage[1],
                    },
                )
                completed = (await session.execute(
                    text(
                        """
                        UPDATE report_v1.report_assistant_requests
                        SET phase = 'completed', status = 'success',
                            definition_id = :definition_id,
                            definition_version = :target_version,
                            result_revision = :target_version,
                            output_hash = :output_hash, error_code = NULL,
                            completed_at = now()
                        WHERE assistant_request_id = :request_id AND owner_id = :owner_id
                          AND data_request_id = :data_request_id
                          AND phase = 'saving_revision' AND status = 'running'
                        RETURNING assistant_request_id
                        """
                    ),
                    {
                        "definition_id": definition_id,
                        "target_version": target_version,
                        "output_hash": output_hash,
                        "request_id": request_uuid,
                        "owner_id": self._owner_id,
                        "data_request_id": data_uuid,
                    },
                )).scalar_one_or_none()
                if completed is None:
                    raise ValueError("REPORT_REVISION_CONFLICT")
        except IntegrityError as error:
            raise ValueError("REPORT_REVISION_CONFLICT") from error
        return await self.get_assistant_session(assistant_request_id)

    async def _transition_assistant_phase(
        self,
        assistant_request_id: str,
        data_request_id: str,
        expected_phase: str,
        target_phase: str,
    ) -> None:
        """동일 owner·request의 예상 phase만 지정한 다음 phase로 전이한다."""

        async with self._sessionmaker.begin() as session:
            row = (await session.execute(
                text(
                    """
                    UPDATE report_v1.report_assistant_requests
                    SET phase = :target_phase
                    WHERE assistant_request_id = :request_id AND owner_id = :owner_id
                      AND data_request_id = :data_request_id
                      AND phase = :expected_phase AND status = 'running'
                    RETURNING assistant_request_id
                    """
                ),
                {
                    "target_phase": target_phase,
                    "expected_phase": expected_phase,
                    "request_id": _uuid(assistant_request_id, "assistant_request_id"),
                    "owner_id": self._owner_id,
                    "data_request_id": _uuid(data_request_id, "data_request_id"),
                },
            )).scalar_one_or_none()
        if row is None:
            raise ValueError("Report Assistant phase 전이에 실패했습니다.")
