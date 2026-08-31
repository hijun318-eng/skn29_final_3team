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
    _prepare_assistant_revision,
    _report_patch_preview,
    _report_turn_payload,
    _recover_and_get_assistant_session,
    _validated_contextual_suggestions,
    report_router,
    cancel_assistant_session,
    decide_assistant_patch,
    decide_assistant_plan,
    retry_assistant_session,
    review_assistant_report,
    submit_assistant_message,
)
from app.adapters.report_artifact_repository import (
    ReportArtifactRepositoryMixin,
    _canonical_required_release_receipt,
    _view_spec_type_matches_block,
)
from app.adapters.view_spec_integrity import (
    canonical_view_spec_json,
    view_spec_sha256,
)
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
    CreateReportDefinitionRequest,
    CreateReportAssistantSessionRequest,
    ReplaceReportBlocksRequest,
    ReportDefinitionResponse,
    ReportAssistantAnalysisPlan,
    ReportAssistantMessageRequest,
    ReportAssistantReviewRequest,
    ReportAssistantApprovalRequest,
    ReportAssistantPatchApprovalRequest,
    ReportAssistantPatch,
    ReportAssistantSessionResponse,
    ReportAssistantRequiredAction,
    report_assistant_retry_policy,
)
from src.report.domain import BlockType, DefinitionStatus, ReportBlock, ReportDefinitionVersion
from src.ai.schema import validate_payload


