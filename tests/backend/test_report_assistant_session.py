"""Report Assistant 대화형 세션 계약과 공개 응답 변환을 회귀 검증한다."""

from __future__ import annotations

import inspect
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from pydantic import ValidationError
from fastapi import HTTPException

from app.api.report_router import (
    _assistant_session_response,
    _compose_assistant_revision,
    _recover_and_get_assistant_session,
    _validated_contextual_suggestions,
    report_router,
    decide_assistant_patch,
    decide_assistant_plan,
    retry_assistant_session,
    review_assistant_report,
    submit_assistant_message,
)
from app.adapters.report_artifact_repository import ReportArtifactRepositoryMixin
from app.contracts import (
    AnalysisData,
    AnalysisResponse,
    AnalysisStatus,
    ArtifactReference,
    RequestContext,
    Role,
    response_meta,
)
from app.report_contracts import (
    CreateReportAssistantSessionRequest,
    ReportAssistantAnalysisPlan,
    ReportAssistantMessageRequest,
    ReportAssistantReviewRequest,
    ReportAssistantApprovalRequest,
    ReportAssistantSessionResponse,
    ReportAssistantRequiredAction,
    report_assistant_retry_policy,
)
from src.report.domain import BlockType, DefinitionStatus, ReportBlock, ReportDefinitionVersion


class ReportAssistantSessionContractTest(unittest.TestCase):
    """서버 phase·승인 계획 계약이 추가 필드와 불완전 계획을 거부하는지 확인한다."""

    def test_ready_session_round_trips_without_analysis_plan(self) -> None:
        """ready 세션은 정의·artifact·base revision만으로 공개 계약을 만족한다."""

        assistant_request_id = uuid4()
        definition_id = uuid4()
        artifact_id = uuid4()
        response = _assistant_session_response(
            {
                "assistant_request_id": assistant_request_id,
                "phase": "ready",
                "session_definition_id": definition_id,
                "session_definition_version": 3,
                "base_revision": 3,
                "artifact_id": artifact_id,
                "analysis_plan_json": None,
                "result_artifact_id": None,
                "result_revision": None,
                "error_code": None,
            }
        )

        validated = ReportAssistantSessionResponse.model_validate(response)

        self.assertEqual("ready", validated.phase)
        self.assertEqual(3, validated.base_revision)
        self.assertIsNone(validated.analysis_plan)

    def test_contextual_suggestions_reject_internal_aliases(self) -> None:
        """후속 제안은 현재 block ID와 Artifact·근거 별칭을 사용자 문장으로 노출하지 못한다."""

        definition = ReportDefinitionVersion(
            str(uuid4()), 1, DefinitionStatus.DRAFT, "보고서",
            (ReportBlock("private-block", "차트", str(uuid4()), 12, "query", BlockType.CHART, 0, 0, 12, 7),),
        )
        artifact = {
            "narrative_markdown": "승인 요약", "evidence_json": {},
        }
        for suggestion in (
            "private-block 제목을 바꿔 줘",
            "source_artifact 차트를 추가해 줘",
            "artifact_narrative를 요약해 줘",
        ):
            with self.subTest(suggestion=suggestion), self.assertRaises(ValueError):
                _validated_contextual_suggestions([suggestion], definition, (artifact,))

    def test_create_and_recovery_routes_are_registered(self) -> None:
        """세션 생성과 새로고침 복구 경로를 보고서 router가 함께 공개한다."""

        routes = {(route.path, tuple(route.methods or ())) for route in report_router.routes}

        self.assertIn(("/reports/assistant/sessions", ("POST",)), routes)
        self.assertIn(
            ("/reports/assistant/sessions/{assistant_request_id}", ("GET",)),
            routes,
        )
        self.assertIn(
            ("/reports/assistant/sessions/{assistant_request_id}/messages", ("POST",)),
            routes,
        )
        self.assertIn(
            ("/reports/assistant/sessions/{assistant_request_id}/approval", ("POST",)),
            routes,
        )
        self.assertIn(
            ("/reports/assistant/sessions/{assistant_request_id}/patch-approval", ("POST",)),
            routes,
        )
        self.assertIn(
            ("/reports/assistant/sessions/{assistant_request_id}/retry", ("POST",)),
            routes,
        )
        self.assertIn(
            ("/reports/assistant/sessions/{assistant_request_id}/review", ("POST",)),
            routes,
        )

    def test_session_creation_rejects_unknown_client_fields(self) -> None:
        """클라이언트가 phase나 실행 권한을 주입하면 요청 계약이 거부한다."""

        with self.assertRaises(ValidationError):
            CreateReportAssistantSessionRequest.model_validate(
                {
                    "definition_id": str(uuid4()),
                    "definition_version": 1,
                    "artifact_id": str(uuid4()),
                    "phase": "running_data_agent",
                }
            )

    def test_session_creation_bounds_unique_additional_artifacts(self) -> None:
        """대표 근거를 포함한 최대 다섯 개만 허용하고 중복 Artifact를 거부한다."""

        primary = uuid4()
        valid = CreateReportAssistantSessionRequest.model_validate({
            "definition_id": str(uuid4()),
            "definition_version": 1,
            "artifact_id": str(primary),
            "additional_artifact_ids": [str(uuid4()), str(uuid4())],
        })
        self.assertEqual(2, len(valid.additional_artifact_ids))
        with self.assertRaises(ValidationError):
            CreateReportAssistantSessionRequest.model_validate({
                "definition_id": str(uuid4()),
                "definition_version": 1,
                "artifact_id": str(primary),
                "additional_artifact_ids": [str(primary)],
            })

    def test_repository_claim_and_artifact_queries_are_owner_bound(self) -> None:
        """승인 claim과 Artifact 재검증 SQL이 owner·request·phase·lineage를 함께 제한한다."""

        claim = inspect.getsource(ReportArtifactRepositoryMixin.decide_assistant_plan)
        for condition in (
            "assistant_request_id = :request_id",
            "owner_id = :owner_id",
            "data_request_id = :data_request_id",
            "phase = 'waiting_approval'",
            "status = 'running'",
            "rejected_at = CASE",
            "approved_at = CASE",
        ):
            self.assertIn(condition, claim)

        patch_claim = inspect.getsource(
            ReportArtifactRepositoryMixin.decide_existing_assistant_patch
        )
        for condition in (
            "assistant_request_id = :request_id",
            "owner_id = :owner_id",
            "patch_request_id = :patch_request_id",
            "phase = 'waiting_patch_approval'",
            "status = 'running'",
        ):
            self.assertIn(condition, patch_claim)

        artifact = inspect.getsource(
            ReportArtifactRepositoryMixin.get_assistant_result_artifact
        )
        for condition in (
            "a.request_id = :data_request_id",
            "a.status = 'APPROVED'",
            "r.status IN ('SUCCEEDED', 'PARTIAL')",
            "r.user_id = :owner_id",
            "JOIN query.query_executions",
            "trino_query_id",
            "[0-9a-f]{64}",
        ):
            self.assertIn(condition, artifact)

        finalize = inspect.getsource(
            ReportArtifactRepositoryMixin.finalize_assistant_revision
        )
        for condition in (
            "phase = 'saving_revision' AND status = 'running'",
            "v.revision = :base_revision",
            "NOT EXISTS",
            "INSERT INTO report_v1.report_definition_versions",
            "CASE WHEN b.artifact_id = :source_artifact_id",
            "a.artifact_checksum = :artifact_checksum",
            "SET phase = 'completed', status = 'success'",
            "result_revision = :target_version",
        ):
            self.assertIn(condition, finalize)

        existing_patch = inspect.getsource(
            ReportArtifactRepositoryMixin.finalize_existing_assistant_patch
        )
        for condition in (
            "assistant_request_id = :request_id AND owner_id = :owner_id",
            "phase = :expected_phase AND status = 'running'",
            "data_request_id = CAST(:data_request_id AS uuid)",
            "v.revision = :base_revision",
            "NOT EXISTS",
            "INSERT INTO report_v1.report_definition_versions",
            "INSERT INTO report_v1.report_blocks",
            "report_patch_json = CAST(:patch AS jsonb)",
            "SET phase = 'completed', status = 'success'",
            "result_revision = :target_version",
        ):
            self.assertIn(condition, existing_patch)

        recovery = inspect.getsource(
            ReportArtifactRepositoryMixin.recover_stale_assistant_session
        )
        self.assertIn("phase IN ('running_data_agent', 'waiting_artifact')", recovery)
        self.assertIn("ASSISTANT_EXECUTION_INTERRUPTED", recovery)
        self.assertNotIn("phase IN ('saving_revision'", recovery)

        history = inspect.getsource(
            ReportArtifactRepositoryMixin.get_assistant_turn_history
        )
        for condition in (
            "r.owner_id = :owner_id",
            "ORDER BY t.turn_number DESC",
            "LIMIT :limit",
            "reversed(rows)",
        ):
            self.assertIn(condition, history)

        append = inspect.getsource(
            ReportArtifactRepositoryMixin._append_assistant_turn
        )
        self.assertIn("r.owner_id = :owner_id", append)
        self.assertIn("COALESCE(MAX(t.turn_number), 0) + 1", append)
        self.assertIn("DELETE FROM report_v1.report_assistant_turns", append)
        self.assertIn("turn_number <= :last_turn_number - 6", append)

        retry = inspect.getsource(ReportArtifactRepositoryMixin.retry_assistant_session)
        for condition in (
            "source.owner_id = :owner_id",
            "source.phase = 'failed' AND source.status = 'failed'",
            "v.revision = source.base_revision",
            "AND EXISTS",
            "a.status = 'APPROVED'",
            "a.artifact_checksum ~ '^[0-9a-f]{64}$'",
            "q.trino_query_id IS NOT NULL",
            "retry_of_assistant_request_id",
            "ON CONFLICT",
        ):
            self.assertIn(condition, retry)
        self.assertNotIn("UPDATE report_v1.report_assistant_requests", retry)


