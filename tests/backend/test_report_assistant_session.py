"""Report Assistant 대화형 세션 계약과 공개 응답 변환을 회귀 검증한다."""

from __future__ import annotations

import inspect
import unittest
from pathlib import Path
from sys import path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from pydantic import ValidationError
from fastapi import HTTPException

BACKEND = Path(__file__).resolve().parents[2] / "app" / "backend"
path.insert(0, str(BACKEND))

from app.api.report_router import (
    _assistant_session_response,
    _compose_assistant_revision,
    _recover_and_get_assistant_session,
    report_router,
    decide_assistant_patch,
    decide_assistant_plan,
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
    ReportAssistantApprovalRequest,
    ReportAssistantSessionResponse,
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


class ReportAssistantMessageTest(unittest.IsolatedAsyncioTestCase):
    """새 데이터 모델 제안이 실행 없이 승인 대기 세션으로 저장되는지 확인한다."""

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
        repository.record_assistant_proposal.assert_not_awaited()
        repository.record_existing_assistant_patch_proposal.assert_awaited_once()
        repository.finalize_existing_assistant_patch.assert_not_awaited()

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
        self.assertEqual("source_query", sent["artifact"]["query_id"])
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
            "artifact": {
                "artifact_id": "artifact-1",
                "query_id": "query-1",
                "title": "승인 분석",
                "narrative": "현재 기간 결과",
                "evidence": {},
                "chart_spec": None,
                "checksum": "a" * 64,
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