class ReportAssistantSessionContractTest(unittest.TestCase):
    """서버 phase·승인 계획 계약이 추가 필드와 불완전 계획을 거부하는지 확인한다."""

    def test_finalizer_receipt_canonicalizes_db_uuids_and_requires_provenance(self) -> None:
        """asyncpg UUID row와 domain str receipt는 같게 비교되고 null source는 거부된다."""

        db_receipt = (uuid4(), uuid4(), uuid4())
        domain_receipt = tuple(str(value) for value in db_receipt)

        self.assertEqual(
            domain_receipt,
            _canonical_required_release_receipt(db_receipt),
        )
        self.assertEqual(
            domain_receipt,
            _canonical_required_release_receipt(domain_receipt),
        )
        with self.assertRaisesRegex(ValueError, "release receipt"):
            _canonical_required_release_receipt((None, None, None))

    def test_view_spec_hash_uses_one_compact_canonical_serializer(self) -> None:
        """생성기와 finalizer가 key 순서·공백과 무관한 동일 ViewSpec hash를 공유한다."""

        first = {"series": ["매출"], "chart_type": "kpi", "options": {"unit": "원"}}
        reordered = {"options": {"unit": "원"}, "chart_type": "kpi", "series": ["매출"]}

        self.assertEqual(
            '{"chart_type":"kpi","options":{"unit":"원"},"series":["매출"]}',
            canonical_view_spec_json(first),
        )
        self.assertEqual(view_spec_sha256(first), view_spec_sha256(reordered))
        self.assertTrue(_view_spec_type_matches_block("chart", "KPI"))
        self.assertFalse(_view_spec_type_matches_block("table", "KPI"))

    def test_turn_payload_exposes_only_bounded_canonical_artifact_views(self) -> None:
        """모델에는 실제 가능 view와 bounded scalar 표만 주고 내부 실행 식별자는 숨긴다."""

        columns = [f"column_{index}" for index in range(18)]
        rows = [
            {
                **{column: row_index for column in columns},
                "column_0": "가" * 700 if row_index == 0 else row_index,
                "column_1": {"nested": "hidden"} if row_index == 0 else row_index,
            }
            for row_index in range(22)
        ]
        artifact_id = uuid4()
        definition = ReportDefinitionVersion(
            str(uuid4()), 1, DefinitionStatus.DRAFT, "월간 보고서", (),
        )
        payload = _report_turn_payload(
            definition,
            {
                "artifact_id": artifact_id,
                "title": "승인 월간 분석",
                "narrative_markdown": "검증된 월간 요약",
                "evidence_json": {
                    "metric_values": [{"label": "매출", "value": 10}],
                    "query_id": "private-evidence-query",
                },
                "chart_spec_json": {
                    "chart_type": "bar", "x_field": "column_0",
                    "y_fields": ["column_2"],
                },
                "data_snapshot_json": {"columns": columns, "rows": rows},
                "trino_query_id": "private-trino-query",
                "artifact_checksum": "a" * 64,
            },
            "승인 결과를 보고서에 추가해 줘",
        )

        validate_payload("report_assistant_turn_request", payload)
        self.assertEqual(1, payload["report"]["page_count"])
        public_artifact = payload["artifact"]
        snapshot = public_artifact["table_snapshot"]
        self.assertEqual(["summary", "kpi", "chart", "table"], public_artifact["available_views"])
        self.assertEqual((16, 0, 22, True), (
            len(snapshot["columns"]), len(snapshot["rows"]),
            snapshot["row_count"], snapshot["truncated"],
        ))
        self.assertEqual(
            [f"column_{index}" for index in range(1, 17)], snapshot["columns"]
        )
        self.assertEqual([], snapshot["rows"])
        self.assertNotIn("가" * 32, repr(payload))
        self.assertNotIn("nested", repr(payload))
        self.assertNotIn("private-trino-query", repr(payload))
        self.assertNotIn("private-evidence-query", repr(payload))
        self.assertNotIn("a" * 64, repr(payload))

    def test_turn_payload_requires_primary_artifact_to_match_current_draft_block(self) -> None:
        """대표 근거와 선택 Artifact 블록이 다르면 모델 호출 payload를 만들지 않는다."""

        primary_id = uuid4()
        secondary_id = uuid4()
        secondary_block_id = str(uuid4())
        definition = ReportDefinitionVersion(
            str(uuid4()), 1, DefinitionStatus.DRAFT, "월간 보고서",
            (
                ReportBlock(
                    str(uuid4()), "매출 차트", str(primary_id), 6, "query-primary",
                    BlockType.CHART, 0, 0, 6, 7,
                ),
                ReportBlock(
                    secondary_block_id, "점유율 표", str(secondary_id), 6, "query-secondary",
                    BlockType.TABLE, 6, 0, 6, 7,
                ),
            ),
        )
        artifact = {
            "artifact_id": primary_id, "title": "승인 매출", "narrative_markdown": "요약",
            "evidence_json": {}, "chart_spec_json": None, "data_snapshot_json": None,
        }

        with self.assertRaisesRegex(ValueError, "ASSISTANT_STATE_CONFLICT"):
            _report_turn_payload(
                definition, artifact, "선택 블록을 수정해 줘",
                selected_block_id=secondary_block_id,
            )

    def test_report_api_and_model_input_share_the_100_block_fail_closed_limit(self) -> None:
        """create·replace·response와 모델 입력이 모두 같은 100-block 상한을 공개한다."""

        for contract in (
            CreateReportDefinitionRequest,
            ReplaceReportBlocksRequest,
            ReportDefinitionResponse,
        ):
            with self.subTest(contract=contract.__name__):
                self.assertEqual(
                    100,
                    contract.model_json_schema()["properties"]["blocks"]["maxItems"],
                )

        oversized = ReportDefinitionVersion(
            str(uuid4()), 1, DefinitionStatus.DRAFT, "과대 보고서",
            tuple(
                ReportBlock(
                    f"block-{index}", f"본문 {index}", None, 12, None,
                    BlockType.TEXT, 0, index, 12, 1, "본문",
                )
                for index in range(101)
            ),
        )
        artifact = {
            "artifact_id": uuid4(), "title": "승인 분석",
            "narrative_markdown": "승인 결과", "evidence_json": {},
            "chart_spec_json": None, "data_snapshot_json": None,
        }
        with self.assertRaisesRegex(ValueError, "REPORT_BLOCK_LIMIT_EXCEEDED"):
            _report_turn_payload(oversized, artifact, "보고서를 수정해 줘")

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
                "turn_history": (
                    {"role": "user", "content": "제목을 더 명확하게 바꿔 줘"},
                    {"role": "assistant", "content": "강조할 기간을 알려 주세요."},
                ),
                "analysis_plan_json": None,
                "result_artifact_id": None,
                "result_revision": None,
                "error_code": None,
            }
        )

        validated = ReportAssistantSessionResponse.model_validate(response)

        self.assertEqual("ready", validated.phase)
        self.assertEqual("full_report", validated.operation_scope)
        self.assertEqual(3, validated.base_revision)
        self.assertIsNone(validated.analysis_plan)
        self.assertEqual("제목을 더 명확하게 바꿔 줘", validated.turn_history[0].content)
        self.assertEqual("assistant", validated.turn_history[1].role)

    def test_stored_preview_without_impact_is_enriched_without_migration(self) -> None:
        """기존 preview JSON은 저장 patch에서 영향값을 재계산해 새 공개 계약으로 복구한다."""

        response = _assistant_session_response({
            "assistant_request_id": uuid4(),
            "phase": "waiting_patch_approval",
            "session_definition_id": uuid4(),
            "session_definition_version": 2,
            "base_revision": 2,
            "artifact_id": uuid4(),
            "operation_scope": "report_title",
            "analysis_plan_json": None,
            "patch_request_id": uuid4(),
            "report_patch_json": {
                "summary": "제목 변경",
                "operations": [{"op": "set_report_title", "title": "새 제목"}],
            },
            "patch_preview_json": [{
                "index": 0, "operation": "set_report_title", "target": "보고서 제목",
                "before": "기존 제목", "after": "새 제목",
            }],
            "result_artifact_id": None,
            "result_revision": None,
            "error_code": None,
            "instruction_hash": "0" * 64,
        })

        self.assertEqual("CONTENT", response["patch_preview"][0]["impact_category"])
        self.assertEqual("report_title", response["operation_scope"])
        self.assertFalse(response["patch_preview"][0]["evidence_required"])
        self.assertEqual(0, response["patch_preview"][0]["evidence_count"])
        self.assertEqual((), response["patch_preview"][0]["depends_on_indexes"])
        self.assertIsNone(response["patch_preview"][0]["page_index"])

    def test_stored_preview_dependencies_are_recomputed_from_typed_patch(self) -> None:
        """legacy 저장 preview의 누락·위조 dependency는 원본 typed patch에서 다시 계산한다."""

        response = _assistant_session_response({
            "assistant_request_id": uuid4(),
            "phase": "waiting_patch_approval",
            "session_definition_id": uuid4(),
            "session_definition_version": 2,
            "base_revision": 2,
            "artifact_id": uuid4(),
            "analysis_plan_json": None,
            "patch_request_id": uuid4(),
            "report_patch_json": {
                "summary": "새 페이지에 요약을 추가합니다.",
                "operations": [
                    {"op": "add_report_page"},
                    {
                        "op": "add_text", "title": "페이지 요약", "content": "근거 요약",
                        "evidence_refs": ["artifact_narrative"],
                    },
                ],
            },
            "patch_preview_json": [
                {
                    "index": 0, "operation": "add_report_page", "target": "보고서 끝",
                    "before": "현재 1페이지", "after": "2페이지",
                    "depends_on_indexes": [11],
                },
                {
                    "index": 1, "operation": "add_text", "target": "페이지 요약",
                    "before": None, "after": "근거 요약",
                    "depends_on_indexes": [],
                },
            ],
            "result_artifact_id": None,
            "result_revision": None,
            "error_code": None,
            "instruction_hash": "0" * 64,
        })

        self.assertEqual(
            ((), (0,)),
            tuple(item["depends_on_indexes"] for item in response["patch_preview"]),
        )

    def test_session_rejects_incomplete_or_out_of_order_turn_history(self) -> None:
        """복구 이력은 사용자·Assistant 메시지가 한 쌍을 이룬 순서만 허용한다."""

        base = {
            "assistant_request_id": str(uuid4()),
            "phase": "ready",
            "operation_scope": "full_report",
            "definition_id": str(uuid4()),
            "definition_version": 1,
            "base_revision": 1,
            "artifact_id": str(uuid4()),
        }
        for history in (
            ({"role": "assistant", "content": "먼저 온 잘못된 답변"},),
            ({"role": "user", "content": "답변이 없는 질문"},),
        ):
            with self.subTest(history=history), self.assertRaises(ValidationError):
                ReportAssistantSessionResponse.model_validate({**base, "turn_history": history})

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

    def test_message_operation_scope_defaults_closed_to_known_values(self) -> None:
        """일반 메시지는 전체 보고서 범위를 유지하고 임의 scope는 API 전에 거부한다."""

        self.assertEqual(
            "full_report",
            ReportAssistantMessageRequest(instruction="제목을 바꿔 줘").operation_scope,
        )
        self.assertEqual(
            "report_title",
            ReportAssistantMessageRequest(
                instruction="제목을 제안해 줘", operation_scope="report_title",
            ).operation_scope,
        )
        with self.assertRaises(ValidationError):
            ReportAssistantMessageRequest(
                instruction="제목을 제안해 줘", operation_scope="title",
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
            "WHEN :approved THEN operation_scope ELSE 'full_report'",
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
            "WHEN :approved THEN operation_scope ELSE 'full_report'",
            "message_revision = message_revision + 1",
        ):
            self.assertIn(condition, patch_claim)

        for method in (
            ReportArtifactRepositoryMixin.record_assistant_proposal,
            ReportArtifactRepositoryMixin.record_existing_assistant_patch_proposal,
            ReportArtifactRepositoryMixin.replace_existing_assistant_patch_proposal,
        ):
            scope_save = inspect.getsource(method)
            self.assertIn("operation_scope = :operation_scope", scope_save)
            self.assertIn("operation_scope <> 'report_title'", scope_save)
            self.assertIn("OR :operation_scope = 'report_title'", scope_save)
            self.assertIn('raise ValueError("ASSISTANT_STATE_CONFLICT")', scope_save)

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
            "product_release_id, permission_snapshot_id",
            "view_spec_id, content, evidence_refs",
            "view_spec_sha256(verified_spec)",
            "_view_spec_type_matches_block",
            "_bind_report_receipt",
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

        cancel = inspect.getsource(ReportArtifactRepositoryMixin.cancel_assistant_session)
        for condition in (
            "assistant_request_id = :request_id AND owner_id = :owner_id",
            "phase IN ('ready', 'waiting_patch_approval', 'waiting_approval')",
            "SET phase = 'cancelled', status = 'failed'",
            "operation_scope = 'full_report'",
            "message_revision = message_revision + 1",
            "ASSISTANT_CANCELLED",
        ):
            self.assertIn(condition, cancel)

        failure = inspect.getsource(ReportArtifactRepositoryMixin.fail_assistant_request)
        for condition in (
            "WHEN :operation_scope = 'report_title' THEN 'report_title'",
            "ELSE operation_scope END",
            "phase = CAST(:expected_phase AS varchar)",
            "message_revision = CAST(:expected_message_revision AS bigint)",
            "RETURNING assistant_request_id",
            "return claimed is not None",
        ):
            self.assertIn(condition, failure)

        freeze = inspect.getsource(ReportArtifactRepositoryMixin.save_assistant_result_artifact)
        for condition in (
            "report_patch_json = CAST(:patch AS jsonb)",
            "patch_preview_json = CAST(:patch_preview AS jsonb)",
            "phase = 'waiting_artifact' AND status = 'running'",
        ):
            self.assertIn(condition, freeze)

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

        session_read = inspect.getsource(
            ReportArtifactRepositoryMixin.get_assistant_session
        )
        for condition in (
            "expected_message_revision: int | None = None",
            "message_revision = CAST(:expected_message_revision AS bigint)",
            "FOR SHARE",
            '"expected_message_revision": expected_message_revision',
        ):
            self.assertIn(condition, session_read)

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
            "source.operation_scope",
            "ON CONFLICT",
        ):
            self.assertIn(condition, retry)
        self.assertNotIn("UPDATE report_v1.report_assistant_requests", retry)