class ReportAssistantRetryTest(unittest.IsolatedAsyncioTestCase):
    """실패 세션을 보존한 채 검증된 새 ready 세션만 만드는 정책을 확인한다."""

    def setUp(self) -> None:
        """동일 owner·draft·승인 Artifact를 가진 재시도 가능한 실패 세션을 준비한다."""

        self.source_id = uuid4()
        self.retry_id = uuid4()
        self.definition_id = uuid4()
        self.artifact_id = uuid4()
        self.context = RequestContext(user_id=uuid4(), role=Role.ANALYST)
        self.failed = {
            "assistant_request_id": self.source_id,
            "phase": "failed",
            "status": "failed",
            "session_definition_id": self.definition_id,
            "session_definition_version": 2,
            "base_revision": 4,
            "artifact_id": self.artifact_id,
            "analysis_plan_json": None,
            "result_artifact_id": None,
            "result_revision": None,
            "error_code": "ANALYSIS_FAILED",
        }
        self.ready = {
            **self.failed,
            "assistant_request_id": self.retry_id,
            "phase": "ready",
            "status": "running",
            "error_code": None,
            "retry_of_assistant_request_id": self.source_id,
        }

    def _repository(self) -> SimpleNamespace:
        """모델·분석·Revision 경계가 없는 재시도 repository fake를 반환한다."""

        return SimpleNamespace(
            get_assistant_session=AsyncMock(return_value=self.failed),
            get_version=AsyncMock(return_value=SimpleNamespace(
                status=DefinitionStatus.DRAFT,
            )),
            get_draft_revision=AsyncMock(return_value=4),
            get_assistant_artifact=AsyncMock(return_value={
                "artifact_checksum": "a" * 64,
                "trino_query_id": "query-1",
            }),
            retry_assistant_session=AsyncMock(return_value=self.ready),
        )

    async def test_retry_creates_new_ready_session_without_execution(self) -> None:
        """일시적 실패는 원본 ID를 lineage로 가진 새 세션만 생성한다."""

        repository = self._repository()
        with (
            patch("app.api.report_router._router", return_value=SimpleNamespace(repository=repository)),
            patch("app.api.report_router.uuid4", return_value=self.retry_id),
            patch("app.api.report_router._execute_assistant_analysis", new=AsyncMock()) as execute,
            patch("app.api.report_router._compose_assistant_revision", new=AsyncMock()) as compose,
        ):
            response = await retry_assistant_session(str(self.source_id), self.context)

        self.assertEqual(self.retry_id, response["assistant_request_id"])
        self.assertEqual("ready", response["phase"])
        self.assertEqual(self.source_id, response["retry_of_assistant_request_id"])
        self.assertFalse(response["retryable"])
        repository.retry_assistant_session.assert_awaited_once()
        repository.get_draft_revision.assert_awaited_once_with(
            str(self.failed["session_definition_id"]),
            self.failed["session_definition_version"],
        )
        execute.assert_not_awaited()
        compose.assert_not_awaited()

    async def test_duplicate_retry_returns_same_child_session(self) -> None:
        """원본 실패를 다시 재시도해도 repository의 동일 자식 세션을 그대로 반환한다."""

        repository = self._repository()
        with (
            patch("app.api.report_router._router", return_value=SimpleNamespace(repository=repository)),
            patch("app.api.report_router.uuid4", side_effect=(uuid4(), uuid4())),
        ):
            first = await retry_assistant_session(str(self.source_id), self.context)
            second = await retry_assistant_session(str(self.source_id), self.context)
        self.assertEqual(first["assistant_request_id"], second["assistant_request_id"])
        self.assertEqual(2, repository.retry_assistant_session.await_count)

    async def test_retry_policy_blocks_non_retryable_and_non_failed_sessions(self) -> None:
        """권한·checksum 오류와 failed가 아닌 phase는 새 세션 생성 전에 차단한다."""

        cases = (
            ("failed", "ANALYSIS_ACCESS_DENIED", ReportAssistantRequiredAction.REAUTHENTICATE),
            ("failed", "ARTIFACT_CHECKSUM_INVALID", ReportAssistantRequiredAction.CONTACT_ADMIN),
            ("ready", "ANALYSIS_FAILED", ReportAssistantRequiredAction.REFRESH),
        )
        for phase, error_code, action in cases:
            with self.subTest(phase=phase, error_code=error_code):
                repository = self._repository()
                repository.get_assistant_session.return_value = {
                    **self.failed,
                    "phase": phase,
                    "status": "failed" if phase == "failed" else "running",
                    "error_code": error_code,
                }
                with patch(
                    "app.api.report_router._router",
                    return_value=SimpleNamespace(repository=repository),
                ):
                    with self.assertRaises(HTTPException) as raised:
                        await retry_assistant_session(str(self.source_id), self.context)
                self.assertEqual(409, raised.exception.status_code)
                self.assertEqual(action.value, raised.exception.detail["required_action"])
                repository.retry_assistant_session.assert_not_awaited()

    async def test_retry_revalidates_revision_and_artifact(self) -> None:
        """변경된 Revision과 손상 Artifact는 각각 최신 보고서 열기와 관리자 문의로 닫는다."""

        repository = self._repository()
        repository.get_draft_revision.return_value = 5
        with patch("app.api.report_router._router", return_value=SimpleNamespace(repository=repository)):
            with self.assertRaises(HTTPException) as stale:
                await retry_assistant_session(str(self.source_id), self.context)
        self.assertEqual("REOPEN_LATEST_REPORT", stale.exception.detail["required_action"])

        repository = self._repository()
        repository.get_assistant_artifact.return_value = {
            "artifact_checksum": "invalid",
            "trino_query_id": "query-1",
        }
        with patch("app.api.report_router._router", return_value=SimpleNamespace(repository=repository)):
            with self.assertRaises(HTTPException) as artifact:
                await retry_assistant_session(str(self.source_id), self.context)
        self.assertEqual("CONTACT_ADMIN", artifact.exception.detail["required_action"])
        repository.retry_assistant_session.assert_not_awaited()

    async def test_hidden_session_is_404_and_policy_fails_closed(self) -> None:
        """타인 세션은 숨기고 알 수 없는 오류는 재시도 불가로 유지한다."""

        repository = self._repository()
        repository.get_assistant_session.side_effect = KeyError("hidden")
        with patch("app.api.report_router._router", return_value=SimpleNamespace(repository=repository)):
            with self.assertRaises(HTTPException) as hidden:
                await retry_assistant_session(str(self.source_id), self.context)
        self.assertEqual(404, hidden.exception.status_code)
        unknown = report_assistant_retry_policy("UNKNOWN_FAILURE")
        self.assertFalse(unknown.retryable)
        self.assertEqual(ReportAssistantRequiredAction.NONE, unknown.required_action)


