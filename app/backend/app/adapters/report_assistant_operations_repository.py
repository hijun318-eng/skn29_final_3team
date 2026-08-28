"""Report Assistant 요청별 평가와 관리자 기간 조회를 안전한 고정 SQL로 저장한다."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text


def _uuid(value: str, field: str) -> UUID:
    try:
        return UUID(str(value))
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field} must be a UUID") from error


class ReportAssistantOperationsRepositoryMixin:
    """핵심 Revision transaction과 분리된 request-scoped 평가 저장·조회 mixin이다."""

    async def count_recent_assistant_requests(self, since: object) -> int:
        """현재 owner가 지정 시각 이후 생성한 세션 수를 DB에서 계산한다."""

        async with self._sessionmaker() as session:
            value = (await session.execute(
                text(
                    """
                    SELECT count(*)
                    FROM report_v1.report_assistant_requests
                    WHERE owner_id = :owner_id AND created_at >= :since
                    """
                ),
                {"owner_id": self._owner_id, "since": since},
            )).scalar_one()
        return int(value)

    async def upsert_assistant_evaluation(
        self,
        assistant_request_id: str,
        *,
        route: str | None = None,
        operation_types: tuple[str, ...] = (),
        contract_valid: bool | None = None,
        model_attempts: int | None = None,
        latency_ms: float | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        estimated_cost: object | None = None,
        error_code: str | None = None,
        accumulate_usage: bool = False,
    ) -> dict[str, Any]:
        """세션 metadata와 안전한 관측치만 request ID 기준으로 멱등 upsert한다."""

        request_id = _uuid(assistant_request_id, "assistant_request_id")
        async with self._sessionmaker.begin() as session:
            row = (await session.execute(
                text(
                    """
                    INSERT INTO report_v1.report_assistant_evaluations
                        (evaluation_id, assistant_request_id, owner_id, data_request_id,
                         patch_request_id, definition_id, definition_version, artifact_id,
                         prompt_id, prompt_version, model_version, route, operation_types,
                         contract_valid, final_phase, model_attempts, latency_ms,
                         input_tokens, output_tokens, estimated_cost, cost_is_estimate, error_code)
                    SELECT :evaluation_id, r.assistant_request_id, r.owner_id, r.data_request_id,
                           r.patch_request_id, r.session_definition_id,
                           r.session_definition_version, r.artifact_id,
                           r.prompt_id, r.prompt_version, r.model_version, :route,
                           CAST(:operation_types AS jsonb), COALESCE(:contract_valid, false),
                           COALESCE(r.phase, 'ready'), :model_attempts, :latency_ms,
                           :input_tokens, :output_tokens,
                           CAST(:estimated_cost AS numeric(18,8)),
                           (CAST(:estimated_cost AS numeric(18,8)) IS NOT NULL), :error_code
                    FROM report_v1.report_assistant_requests r
                    WHERE r.assistant_request_id = :request_id AND r.owner_id = :owner_id
                    ON CONFLICT (assistant_request_id) DO UPDATE SET
                        data_request_id = EXCLUDED.data_request_id,
                        patch_request_id = EXCLUDED.patch_request_id,
                        definition_id = EXCLUDED.definition_id,
                        definition_version = EXCLUDED.definition_version,
                        artifact_id = EXCLUDED.artifact_id,
                        prompt_id = EXCLUDED.prompt_id,
                        prompt_version = EXCLUDED.prompt_version,
                        model_version = EXCLUDED.model_version,
                        route = COALESCE(EXCLUDED.route, report_assistant_evaluations.route),
                        operation_types = CASE
                            WHEN EXCLUDED.operation_types = '[]'::jsonb
                            THEN report_assistant_evaluations.operation_types
                            ELSE EXCLUDED.operation_types END,
                        contract_valid = COALESCE(:contract_valid,
                            report_assistant_evaluations.contract_valid),
                        final_phase = EXCLUDED.final_phase,
                        model_attempts = CASE WHEN :accumulate_usage
                            THEN CASE WHEN report_assistant_evaluations.model_attempts IS NULL
                                           AND EXCLUDED.model_attempts IS NULL THEN NULL
                                      ELSE COALESCE(report_assistant_evaluations.model_attempts, 0)
                                         + COALESCE(EXCLUDED.model_attempts, 0) END
                            ELSE COALESCE(EXCLUDED.model_attempts,
                                report_assistant_evaluations.model_attempts) END,
                        latency_ms = CASE WHEN :accumulate_usage
                            THEN CASE WHEN report_assistant_evaluations.latency_ms IS NULL
                                           AND EXCLUDED.latency_ms IS NULL THEN NULL
                                      ELSE COALESCE(report_assistant_evaluations.latency_ms, 0)
                                         + COALESCE(EXCLUDED.latency_ms, 0) END
                            ELSE COALESCE(EXCLUDED.latency_ms,
                                report_assistant_evaluations.latency_ms) END,
                        input_tokens = CASE WHEN :accumulate_usage
                            THEN CASE WHEN report_assistant_evaluations.input_tokens IS NULL
                                           AND EXCLUDED.input_tokens IS NULL THEN NULL
                                      ELSE COALESCE(report_assistant_evaluations.input_tokens, 0)
                                         + COALESCE(EXCLUDED.input_tokens, 0) END
                            ELSE COALESCE(EXCLUDED.input_tokens,
                                report_assistant_evaluations.input_tokens) END,
                        output_tokens = CASE WHEN :accumulate_usage
                            THEN CASE WHEN report_assistant_evaluations.output_tokens IS NULL
                                           AND EXCLUDED.output_tokens IS NULL THEN NULL
                                      ELSE COALESCE(report_assistant_evaluations.output_tokens, 0)
                                         + COALESCE(EXCLUDED.output_tokens, 0) END
                            ELSE COALESCE(EXCLUDED.output_tokens,
                                report_assistant_evaluations.output_tokens) END,
                        estimated_cost = CASE WHEN :accumulate_usage
                            THEN CASE WHEN report_assistant_evaluations.estimated_cost IS NULL
                                           AND EXCLUDED.estimated_cost IS NULL THEN NULL
                                      ELSE COALESCE(report_assistant_evaluations.estimated_cost, 0)
                                         + COALESCE(EXCLUDED.estimated_cost, 0) END
                            ELSE COALESCE(EXCLUDED.estimated_cost,
                                report_assistant_evaluations.estimated_cost) END,
                        cost_is_estimate = report_assistant_evaluations.cost_is_estimate
                            OR EXCLUDED.cost_is_estimate,
                        error_code = EXCLUDED.error_code,
                        evaluated_at = now()
                    RETURNING *
                    """
                ),
                {
                    "evaluation_id": uuid4(),
                    "request_id": request_id,
                    "owner_id": self._owner_id,
                    "route": route,
                    "operation_types": json.dumps(operation_types),
                    "contract_valid": contract_valid,
                    "model_attempts": model_attempts,
                    "latency_ms": latency_ms,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "estimated_cost": estimated_cost,
                    "error_code": error_code,
                    "accumulate_usage": accumulate_usage,
                },
            )).mappings().one_or_none()
        if row is None:
            raise KeyError("Report Assistant 세션을 찾을 수 없습니다.")
        return dict(row)

    async def finalize_assistant_evaluation(
        self,
        assistant_request_id: str,
        *,
        approval_decision: str | None = None,
        revision_created: bool | None = None,
        duplicate_revision_prevented: bool | None = None,
        error_code: str | None = None,
    ) -> dict[str, Any]:
        """현재 세션 phase와 승인·Revision 최종 결과를 기존 평가 한 건에 반영한다."""

        async with self._sessionmaker.begin() as session:
            row = (await session.execute(
                text(
                    """
                    UPDATE report_v1.report_assistant_evaluations e
                    SET approval_decision = COALESCE(:approval_decision, e.approval_decision),
                        final_phase = COALESCE(r.phase, e.final_phase),
                        revision_created = COALESCE(:revision_created, e.revision_created),
                        duplicate_revision_prevented = COALESCE(
                            :duplicate_revision_prevented, e.duplicate_revision_prevented),
                        error_code = COALESCE(:error_code, r.error_code, e.error_code),
                        evaluated_at = now()
                    FROM report_v1.report_assistant_requests r
                    WHERE e.assistant_request_id = :request_id
                      AND r.assistant_request_id = e.assistant_request_id
                      AND r.owner_id = :owner_id
                    RETURNING e.*
                    """
                ),
                {
                    "request_id": _uuid(assistant_request_id, "assistant_request_id"),
                    "owner_id": self._owner_id,
                    "approval_decision": approval_decision,
                    "revision_created": revision_created,
                    "duplicate_revision_prevented": duplicate_revision_prevented,
                    "error_code": error_code,
                },
            )).mappings().one_or_none()
        if row is None:
            raise KeyError("Report Assistant 평가를 찾을 수 없습니다.")
        return dict(row)

    async def get_assistant_evaluation(self, assistant_request_id: str) -> dict[str, Any]:
        """소유자 또는 manage-all 관리자만 안전한 평가 필드를 조회한다."""

        async with self._sessionmaker() as session:
            row = (await session.execute(
                text(
                    """
                    SELECT evaluation_id, assistant_request_id, data_request_id,
                           patch_request_id, definition_id, definition_version, artifact_id,
                           prompt_id, prompt_version, model_version, route, operation_types,
                           contract_valid, approval_decision, final_phase, revision_created,
                           duplicate_revision_prevented, model_attempts, latency_ms,
                           input_tokens, output_tokens, estimated_cost, cost_is_estimate,
                           error_code, evaluated_at
                    FROM report_v1.report_assistant_evaluations
                    WHERE assistant_request_id = :request_id
                      AND (:manage_all OR owner_id = :owner_id)
                    """
                ),
                {
                    "request_id": _uuid(assistant_request_id, "assistant_request_id"),
                    "owner_id": self._owner_id,
                    "manage_all": self._manage_all,
                },
            )).mappings().one_or_none()
        if row is None:
            raise KeyError("Report Assistant 평가를 찾을 수 없습니다.")
        return dict(row)

    async def list_assistant_evaluations(
        self,
        start_at: object,
        end_at: object,
        *,
        failures_only: bool = False,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """관리자에게만 bounded 기간 평가 또는 실패 목록을 반환한다."""

        if not self._manage_all:
            raise PermissionError("Report Assistant 운영 조회 권한이 없습니다.")
        async with self._sessionmaker() as session:
            rows = (await session.execute(
                text(
                    """
                    SELECT evaluation_id, assistant_request_id, data_request_id,
                           patch_request_id, definition_id, definition_version, artifact_id,
                           prompt_id, prompt_version, model_version, route, operation_types,
                           contract_valid, approval_decision, final_phase, revision_created,
                           duplicate_revision_prevented, model_attempts, latency_ms,
                           input_tokens, output_tokens, estimated_cost, cost_is_estimate,
                           error_code, evaluated_at
                    FROM report_v1.report_assistant_evaluations
                    WHERE evaluated_at >= :start_at AND evaluated_at < :end_at
                      AND (NOT :failures_only OR error_code IS NOT NULL)
                    ORDER BY evaluated_at DESC
                    LIMIT COALESCE(:limit, 2147483647)
                    """
                ),
                {
                    "start_at": start_at,
                    "end_at": end_at,
                    "failures_only": failures_only,
                    "limit": limit,
                },
            )).mappings().all()
        return [dict(row) for row in rows]