class ReportAssistantRevisionIdempotencyTest(unittest.IsolatedAsyncioTestCase):
    """동시 저장 패자는 동일 완료 결과만 멱등 성공으로 읽는다."""

    async def test_matching_completed_revision_is_reused(self) -> None:
        repository = object.__new__(ReportArtifactRepositoryMixin)
        repository.get_assistant_session = AsyncMock(return_value={
            "phase": "completed",
            "status": "success",
            "result_revision": 2,
            "output_hash": "a" * 64,
            "decision_hash": "b" * 64,
            "data_request_id": uuid4(),
        })

        completed = await repository._completed_assistant_revision(
            str(uuid4()),
            "a" * 64,
            decision_hash="b" * 64,
        )

        self.assertEqual(2, completed["result_revision"])

    async def test_mismatched_completed_revision_remains_a_conflict(self) -> None:
        repository = object.__new__(ReportArtifactRepositoryMixin)
        repository.get_assistant_session = AsyncMock(return_value={
            "phase": "completed",
            "status": "success",
            "result_revision": 2,
            "output_hash": "a" * 64,
            "decision_hash": "b" * 64,
            "data_request_id": uuid4(),
        })

        completed = await repository._completed_assistant_revision(
            str(uuid4()),
            "c" * 64,
            decision_hash="b" * 64,
        )

        self.assertIsNone(completed)


class ReportAssistantScopePersistenceTest(unittest.IsolatedAsyncioTestCase):
    """동시 제안의 역순 저장이 제목 범위를 넓히지 못하는지 검증한다."""

    async def test_late_full_report_update_loses_to_persisted_title_scope(self) -> None:
        class Result:
            def __init__(self, row):
                self.row = row

            def mappings(self):
                return self

            def one_or_none(self):
                return self.row

        class Session:
            operation_scope = "full_report"
            message_revision = 0

            async def execute(self, statement, parameters):
                sql = str(statement)
                self.test_case.assertIn("operation_scope <> 'report_title'", sql)
                self.test_case.assertIn("message_revision = :expected_message_revision", sql)
                if self.message_revision != parameters["expected_message_revision"]:
                    return Result(None)
                requested_scope = parameters["operation_scope"]
                if self.operation_scope == "report_title" and requested_scope == "full_report":
                    return Result(None)
                self.operation_scope = requested_scope
                self.message_revision += 1
                return Result({
                    "assistant_request_id": parameters["request_id"],
                    "phase": "ready",
                    "operation_scope": self.operation_scope,
                    "message_revision": self.message_revision,
                })

        class Transaction:
            def __init__(self, session):
                self.session = session

            async def __aenter__(self):
                return self.session

            async def __aexit__(self, *_args):
                return False

        class Factory:
            def __init__(self, session):
                self.session = session

            def begin(self):
                return Transaction(self.session)

        session = Session()
        session.test_case = self
        repository = object.__new__(ReportArtifactRepositoryMixin)
        repository._owner_id = uuid4()
        repository._sessionmaker = Factory(session)
        repository._append_assistant_turn = AsyncMock()
        request_id = str(uuid4())
        common = (
            request_id, "a" * 64, "b" * 64, "model-v1",
            "report.assistant.turn", "PROMPT-v1", "c" * 64,
            None, "지시", "질문", "clarification",
        )

        stored = await repository.record_assistant_proposal(
            *common, "report_title", expected_message_revision=0,
        )
        with self.assertRaisesRegex(ValueError, "ASSISTANT_STATE_CONFLICT"):
            await repository.record_assistant_proposal(
                *common, "full_report", expected_message_revision=0,
            )

        self.assertEqual("report_title", stored["operation_scope"])
        self.assertEqual("report_title", session.operation_scope)
        repository._append_assistant_turn.assert_awaited_once()


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
        timeout = report_assistant_retry_policy("REPORT_ASSISTANT_MODEL_TIMEOUT")
        self.assertTrue(timeout.retryable)
        self.assertEqual(ReportAssistantRequiredAction.RETRY, timeout.required_action)
        authentication = report_assistant_retry_policy(
            "REPORT_ASSISTANT_MODEL_AUTHENTICATION_FAILED"
        )
        self.assertFalse(authentication.retryable)
        self.assertEqual(ReportAssistantRequiredAction.CONTACT_ADMIN, authentication.required_action)