class ReportAssistantMessageTest(unittest.IsolatedAsyncioTestCase):
    """새 데이터 모델 제안이 실행 없이 승인 대기 세션으로 저장되는지 확인한다."""

    async def test_quality_review_returns_typed_findings_without_session_or_report_write(self) -> None:
        """검토는 현재 block·근거 별칭만 반환하고 phase·patch·Revision을 만들지 않는다."""

        assistant_request_id = uuid4()
        artifact_id = uuid4()
        definition_id = uuid4()
        block_id = uuid4()
        session = {
            "assistant_request_id": assistant_request_id,
            "phase": "ready",
            "session_definition_id": definition_id,
            "session_definition_version": 2,
            "base_revision": 2,
            "artifact_id": artifact_id,
        }
        artifact = {
            "artifact_id": artifact_id,
            "title": "승인 분석",
            "narrative_markdown": "매출 지표의 승인된 요약",
            "evidence_json": {"metric_values": [{"label": "매출", "value": 120, "unit": "KRW"}]},
            "chart_spec_json": None,
            "trino_query_id": "private-query",
            "artifact_checksum": "a" * 64,
        }
        definition = ReportDefinitionVersion(
            str(definition_id), 2, DefinitionStatus.DRAFT, "현재 보고서",
            (ReportBlock(
                str(block_id), "매출 차트", str(artifact_id), 12, "private-query",
                BlockType.CHART, 0, 0, 12, 7,
            ),),
        )
        repository = SimpleNamespace(
            get_assistant_session=AsyncMock(return_value=session),
            get_assistant_artifact=AsyncMock(return_value=artifact),
            get_version=AsyncMock(return_value=definition),
        )
        model = AsyncMock(return_value=({
            "summary": "표현 한 건을 검토했습니다.",
            "suggestions": ["선택한 차트 제목을 더 간결하게 바꿔 줘"],
            "findings": [{
                "category": "title_mismatch",
                "severity": "warning",
                "block_id": str(block_id),
                "title": "차트 제목 확인",
                "detail": "제목이 승인 지표 표현과 다릅니다.",
                "suggested_instruction": "매출 차트 제목을 승인 지표 표현에 맞춰 바꿔 줘",
                "evidence_refs": ["metric_1"],
            }],
        }, {
            "model_version": "report-model",
            "prompt_id": "report.assistant.review",
            "prompt_version": "PROMPT-v1.0.0",
            "prompt_hash": "b" * 64,
            "attempts": 1,
            "duration_ms": 10.0,
            "input_tokens": 100,
            "output_tokens": 50,
        }))
        with (
            patch("app.api.report_router._router", return_value=SimpleNamespace(repository=repository)),
            patch("app.adapters.report_assistant.generate_report_quality_review", new=model),
        ):
            response = await review_assistant_report(
                str(assistant_request_id), object(), ReportAssistantReviewRequest(
                    selected_block_id=str(block_id)
                )
            )

        self.assertEqual(str(assistant_request_id), response["assistant_request_id"])
        self.assertEqual(str(block_id), response["findings"][0].block_id)
        self.assertEqual("metric_1", response["findings"][0].evidence_refs[0])
        self.assertEqual(("선택한 차트 제목을 더 간결하게 바꿔 줘",), response["suggestions"])
        self.assertEqual("chart", model.await_args.args[0]["selected_block"]["type"])
        serialized_input = repr(model.await_args.args[0])
        self.assertNotIn("private-query", serialized_input)
        self.assertNotIn("a" * 64, serialized_input)
        self.assertEqual("ready", session["phase"])
        self.assertFalse(hasattr(repository, "record_assistant_proposal"))

    async def test_quality_review_rejects_busy_phase_before_model_call(self) -> None:
        """승인 대기 등 ready가 아닌 phase에서는 검토 모델을 호출하지 않는다."""

        repository = SimpleNamespace(get_assistant_session=AsyncMock(return_value={
            "phase": "waiting_patch_approval",
        }))
        model = AsyncMock()
        with (
            patch("app.api.report_router._router", return_value=SimpleNamespace(repository=repository)),
            patch("app.adapters.report_assistant.generate_report_quality_review", new=model),
        ):
            with self.assertRaises(HTTPException) as raised:
                await review_assistant_report(str(uuid4()), object())
        self.assertEqual(409, raised.exception.status_code)
        model.assert_not_awaited()

    async def test_unknown_selected_block_is_rejected_before_model_call(self) -> None:
        """현재 Report에 없는 선택 블록은 모델 호출 전에 state conflict로 닫는다."""

        definition_id = uuid4()
        artifact_id = uuid4()
        repository = SimpleNamespace(
            get_assistant_session=AsyncMock(return_value={
                "phase": "ready", "session_definition_id": definition_id,
                "session_definition_version": 1, "artifact_id": artifact_id,
            }),
            get_assistant_artifact=AsyncMock(return_value={
                "artifact_id": artifact_id, "title": "승인 분석", "narrative_markdown": "요약",
                "evidence_json": {}, "chart_spec_json": None,
            }),
            get_version=AsyncMock(return_value=ReportDefinitionVersion(
                str(definition_id), 1, DefinitionStatus.DRAFT, "보고서", (),
            )),
        )
        model = AsyncMock()
        with (
            patch("app.api.report_router._router", return_value=SimpleNamespace(repository=repository)),
            patch("app.adapters.report_assistant.generate_report_quality_review", new=model),
        ):
            with self.assertRaises(HTTPException) as raised:
                await review_assistant_report(
                    str(uuid4()), object(), ReportAssistantReviewRequest(selected_block_id="missing")
                )
        self.assertEqual(409, raised.exception.status_code)
        model.assert_not_awaited()

    async def test_quality_review_rejects_unknown_block_or_evidence_without_write(self) -> None:
        """다른 block·Artifact 별칭을 섞은 모델 finding은 세션 변경 없이 fail-closed한다."""

        assistant_request_id = uuid4()
        artifact_id = uuid4()
        definition_id = uuid4()
        session = {
            "assistant_request_id": assistant_request_id,
            "phase": "ready",
            "session_definition_id": definition_id,
            "session_definition_version": 1,
            "artifact_id": artifact_id,
        }
        repository = SimpleNamespace(
            get_assistant_session=AsyncMock(return_value=session),
            get_assistant_artifact=AsyncMock(return_value={
                "artifact_id": artifact_id, "title": "승인 분석", "narrative_markdown": "요약",
                "evidence_json": {}, "chart_spec_json": None,
            }),
            get_version=AsyncMock(return_value=ReportDefinitionVersion(
                str(definition_id), 1, DefinitionStatus.DRAFT, "보고서", (),
            )),
        )
        model = AsyncMock(return_value=({
            "summary": "검토 결과",
            "findings": [{
                "category": "unsupported_claim", "severity": "warning",
                "block_id": "other-block", "title": "근거 확인", "detail": "근거 확인 필요",
                "suggested_instruction": "근거 없는 단정을 완화해 줘", "evidence_refs": ["metric_99"],
            }],
        }, {
            "model_version": "report-model", "prompt_id": "report.assistant.review",
            "prompt_version": "PROMPT-v1.0.0", "prompt_hash": "b" * 64,
            "attempts": 1, "duration_ms": 10.0,
        }))
        with (
            patch("app.api.report_router._router", return_value=SimpleNamespace(repository=repository)),
            patch("app.adapters.report_assistant.generate_report_quality_review", new=model),
        ):
            with self.assertRaises(HTTPException) as raised:
                await review_assistant_report(str(assistant_request_id), object())
        self.assertEqual(502, raised.exception.status_code)
        self.assertEqual("REPORT_ASSISTANT_REVIEW_INVALID", raised.exception.detail["code"])
        self.assertEqual("ready", session["phase"])

    async def test_multiple_artifacts_use_safe_aliases_and_second_binding_in_patch(self) -> None:
        """다중 근거는 실제 ID 없이 별칭으로 모델에 전달되고 두 번째 Artifact view도 dry-run된다."""

        assistant_request_id = uuid4()
        definition_id = uuid4()
        primary_id = uuid4()
        secondary_id = uuid4()
        session = {
            "assistant_request_id": assistant_request_id,
            "phase": "ready",
            "session_definition_id": definition_id,
            "session_definition_version": 1,
            "base_revision": 1,
            "artifact_id": primary_id,
        }
        definition = ReportDefinitionVersion(
            str(definition_id), 1, DefinitionStatus.DRAFT, "종합 보고서",
            (ReportBlock(
                str(uuid4()), "기존 차트", str(primary_id), 12, "private-primary-query",
                BlockType.CHART, 0, 0, 12, 7,
            ),),
        )
        artifacts = (
            {
                "artifact_id": primary_id, "title": "매출", "narrative_markdown": "승인 매출",
                "evidence_json": {}, "chart_spec_json": None,
                "trino_query_id": "private-primary-query", "artifact_checksum": "a" * 64,
            },
            {
                "artifact_id": secondary_id, "title": "객실", "narrative_markdown": "승인 객실",
                "evidence_json": {"metric_values": [{"label": "객실", "value": 80}]},
                "chart_spec_json": None,
                "trino_query_id": "private-secondary-query", "artifact_checksum": "b" * 64,
            },
        )
        waiting = {
            **session,
            "phase": "waiting_patch_approval",
            "patch_request_id": uuid4(),
            "report_patch_json": {
                "summary": "두 번째 승인 근거 표 추가",
                "operations": [{
                    "op": "add_artifact_view", "artifact_ref": "source_artifact_2",
                    "view": "table", "title": "객실 현황",
                }],
            },
        }
        repository = SimpleNamespace(
            get_assistant_session=AsyncMock(return_value=session),
            get_assistant_artifacts=AsyncMock(return_value=artifacts),
            get_assistant_turn_history=AsyncMock(return_value=()),
            get_version=AsyncMock(return_value=definition),
            record_existing_assistant_patch_proposal=AsyncMock(return_value=waiting),
        )
        model = AsyncMock(return_value=({
            "change_kind": "existing_artifact",
            "message": "두 번째 승인 근거의 표를 추가합니다.",
            "analysis_plan": None,
            "patch": {
                "summary": "두 번째 승인 근거 표 추가",
                "operations": [{
                    "op": "add_artifact_view", "artifact_ref": "source_artifact_2",
                    "view": "table", "title": "객실 현황",
                }],
            },
        }, {
            "model_version": "report-model", "prompt_id": "report.assistant.turn",
            "prompt_version": "PROMPT-v1.7.0", "prompt_hash": "c" * 64,
        }))
        with (
            patch("app.api.report_router._router", return_value=SimpleNamespace(repository=repository)),
            patch("app.adapters.report_assistant.generate_report_change_proposal", new=model),
        ):
            response = await submit_assistant_message(
                str(assistant_request_id),
                ReportAssistantMessageRequest(instruction="두 승인 결과를 표로 함께 구성해 줘"),
                object(),
            )

        payload = model.await_args.args[0]
        self.assertEqual("source_artifact", payload["artifact"]["artifact_id"])
        self.assertEqual("source_artifact_2", payload["additional_artifacts"][0]["artifact_id"])
        self.assertEqual("artifact_2_metric_1", payload["additional_artifacts"][0]["evidence"]["catalog"][1]["ref"])
        self.assertNotIn(str(primary_id), repr(payload))
        self.assertNotIn(str(secondary_id), repr(payload))
        self.assertNotIn("private-secondary-query", repr(payload))
        self.assertEqual("waiting_patch_approval", response["session"]["phase"])
        repository.record_existing_assistant_patch_proposal.assert_awaited_once()

    async def test_new_data_proposal_stops_at_waiting_approval(self) -> None:
        """서버 request ID를 붙인 계획을 한 번 저장하고 분석 실행 경계는 호출하지 않는다."""

        assistant_request_id = uuid4()
        artifact_id = uuid4()
        definition_id = uuid4()
        session = {
            "assistant_request_id": assistant_request_id,
            "phase": "ready",
            "session_definition_id": definition_id,
            "session_definition_version": 2,
            "base_revision": 2,
            "artifact_id": artifact_id,
            "analysis_plan_json": None,
            "result_artifact_id": None,
            "result_revision": None,
            "error_code": None,
        }
        repository = SimpleNamespace(
            get_assistant_session=AsyncMock(return_value=session),
            get_assistant_turn_history=AsyncMock(return_value=()),
            get_assistant_artifact=AsyncMock(return_value={
                "artifact_id": artifact_id,
                "trino_query_id": "query-1",
                "title": "승인 분석",
                "narrative_markdown": "현재 기간 결과",
                "evidence_json": {"metrics": []},
                "chart_spec_json": None,
                "artifact_checksum": "a" * 64,
            }),
            get_version=AsyncMock(return_value=ReportDefinitionVersion(
                str(definition_id),
                2,
                DefinitionStatus.DRAFT,
                "현재 보고서",
                (ReportBlock(
                    str(uuid4()), "현재 차트", str(artifact_id), 12, "query-1",
                    BlockType.CHART, 0, 0, 12, 7,
                ),),
            )),
        )

        async def save_proposal(*args):
            plan = args[7]
            return {**session, "phase": "waiting_approval", "analysis_plan_json": plan}

        repository.record_assistant_proposal = AsyncMock(side_effect=save_proposal)
        model_result = (
            {
                "change_kind": "new_data",
                "message": "직전 월 비교를 위해 승인이 필요합니다.",
                "analysis_plan": {
                    "question": "현재 지표를 직전 월과 비교해 줘",
                    "reason": "현재 Artifact에는 직전 월 값이 없습니다.",
                    "scope": {
                        "period": "현재 기간과 직전 월",
                        "metrics": ["승인 지표"],
                        "dimensions": [],
                    },
                },
                "patch": None,
            },
            {
                "model_version": "report-model",
                "prompt_id": "report.assistant.turn",
                "prompt_version": "PROMPT-v1.0.0",
                "prompt_hash": "b" * 64,
            },
        )
        with (
            patch("app.api.report_router._router", return_value=SimpleNamespace(repository=repository)),
            patch(
                "app.adapters.report_assistant.generate_report_change_proposal",
                new=AsyncMock(return_value=model_result),
            ),
        ):
            response = await submit_assistant_message(
                str(assistant_request_id),
                ReportAssistantMessageRequest(instruction="직전 월과 비교해 줘"),
                object(),
            )

        self.assertEqual("new_data", response["change_kind"])
        self.assertEqual("waiting_approval", response["session"]["phase"])
        saved_plan = repository.record_assistant_proposal.await_args.args[7]
        self.assertRegex(saved_plan["request_id"], r"^[0-9a-f-]{36}$")
        repository.record_assistant_proposal.assert_awaited_once()

    async def test_model_failure_terminates_session_for_safe_retry(self) -> None:
        """모델 장애는 평가만 남기지 않고 원본 세션을 typed failed로 종결한다."""

        from app.adapters.report_assistant import ReportAssistantModelError

        assistant_request_id = uuid4()
        artifact_id = uuid4()
        definition_id = uuid4()
        session = {
            "assistant_request_id": assistant_request_id,
            "phase": "ready",
            "session_definition_id": definition_id,
            "session_definition_version": 2,
            "base_revision": 1,
            "artifact_id": artifact_id,
            "analysis_plan_json": None,
            "result_artifact_id": None,
            "result_revision": None,
            "error_code": None,
        }
        repository = SimpleNamespace(
            get_assistant_session=AsyncMock(return_value=session),
            get_assistant_turn_history=AsyncMock(return_value=()),
            get_assistant_artifact=AsyncMock(return_value={
                "artifact_id": artifact_id,
                "trino_query_id": "query-1",
                "title": "승인 분석",
                "narrative_markdown": "현재 기간 결과",
                "evidence_json": {},
                "chart_spec_json": {"chart_type": "bar"},
                "artifact_checksum": "a" * 64,
            }),
            get_version=AsyncMock(return_value=ReportDefinitionVersion(
                str(definition_id), 2, DefinitionStatus.DRAFT, "현재 보고서", (),
            )),
            fail_assistant_request=AsyncMock(),
            upsert_assistant_evaluation=AsyncMock(),
        )
        with (
            patch("app.api.report_router._router", return_value=SimpleNamespace(repository=repository)),
            patch(
                "app.adapters.report_assistant.generate_report_change_proposal",
                new=AsyncMock(side_effect=ReportAssistantModelError("model unavailable")),
            ),
        ):
            with self.assertRaises(HTTPException) as raised:
                await submit_assistant_message(
                    str(assistant_request_id),
                    ReportAssistantMessageRequest(instruction="요약을 줄여 줘"),
                    object(),
                )

        self.assertEqual(502, raised.exception.status_code)
        repository.fail_assistant_request.assert_awaited_once_with(
            str(assistant_request_id), "REPORT_ASSISTANT_TURN_MODEL_FAILED"
        )
        repository.upsert_assistant_evaluation.assert_awaited_once()

    async def test_clarification_persists_turn_and_next_prompt_history(self) -> None:
        """모호한 지시는 ready에서 질문으로 멈추고 저장된 최근 대화를 모델에 전달한다."""

        assistant_request_id = uuid4()
        artifact_id = uuid4()
        definition_id = uuid4()
        session = {
            "assistant_request_id": assistant_request_id,
            "phase": "ready",
            "session_definition_id": definition_id,
            "session_definition_version": 2,
            "base_revision": 1,
            "artifact_id": artifact_id,
            "analysis_plan_json": None,
            "result_artifact_id": None,
            "result_revision": None,
            "error_code": None,
        }
        history = (
            {"role": "user", "content": "비교해 줘"},
            {"role": "assistant", "content": "어느 기간과 비교할까요?"},
        )
        repository = SimpleNamespace(
            get_assistant_session=AsyncMock(return_value=session),
            get_assistant_turn_history=AsyncMock(return_value=history),
            get_assistant_artifact=AsyncMock(return_value={
                "artifact_id": artifact_id, "trino_query_id": "query-1",
                "title": "승인 분석", "narrative_markdown": "현재 결과",
                "evidence_json": {}, "chart_spec_json": None,
                "artifact_checksum": "a" * 64,
            }),
            get_version=AsyncMock(return_value=ReportDefinitionVersion(
                str(definition_id), 2, DefinitionStatus.DRAFT, "현재 보고서", (),
            )),
            record_assistant_proposal=AsyncMock(return_value=session),
            finalize_existing_assistant_patch=AsyncMock(),
        )
        model = AsyncMock(return_value=({
            "change_kind": "clarification",
            "message": "어느 지표를 비교할까요?",
            "analysis_plan": None,
            "patch": None,
            "suggestions": [],
        }, {
            "model_version": "report-model",
            "prompt_id": "report.assistant.turn",
            "prompt_version": "PROMPT-v1.4.0",
            "prompt_hash": "b" * 64,
        }))
        with (
            patch("app.api.report_router._router", return_value=SimpleNamespace(repository=repository)),
            patch(
                "app.adapters.report_assistant.generate_report_change_proposal",
                new=model,
            ),
        ):
            response = await submit_assistant_message(
                str(assistant_request_id),
                ReportAssistantMessageRequest(instruction="매출 지표로 해 줘"),
                object(),
            )

        self.assertEqual("clarification", response["change_kind"])
        self.assertEqual("ready", response["session"]["phase"])
        self.assertEqual(list(history), model.await_args.args[0]["history"])
        saved = repository.record_assistant_proposal.await_args.args
        self.assertIsNone(saved[7])
        self.assertEqual("매출 지표로 해 줘", saved[8])
        self.assertEqual("clarification", saved[10])
        repository.finalize_existing_assistant_patch.assert_not_awaited()

    async def test_existing_artifact_patch_stops_for_user_approval(self) -> None:
        """기존 근거 요청은 서버 dry-run 뒤 Revision 저장 없이 patch 승인 대기에서 멈춘다."""

        assistant_request_id = uuid4()
        artifact_id = uuid4()
        definition_id = uuid4()
        block_id = uuid4()
        session = {
            "assistant_request_id": assistant_request_id,
            "phase": "ready",
            "session_definition_id": definition_id,
            "session_definition_version": 2,
            "base_revision": 1,
            "artifact_id": artifact_id,
            "analysis_plan_json": None,
            "result_artifact_id": None,
            "result_revision": None,
            "error_code": None,
        }
        definition = ReportDefinitionVersion(
            str(definition_id), 2, DefinitionStatus.DRAFT, "현재 보고서",
            (ReportBlock(
                str(block_id), "현재 차트", str(artifact_id), 12, "query-1",
                BlockType.CHART, 0, 0, 12, 7,
            ),),
        )
        waiting = {
            **session,
            "phase": "waiting_patch_approval",
            "patch_request_id": uuid4(),
            "report_patch_json": {
                "summary": "기존 근거 요약 추가",
                "operations": [{
                    "op": "add_text", "title": "경영 요약",
                    "content": "현재 승인 근거의 요약입니다.",
                    "evidence_refs": ["artifact_narrative"],
                    "placement": {"after_block_id": str(block_id), "width": "full"},
                }],
            },
        }
        repository = SimpleNamespace(
            get_assistant_session=AsyncMock(return_value=session),
            get_assistant_turn_history=AsyncMock(return_value=()),
            get_assistant_artifact=AsyncMock(return_value={
                "artifact_id": artifact_id,
                "trino_query_id": "query-1",
                "title": "승인 분석",
                "narrative_markdown": "현재 기간 결과",
                "evidence_json": {},
                "chart_spec_json": {"chart_type": "bar"},
                "artifact_checksum": "a" * 64,
            }),
            get_version=AsyncMock(return_value=definition),
            record_assistant_proposal=AsyncMock(),
            record_existing_assistant_patch_proposal=AsyncMock(return_value=waiting),
            finalize_existing_assistant_patch=AsyncMock(),
        )
        model_result = ({
            "change_kind": "existing_artifact",
            "message": "기존 근거로 요약을 추가합니다.",
            "analysis_plan": None,
            "patch": {
                "summary": "기존 근거 요약 추가",
                "operations": [{
                    "op": "add_text",
                    "title": "경영 요약",
                    "content": "현재 승인 근거의 요약입니다.",
                    "evidence_refs": ["artifact_narrative"],
                    "placement": {"after_block_id": str(block_id), "width": "full"},
                }],
            },
        }, {
            "model_version": "report-model",
            "prompt_id": "report.assistant.turn",
            "prompt_version": "PROMPT-v1.4.0",
            "prompt_hash": "b" * 64,
        })
        with (
            patch("app.api.report_router._router", return_value=SimpleNamespace(repository=repository)),
            patch(
                "app.adapters.report_assistant.generate_report_change_proposal",
                new=AsyncMock(return_value=model_result),
            ),
        ):
            response = await submit_assistant_message(
                str(assistant_request_id),
                ReportAssistantMessageRequest(instruction="경영 요약을 추가해 줘"),
                object(),
            )

        self.assertEqual("waiting_patch_approval", response["session"]["phase"])
        self.assertEqual("기존 근거 요약 추가", response["session"]["patch_summary"])
        self.assertEqual(("add_text",), response["session"]["patch_operations"])
        self.assertEqual(("artifact_narrative",), response["session"]["patch_evidence_refs"])
        repository.record_assistant_proposal.assert_not_awaited()
        repository.record_existing_assistant_patch_proposal.assert_awaited_once()
        repository.finalize_existing_assistant_patch.assert_not_awaited()

    async def test_waiting_patch_can_be_replaced_without_saving_revision(self) -> None:
        """현재 patch request ID의 재수정만 새 dry-run patch로 교환하고 Report는 저장하지 않는다."""

        assistant_request_id = uuid4()
        artifact_id = uuid4()
        definition_id = uuid4()
        block_id = uuid4()
        old_patch_request_id = uuid4()
        session = {
            "assistant_request_id": assistant_request_id,
            "phase": "waiting_patch_approval",
            "session_definition_id": definition_id,
            "session_definition_version": 2,
            "base_revision": 1,
            "artifact_id": artifact_id,
            "analysis_plan_json": None,
            "patch_request_id": old_patch_request_id,
            "report_patch_json": {
                "summary": "요약과 차트 위치 변경",
                "operations": [{
                    "op": "reposition_block", "block_id": str(block_id),
                    "after_block_id": None, "width": "half",
                }],
            },
            "result_artifact_id": None,
            "result_revision": None,
            "error_code": None,
        }
        definition = ReportDefinitionVersion(
            str(definition_id), 2, DefinitionStatus.DRAFT, "현재 보고서",
            (ReportBlock(
                str(block_id), "현재 차트", str(artifact_id), 12, "query-1",
                BlockType.CHART, 0, 0, 12, 7,
            ),),
        )
        repository = SimpleNamespace(
            get_assistant_session=AsyncMock(return_value=session),
            get_assistant_turn_history=AsyncMock(return_value=()),
            get_assistant_artifact=AsyncMock(return_value={
                "artifact_id": artifact_id, "trino_query_id": "query-1",
                "title": "승인 분석", "narrative_markdown": "현재 결과",
                "evidence_json": {}, "chart_spec_json": None,
                "artifact_checksum": "a" * 64,
            }),
            get_version=AsyncMock(return_value=definition),
            record_existing_assistant_patch_proposal=AsyncMock(),
            replace_existing_assistant_patch_proposal=AsyncMock(),
            finalize_existing_assistant_patch=AsyncMock(),
        )

        async def replace(*args):
            return {
                **session,
                "patch_request_id": uuid4(),
                "report_patch_json": args[9],
            }

        repository.replace_existing_assistant_patch_proposal.side_effect = replace
        model = AsyncMock(return_value=({
            "change_kind": "existing_artifact",
            "message": "차트 위치는 유지하고 제목만 바꿉니다.",
            "analysis_plan": None,
            "patch": {
                "summary": "제목만 변경",
                "operations": [{"op": "set_report_title", "title": "간결한 보고서"}],
            },
        }, {
            "model_version": "report-model",
            "prompt_id": "report.assistant.turn",
            "prompt_version": "PROMPT-v1.5.0",
            "prompt_hash": "b" * 64,
        }))
        with (
            patch("app.api.report_router._router", return_value=SimpleNamespace(repository=repository)),
            patch("app.adapters.report_assistant.generate_report_change_proposal", new=model),
        ):
            response = await submit_assistant_message(
                str(assistant_request_id),
                ReportAssistantMessageRequest(
                    instruction="차트 위치는 유지하고 제목만 바꿔 줘",
                    expected_patch_request_id=old_patch_request_id,
                ),
                object(),
            )

        self.assertEqual("waiting_patch_approval", response["session"]["phase"])
        self.assertEqual(("set_report_title",), response["session"]["patch_operations"])
        self.assertEqual(
            str(old_patch_request_id),
            repository.replace_existing_assistant_patch_proposal.await_args.args[1],
        )
        self.assertEqual("요약과 차트 위치 변경", model.await_args.args[0]["current_patch"]["summary"])
        repository.record_existing_assistant_patch_proposal.assert_not_awaited()
        repository.finalize_existing_assistant_patch.assert_not_awaited()

    async def test_stale_patch_refinement_is_rejected_before_model_call(self) -> None:
        """현재 patch와 다른 재수정 request ID는 모델·Report 저장 경계 전에 409로 닫는다."""

        repository = SimpleNamespace(get_assistant_session=AsyncMock(return_value={
            "phase": "waiting_patch_approval",
            "patch_request_id": uuid4(),
        }))
        model = AsyncMock()
        with (
            patch("app.api.report_router._router", return_value=SimpleNamespace(repository=repository)),
            patch("app.adapters.report_assistant.generate_report_change_proposal", new=model),
        ):
            with self.assertRaises(HTTPException) as raised:
                await submit_assistant_message(
                    str(uuid4()),
                    ReportAssistantMessageRequest(
                        instruction="요약만 바꿔 줘",
                        expected_patch_request_id=uuid4(),
                    ),
                    object(),
                )

        self.assertEqual(409, raised.exception.status_code)
        self.assertEqual("ASSISTANT_STATE_CONFLICT", raised.exception.detail["code"])
        model.assert_not_awaited()

    async def test_restore_previous_revision_is_dry_run_before_approval(self) -> None:
        """직전 version 복원도 현재 source를 바꾸지 않고 승인 가능한 patch로만 저장한다."""

        assistant_request_id = uuid4()
        artifact_id = uuid4()
        definition_id = uuid4()
        current_block_id = uuid4()
        previous_block_id = uuid4()
        session = {
            "assistant_request_id": assistant_request_id,
            "phase": "ready",
            "session_definition_id": definition_id,
            "session_definition_version": 2,
            "base_revision": 1,
            "artifact_id": artifact_id,
            "analysis_plan_json": None,
            "result_artifact_id": None,
            "result_revision": None,
            "error_code": None,
        }
        current = ReportDefinitionVersion(
            str(definition_id), 2, DefinitionStatus.DRAFT, "현재 보고서",
            (ReportBlock(
                str(current_block_id), "현재 차트", str(artifact_id), 12, "query-1",
                BlockType.CHART, 0, 0, 12, 7,
            ),),
        )
        previous = ReportDefinitionVersion(
            str(definition_id), 1, DefinitionStatus.DRAFT, "직전 보고서",
            (ReportBlock(
                str(previous_block_id), "직전 요약", None, 12, None,
                BlockType.TEXT, 0, 0, 12, 4, "복원할 내용",
            ),),
            orientation="landscape",
        )
        waiting = {
            **session,
            "phase": "waiting_patch_approval",
            "patch_request_id": uuid4(),
            "report_patch_json": {
                "summary": "직전 revision 복원",
                "operations": [{"op": "restore_previous_revision"}],
            },
        }
        repository = SimpleNamespace(
            get_assistant_session=AsyncMock(return_value=session),
            get_assistant_turn_history=AsyncMock(return_value=()),
            get_assistant_artifact=AsyncMock(return_value={
                "artifact_id": artifact_id,
                "trino_query_id": "query-1",
                "title": "승인 분석",
                "narrative_markdown": "현재 기간 결과",
                "evidence_json": {},
                "chart_spec_json": {"chart_type": "bar"},
                "artifact_checksum": "a" * 64,
            }),
            get_version=AsyncMock(side_effect=(current, previous)),
            record_assistant_proposal=AsyncMock(),
            record_existing_assistant_patch_proposal=AsyncMock(return_value=waiting),
            finalize_existing_assistant_patch=AsyncMock(),
        )
        model_result = ({
            "change_kind": "existing_artifact",
            "message": "직전 revision을 새 revision으로 복원합니다.",
            "analysis_plan": None,
            "patch": {
                "summary": "직전 revision 복원",
                "operations": [{"op": "restore_previous_revision"}],
            },
        }, {
            "model_version": "report-model",
            "prompt_id": "report.assistant.turn",
            "prompt_version": "PROMPT-v1.4.0",
            "prompt_hash": "b" * 64,
        })
        with (
            patch("app.api.report_router._router", return_value=SimpleNamespace(repository=repository)),
            patch(
                "app.adapters.report_assistant.generate_report_change_proposal",
                new=AsyncMock(return_value=model_result),
            ),
        ):
            response = await submit_assistant_message(
                str(assistant_request_id),
                ReportAssistantMessageRequest(instruction="방금 변경을 이전으로 되돌려 줘"),
                object(),
            )

        self.assertEqual("waiting_patch_approval", response["session"]["phase"])
        self.assertEqual(2, repository.get_version.await_count)
        repository.get_version.assert_any_await(str(definition_id), 1)
        repository.record_existing_assistant_patch_proposal.assert_awaited_once()
        repository.finalize_existing_assistant_patch.assert_not_awaited()


