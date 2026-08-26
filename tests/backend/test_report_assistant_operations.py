from __future__ import annotations

from decimal import Decimal
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from app.services.report_assistant_operations import estimate_model_cost, summarize_evaluations
from app.api.report_router import (
    _operations_period,
    create_assistant_session,
    get_assistant_evaluation,
    get_assistant_operation_failures,
    get_assistant_operations_summary,
    submit_assistant_message,
)
from app.contracts import RequestContext, Role
from app.report_contracts import (
    CreateReportAssistantSessionRequest,
    ReportAssistantMessageRequest,
)
from fastapi import HTTPException
from evals.report_assistant_quality import evaluate_report_assistant_quality
from src.report.domain import DefinitionStatus, ReportDefinitionVersion


class ReportAssistantOperationsTest(unittest.TestCase):
    def test_empty_sample_is_not_reported_as_zero_percent(self):
        summary = summarize_evaluations([])
        self.assertEqual(0, summary["total_requests"])
        self.assertIsNone(summary["contract_success_rate"])
        self.assertIsNone(summary["approval_rate"])
        self.assertIsNone(summary["total_input_tokens"])

    def test_summary_uses_request_rows_as_denominator_and_groups_safe_codes(self):
        rows = [
            {
                "contract_valid": True, "route": "existing_artifact",
                "approval_decision": "approved", "revision_created": True,
                "duplicate_revision_prevented": True, "latency_ms": 100,
                "model_attempts": 1, "input_tokens": 10, "output_tokens": 5,
                "estimated_cost": "0.01", "error_code": None,
            },
            {
                "contract_valid": False, "route": "new_data",
                "approval_decision": "rejected", "revision_created": False,
                "duplicate_revision_prevented": False, "latency_ms": 300,
                "model_attempts": 2, "input_tokens": None, "output_tokens": None,
                "estimated_cost": None, "error_code": "ANALYSIS_FAILED",
            },
        ]
        summary = summarize_evaluations(rows)
        self.assertEqual(2, summary["total_requests"])
        self.assertEqual(0.5, summary["contract_success_rate"])
        self.assertEqual(0.5, summary["approval_rate"])
        self.assertEqual(200, summary["average_model_latency_ms"])
        self.assertEqual({"ANALYSIS_FAILED": 0.5}, summary["failure_rate_by_error_code"])
        self.assertEqual(Decimal("0.01"), summary["estimated_cost_total"])

    def test_cost_is_null_without_provider_price_configuration(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(estimate_model_cost(10, 5))

    def test_cost_is_explicitly_estimated_from_configured_prices(self):
        with patch.dict(os.environ, {
            "REPORT_ASSISTANT_INPUT_USD_PER_MILLION": "2",
            "REPORT_ASSISTANT_OUTPUT_USD_PER_MILLION": "8",
        }, clear=True):
            self.assertEqual(Decimal("0.00006"), estimate_model_cost(10, 5))

    def test_deterministic_eval_rejects_forbidden_patch_operation(self):
        result = evaluate_report_assistant_quality(
            [{"id": "title", "route": "existing_artifact", "allowed": ["set_report_title"]}],
            {"title": {"route": "existing_artifact", "operations": ["remove_block"]}},
        )
        self.assertEqual(1, result["failed"])
        self.assertEqual("deterministic_fake", result["mode"])

    def test_operations_period_rejects_naive_or_more_than_31_days(self):
        end = datetime.now(timezone.utc)
        with self.assertRaises(HTTPException):
            _operations_period(end.replace(tzinfo=None) - timedelta(days=1), end)
        with self.assertRaises(HTTPException):
            _operations_period(end - timedelta(days=32), end)

    def test_successful_model_observation_clears_previous_transient_error(self):
        source = Path(
            "app/backend/app/adapters/report_assistant_operations_repository.py"
        ).read_text(encoding="utf-8")
        self.assertIn("error_code = EXCLUDED.error_code", source)
        self.assertNotIn(
            "error_code = COALESCE(EXCLUDED.error_code,\n"
            "                            report_assistant_evaluations.error_code)",
            source,
        )

    def test_nullable_estimated_cost_has_explicit_postgres_type(self):
        """비용 미측정값도 실제 PostgreSQL에서 모호한 bind parameter가 되지 않아야 한다."""

        source = Path(
            "app/backend/app/adapters/report_assistant_operations_repository.py"
        ).read_text(encoding="utf-8")
        self.assertIn("CAST(:estimated_cost AS numeric)", source)
        self.assertNotIn("(:estimated_cost IS NOT NULL)", source)

    def test_e2e_migration_receipt_uses_current_alembic_head(self):
        source = Path("tests/e2e/prepare_report_assistant_e2e.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("ScriptDirectory.from_config(config).get_current_head()", source)
        self.assertIn('print(f"E2E_MIGRATION_HEAD={head}")', source)
        self.assertNotIn('E2E_MIGRATION_HEAD=20260825_34', source)


class ReportAssistantOperationsApiTest(unittest.IsolatedAsyncioTestCase):
    def _ready_message_repository(self):
        assistant_request_id = uuid4()
        artifact_id = uuid4()
        definition_id = uuid4()
        session = {
            "assistant_request_id": assistant_request_id,
            "phase": "ready",
            "session_definition_id": definition_id,
            "session_definition_version": 1,
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
                "narrative_markdown": "승인된 결과",
                "evidence_json": {},
                "chart_spec_json": None,
                "artifact_checksum": "a" * 64,
            }),
            get_version=AsyncMock(return_value=ReportDefinitionVersion(
                str(definition_id), 1, DefinitionStatus.DRAFT, "보고서", (),
            )),
            record_assistant_proposal=AsyncMock(return_value=session),
            fail_assistant_request=AsyncMock(),
            upsert_assistant_evaluation=AsyncMock(),
        )
        return assistant_request_id, repository

    async def test_rate_limit_stops_before_session_or_model_work(self):
        repository = SimpleNamespace(
            count_recent_assistant_requests=AsyncMock(return_value=30),
            start_assistant_session=AsyncMock(),
        )
        context = RequestContext(user_id=uuid4(), role=Role.ANALYST)
        with (
            patch("app.api.report_router._router", return_value=SimpleNamespace(repository=repository)),
            patch.dict(os.environ, {"REPORT_ASSISTANT_REQUESTS_PER_HOUR": "30"}),
        ):
            with self.assertRaises(HTTPException) as raised:
                await create_assistant_session(
                    CreateReportAssistantSessionRequest(
                        definition_id=uuid4(), definition_version=1, artifact_id=uuid4()
                    ),
                    context,
                )
        self.assertEqual(429, raised.exception.status_code)
        self.assertEqual("ASSISTANT_RATE_LIMITED", raised.exception.detail["code"])
        repository.start_assistant_session.assert_not_awaited()

    async def test_admin_summary_and_failures_expose_only_typed_safe_rows(self):
        now = datetime.now(timezone.utc)
        row = {
            "evaluation_id": uuid4(), "assistant_request_id": uuid4(),
            "data_request_id": None, "patch_request_id": uuid4(),
            "definition_id": uuid4(), "definition_version": 2,
            "artifact_id": uuid4(), "prompt_id": "report.assistant.turn",
            "prompt_version": "PROMPT-v1", "model_version": "model-v1",
            "route": "existing_artifact", "operation_types": ["add_text"],
            "contract_valid": True, "approval_decision": "approved",
            "final_phase": "failed", "revision_created": False,
            "duplicate_revision_prevented": False, "model_attempts": 1,
            "latency_ms": 12.0, "input_tokens": None, "output_tokens": None,
            "estimated_cost": None, "cost_is_estimate": False,
            "error_code": "REPORT_REVISION_CONFLICT", "evaluated_at": now,
        }
        repository = SimpleNamespace(
            list_assistant_evaluations=AsyncMock(side_effect=([row], [row])),
        )
        context = RequestContext(user_id=uuid4(), role=Role.REPORT_ADMIN)
        with patch(
            "app.api.report_router._router",
            return_value=SimpleNamespace(repository=repository),
        ):
            summary = await get_assistant_operations_summary(context, now - timedelta(days=1), now)
            failures = await get_assistant_operation_failures(context, now - timedelta(days=1), now)
        self.assertEqual(1, summary["denominator"])
        self.assertEqual([row], failures["items"])
        self.assertNotIn("sql", str(summary).lower())
        self.assertNotIn("raw_model_response", str(failures))

    async def test_analyst_other_evaluation_is_hidden_as_not_found(self):
        repository = SimpleNamespace(
            get_assistant_evaluation=AsyncMock(side_effect=KeyError("평가를 찾을 수 없습니다.")),
        )
        context = RequestContext(user_id=uuid4(), role=Role.ANALYST)
        with patch(
            "app.api.report_router._router",
            return_value=SimpleNamespace(repository=repository),
        ):
            with self.assertRaises(HTTPException) as raised:
                await get_assistant_evaluation(str(uuid4()), context)
        self.assertEqual(404, raised.exception.status_code)

    async def test_input_token_limit_stops_before_model_call(self):
        assistant_request_id, repository = self._ready_message_repository()
        model = AsyncMock()
        with (
            patch("app.api.report_router._router", return_value=SimpleNamespace(repository=repository)),
            patch("app.adapters.report_assistant.generate_report_change_proposal", new=model),
            patch.dict(os.environ, {"REPORT_ASSISTANT_MAX_INPUT_TOKENS": "1"}),
        ):
            with self.assertRaises(HTTPException) as raised:
                await submit_assistant_message(
                    str(assistant_request_id),
                    ReportAssistantMessageRequest(instruction="보고서 제목을 바꿔 줘"),
                    object(),
                )
        self.assertEqual("ASSISTANT_TOKEN_BUDGET_EXCEEDED", raised.exception.detail["code"])
        model.assert_not_awaited()
        repository.record_assistant_proposal.assert_not_awaited()

    async def test_concurrency_limit_stops_before_model_call(self):
        assistant_request_id, repository = self._ready_message_repository()
        model = AsyncMock()
        gate = SimpleNamespace(acquire=AsyncMock(return_value=False), release=unittest.mock.Mock())
        with (
            patch("app.api.report_router._router", return_value=SimpleNamespace(repository=repository)),
            patch("app.api.router.execution_gate", gate),
            patch("app.adapters.report_assistant.generate_report_change_proposal", new=model),
        ):
            with self.assertRaises(HTTPException) as raised:
                await submit_assistant_message(
                    str(assistant_request_id),
                    ReportAssistantMessageRequest(instruction="보고서 제목을 바꿔 줘"),
                    object(),
                )
        self.assertEqual("ASSISTANT_CONCURRENCY_LIMITED", raised.exception.detail["code"])
        model.assert_not_awaited()
        gate.release.assert_not_called()
        repository.record_assistant_proposal.assert_not_awaited()

    async def test_cost_limit_fails_without_creating_revision(self):
        assistant_request_id, repository = self._ready_message_repository()
        model = AsyncMock(return_value=({
            "change_kind": "clarification",
            "message": "어느 기간을 사용할까요?",
            "analysis_plan": None,
            "patch": None,
        }, {
            "model_version": "model-v1",
            "prompt_id": "report.assistant.turn",
            "prompt_version": "PROMPT-v1",
            "prompt_hash": "b" * 64,
            "attempts": 1,
            "duration_ms": 10,
            "input_tokens": 100,
            "output_tokens": 100,
        }))
        with (
            patch("app.api.report_router._router", return_value=SimpleNamespace(repository=repository)),
            patch("app.adapters.report_assistant.generate_report_change_proposal", new=model),
            patch.dict(os.environ, {
                "REPORT_ASSISTANT_INPUT_USD_PER_MILLION": "1000",
                "REPORT_ASSISTANT_OUTPUT_USD_PER_MILLION": "1000",
                "REPORT_ASSISTANT_MAX_ESTIMATED_COST_USD": "0.01",
            }),
        ):
            with self.assertRaises(HTTPException) as raised:
                await submit_assistant_message(
                    str(assistant_request_id),
                    ReportAssistantMessageRequest(instruction="비교해 줘"),
                    object(),
                )
        self.assertEqual("ASSISTANT_COST_BUDGET_EXCEEDED", raised.exception.detail["code"])
        repository.fail_assistant_request.assert_awaited_once_with(
            str(assistant_request_id), "ASSISTANT_COST_BUDGET_EXCEEDED"
        )
        self.assertFalse(hasattr(repository, "finalize_existing_assistant_patch"))

    async def test_invalid_patch_is_recorded_without_creating_revision(self):
        assistant_request_id, repository = self._ready_message_repository()
        model = AsyncMock(return_value=({
            "change_kind": "existing_artifact",
            "message": "텍스트를 수정합니다.",
            "analysis_plan": None,
            "patch": {
                "summary": "없는 블록 수정",
                "operations": [{
                    "op": "update_text",
                    "block_id": str(uuid4()),
                    "title": "수정",
                    "content": None,
                }],
            },
        }, {
            "model_version": "model-v1",
            "prompt_id": "report.assistant.turn",
            "prompt_version": "PROMPT-v1",
            "prompt_hash": "b" * 64,
            "attempts": 1,
            "duration_ms": 10,
            "input_tokens": None,
            "output_tokens": None,
        }))
        with (
            patch("app.api.report_router._router", return_value=SimpleNamespace(repository=repository)),
            patch("app.adapters.report_assistant.generate_report_change_proposal", new=model),
        ):
            with self.assertRaises(HTTPException) as raised:
                await submit_assistant_message(
                    str(assistant_request_id),
                    ReportAssistantMessageRequest(instruction="없는 블록을 수정해 줘"),
                    object(),
                )
        self.assertEqual("REPORT_ASSISTANT_PATCH_INVALID", raised.exception.detail["code"])
        observed = repository.upsert_assistant_evaluation.await_args.kwargs
        self.assertEqual("existing_artifact", observed["route"])
        self.assertEqual("REPORT_ASSISTANT_PATCH_INVALID", observed["error_code"])
        self.assertTrue(observed["contract_valid"])
        self.assertFalse(hasattr(repository, "finalize_existing_assistant_patch"))


if __name__ == "__main__":
    unittest.main()