class ReportAssistantMessageTest(unittest.IsolatedAsyncioTestCase):
    """새 데이터 모델 제안이 실행 없이 승인 대기 세션으로 저장되는지 확인한다."""

    @staticmethod
    def _revision_session_reader(initial, saved):
        async def read(_assistant_request_id, *, expected_message_revision=None):
            if expected_message_revision is None:
                return initial
            if expected_message_revision == saved.get("message_revision"):
                return saved
            raise KeyError("stale message revision")

        return AsyncMock(side_effect=read)

    def test_model_failures_keep_safe_typed_causes(self) -> None:
        """provider 원문 없이 인증·한도·timeout·전송·계약 실패를 구분한다."""

        from app.adapters.async_model_client import (
            ModelAuthenticationError,
            ModelRateLimitError,
            ModelRequestRejectedError,
        )
        from app.adapters.report_assistant import _model_failure
        from src.ai.schema import ContractError

        cases = (
            (ModelAuthenticationError("secret"), "REPORT_ASSISTANT_MODEL_AUTHENTICATION_FAILED"),
            (ModelRateLimitError("limited"), "REPORT_ASSISTANT_MODEL_RATE_LIMITED"),
            (ModelRequestRejectedError("bad request"), "REPORT_ASSISTANT_MODEL_REQUEST_REJECTED"),
            (TimeoutError("slow"), "REPORT_ASSISTANT_MODEL_TIMEOUT"),
            (OSError("offline"), "REPORT_ASSISTANT_MODEL_TRANSPORT_FAILED"),
            (ContractError("invalid"), "REPORT_ASSISTANT_MODEL_CONTRACT_INVALID"),
        )
        for source, code in cases:
            with self.subTest(code=code):
                failure = _model_failure(
                    source,
                    message="safe failure",
                    attempts=2,
                    started=None,
                )
                self.assertEqual(code, failure.code)
                self.assertEqual(2, failure.attempts)
                self.assertIsNone(failure.duration_ms)
                self.assertNotIn(str(source), str(failure))

    async def test_non_retryable_model_failure_stops_after_one_attempt(self) -> None:
        """인증·provider 요청 거절은 동일 호출을 반복하지 않고 즉시 닫는다."""

        from app.adapters.async_model_client import ModelAuthenticationError
        from app.adapters.report_assistant import (
            ReportAssistantModelError,
            generate_report_change_proposal,
        )

        route = SimpleNamespace(
            endpoint="https://model.invalid",
            token="secret",
            model="report-model",
            provider="openai",
        )
        transport = AsyncMock(side_effect=ModelAuthenticationError("do not expose"))
        with (
            patch("app.adapters.report_assistant.resolve_active_model_routes", return_value=object()),
            patch("app.adapters.report_assistant.active_route_for_node", return_value=route),
            patch("app.adapters.report_assistant.validate_payload"),
            patch("app.adapters.report_assistant.openai_transport", new=transport),
        ):
            with self.assertRaises(ReportAssistantModelError) as raised:
                await generate_report_change_proposal({})

        self.assertEqual(1, transport.await_count)
        self.assertEqual("REPORT_ASSISTANT_MODEL_AUTHENTICATION_FAILED", raised.exception.code)
        self.assertEqual(1, raised.exception.attempts)

    async def test_invalid_model_limits_fail_before_transport(self) -> None:
        """잘못된 timeout·attempt 설정은 네트워크 호출 전에 typed 설정 오류로 닫는다."""

        from app.adapters.report_assistant import (
            ReportAssistantModelError,
            generate_report_change_proposal,
        )

        route = SimpleNamespace(
            endpoint="https://model.invalid",
            token="secret",
            model="report-model",
            provider="openai",
        )
        transport = AsyncMock()
        with (
            patch("app.adapters.report_assistant.resolve_active_model_routes", return_value=object()),
            patch("app.adapters.report_assistant.active_route_for_node", return_value=route),
            patch("app.adapters.report_assistant.validate_payload"),
            patch("app.adapters.report_assistant.openai_transport", new=transport),
            patch.dict("os.environ", {"MODEL_TIMEOUT_SECONDS": "invalid"}),
        ):
            with self.assertRaises(ReportAssistantModelError) as raised:
                await generate_report_change_proposal({})

        transport.assert_not_awaited()
        self.assertEqual("REPORT_ASSISTANT_MODEL_CONFIGURATION_INVALID", raised.exception.code)
        self.assertIsNone(raised.exception.attempts)

    async def test_quality_review_returns_typed_findings_without_session_or_report_write(self) -> None:
        """검토는 현재 block·근거 별칭만 반환하고 phase·patch·Revision을 만들지 않는다."""

        assistant_request_id = uuid4()
        artifact_id = uuid4()
        definition_id = uuid4()
        block_id = uuid4()
        session = {
            "assistant_request_id": assistant_request_id,
            "phase": "ready",
            "message_revision": 0,
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
            upsert_assistant_evaluation=AsyncMock(),
        )
        model = AsyncMock(return_value=({
            "summary": "표현 한 건을 검토했습니다.",
            "suggestions": ["승인 지표를 설명하는 텍스트 블록을 추가해 줘"],
            "findings": [{
                "category": "title_mismatch",
                "severity": "warning",
                "block_id": str(block_id),
                "title": "차트 제목 확인",
                "detail": "제목이 승인 지표 표현과 다릅니다.",
                "suggested_instruction": "보고서 요약을 승인 지표 표현에 맞춰 바꿔 줘",
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
        self.assertEqual(("승인 지표를 설명하는 텍스트 블록을 추가해 줘",), response["suggestions"])
        self.assertEqual("chart", model.await_args.args[0]["selected_block"]["type"])
        serialized_input = repr(model.await_args.args[0])
        self.assertNotIn("private-query", serialized_input)
        self.assertNotIn("a" * 64, serialized_input)
        self.assertEqual("ready", session["phase"])
        self.assertFalse(hasattr(repository, "record_assistant_proposal"))
        observation = repository.upsert_assistant_evaluation.await_args
        self.assertEqual(100, observation.kwargs["input_tokens"])
        self.assertEqual(50, observation.kwargs["output_tokens"])
        self.assertTrue(observation.kwargs["accumulate_usage"])
        self.assertEqual(0, observation.kwargs["expected_message_revision"])

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
                "message_revision": 0,
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
            "message_revision": 0,
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
            "instruction_hash": "0" * 64,
            "message_revision": 0,
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
                "data_snapshot_json": {
                    "columns": ["객실"], "rows": [{"객실": 80}],
                },
                "trino_query_id": "private-secondary-query", "artifact_checksum": "b" * 64,
            },
        )
        waiting = {
            **session,
            "phase": "waiting_patch_approval",
            "message_revision": 1,
            "patch_request_id": uuid4(),
            "report_patch_json": {
                "summary": "두 번째 승인 근거 표 추가",
                "operations": [{
                    "op": "add_artifact_view", "artifact_ref": "source_artifact_2",
                    "view": "table", "title": "객실 · 표",
                }],
            },
        }
        repository = SimpleNamespace(
            get_assistant_session=self._revision_session_reader(session, waiting),
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
                    "view": "table", "title": "객실 · 표",
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
            "instruction_hash": "0" * 64,
            "message_revision": 0,
        }
        saved_session = {}
        repository = SimpleNamespace(
            get_assistant_session=self._revision_session_reader(session, saved_session),
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

        async def save_proposal(*args, **_kwargs):
            plan = args[7]
            saved_session.update({
                **session,
                "phase": "waiting_approval",
                "analysis_plan_json": plan,
                "message_revision": 1,
            })
            return saved_session

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
            "instruction_hash": "0" * 64,
            "message_revision": 0,
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
                "chart_spec_json": {
                    "chart_type": "bar", "x_field": "period",
                    "y_fields": ["value"],
                },
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
                new=AsyncMock(side_effect=ReportAssistantModelError(
                    "model unavailable",
                    code="REPORT_ASSISTANT_MODEL_TIMEOUT",
                    attempts=2,
                    duration_ms=1250.5,
                )),
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
            str(assistant_request_id),
            "REPORT_ASSISTANT_MODEL_TIMEOUT",
            operation_scope="full_report",
            expected_phase="ready",
            expected_message_revision=0,
        )
        repository.upsert_assistant_evaluation.assert_awaited_once()
        observed = repository.upsert_assistant_evaluation.await_args.kwargs
        self.assertEqual("REPORT_ASSISTANT_MODEL_TIMEOUT", observed["error_code"])
        self.assertEqual(2, observed["model_attempts"])
        self.assertEqual(1250.5, observed["latency_ms"])

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
            "instruction_hash": "0" * 64,
            "message_revision": 0,
        }
        history = (
            {"role": "user", "content": "비교해 줘"},
            {"role": "assistant", "content": "어느 기간과 비교할까요?"},
        )
        saved_session = {**session, "message_revision": 1, "turn_history": history}
        repository = SimpleNamespace(
            get_assistant_session=self._revision_session_reader(session, saved_session),
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
            record_assistant_proposal=AsyncMock(return_value=saved_session),
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
        self.assertEqual(
            {"expected_message_revision": 1},
            repository.get_assistant_session.await_args.kwargs,
        )
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
            "instruction_hash": "0" * 64,
            "message_revision": 0,
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
            "message_revision": 1,
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
            get_assistant_session=self._revision_session_reader(session, waiting),
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

    async def test_existing_artifact_noop_returns_clarification_without_failed_session(self) -> None:
        """모델의 의미 없는 patch는 장애가 아니라 현재 반영 상태 안내로 ready를 유지한다."""

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
            "instruction_hash": "0" * 64,
            "message_revision": 0,
        }
        definition = ReportDefinitionVersion(
            str(definition_id), 2, DefinitionStatus.DRAFT, "현재 보고서",
            (ReportBlock(
                str(block_id), "현재 차트", str(artifact_id), 6, "query-1",
                BlockType.CHART, 0, 29, 6, 7,
            ),),
        )
        saved_session = {**session, "message_revision": 1}
        repository = SimpleNamespace(
            get_assistant_session=self._revision_session_reader(session, saved_session),
            get_assistant_turn_history=AsyncMock(return_value=()),
            get_assistant_artifact=AsyncMock(return_value={
                "artifact_id": artifact_id, "trino_query_id": "query-1",
                "title": "승인 분석", "narrative_markdown": "현재 결과",
                "evidence_json": {}, "chart_spec_json": None,
                "artifact_checksum": "a" * 64,
            }),
            get_version=AsyncMock(return_value=definition),
            record_assistant_proposal=AsyncMock(return_value=saved_session),
            record_existing_assistant_patch_proposal=AsyncMock(),
            finalize_existing_assistant_patch=AsyncMock(),
        )
        model = AsyncMock(return_value=({
            "change_kind": "existing_artifact",
            "message": "현재 차트를 반 너비로 설정합니다.",
            "analysis_plan": None,
            "patch": {
                "summary": "현재 너비 유지",
                "operations": [{
                    "op": "reposition_block", "block_id": str(block_id), "width": "half",
                }],
            },
            "suggestions": [],
        }, {
            "model_version": "report-model",
            "prompt_id": "report.assistant.turn",
            "prompt_version": "PROMPT-v1.8.6",
            "prompt_hash": "b" * 64,
        }))
        with (
            patch("app.api.report_router._router", return_value=SimpleNamespace(repository=repository)),
            patch("app.adapters.report_assistant.generate_report_change_proposal", new=model),
        ):
            response = await submit_assistant_message(
                str(assistant_request_id),
                ReportAssistantMessageRequest(instruction="현재 차트를 지금처럼 반 너비로 해 줘"),
                object(),
            )

        self.assertEqual("clarification", response["change_kind"])
        self.assertEqual("ready", response["session"]["phase"])
        self.assertIn("이미 반영", response["message"])
        repository.record_assistant_proposal.assert_awaited_once()
        repository.record_existing_assistant_patch_proposal.assert_not_awaited()
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
            "instruction_hash": "0" * 64,
            "message_revision": 0,
        }
        definition = ReportDefinitionVersion(
            str(definition_id), 2, DefinitionStatus.DRAFT, "현재 보고서",
            (ReportBlock(
                str(block_id), "현재 차트", str(artifact_id), 12, "query-1",
                BlockType.CHART, 0, 0, 12, 7,
            ),),
        )
        replaced = {
            **session,
            "message_revision": 1,
            "patch_request_id": uuid4(),
            "report_patch_json": {
                "summary": "제목 변경",
                "operations": [{"op": "set_report_title", "title": "수정된 보고서"}],
            },
        }
        repository = SimpleNamespace(
            get_assistant_session=self._revision_session_reader(session, replaced),
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

        async def replace(*args, **_kwargs):
            replaced["report_patch_json"] = args[9]
            return replaced

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
            "instruction_hash": "0" * 64,
            "message_revision": 0,
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
            "message_revision": 1,
            "patch_request_id": uuid4(),
            "report_patch_json": {
                "summary": "직전 revision 복원",
                "operations": [{"op": "restore_previous_revision"}],
            },
        }
        repository = SimpleNamespace(
            get_assistant_session=self._revision_session_reader(session, waiting),
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
                "title": "승인 분석", "narrative_markdown": "승인 근거 요약",
                "evidence_json": {}, "chart_spec_json": None,
                "data_snapshot_json": None,
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

    async def test_selected_operations_only_are_applied_and_audited(self) -> None:
        """부분 승인은 원본 patch를 감사에 보존하고 선택 operation만 Revision에 적용한다."""

        waiting = self._session()
        waiting["report_patch_json"]["operations"].insert(0, {
            "op": "set_report_title", "title": "선택한 새 제목",
        })
        block = ReportBlock(
            str(uuid4()), "차트", str(waiting["artifact_id"]), 12, "query-1",
            BlockType.CHART, 0, 0, 12, 7,
        )
        definition = ReportDefinitionVersion(
            str(waiting["session_definition_id"]), 2, DefinitionStatus.DRAFT,
            "기존 제목", (block,),
        )
        saving = {
            **waiting, "phase": "saving_revision", "approved_at": object(),
            "approved_operation_indexes": [0],
        }
        completed = {
            **saving, "phase": "completed", "status": "success", "result_revision": 3,
        }
        repository = SimpleNamespace(
            decide_existing_assistant_patch=AsyncMock(return_value=(saving, True)),
            get_version=AsyncMock(return_value=definition),
            get_assistant_artifact=AsyncMock(return_value={
                "artifact_id": waiting["artifact_id"], "trino_query_id": "query-1",
                "title": "승인 분석", "narrative_markdown": "승인 근거 요약",
                "evidence_json": {}, "chart_spec_json": None,
                "data_snapshot_json": None,
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
                ReportAssistantPatchApprovalRequest(
                    request_id=waiting["patch_request_id"], approved=True,
                    operation_indexes=(0,),
                ),
                object(),
            )

        self.assertEqual((0,), response["approved_operation_indexes"])
        repository.decide_existing_assistant_patch.assert_awaited_once_with(
            str(waiting["assistant_request_id"]), str(waiting["patch_request_id"]),
            True, (0,),
        )
        finalized = repository.finalize_existing_assistant_patch.await_args.args
        self.assertEqual(2, len(finalized[7]["operations"]))
        self.assertEqual("선택한 새 제목", finalized[8].title)
        self.assertEqual((block,), finalized[8].blocks)

    async def test_saving_patch_resumes_without_a_second_claim(self) -> None:
        """중단된 saving_revision은 저장된 선택으로 CAS 저장만 재개한다."""

        saving = self._session()
        saving.update({
            "phase": "saving_revision", "approved_at": object(),
            "approved_operation_indexes": [0],
        })
        definition = ReportDefinitionVersion(
            str(saving["session_definition_id"]), 2, DefinitionStatus.DRAFT, "보고서",
            (ReportBlock(
                str(uuid4()), "차트", str(saving["artifact_id"]), 12, "query-1",
                BlockType.CHART, 0, 0, 12, 7,
            ),),
        )
        completed = {
            **saving, "phase": "completed", "status": "success", "result_revision": 3,
        }
        repository = SimpleNamespace(
            decide_existing_assistant_patch=AsyncMock(return_value=(saving, False)),
            get_version=AsyncMock(return_value=definition),
            get_assistant_artifact=AsyncMock(return_value={
                "artifact_id": saving["artifact_id"], "trino_query_id": "query-1",
                "title": "승인 분석", "narrative_markdown": "승인 근거 요약",
                "evidence_json": {}, "chart_spec_json": None,
                "data_snapshot_json": None,
                "artifact_checksum": "d" * 64,
            }),
            finalize_existing_assistant_patch=AsyncMock(return_value=completed),
            fail_assistant_request=AsyncMock(),
        )
        with (
            patch("app.api.report_router._router", return_value=SimpleNamespace(repository=repository)),
            patch("app.api.report_router._recover_and_get_assistant_session", new=AsyncMock(return_value=saving)),
        ):
            response = await decide_assistant_patch(
                str(saving["assistant_request_id"]),
                ReportAssistantPatchApprovalRequest(
                    request_id=saving["patch_request_id"], approved=True,
                    operation_indexes=(0,),
                ),
                object(),
            )

        self.assertEqual("completed", response["phase"])
        repository.decide_existing_assistant_patch.assert_awaited_once()
        repository.finalize_existing_assistant_patch.assert_awaited_once()
        repository.fail_assistant_request.assert_not_awaited()

    async def test_out_of_range_selection_is_rejected_before_claim(self) -> None:
        """존재하지 않는 operation 인덱스는 DB claim이나 Revision 호출 전에 거부한다."""

        waiting = self._session()
        repository = SimpleNamespace(
            decide_existing_assistant_patch=AsyncMock(),
            finalize_existing_assistant_patch=AsyncMock(),
        )
        with (
            patch("app.api.report_router._router", return_value=SimpleNamespace(repository=repository)),
            patch("app.api.report_router._recover_and_get_assistant_session", new=AsyncMock(return_value=waiting)),
        ):
            with self.assertRaises(HTTPException) as raised:
                await decide_assistant_patch(
                    str(waiting["assistant_request_id"]),
                    ReportAssistantPatchApprovalRequest(
                        request_id=waiting["patch_request_id"], approved=True,
                        operation_indexes=(1,),
                    ),
                    object(),
                )

        self.assertEqual(409, raised.exception.status_code)
        repository.decide_existing_assistant_patch.assert_not_awaited()
        repository.finalize_existing_assistant_patch.assert_not_awaited()

    async def test_explicit_empty_selection_never_becomes_full_approval(self) -> None:
        """검증 경계를 우회한 명시 빈 선택도 legacy None 전체 승인으로 해석하지 않는다."""

        waiting = self._session()
        repository = SimpleNamespace(
            decide_existing_assistant_patch=AsyncMock(),
            finalize_existing_assistant_patch=AsyncMock(),
        )
        payload = ReportAssistantPatchApprovalRequest.model_construct(
            request_id=waiting["patch_request_id"],
            approved=True,
            operation_indexes=(),
        )
        with (
            patch("app.api.report_router._router", return_value=SimpleNamespace(repository=repository)),
            patch(
                "app.api.report_router._recover_and_get_assistant_session",
                new=AsyncMock(return_value=waiting),
            ),
        ):
            with self.assertRaises(HTTPException) as raised:
                await decide_assistant_patch(
                    str(waiting["assistant_request_id"]), payload, object()
                )

        self.assertEqual(409, raised.exception.status_code)
        self.assertEqual("ASSISTANT_STATE_CONFLICT", raised.exception.detail["code"])
        repository.decide_existing_assistant_patch.assert_not_awaited()
        repository.finalize_existing_assistant_patch.assert_not_awaited()

    async def test_missing_page_dependency_is_rejected_before_claim(self) -> None:
        """새 페이지 내용만 고르는 선택은 CAS claim 전에 409로 닫힌다."""

        waiting = self._session()
        waiting["report_patch_json"] = {
            "summary": "새 페이지에 요약을 추가합니다.",
            "operations": [
                {"op": "add_report_page"},
                {
                    "op": "add_text", "title": "페이지 요약", "content": "승인 근거 요약",
                    "evidence_refs": ["artifact_narrative"],
                },
            ],
        }
        repository = SimpleNamespace(
            decide_existing_assistant_patch=AsyncMock(),
            finalize_existing_assistant_patch=AsyncMock(),
        )
        with (
            patch("app.api.report_router._router", return_value=SimpleNamespace(repository=repository)),
            patch(
                "app.api.report_router._recover_and_get_assistant_session",
                new=AsyncMock(return_value=waiting),
            ),
        ):
            with self.assertRaises(HTTPException) as raised:
                await decide_assistant_patch(
                    str(waiting["assistant_request_id"]),
                    ReportAssistantPatchApprovalRequest(
                        request_id=waiting["patch_request_id"], approved=True,
                        operation_indexes=(1,),
                    ),
                    object(),
                )

        self.assertEqual(409, raised.exception.status_code)
        self.assertEqual("ASSISTANT_STATE_CONFLICT", raised.exception.detail["code"])
        repository.decide_existing_assistant_patch.assert_not_awaited()
        repository.finalize_existing_assistant_patch.assert_not_awaited()

    async def test_conflicting_selection_is_rejected_before_claim(self) -> None:
        """같은 block의 수정·삭제 조합은 승인 claim과 Revision 저장 전에 거부한다."""

        waiting = self._session()
        text_block_id = str(uuid4())
        waiting["report_patch_json"] = {
            "summary": "요약을 수정하고 삭제합니다.",
            "operations": [
                {"op": "update_text", "block_id": text_block_id, "content": "새 요약"},
                {"op": "remove_block", "block_id": text_block_id},
            ],
        }
        definition = ReportDefinitionVersion(
            str(waiting["session_definition_id"]), 2, DefinitionStatus.DRAFT, "보고서",
            (
                ReportBlock(
                    text_block_id, "요약", None, 12, None,
                    BlockType.TEXT, 0, 0, 12, 4, "기존 요약",
                ),
                ReportBlock(
                    str(uuid4()), "차트", str(waiting["artifact_id"]), 12, "query-1",
                    BlockType.CHART, 0, 4, 12, 7,
                ),
            ),
        )
        repository = SimpleNamespace(
            get_version=AsyncMock(return_value=definition),
            get_assistant_artifact=AsyncMock(return_value={
                "artifact_id": waiting["artifact_id"], "trino_query_id": "query-1",
                "artifact_checksum": "d" * 64,
            }),
            decide_existing_assistant_patch=AsyncMock(),
            finalize_existing_assistant_patch=AsyncMock(),
        )
        with (
            patch("app.api.report_router._router", return_value=SimpleNamespace(repository=repository)),
            patch("app.api.report_router._recover_and_get_assistant_session", new=AsyncMock(return_value=waiting)),
        ):
            with self.assertRaises(HTTPException) as raised:
                await decide_assistant_patch(
                    str(waiting["assistant_request_id"]),
                    ReportAssistantPatchApprovalRequest(
                        request_id=waiting["patch_request_id"], approved=True,
                        operation_indexes=(0, 1),
                    ),
                    object(),
                )

        self.assertEqual(409, raised.exception.status_code)
        self.assertEqual("REPORT_ASSISTANT_PATCH_INVALID", raised.exception.detail["code"])
        repository.decide_existing_assistant_patch.assert_not_awaited()
        repository.finalize_existing_assistant_patch.assert_not_awaited()

    async def test_noop_operation_selection_is_conflict_before_claim(self) -> None:
        """전체 patch 중 현재와 같은 작업만 선택하면 세션을 실패시키지 않고 409로 거부한다."""

        waiting = self._session()
        block_id = str(uuid4())
        waiting["report_patch_json"] = {
            "summary": "제목 유지와 요약 추가",
            "operations": [
                {"op": "set_report_title", "title": "현재 보고서"},
                {
                    "op": "add_text", "title": "새 요약", "content": "검증된 요약",
                    "evidence_refs": ["artifact_narrative"],
                    "placement": {"after_block_id": block_id, "width": "full"},
                },
            ],
        }
        definition = ReportDefinitionVersion(
            str(waiting["session_definition_id"]), 2, DefinitionStatus.DRAFT, "현재 보고서",
            (ReportBlock(
                block_id, "차트", str(waiting["artifact_id"]), 12, "query-1",
                BlockType.CHART, 0, 0, 12, 7,
            ),),
        )
        repository = SimpleNamespace(
            get_version=AsyncMock(return_value=definition),
            get_assistant_artifact=AsyncMock(return_value={
                "artifact_id": waiting["artifact_id"], "trino_query_id": "query-1",
                "title": "승인 분석", "narrative_markdown": "현재 결과",
                "evidence_json": {}, "chart_spec_json": None,
                "artifact_checksum": "d" * 64,
            }),
            decide_existing_assistant_patch=AsyncMock(),
            finalize_existing_assistant_patch=AsyncMock(),
        )
        with (
            patch("app.api.report_router._router", return_value=SimpleNamespace(repository=repository)),
            patch(
                "app.api.report_router._recover_and_get_assistant_session",
                new=AsyncMock(return_value=waiting),
            ),
        ):
            with self.assertRaises(HTTPException) as raised:
                await decide_assistant_patch(
                    str(waiting["assistant_request_id"]),
                    ReportAssistantPatchApprovalRequest(
                        request_id=waiting["patch_request_id"], approved=True,
                        operation_indexes=(0,),
                    ),
                    object(),
                )

        self.assertEqual(409, raised.exception.status_code)
        self.assertEqual("REPORT_ASSISTANT_PATCH_INVALID", raised.exception.detail["code"])
        repository.decide_existing_assistant_patch.assert_not_awaited()
        repository.finalize_existing_assistant_patch.assert_not_awaited()

    async def test_completed_patch_rejects_a_different_duplicate_selection(self) -> None:
        """완료된 patch의 중복 승인은 최초 선택과 같을 때만 멱등 응답한다."""

        completed = self._session()
        completed["report_patch_json"]["operations"].insert(0, {
            "op": "set_report_title", "title": "새 제목",
        })
        completed.update({
            "phase": "completed", "status": "success", "approved_at": object(),
            "approved_operation_indexes": [0], "result_revision": 3,
        })
        repository = SimpleNamespace(decide_existing_assistant_patch=AsyncMock())
        with (
            patch("app.api.report_router._router", return_value=SimpleNamespace(repository=repository)),
            patch("app.api.report_router._recover_and_get_assistant_session", new=AsyncMock(return_value=completed)),
        ):
            with self.assertRaises(HTTPException) as raised:
                await decide_assistant_patch(
                    str(completed["assistant_request_id"]),
                    ReportAssistantPatchApprovalRequest(
                        request_id=completed["patch_request_id"], approved=True,
                        operation_indexes=(1,),
                    ),
                    object(),
                )

        self.assertEqual(409, raised.exception.status_code)
        repository.decide_existing_assistant_patch.assert_not_awaited()

    async def test_legacy_completed_patch_treats_null_selection_as_all(self) -> None:
        """migration 이전 완료 patch의 NULL 선택값은 기존 전체 승인 멱등성을 유지한다."""

        completed = self._session()
        completed.update({
            "phase": "completed", "status": "success", "approved_at": object(),
            "approved_operation_indexes": None, "result_revision": 3,
        })
        repository = SimpleNamespace(decide_existing_assistant_patch=AsyncMock())
        with (
            patch("app.api.report_router._router", return_value=SimpleNamespace(repository=repository)),
            patch("app.api.report_router._recover_and_get_assistant_session", new=AsyncMock(return_value=completed)),
        ):
            response = await decide_assistant_patch(
                str(completed["assistant_request_id"]),
                ReportAssistantPatchApprovalRequest(
                    request_id=completed["patch_request_id"], approved=True,
                ),
                object(),
            )

        self.assertEqual("completed", response["phase"])
        self.assertEqual((0,), response["approved_operation_indexes"])
        repository.decide_existing_assistant_patch.assert_not_awaited()

    def test_patch_preview_hides_internal_identifiers(self) -> None:
        """변경 전후 미리보기에는 block·Artifact 내부 식별자가 포함되지 않는다."""

        block_id = str(uuid4())
        artifact_id = str(uuid4())
        definition = ReportDefinitionVersion(
            str(uuid4()), 2, DefinitionStatus.DRAFT, "기존 제목",
            (ReportBlock(
                block_id, "매출 차트", artifact_id, 12, "query-secret",
                BlockType.CHART, 0, 0, 12, 7,
            ),),
        )
        patch_value = ReportAssistantPatch.model_validate({
            "summary": "제목과 배치 변경",
            "operations": [
                {"op": "set_report_title", "title": "새 제목"},
                {"op": "reposition_block", "block_id": block_id, "width": "half"},
            ],
        })

        preview = _report_patch_preview(definition, patch_value)

        self.assertEqual((0, 1), tuple(item["index"] for item in preview))
        self.assertEqual(((), ()), tuple(item["depends_on_indexes"] for item in preview))
        self.assertEqual(("CONTENT", "LAYOUT"), tuple(item["impact_category"] for item in preview))
        self.assertTrue(all(item["evidence_count"] == 0 for item in preview))
        public_text = str(preview)
        self.assertNotIn(block_id, public_text)
        self.assertNotIn(artifact_id, public_text)
        self.assertNotIn("query-secret", public_text)

    def test_patch_preview_classifies_destructive_and_grounded_changes(self) -> None:
        """삭제 위험과 생성 본문의 근거 개수는 모델 문구가 아닌 typed operation에서 계산한다."""

        block_id = str(uuid4())
        definition = ReportDefinitionVersion(
            str(uuid4()), 2, DefinitionStatus.DRAFT, "기존 제목",
            (ReportBlock(block_id, "요약", None, 12, None, BlockType.TEXT, 0, 0, 12, 4, "기존 본문"),),
        )
        patch_value = ReportAssistantPatch.model_validate({
            "summary": "요약 추가와 기존 블록 삭제",
            "operations": [
                {
                    "op": "add_text", "title": "새 요약", "content": "근거 기반 본문",
                    "evidence_refs": ["artifact_narrative"],
                },
                {"op": "remove_block", "block_id": block_id},
            ],
        })

        preview = _report_patch_preview(definition, patch_value)

        self.assertEqual("CONTENT", preview[0]["impact_category"])
        self.assertTrue(preview[0]["evidence_required"])
        self.assertEqual(1, preview[0]["evidence_count"])
        self.assertEqual("DESTRUCTIVE", preview[1]["impact_category"])
        self.assertFalse(preview[1]["evidence_required"])

    def test_patch_preview_describes_editor_settings_without_raw_json(self) -> None:
        """차트 변경 카드는 허용 설정의 전후만 설명하고 내부 설정 JSON은 노출하지 않는다."""

        block_id = str(uuid4())
        definition = ReportDefinitionVersion(
            str(uuid4()), 2, DefinitionStatus.DRAFT, "기존 제목",
            (ReportBlock(
                block_id, "매출 차트", str(uuid4()), 12, "query-secret",
                BlockType.CHART, 0, 0, 12, 7,
                '{"chartType":"bar","showLegend":true,"sizeMode":"manual","private":"hidden"}',
            ),),
        )
        patch_value = ReportAssistantPatch.model_validate({
            "summary": "차트 표현 변경",
            "operations": [{
                "op": "update_chart_settings", "block_id": block_id,
                "chart_type": "horizontal-bar", "show_legend": False,
                "size_mode": "auto",
            }],
        })

        preview = _report_patch_preview(definition, patch_value)

        self.assertIn("차트 유형: 세로 막대", preview[0]["before"])
        self.assertIn("차트 유형: 가로 막대", preview[0]["after"])
        self.assertIn("범례: 표시", preview[0]["before"])
        self.assertIn("범례: 숨김", preview[0]["after"])
        self.assertNotIn("private", str(preview))
        self.assertNotIn("query-secret", str(preview))

    def test_patch_preview_describes_one_blank_trailing_page(self) -> None:
        """빈 페이지 추가 카드는 내부 marker 대신 사용자에게 보일 결과만 설명한다."""

        definition = ReportDefinitionVersion(
            str(uuid4()), 2, DefinitionStatus.DRAFT, "기존 제목",
            (ReportBlock(
                "summary", "요약", None, 12, None,
                BlockType.TEXT, 0, 0, 12, 4, "본문",
            ),),
        )
        patch_value = ReportAssistantPatch.model_validate({
            "summary": "빈 페이지 추가",
            "operations": [{"op": "add_report_page"}],
        })

        preview = _report_patch_preview(definition, patch_value)

        self.assertEqual("add_report_page", preview[0]["operation"])
        self.assertEqual("보고서 끝", preview[0]["target"])
        self.assertEqual("현재 1페이지", preview[0]["before"])
        self.assertEqual("2페이지 · 빈 A4 페이지 1장 추가", preview[0]["after"])
        self.assertEqual((), preview[0]["depends_on_indexes"])
        self.assertEqual(2, preview[0]["page_index"])
        self.assertEqual("LAYOUT", preview[0]["impact_category"])
        self.assertNotIn("page_break", str(preview))

    def test_multi_page_preview_groups_content_by_server_page_index(self) -> None:
        """다중 page와 후속 content는 target 문구가 아닌 1-based renderer page로 묶인다."""

        definition = ReportDefinitionVersion(
            str(uuid4()), 2, DefinitionStatus.DRAFT, "기존 제목",
            (ReportBlock(
                "summary", "요약", None, 12, None,
                BlockType.TEXT, 0, 0, 12, 4, "본문",
            ),),
        )
        patch_value = ReportAssistantPatch.model_validate({
            "summary": "두 페이지 구성 추가",
            "operations": [
                {"op": "add_report_page"},
                {
                    "op": "add_text", "title": "2페이지 요약", "content": "근거 요약",
                    "evidence_refs": ["artifact_narrative"],
                },
                {"op": "add_report_page"},
                {
                    "op": "add_text", "title": "3페이지 요약", "content": "근거 요약",
                    "evidence_refs": ["artifact_narrative"],
                },
            ],
        })

        preview = _report_patch_preview(definition, patch_value)

        self.assertEqual((2, 2, 3, 3), tuple(item["page_index"] for item in preview))
        self.assertEqual(
            ((), (0,), (0,), (2,)),
            tuple(item["depends_on_indexes"] for item in preview),
        )


class ReportAssistantComposeTest(unittest.IsolatedAsyncioTestCase):
    """새 분석 patch를 한 번 고정하고 저장 재개에서는 모델을 호출하지 않는지 검증한다."""

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
                "chart_spec_json": {
                    "chart_type": "bar", "x_field": "period",
                    "y_fields": ["value"],
                },
                "data_snapshot_json": {
                    "columns": ["period", "value"],
                    "rows": [{"period": "직전 월", "value": 1}],
                },
                "artifact_checksum": "a" * 64,
            }),
            finalize_existing_assistant_patch=AsyncMock(return_value=completed),
        )
        session = {
            "phase": "waiting_artifact",
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
                        "title": "직전 월 비교 · 차트",
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
            prepared = await _prepare_assistant_revision(
                repository,
                str(completed["assistant_request_id"]),
                session,
                await repository.get_assistant_artifact(str(new_artifact_id)),
                plan,
            )
            saving_session = {
                **session,
                "phase": "saving_revision",
                "report_patch_json": prepared["patch"],
                "decision_hash": prepared["decision_hash"],
                "model_version": prepared["model_version"],
                "prompt_id": prepared["prompt_id"],
                "prompt_version": prepared["prompt_version"],
                "prompt_hash": prepared["prompt_hash"],
            }
            result = await _compose_assistant_revision(
                repository,
                str(completed["assistant_request_id"]),
                str(data_request_id),
                saving_session,
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
        self.assertEqual(1, model.await_count)

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
                await _prepare_assistant_revision(
                    repository, str(uuid4()), session,
                    await repository.get_assistant_artifact(str(session["result_artifact_id"])), plan
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
                await _prepare_assistant_revision(
                    repository, str(uuid4()), session,
                    await repository.get_assistant_artifact(str(session["result_artifact_id"])), plan
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
            get_assistant_artifact=AsyncMock(return_value={
                "artifact_id": self.artifact_id,
                "trino_query_id": "query-1",
                "artifact_checksum": "a" * 64,
                "title": "새 분석",
                "narrative_markdown": "승인된 분석 결과",
                "evidence_json": {"metrics": []},
                "chart_spec_json": None,
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

    async def test_waiting_session_cancel_is_terminal_without_execution(self) -> None:
        """대기 세션 취소는 terminal 상태만 저장하고 모델·분석·Revision을 실행하지 않는다."""

        cancelled = {
            **self.session,
            "phase": "cancelled",
            "status": "failed",
            "error_code": "ASSISTANT_CANCELLED",
        }
        repository = SimpleNamespace(
            cancel_assistant_session=AsyncMock(return_value=(cancelled, True)),
        )
        with patch("app.api.report_router._router", return_value=SimpleNamespace(repository=repository)):
            response = await cancel_assistant_session(str(self.assistant_request_id), self.context)

        self.assertEqual("cancelled", response["phase"])
        self.assertFalse(response["retryable"])
        repository.cancel_assistant_session.assert_awaited_once_with(str(self.assistant_request_id))

    async def test_running_session_cancel_is_rejected_without_state_change(self) -> None:
        """실행·저장 중 취소 요청은 현재 작업을 취소했다고 가장하지 않고 409로 닫는다."""

        repository = SimpleNamespace(
            cancel_assistant_session=AsyncMock(side_effect=ValueError("ASSISTANT_CANCEL_NOT_ALLOWED")),
        )
        with patch("app.api.report_router._router", return_value=SimpleNamespace(repository=repository)):
            with self.assertRaises(HTTPException) as raised:
                await cancel_assistant_session(str(self.assistant_request_id), self.context)
        self.assertEqual(409, raised.exception.status_code)
        self.assertEqual("ASSISTANT_CANCEL_NOT_ALLOWED", raised.exception.detail["code"])

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
        prepare = AsyncMock(return_value={
            "decision_hash": "d" * 64,
            "model_version": "model",
            "prompt_id": "report.assistant.turn",
            "prompt_version": "PROMPT-v1.8.6",
            "prompt_hash": "p" * 64,
            "patch": {"summary": "새 근거 반영", "operations": []},
            "patch_preview": (),
        })
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
            patch("app.api.report_router._prepare_assistant_revision", new=prepare),
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
        prepare.assert_awaited_once()
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
            "operation_scope": "full_report",
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
                "available_views": ["summary"],
                "table_snapshot": {
                    "columns": [], "rows": [], "row_count": 0, "truncated": False,
                },
            },
            "report": {
                "title": "현재 보고서",
                "orientation": "portrait",
                "currency_display_unit": "auto",
                "page_count": 1,
                "blocks": [],
            },
            "history": [],
        }
        with (
            patch("app.adapters.report_assistant.resolve_active_model_routes", return_value=object()),
            patch("app.adapters.report_assistant.active_route_for_node", return_value=route),
            patch("app.adapters.report_assistant.openai_transport", new=transport),
        ):
            with self.assertRaises(ReportAssistantModelError) as raised:
                await generate_report_change_proposal(payload)

        self.assertEqual(2, transport.await_count)
        self.assertEqual("REPORT_ASSISTANT_MODEL_CONTRACT_INVALID", raised.exception.code)
        self.assertEqual(2, raised.exception.attempts)
        self.assertIsNotNone(raised.exception.duration_ms)

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