class ReportAssistantPatchApprovalTest(unittest.IsolatedAsyncioTestCase):
    """기존 Artifact patch가 승인 전 무저장이고 최초 승인만 Revision을 만드는지 검증한다."""

    def _session(self) -> dict[str, object]:
        patch_request_id = uuid4()
        definition_id = uuid4()
        artifact_id = uuid4()
        return {
            "assistant_request_id": uuid4(),
            "phase": "waiting_patch_approval",
            "session_definition_id": definition_id,
            "session_definition_version": 2,
            "base_revision": 1,
            "artifact_id": artifact_id,
            "analysis_plan_json": None,
            "patch_request_id": patch_request_id,
            "report_patch_json": {
                "summary": "요약 블록 추가",
                "operations": [{
                    "op": "add_text", "title": "요약", "content": "승인 근거 요약",
                    "evidence_refs": ["artifact_narrative"],
                    "placement": {"width": "full"},
                }],
            },
            "instruction_hash": "a" * 64,
            "decision_hash": "b" * 64,
            "model_version": "report-model",
            "prompt_id": "report.assistant.turn",
            "prompt_version": "PROMPT-v1.4.0",
            "prompt_hash": "c" * 64,
            "status": "running",
            "approved_at": None,
            "rejected_at": None,
            "result_artifact_id": None,
            "result_revision": None,
            "error_code": None,
        }

    async def test_approval_creates_revision_and_rejection_does_not(self) -> None:
        """같은 patch 요청의 승인만 저장기를 호출하고 거절은 ready로 돌아간다."""

        waiting = self._session()
        definition = ReportDefinitionVersion(
            str(waiting["session_definition_id"]), 2, DefinitionStatus.DRAFT, "보고서",
            (ReportBlock(
                str(uuid4()), "차트", str(waiting["artifact_id"]), 12, "query-1",
                BlockType.CHART, 0, 0, 12, 7,
            ),),
        )
        saving = {**waiting, "phase": "saving_revision", "approved_at": object()}
        completed = {**saving, "phase": "completed", "status": "success", "result_revision": 3}
        repository = SimpleNamespace(
            decide_existing_assistant_patch=AsyncMock(return_value=(saving, True)),
            get_version=AsyncMock(return_value=definition),
            get_assistant_artifact=AsyncMock(return_value={
                "artifact_id": waiting["artifact_id"], "trino_query_id": "query-1",
                "artifact_checksum": "d" * 64,
            }),
            finalize_existing_assistant_patch=AsyncMock(return_value=completed),
            fail_assistant_request=AsyncMock(),
        )
        with (
            patch("app.api.report_router._router", return_value=SimpleNamespace(repository=repository)),
            patch("app.api.report_router._recover_and_get_assistant_session", new=AsyncMock(return_value=waiting)),
        ):
            response = await decide_assistant_patch(
                str(waiting["assistant_request_id"]),
                ReportAssistantApprovalRequest(
                    request_id=waiting["patch_request_id"], approved=True
                ),
                object(),
            )

        self.assertEqual("completed", response["phase"])
        self.assertEqual(3, response["result_revision"])
        repository.finalize_existing_assistant_patch.assert_awaited_once()
        repository.fail_assistant_request.assert_not_awaited()

        rejected = {**waiting, "phase": "ready", "rejected_at": object()}
        reject_repository = SimpleNamespace(
            decide_existing_assistant_patch=AsyncMock(return_value=(rejected, True)),
            finalize_existing_assistant_patch=AsyncMock(),
        )
        with (
            patch("app.api.report_router._router", return_value=SimpleNamespace(repository=reject_repository)),
            patch("app.api.report_router._recover_and_get_assistant_session", new=AsyncMock(return_value=waiting)),
        ):
            response = await decide_assistant_patch(
                str(waiting["assistant_request_id"]),
                ReportAssistantApprovalRequest(
                    request_id=waiting["patch_request_id"], approved=False
                ),
                object(),
            )

        self.assertEqual("ready", response["phase"])
        reject_repository.finalize_existing_assistant_patch.assert_not_awaited()


class ReportAssistantComposeTest(unittest.IsolatedAsyncioTestCase):
    """새 분석 결과가 두 번째 strict 모델 turn을 거쳐 실제 ReportPatch가 되는지 검증한다."""

    async def test_new_artifact_is_composed_and_saved_with_data_request_cas(self) -> None:
        """검증된 새 Artifact 별칭만 모델과 patch에 전달하고 기존 block을 보존한다."""

        definition_id = uuid4()
        old_artifact_id = uuid4()
        new_artifact_id = uuid4()
        data_request_id = uuid4()
        definition = ReportDefinitionVersion(
            str(definition_id), 2, DefinitionStatus.DRAFT, "현재 보고서",
            (ReportBlock(
                str(uuid4()), "현재 차트", str(old_artifact_id), 12, "old-query",
                BlockType.CHART, 0, 0, 12, 7,
            ),),
        )
        completed = {
            "assistant_request_id": uuid4(),
            "phase": "completed",
            "result_revision": 3,
        }
        repository = SimpleNamespace(
            get_version=AsyncMock(return_value=definition),
            get_assistant_turn_history=AsyncMock(return_value=({
                "role": "user", "content": "직전 월과 비교해 줘",
            }, {
                "role": "assistant", "content": "분석 계획을 승인해 주세요.",
            })),
            get_assistant_artifact=AsyncMock(return_value={
                "artifact_id": new_artifact_id,
                "trino_query_id": "new-query",
                "title": "직전 월 비교",
                "narrative_markdown": "승인된 비교 결과입니다.",
                "evidence_json": {"metrics": []},
                "chart_spec_json": {"chart_type": "bar"},
                "artifact_checksum": "a" * 64,
            }),
            finalize_existing_assistant_patch=AsyncMock(return_value=completed),
        )
        session = {
            "phase": "saving_revision",
            "session_definition_id": definition_id,
            "session_definition_version": 2,
            "result_artifact_id": new_artifact_id,
        }
        plan = ReportAssistantAnalysisPlan.model_validate({
            "request_id": data_request_id,
            "question": "직전 월 비교 차트와 요약을 추가해 줘",
            "reason": "새 비교 근거가 필요합니다.",
            "scope": {
                "period": "현재 기간과 직전 월",
                "metrics": ["승인 지표"],
                "dimensions": [],
            },
        })
        model = AsyncMock(return_value=({
            "change_kind": "existing_artifact",
            "message": "새 분석 근거로 차트와 요약을 추가합니다.",
            "analysis_plan": None,
            "patch": {
                "summary": "비교 차트와 요약 추가",
                "operations": [
                    {
                        "op": "add_artifact_view",
                        "artifact_ref": "source_artifact",
                        "view": "chart",
                        "title": "직전 월 비교",
                        "placement": {"after_block_id": None, "width": "full"},
                    },
                    {
                        "op": "add_text",
                        "title": "분석 요약",
                        "content": "승인된 비교 결과 요약입니다.",
                        "evidence_refs": ["artifact_narrative"],
                        "placement": {"after_block_id": None, "width": "full"},
                    },
                ],
            },
        }, {
            "model_version": "report-model",
            "prompt_id": "report.assistant.turn",
            "prompt_version": "PROMPT-v1.4.0",
            "prompt_hash": "b" * 64,
        }))
        with patch(
            "app.adapters.report_assistant.generate_report_change_proposal",
            new=model,
        ):
            result = await _compose_assistant_revision(
                repository,
                str(completed["assistant_request_id"]),
                str(data_request_id),
                session,
                plan,
            )

        self.assertEqual(completed, result)
        sent = model.await_args.args[0]
        self.assertEqual("source_artifact", sent["artifact"]["artifact_id"])
        self.assertNotIn("query_id", sent["artifact"])
        self.assertNotIn("checksum", sent["artifact"])
        self.assertEqual("artifact_narrative", sent["artifact"]["evidence"]["catalog"][0]["ref"])
        self.assertIsNone(sent["report"]["blocks"][0]["artifact_ref"])
        call = repository.finalize_existing_assistant_patch.await_args
        self.assertEqual(str(data_request_id), call.kwargs["data_request_id"])
        self.assertEqual("saving_revision", call.kwargs["expected_phase"])
        patched = call.args[-1]
        self.assertEqual(3, len(patched.blocks))
        self.assertEqual(str(old_artifact_id), patched.blocks[0].artifact_id)
        self.assertEqual(str(new_artifact_id), patched.blocks[1].artifact_id)

    async def test_compose_rejects_model_request_for_more_data(self) -> None:
        """분석 완료 뒤 모델이 다시 new_data를 반환하면 revision을 만들지 않는다."""

        from app.adapters.report_assistant import ReportAssistantModelError

        repository = SimpleNamespace(
            get_version=AsyncMock(return_value=ReportDefinitionVersion(
                str(uuid4()), 1, DefinitionStatus.DRAFT, "보고서", (),
            )),
            get_assistant_turn_history=AsyncMock(return_value=()),
            get_assistant_artifact=AsyncMock(return_value={
                "artifact_id": uuid4(), "trino_query_id": "query-1", "title": "분석",
                "narrative_markdown": "결과", "evidence_json": {},
                "chart_spec_json": None, "artifact_checksum": "a" * 64,
            }),
            finalize_existing_assistant_patch=AsyncMock(),
        )
        plan = ReportAssistantAnalysisPlan.model_validate({
            "request_id": uuid4(), "question": "비교해 줘", "reason": "근거 필요",
            "scope": {"period": "직전 월", "metrics": ["지표"], "dimensions": []},
        })
        session = {
            "phase": "saving_revision",
            "session_definition_id": uuid4(),
            "session_definition_version": 1,
            "result_artifact_id": uuid4(),
        }
        model = AsyncMock(return_value=({
            "change_kind": "new_data", "message": "추가 분석 필요",
            "analysis_plan": {"question": "다시 분석", "reason": "부족", "scope": {}},
            "patch": None,
        }, {}))
        with patch(
            "app.adapters.report_assistant.generate_report_change_proposal",
            new=model,
        ):
            with self.assertRaises(ReportAssistantModelError):
                await _compose_assistant_revision(
                    repository, str(uuid4()), str(plan.request_id), session, plan
                )
        repository.finalize_existing_assistant_patch.assert_not_awaited()

    async def test_compose_rejects_revision_restore_after_new_analysis(self) -> None:
        """새 Artifact를 만든 합성 단계가 되돌리기로 분석 결과를 버리지 못하게 한다."""

        from app.adapters.report_assistant import ReportAssistantModelError

        definition_id = uuid4()
        repository = SimpleNamespace(
            get_version=AsyncMock(return_value=ReportDefinitionVersion(
                str(definition_id), 2, DefinitionStatus.DRAFT, "보고서", (),
            )),
            get_assistant_turn_history=AsyncMock(return_value=()),
            get_assistant_artifact=AsyncMock(return_value={
                "artifact_id": uuid4(), "trino_query_id": "query-1", "title": "분석",
                "narrative_markdown": "결과", "evidence_json": {},
                "chart_spec_json": None, "artifact_checksum": "a" * 64,
            }),
            finalize_existing_assistant_patch=AsyncMock(),
        )
        plan = ReportAssistantAnalysisPlan.model_validate({
            "request_id": uuid4(), "question": "비교해 줘", "reason": "근거 필요",
            "scope": {"period": "직전 월", "metrics": ["지표"], "dimensions": []},
        })
        session = {
            "phase": "saving_revision",
            "session_definition_id": definition_id,
            "session_definition_version": 2,
            "result_artifact_id": uuid4(),
        }
        model = AsyncMock(return_value=({
            "change_kind": "existing_artifact",
            "message": "이전 revision으로 복원합니다.",
            "analysis_plan": None,
            "patch": {
                "summary": "잘못된 합성 복원",
                "operations": [{"op": "restore_previous_revision"}],
            },
        }, {}))
        with patch(
            "app.adapters.report_assistant.generate_report_change_proposal",
            new=model,
        ):
            with self.assertRaises(ReportAssistantModelError):
                await _compose_assistant_revision(
                    repository, str(uuid4()), str(plan.request_id), session, plan
                )
        repository.finalize_existing_assistant_patch.assert_not_awaited()


class ReportAssistantApprovalTest(unittest.IsolatedAsyncioTestCase):
    """승인 claim·분석 실행·Artifact 검증과 거절 무실행 계약을 확인한다."""

    def setUp(self) -> None:
        """각 테스트에 동일 owner의 승인 대기 계획과 분석 권한 Context를 준비한다."""

        self.assistant_request_id = uuid4()
        self.data_request_id = uuid4()
        self.artifact_id = uuid4()
        self.definition_id = uuid4()
        self.context = RequestContext(user_id=uuid4(), role=Role.ANALYST)
        self.session = {
            "assistant_request_id": self.assistant_request_id,
            "phase": "waiting_approval",
            "session_definition_id": self.definition_id,
            "session_definition_version": 2,
            "base_revision": 2,
            "artifact_id": uuid4(),
            "analysis_plan_json": {
                "request_id": str(self.data_request_id),
                "question": "현재 지표를 직전 월과 비교해 줘",
                "reason": "직전 월 값이 필요합니다.",
                "scope": {
                    "period": "현재 기간과 직전 월",
                    "metrics": ["승인 지표"],
                    "dimensions": [],
                },
            },
            "data_request_id": self.data_request_id,
            "status": "running",
            "result_artifact_id": None,
            "result_revision": None,
            "error_code": None,
        }

    def _repository(self) -> SimpleNamespace:
        """외부 DB 없이 상태 전이 호출을 관찰할 최소 repository fake를 반환한다."""

        repository = SimpleNamespace(
            get_assistant_session=AsyncMock(return_value=self.session),
            recover_stale_assistant_session=AsyncMock(),
            decide_assistant_plan=AsyncMock(),
            mark_assistant_waiting_artifact=AsyncMock(),
            get_assistant_result_artifact=AsyncMock(return_value={
                "artifact_id": self.artifact_id,
                "trino_query_id": "query-1",
                "artifact_checksum": "a" * 64,
            }),
            save_assistant_result_artifact=AsyncMock(return_value={
                **self.session,
                "phase": "saving_revision",
                "result_artifact_id": self.artifact_id,
            }),
            finalize_existing_assistant_patch=AsyncMock(return_value={
                **self.session,
                "phase": "completed",
                "result_artifact_id": self.artifact_id,
                "result_revision": 3,
                "status": "success",
            }),
            fail_assistant_request=AsyncMock(),
            replace_draft_blocks=AsyncMock(),
        )
        return repository

    async def test_stale_recovery_uses_bounded_timeout_before_read(self) -> None:
        """세션 조회는 설정된 timeout으로 중단 실행을 종결한 뒤 최신 상태를 반환한다."""

        repository = self._repository()
        with patch.dict("os.environ", {"REPORT_ASSISTANT_STALE_SECONDS": "600"}):
            result = await _recover_and_get_assistant_session(
                repository,
                str(self.assistant_request_id),
            )

        self.assertEqual(self.session, result)
        repository.recover_stale_assistant_session.assert_awaited_once_with(
            str(self.assistant_request_id), 600
        )
        repository.get_assistant_session.assert_awaited_once_with(
            str(self.assistant_request_id)
        )

    async def test_invalid_stale_timeout_fails_closed(self) -> None:
        """잘못된 운영 timeout은 DB 상태를 임의 변경하지 않고 500으로 닫는다."""

        repository = self._repository()
        with patch.dict("os.environ", {"REPORT_ASSISTANT_STALE_SECONDS": "5"}):
            with self.assertRaises(HTTPException) as raised:
                await _recover_and_get_assistant_session(
                    repository,
                    str(self.assistant_request_id),
                )

        self.assertEqual(500, raised.exception.status_code)
        repository.recover_stale_assistant_session.assert_not_awaited()

    async def test_rejection_returns_ready_without_analysis(self) -> None:
        """최초 거절은 ready를 반환하고 분석·Artifact 경계를 전혀 호출하지 않는다."""

        repository = self._repository()
        repository.decide_assistant_plan.return_value = (
            {**self.session, "phase": "ready", "rejected_at": "2026-08-24T00:00:00Z"},
            True,
        )
        execute = AsyncMock()
        with (
            patch("app.api.report_router._router", return_value=SimpleNamespace(repository=repository)),
            patch("app.api.report_router._execute_assistant_analysis", new=execute),
        ):
            response = await decide_assistant_plan(
                str(self.assistant_request_id),
                ReportAssistantApprovalRequest(request_id=self.data_request_id, approved=False),
                self.context,
            )

        self.assertEqual("ready", response["phase"])
        repository.decide_assistant_plan.assert_awaited_once_with(
            str(self.assistant_request_id), str(self.data_request_id), False
        )
        execute.assert_not_awaited()
        repository.get_assistant_result_artifact.assert_not_awaited()
        repository.replace_draft_blocks.assert_not_awaited()

    async def test_first_approval_executes_once_and_completes_revision(self) -> None:
        """최초 claim만 분석하고 검증된 Artifact로 새 revision을 원자 완료한다."""

        repository = self._repository()
        repository.decide_assistant_plan.return_value = (
            {**self.session, "phase": "running_data_agent"},
            True,
        )
        analysis_response = AnalysisResponse(
            data=AnalysisData(
                status=AnalysisStatus.SUCCEEDED,
                transitions=(AnalysisStatus.RECEIVED, AnalysisStatus.SUCCEEDED),
                artifact=ArtifactReference(
                    artifact_id=self.artifact_id,
                    query_id="query-1",
                    context_hash="c" * 64,
                ),
            ),
            meta=response_meta(self.context.model_copy(update={"request_id": self.data_request_id})),
        )
        execute = AsyncMock(return_value=analysis_response)
        compose = AsyncMock(return_value={
            **self.session,
            "phase": "completed",
            "result_artifact_id": self.artifact_id,
            "result_revision": 3,
            "status": "success",
        })
        with (
            patch("app.api.report_router._router", return_value=SimpleNamespace(repository=repository)),
            patch("app.api.report_router._execute_assistant_analysis", new=execute),
            patch("app.api.report_router._compose_assistant_revision", new=compose),
        ):
            response = await decide_assistant_plan(
                str(self.assistant_request_id),
                ReportAssistantApprovalRequest(request_id=self.data_request_id, approved=True),
                self.context,
            )

        self.assertEqual("completed", response["phase"])
        self.assertEqual(3, response["result_revision"])
        execute.assert_awaited_once()
        executed_context = execute.await_args.args[1]
        self.assertEqual(self.data_request_id, executed_context.request_id)
        repository.get_assistant_result_artifact.assert_awaited_once_with(
            str(self.artifact_id), str(self.data_request_id), "query-1"
        )
        repository.save_assistant_result_artifact.assert_awaited_once()
        compose.assert_awaited_once()
        repository.replace_draft_blocks.assert_not_awaited()

    async def test_duplicate_approval_does_not_execute_again(self) -> None:
        """동일 request가 이미 후속 phase에 있으면 현재 상태만 반환하고 분석을 반복하지 않는다."""

        repository = self._repository()
        repository.decide_assistant_plan.return_value = (
            {**self.session, "phase": "saving_revision", "result_artifact_id": self.artifact_id},
            False,
        )
        execute = AsyncMock()
        compose = AsyncMock(return_value={
            **self.session,
            "phase": "completed",
            "result_artifact_id": self.artifact_id,
            "result_revision": 3,
            "status": "success",
        })
        with (
            patch("app.api.report_router._router", return_value=SimpleNamespace(repository=repository)),
            patch("app.api.report_router._execute_assistant_analysis", new=execute),
            patch("app.api.report_router._compose_assistant_revision", new=compose),
        ):
            response = await decide_assistant_plan(
                str(self.assistant_request_id),
                ReportAssistantApprovalRequest(request_id=self.data_request_id, approved=True),
                self.context,
            )

        self.assertEqual("completed", response["phase"])
        execute.assert_not_awaited()
        compose.assert_awaited_once()

    async def test_completed_duplicate_returns_current_session(self) -> None:
        """이미 완료된 동일 승인은 claim·분석·revision 저장을 모두 반복하지 않는다."""

        repository = self._repository()
        repository.get_assistant_session.return_value = {
            **self.session,
            "phase": "completed",
            "status": "success",
            "approved_at": "2026-08-24T00:00:00Z",
            "result_artifact_id": self.artifact_id,
            "result_revision": 3,
        }
        execute = AsyncMock()
        with (
            patch("app.api.report_router._router", return_value=SimpleNamespace(repository=repository)),
            patch("app.api.report_router._execute_assistant_analysis", new=execute),
        ):
            response = await decide_assistant_plan(
                str(self.assistant_request_id),
                ReportAssistantApprovalRequest(request_id=self.data_request_id, approved=True),
                self.context,
            )

        self.assertEqual("completed", response["phase"])
        self.assertEqual(3, response["result_revision"])
        repository.decide_assistant_plan.assert_not_awaited()
        repository.finalize_existing_assistant_patch.assert_not_awaited()
        execute.assert_not_awaited()

    async def test_revision_cas_conflict_fails_without_direct_block_mutation(self) -> None:
        """기준 draft가 바뀌면 새 revision을 만들지 않고 409 typed failure로 닫는다."""

        repository = self._repository()
        repository.decide_assistant_plan.return_value = (
            {**self.session, "phase": "saving_revision", "result_artifact_id": self.artifact_id},
            False,
        )
        compose = AsyncMock(side_effect=ValueError("REPORT_REVISION_CONFLICT"))
        with (
            patch("app.api.report_router._router", return_value=SimpleNamespace(repository=repository)),
            patch("app.api.report_router._compose_assistant_revision", new=compose),
        ):
            with self.assertRaises(HTTPException) as raised:
                await decide_assistant_plan(
                    str(self.assistant_request_id),
                    ReportAssistantApprovalRequest(
                        request_id=self.data_request_id,
                        approved=True,
                    ),
                    self.context,
                )

        self.assertEqual(409, raised.exception.status_code)
        self.assertEqual("REPORT_REVISION_CONFLICT", raised.exception.detail["code"])
        repository.fail_assistant_request.assert_awaited_once_with(
            str(self.assistant_request_id),
            "REPORT_REVISION_CONFLICT",
            str(self.data_request_id),
        )
        repository.replace_draft_blocks.assert_not_awaited()

    async def test_compose_failure_is_typed_and_does_not_repeat_analysis(self) -> None:
        """저장 재개 중 모델 합성이 실패하면 분석 재호출 없이 typed failed로 닫는다."""

        repository = self._repository()
        repository.decide_assistant_plan.return_value = (
            {**self.session, "phase": "saving_revision", "result_artifact_id": self.artifact_id},
            False,
        )
        execute = AsyncMock()
        compose = AsyncMock(side_effect=RuntimeError("model unavailable"))
        with (
            patch("app.api.report_router._router", return_value=SimpleNamespace(repository=repository)),
            patch("app.api.report_router._execute_assistant_analysis", new=execute),
            patch("app.api.report_router._compose_assistant_revision", new=compose),
        ):
            with self.assertRaises(HTTPException) as raised:
                await decide_assistant_plan(
                    str(self.assistant_request_id),
                    ReportAssistantApprovalRequest(
                        request_id=self.data_request_id,
                        approved=True,
                    ),
                    self.context,
                )

        self.assertEqual(502, raised.exception.status_code)
        self.assertEqual("REPORT_ASSISTANT_COMPOSE_FAILED", raised.exception.detail["code"])
        execute.assert_not_awaited()
        repository.fail_assistant_request.assert_awaited_once_with(
            str(self.assistant_request_id),
            "REPORT_ASSISTANT_COMPOSE_FAILED",
            str(self.data_request_id),
        )

    async def test_artifact_validation_failure_marks_session_failed(self) -> None:
        """분석 성공 응답의 Artifact가 승인 lineage와 다르면 결과 저장 없이 typed 실패한다."""

        repository = self._repository()
        repository.decide_assistant_plan.return_value = (
            {**self.session, "phase": "running_data_agent"},
            True,
        )
        repository.get_assistant_result_artifact.side_effect = ValueError(
            "Analysis Artifact checksum이 유효하지 않습니다."
        )
        analysis_response = AnalysisResponse(
            data=AnalysisData(
                status=AnalysisStatus.SUCCEEDED,
                transitions=(AnalysisStatus.RECEIVED, AnalysisStatus.SUCCEEDED),
                artifact=ArtifactReference(
                    artifact_id=self.artifact_id,
                    query_id="query-1",
                    context_hash="c" * 64,
                ),
            ),
            meta=response_meta(self.context.model_copy(update={"request_id": self.data_request_id})),
        )
        with (
            patch("app.api.report_router._router", return_value=SimpleNamespace(repository=repository)),
            patch(
                "app.api.report_router._execute_assistant_analysis",
                new=AsyncMock(return_value=analysis_response),
            ),
        ):
            with self.assertRaises(HTTPException) as raised:
                await decide_assistant_plan(
                    str(self.assistant_request_id),
                    ReportAssistantApprovalRequest(request_id=self.data_request_id, approved=True),
                    self.context,
                )

        self.assertEqual(409, raised.exception.status_code)
        repository.fail_assistant_request.assert_awaited_once_with(
            str(self.assistant_request_id),
            "ARTIFACT_CHECKSUM_INVALID",
            str(self.data_request_id),
        )
        repository.save_assistant_result_artifact.assert_not_awaited()

    async def test_hidden_session_returns_404_before_claim(self) -> None:
        """타인 또는 미존재 세션은 repository owner filter의 KeyError를 404로 감춘다."""

        repository = self._repository()
        repository.get_assistant_session.side_effect = KeyError(
            "Report Assistant 세션을 찾을 수 없습니다."
        )
        with patch(
            "app.api.report_router._router",
            return_value=SimpleNamespace(repository=repository),
        ):
            with self.assertRaises(HTTPException) as raised:
                await decide_assistant_plan(
                    str(self.assistant_request_id),
                    ReportAssistantApprovalRequest(request_id=self.data_request_id, approved=True),
                    self.context,
                )

        self.assertEqual(404, raised.exception.status_code)
        repository.decide_assistant_plan.assert_not_awaited()

    async def test_wrong_request_and_missing_capability_fail_before_execution(self) -> None:
        """오래된 request와 분석 권한 없는 주체는 claim이나 분석 실행 전에 차단한다."""

        repository = self._repository()
        execute = AsyncMock()
        with (
            patch("app.api.report_router._router", return_value=SimpleNamespace(repository=repository)),
            patch("app.api.report_router._execute_assistant_analysis", new=execute),
        ):
            with self.assertRaises(HTTPException) as wrong:
                await decide_assistant_plan(
                    str(self.assistant_request_id),
                    ReportAssistantApprovalRequest(request_id=uuid4(), approved=True),
                    self.context,
                )
            with self.assertRaises(HTTPException) as denied:
                await decide_assistant_plan(
                    str(self.assistant_request_id),
                    ReportAssistantApprovalRequest(request_id=self.data_request_id, approved=True),
                    self.context.model_copy(update={"role": Role.REPORT_ADMIN}),
                )

        self.assertEqual(409, wrong.exception.status_code)
        self.assertEqual(403, denied.exception.status_code)
        execute.assert_not_awaited()

    async def test_non_waiting_phase_conflicts_without_execution(self) -> None:
        """승인 대기가 아닌 phase는 repository CAS 충돌로 닫고 분석을 실행하지 않는다."""

        repository = self._repository()
        repository.get_assistant_session.return_value = {
            **self.session,
            "phase": "ready",
        }
        repository.decide_assistant_plan.side_effect = ValueError("phase conflict")
        execute = AsyncMock()
        with (
            patch("app.api.report_router._router", return_value=SimpleNamespace(repository=repository)),
            patch("app.api.report_router._execute_assistant_analysis", new=execute),
        ):
            with self.assertRaises(HTTPException) as raised:
                await decide_assistant_plan(
                    str(self.assistant_request_id),
                    ReportAssistantApprovalRequest(request_id=self.data_request_id, approved=True),
                    self.context,
                )

        self.assertEqual(409, raised.exception.status_code)
        self.assertEqual("ASSISTANT_STATE_CONFLICT", raised.exception.detail["code"])
        execute.assert_not_awaited()

    async def test_controller_failure_does_not_use_existing_artifact(self) -> None:
        """분석 실패는 기존 Artifact로 대체하지 않고 typed failed로만 종결한다."""

        repository = self._repository()
        repository.decide_assistant_plan.return_value = (
            {**self.session, "phase": "running_data_agent"},
            True,
        )
        failed = AnalysisResponse(
            data=AnalysisData(
                status=AnalysisStatus.FAILED,
                transitions=(AnalysisStatus.RECEIVED, AnalysisStatus.FAILED),
            ),
            meta=response_meta(self.context.model_copy(update={"request_id": self.data_request_id})),
        )
        with (
            patch("app.api.report_router._router", return_value=SimpleNamespace(repository=repository)),
            patch(
                "app.api.report_router._execute_assistant_analysis",
                new=AsyncMock(return_value=failed),
            ),
        ):
            with self.assertRaises(HTTPException) as raised:
                await decide_assistant_plan(
                    str(self.assistant_request_id),
                    ReportAssistantApprovalRequest(request_id=self.data_request_id, approved=True),
                    self.context,
                )

        self.assertEqual(502, raised.exception.status_code)
        repository.fail_assistant_request.assert_awaited_once_with(
            str(self.assistant_request_id), "ANALYSIS_FAILED", str(self.data_request_id)
        )
        repository.get_assistant_result_artifact.assert_not_awaited()
        repository.save_assistant_result_artifact.assert_not_awaited()
        repository.replace_draft_blocks.assert_not_awaited()

    async def test_unapproved_and_wrong_query_artifacts_are_rejected(self) -> None:
        """미승인 Artifact와 query lineage 불일치는 결과 저장 전에 안전하게 거부한다."""

        analysis_response = AnalysisResponse(
            data=AnalysisData(
                status=AnalysisStatus.PARTIAL,
                transitions=(AnalysisStatus.RECEIVED, AnalysisStatus.PARTIAL),
                artifact=ArtifactReference(
                    artifact_id=self.artifact_id,
                    query_id="query-1",
                    context_hash="c" * 64,
                ),
            ),
            meta=response_meta(self.context.model_copy(update={"request_id": self.data_request_id})),
        )
        cases = (
            (KeyError("artifact hidden"), 502, "ARTIFACT_NOT_FOUND"),
            (ValueError("query lineage mismatch"), 409, "ARTIFACT_LINEAGE_MISMATCH"),
        )
        for failure, status_code, error_code in cases:
            with self.subTest(error_code=error_code):
                repository = self._repository()
                repository.decide_assistant_plan.return_value = (
                    {**self.session, "phase": "running_data_agent"},
                    True,
                )
                repository.get_assistant_result_artifact.side_effect = failure
                with (
                    patch(
                        "app.api.report_router._router",
                        return_value=SimpleNamespace(repository=repository),
                    ),
                    patch(
                        "app.api.report_router._execute_assistant_analysis",
                        new=AsyncMock(return_value=analysis_response),
                    ),
                ):
                    with self.assertRaises(HTTPException) as raised:
                        await decide_assistant_plan(
                            str(self.assistant_request_id),
                            ReportAssistantApprovalRequest(
                                request_id=self.data_request_id,
                                approved=True,
                            ),
                            self.context,
                        )

                self.assertEqual(status_code, raised.exception.status_code)
                self.assertEqual(error_code, raised.exception.detail["code"])
                repository.save_assistant_result_artifact.assert_not_awaited()
                repository.replace_draft_blocks.assert_not_awaited()

    async def test_model_cannot_mark_new_data_without_plan(self) -> None:
        """strict 응답을 통과해도 종류와 계획이 모순이면 두 번 뒤 모델 실패로 닫는다."""

        from app.adapters.report_assistant import (
            ReportAssistantModelError,
            generate_report_change_proposal,
        )

        transport = AsyncMock(return_value={
            "change_kind": "new_data",
            "message": "새 데이터가 필요합니다.",
            "analysis_plan": None,
            "patch": None,
        })
        route = SimpleNamespace(
            endpoint="https://model.invalid",
            token="token",
            model="report-model",
            provider="openai",
        )
        payload = {
            "instruction": "직전 월과 비교해 줘",
            "current_patch": None,
            "selected_block": None,
            "additional_artifacts": [],
            "artifact": {
                "artifact_id": "source_artifact",
                "title": "승인 분석",
                "narrative": "현재 기간 결과",
                "evidence": {"catalog": [{
                    "ref": "artifact_narrative",
                    "kind": "narrative",
                    "label": "Artifact 요약",
                    "content": "현재 기간 결과",
                    "value": None,
                    "unit": None,
                }]},
                "chart_spec": None,
            },
            "report": {
                "title": "현재 보고서",
                "orientation": "portrait",
                "currency_display_unit": "auto",
                "blocks": [],
            },
            "history": [],
        }
        with (
            patch("app.adapters.report_assistant.resolve_active_model_routes", return_value=object()),
            patch("app.adapters.report_assistant.active_route_for_node", return_value=route),
            patch("app.adapters.report_assistant.openai_transport", new=transport),
        ):
            with self.assertRaises(ReportAssistantModelError):
                await generate_report_change_proposal(payload)

        self.assertEqual(2, transport.await_count)

    def test_waiting_approval_requires_complete_plan(self) -> None:
        """승인 카드에 표시할 질문·이유·범위가 불완전하면 응답을 만들지 않는다."""

        with self.assertRaises(ValidationError):
            ReportAssistantSessionResponse.model_validate(
                {
                    "assistant_request_id": str(uuid4()),
                    "phase": "waiting_approval",
                    "definition_id": str(uuid4()),
                    "definition_version": 1,
                    "base_revision": 1,
                    "artifact_id": str(uuid4()),
                    "analysis_plan": {
                        "request_id": str(uuid4()),
                        "question": "직전 월과 비교해 줘",
                        "reason": "비교 데이터가 필요합니다.",
                        "scope": {"period": "직전 월"},
                    },
                }
            )


if __name__ == "__main__":
    unittest.main()
