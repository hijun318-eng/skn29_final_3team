from __future__ import annotations

import asyncio
from decimal import Decimal
from datetime import datetime, timedelta, timezone
import json
import os
from base64 import urlsafe_b64encode
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

BACKEND = Path(__file__).resolve().parents[2] / "app" / "backend"
sys.path.insert(0, str(BACKEND))

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
from src.report.domain import (
    BlockType,
    DefinitionStatus,
    ReportDefinitionVersion,
    normalize_report_block_content,
)
from tests.e2e.prepare_report_assistant_e2e import (
    E2E_ATOMIC_CHART_CONTENT,
    E2E_DATABASE,
    E2E_FIXTURE_VERSION,
    _analyst_account,
)
from tests.e2e.run_local_backend import (
    E2E_DATABASE as RUNNER_E2E_DATABASE,
    _require_read_only_environment,
)


PAGE_RENDERER_FINGERPRINT = "f" * 64
MODEL_COST_ENVIRONMENT = {
    "REPORT_ASSISTANT_INPUT_USD_PER_MILLION": "1",
    "REPORT_ASSISTANT_OUTPUT_USD_PER_MILLION": "1",
    "REPORT_ASSISTANT_MAX_ESTIMATED_COST_USD": "100",
}


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

    def test_cost_fails_closed_without_provider_price_configuration(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(RuntimeError):
                estimate_model_cost(10, 5)

    def test_cost_is_explicitly_estimated_from_configured_prices(self):
        with patch.dict(os.environ, {
            "REPORT_ASSISTANT_INPUT_USD_PER_MILLION": "2",
            "REPORT_ASSISTANT_OUTPUT_USD_PER_MILLION": "8",
            "REPORT_ASSISTANT_MAX_ESTIMATED_COST_USD": "1",
        }, clear=True):
            self.assertEqual(Decimal("0.00006"), estimate_model_cost(10, 5))

    def test_deterministic_eval_rejects_forbidden_patch_operation(self):
        result = evaluate_report_assistant_quality(
            [{"id": "title", "route": "existing_artifact", "allowed": ["set_report_title"]}],
            {"title": {"route": "existing_artifact", "operations": ["remove_block"]}},
        )
        self.assertEqual(1, result["failed"])
        self.assertEqual("deterministic_fake", result["mode"])

    def test_report_assistant_quality_dataset_covers_safe_gpt_workflows(self):
        cases = json.loads(
            Path("evals/report_assistant_quality_cases.json").read_text(encoding="utf-8")
        )
        self.assertEqual(28, len(cases))
        self.assertEqual(28, len({case["id"] for case in cases}))
        self.assertTrue(all(case.get("instruction") for case in cases))
        case_ids = {case["id"] for case in cases}
        self.assertTrue({
            "prompt-injection", "refinement-removes-old-operation",
            "add-grounded-text", "add-table-view", "add-chart-view",
            "add-artifact-bundle", "reposition-known-block", "resize-known-block",
            "duplicate-known-block", "remove-known-block", "restore-previous-revision",
            "composite-safe-edit", "selected-block-edit", "new-data-missing-period",
            "new-data-missing-metric", "unsupported-style-request",
            "unsupported-external-share", "invented-data-request",
            "conflicting-preserve-remove",
            "conflicting-move-unchanged",
        }.issubset(case_ids))

        outputs = {}
        for case in cases:
            refs = case.get("allowed_evidence_refs", []) if case.get("evidence_required") else []
            outputs[case["id"]] = {
                "route": case["route"],
                "contract_valid": True,
                "operations": [
                    {"op": operation, "evidence_refs": refs}
                    for operation in case.get("required", [])
                ],
                "dry_run_valid": case.get("dry_run_expected"),
                "approval": case.get("approval"),
                "error_code": case.get("error_code"),
                "attempts": 1,
                "latency_ms": 25,
                "input_tokens": None,
                "output_tokens": None,
                "estimated_cost": None,
                "prompt_version": "PROMPT-test",
                "model_version": "fake-model",
            }
        result = evaluate_report_assistant_quality(cases, outputs)
        self.assertEqual(len(cases), result["passed"])
        self.assertEqual(1.0, result["metrics"]["strict_contract_success_rate"])
        self.assertEqual(1.0, result["metrics"]["route_accuracy"])
        self.assertEqual(0.0, result["metrics"]["unnecessary_operation_rate"])
        self.assertIsNone(result["metrics"]["total_input_tokens"])
        self.assertIsNone(result["metrics"]["estimated_cost_total"])
        self.assertEqual(["PROMPT-test"], result["prompt_versions"])
        self.assertEqual(["fake-model"], result["model_versions"])

    def test_report_assistant_quality_reports_invalid_evidence_and_observations(self):
        result = evaluate_report_assistant_quality(
            [{
                "id": "summary", "route": "existing_artifact",
                "allowed": ["update_text"], "required": ["update_text"],
                "allowed_evidence_refs": ["artifact_narrative"],
                "evidence_required": True,
            }],
            {"summary": {
                "route": "existing_artifact", "contract_valid": True,
                "operations": [{"op": "update_text", "evidence_refs": ["unknown_ref"]}],
                "attempts": 2, "latency_ms": 40,
                "input_tokens": 100, "output_tokens": 20,
                "estimated_cost": "0.001",
            }},
        )
        self.assertEqual(1, result["failed"])
        self.assertEqual(0.0, result["metrics"]["evidence_ref_validity_rate"])
        self.assertEqual(2.0, result["metrics"]["average_model_attempts"])
        self.assertEqual(120, result["metrics"]["total_input_tokens"] + result["metrics"]["total_output_tokens"])
        self.assertEqual("0.001", result["metrics"]["estimated_cost_total"])

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
        self.assertIn("CAST(:estimated_cost AS numeric(18,8))", source)
        self.assertNotIn(
            "error_code = COALESCE(EXCLUDED.error_code,\n"
            "                            report_assistant_evaluations.error_code)",
            source,
        )

    def test_message_observation_is_serialized_by_revision_cas(self):
        source = Path(
            "app/backend/app/adapters/report_assistant_operations_repository.py"
        ).read_text(encoding="utf-8")
        for boundary in (
            "WITH current_request AS",
            "r.message_revision = CAST(:expected_message_revision AS bigint)",
            "FOR UPDATE",
            '"expected_message_revision": expected_message_revision',
        ):
            self.assertIn(boundary, source)

    def test_nullable_estimated_cost_has_explicit_postgres_type(self):
        """비용 미측정값도 실제 PostgreSQL에서 모호한 bind parameter가 되지 않아야 한다."""

        source = Path(
            "app/backend/app/adapters/report_assistant_operations_repository.py"
        ).read_text(encoding="utf-8")
        self.assertIn("CAST(:estimated_cost AS numeric(18,8))", source)
        self.assertNotIn("(:estimated_cost IS NOT NULL)", source)

    def test_e2e_migration_receipt_uses_current_alembic_head(self):
        source = Path("tests/e2e/prepare_report_assistant_e2e.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("ScriptDirectory.from_config(config).get_current_head()", source)
        self.assertIn('print(f"E2E_MIGRATION_HEAD={head}")', source)
        self.assertNotIn('E2E_MIGRATION_HEAD=20260825_34', source)

    def test_e2e_fixture_pins_atomic_v2_chart_content_and_readback(self):
        source = Path("tests/e2e/prepare_report_assistant_e2e.py").read_text(
            encoding="utf-8"
        )

        self.assertEqual("atomic-v2", E2E_FIXTURE_VERSION)
        self.assertEqual(
            E2E_ATOMIC_CHART_CONTENT,
            normalize_report_block_content(BlockType.CHART, E2E_ATOMIC_CHART_CONTENT),
        )
        for contract in (
            'uuid5(NAMESPACE, f"{E2E_FIXTURE_VERSION}:{name}")',
            "e2e_query_report_assistant_atomic_v2",
            "E2E_ATOMIC_CHART_CONTENT",
            "b.block_type = 'chart'",
            "b.artifact_id = a.artifact_id",
            "b.content::jsonb = %s::jsonb",
        ):
            self.assertIn(contract, source)
        self.assertNotIn("complete-receipt-v1", source)
        concurrency_fixture = Path(
            "tests/backend/test_report_assistant_postgres_concurrency.py"
        ).read_text(encoding="utf-8")
        self.assertIn("E2E_ATOMIC_CHART_CONTENT", concurrency_fixture)

    def test_e2e_account_seed_accepts_only_the_production_verifier_shape(self):
        with tempfile.TemporaryDirectory() as directory:
            principal_path = Path(directory) / "principals.json"
            subject = str(uuid4())
            account = {
                "username": "analyst",
                "password_salt": urlsafe_b64encode(b"0123456789abcdef").decode().rstrip("="),
                "password_hash": "a" * 64,
                "password_iterations": 210_000,
                "subject": subject,
                "role": "analyst",
                "active": True,
            }
            principal_path.write_text(json.dumps([account]), encoding="utf-8")

            loaded = _analyst_account({"AUTH_PRINCIPALS_HOST_FILE": str(principal_path)})

            self.assertEqual("analyst", loaded["username"])
            self.assertEqual(subject, str(loaded["subject"]))
            self.assertNotIn("role", loaded)
            self.assertNotIn("active", loaded)

            for field, value in (
                ("password_hash", "not-a-lowercase-sha256"),
                ("password_salt", "short"),
                ("password_iterations", True),
            ):
                invalid = {**account, field: value}
                principal_path.write_text(json.dumps([invalid]), encoding="utf-8")
                with self.subTest(field=field), self.assertRaisesRegex(
                    RuntimeError, "verifier 형식"
                ):
                    _analyst_account({"AUTH_PRINCIPALS_HOST_FILE": str(principal_path)})

    def test_read_only_e2e_backend_requires_isolated_db_without_model_credentials(self):
        valid = f"postgresql://local:local@127.0.0.1:15432/{E2E_DATABASE}"
        self.assertEqual(E2E_DATABASE, RUNNER_E2E_DATABASE)
        with patch.dict(os.environ, {"APP_RUNTIME_DATABASE_URL": valid}, clear=True):
            _require_read_only_environment()

        for invalid in (
            "",
            "postgresql://local:local@127.0.0.1:15432/app_db",
            f"postgresql://local:local@database.internal:5432/{E2E_DATABASE}",
            f"sqlite:///{E2E_DATABASE}",
        ):
            with self.subTest(database_url=invalid), patch.dict(
                os.environ, {"APP_RUNTIME_DATABASE_URL": invalid}, clear=True
            ), self.assertRaisesRegex(RuntimeError, E2E_DATABASE):
                _require_read_only_environment()

        for credential in ("OPENAI_API_KEY", "NODE2_MODEL_API_TOKEN"):
            with self.subTest(credential=credential), patch.dict(os.environ, {
                "APP_RUNTIME_DATABASE_URL": valid,
                credential: "configured-forbidden-secret",
            }, clear=True), self.assertRaisesRegex(RuntimeError, credential):
                _require_read_only_environment()

        runner = Path("tests/e2e/run_local_backend.py").read_text(encoding="utf-8")
        self.assertIn('lifespan="off"', runner)


class ReportAssistantOperationsApiTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        """모델 흐름 테스트는 명시적인 저비용 provider 정책으로 실행한다."""

        from app.adapters.report_assistant import ReportAssistantModelInvocation

        self._cost_environment = patch.dict(
            os.environ, MODEL_COST_ENVIRONMENT, clear=False
        )
        self._cost_environment.start()
        self.addCleanup(self._cost_environment.stop)
        self._test_model_invocation = ReportAssistantModelInvocation(
            node="report_assistant_turn",
            route=SimpleNamespace(data_boundary="internal"),
            payload_hash="a" * 64,
            timeout=60.0,
            max_attempts=1,
            authorization=object(),
            repository=object(),
        )
        self._consent_gate = patch(
            "app.api.report_router._consented_assistant_model_invocation",
            new=AsyncMock(return_value=self._test_model_invocation),
        )
        self._consent_gate.start()
        self.addCleanup(self._consent_gate.stop)

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
                "narrative_markdown": "승인된 결과",
                "evidence_json": {},
                "chart_spec_json": None,
                "artifact_checksum": "a" * 64,
            }),
            get_version=AsyncMock(return_value=ReportDefinitionVersion(
                str(definition_id), 1, DefinitionStatus.DRAFT, "보고서", (),
            )),
            record_assistant_proposal=AsyncMock(return_value={
                **session, "message_revision": 1,
            }),
            claim_assistant_model_execution=AsyncMock(
                return_value="33333333-3333-4333-8333-333333333333"
            ),
            release_assistant_model_execution=AsyncMock(return_value=True),
            fail_assistant_request=AsyncMock(return_value=True),
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

    async def test_report_title_scope_rejects_other_operation_before_persistence(self):
        """모델 어댑터를 우회한 잘못된 제목 전용 응답도 router가 저장 전에 닫는다."""

        assistant_request_id, repository = self._ready_message_repository()
        model = AsyncMock(return_value=({
            "change_kind": "existing_artifact",
            "message": "요약을 추가합니다.",
            "analysis_plan": None,
            "patch": {
                "summary": "요약 추가",
                "operations": [{
                    "op": "add_text", "title": "요약", "content": "내용",
                    "evidence_refs": ["artifact_narrative"],
                    "placement": {"after_block_id": None, "width": "full"},
                }],
            },
            "suggestions": [],
        }, {
            "model_version": "model-v1", "prompt_id": "report.assistant.turn",
            "prompt_version": "PROMPT-v1", "prompt_hash": "b" * 64,
            "attempts": 1, "duration_ms": 10,
            "input_tokens": None, "output_tokens": None,
        }))
        with (
            patch("app.api.report_router._router", return_value=SimpleNamespace(repository=repository)),
            patch("app.adapters.report_assistant.generate_report_change_proposal", new=model),
        ):
            with self.assertRaises(HTTPException) as raised:
                await submit_assistant_message(
                    str(assistant_request_id),
                    ReportAssistantMessageRequest(
                        instruction="제목을 제안해 줘", operation_scope="report_title",
                    ),
                    object(),
                )

        self.assertEqual(502, raised.exception.status_code)
        self.assertEqual("REPORT_ASSISTANT_MODEL_CONTRACT_INVALID", raised.exception.detail["code"])
        self.assertEqual("report_title", model.await_args.args[0]["operation_scope"])
        repository.fail_assistant_request.assert_awaited_once_with(
            str(assistant_request_id), "REPORT_ASSISTANT_MODEL_CONTRACT_INVALID",
            operation_scope="report_title",
            expected_phase="ready",
            expected_message_revision=0,
            model_execution_id="33333333-3333-4333-8333-333333333333",
        )
        repository.record_assistant_proposal.assert_not_awaited()

    async def test_single_title_patch_refinement_cannot_expand_scope(self):
        """기존 제목 단일 patch는 클라이언트의 full_report 요청보다 좁은 scope를 유지한다."""

        assistant_request_id, repository = self._ready_message_repository()
        patch_request_id = uuid4()
        repository.get_assistant_session.return_value.update({
            "phase": "waiting_patch_approval",
            "patch_request_id": patch_request_id,
            "report_patch_json": {
                "summary": "제목 변경",
                "operations": [{"op": "set_report_title", "title": "첫 제목"}],
            },
        })
        repository.replace_existing_assistant_patch_proposal = AsyncMock()
        model = AsyncMock(return_value=({
            "change_kind": "existing_artifact",
            "message": "본문을 추가합니다.",
            "analysis_plan": None,
            "patch": {
                "summary": "본문 추가",
                "operations": [{
                    "op": "add_text", "title": "본문", "content": "내용",
                    "evidence_refs": ["artifact_narrative"],
                    "placement": {"after_block_id": None, "width": "full"},
                }],
            },
            "suggestions": [],
        }, {
            "model_version": "model-v1", "prompt_id": "report.assistant.turn",
            "prompt_version": "PROMPT-v1", "prompt_hash": "b" * 64,
            "attempts": 1, "duration_ms": 10,
            "input_tokens": None, "output_tokens": None,
        }))
        with (
            patch("app.api.report_router._router", return_value=SimpleNamespace(repository=repository)),
            patch("app.adapters.report_assistant.generate_report_change_proposal", new=model),
        ):
            with self.assertRaises(HTTPException) as raised:
                await submit_assistant_message(
                    str(assistant_request_id),
                    ReportAssistantMessageRequest(
                        instruction="본문도 추가해 줘",
                        expected_patch_request_id=patch_request_id,
                        operation_scope="full_report",
                    ),
                    object(),
                )

        self.assertEqual(502, raised.exception.status_code)
        self.assertEqual("report_title", model.await_args.args[0]["operation_scope"])
        repository.replace_existing_assistant_patch_proposal.assert_not_awaited()

    async def test_title_clarification_followup_cannot_expand_to_data_or_other_patch(self):
        """저장된 제목 clarification 후속 턴은 클라이언트 default보다 서버 scope가 우선한다."""

        trace = {
            "model_version": "model-v1", "prompt_id": "report.assistant.turn",
            "prompt_version": "PROMPT-v1", "prompt_hash": "b" * 64,
            "attempts": 1, "duration_ms": 10,
            "input_tokens": None, "output_tokens": None,
        }
        invalid_followups = (
            {
                "change_kind": "new_data", "message": "새 분석이 필요합니다.",
                "analysis_plan": {"question": "새 분석"}, "patch": None,
                "suggestions": [],
            },
            {
                "change_kind": "existing_artifact", "message": "본문을 추가합니다.",
                "analysis_plan": None,
                "patch": {
                    "summary": "본문 추가",
                    "operations": [{
                        "op": "add_text", "title": "본문", "content": "내용",
                        "evidence_refs": ["artifact_narrative"],
                        "placement": {"after_block_id": None, "width": "full"},
                    }],
                },
                "suggestions": [],
            },
        )
        for invalid_followup in invalid_followups:
            with self.subTest(change_kind=invalid_followup["change_kind"]):
                assistant_request_id, repository = self._ready_message_repository()
                session = repository.get_assistant_session.return_value
                session["operation_scope"] = "full_report"

                async def save_clarification(*args, **_kwargs):
                    session["operation_scope"] = args[-1]
                    session["message_revision"] += 1
                    return dict(session)

                repository.record_assistant_proposal.side_effect = save_clarification
                model = AsyncMock(side_effect=[
                    ({
                        "change_kind": "clarification", "message": "제목의 초점을 알려 주세요.",
                        "analysis_plan": None, "patch": None, "suggestions": [],
                    }, trace),
                    (invalid_followup, trace),
                ])
                with (
                    patch(
                        "app.api.report_router._router",
                        return_value=SimpleNamespace(repository=repository),
                    ),
                    patch(
                        "app.adapters.report_assistant.generate_report_change_proposal",
                        new=model,
                    ),
                ):
                    first = await submit_assistant_message(
                        str(assistant_request_id),
                        ReportAssistantMessageRequest(
                            instruction="제목을 제안해 줘", operation_scope="report_title",
                        ),
                        object(),
                    )
                    with self.assertRaises(HTTPException) as raised:
                        await submit_assistant_message(
                            str(assistant_request_id),
                            ReportAssistantMessageRequest(
                                instruction="간결한 월간 제목이야", operation_scope="full_report",
                            ),
                            object(),
                        )

                self.assertEqual("report_title", first["session"]["operation_scope"])
                self.assertEqual("report_title", model.await_args_list[1].args[0]["operation_scope"])
                self.assertEqual(502, raised.exception.status_code)
                self.assertEqual(
                    "REPORT_ASSISTANT_MODEL_CONTRACT_INVALID", raised.exception.detail["code"],
                )
                repository.record_assistant_proposal.assert_awaited_once()

    async def test_title_clarification_followup_accepts_one_title_preview(self):
        """제목 clarification 후속 턴은 단일 제목 미리보기만 영속한다."""

        assistant_request_id, repository = self._ready_message_repository()
        session = repository.get_assistant_session.return_value
        session["operation_scope"] = "full_report"

        async def save_clarification(*args, **_kwargs):
            session["operation_scope"] = args[-1]
            session["message_revision"] += 1
            return dict(session)

        async def save_title_patch(*args, **_kwargs):
            session.update({
                "phase": "waiting_patch_approval",
                "operation_scope": args[-1],
                "message_revision": session["message_revision"] + 1,
                "patch_request_id": args[1],
                "report_patch_json": args[8],
                "patch_preview_json": args[9],
                "verified_page_count": _kwargs["verified_page_count"],
                "page_renderer_fingerprint": _kwargs["page_renderer_fingerprint"],
            })
            return dict(session)

        repository.record_assistant_proposal.side_effect = save_clarification
        repository.record_existing_assistant_patch_proposal = AsyncMock(
            side_effect=save_title_patch
        )
        trace = {
            "model_version": "model-v1", "prompt_id": "report.assistant.turn",
            "prompt_version": "PROMPT-v1", "prompt_hash": "b" * 64,
            "attempts": 1, "duration_ms": 10,
            "input_tokens": None, "output_tokens": None,
        }
        model = AsyncMock(side_effect=[
            ({
                "change_kind": "clarification", "message": "제목의 초점을 알려 주세요.",
                "analysis_plan": None, "patch": None, "suggestions": [],
            }, trace),
            ({
                "change_kind": "existing_artifact", "message": "제목을 제안합니다.",
                "analysis_plan": None,
                "patch": {
                    "summary": "보고서 제목 변경",
                    "operations": [{
                        "op": "set_report_title", "title": "월간 객실 매출 운영 보고서",
                    }],
                },
                "suggestions": [],
            }, trace),
        ])
        with (
            patch(
                "app.api.report_router._router",
                return_value=SimpleNamespace(repository=repository),
            ),
            patch(
                "app.adapters.report_assistant.generate_report_change_proposal", new=model,
            ),
            patch(
                "app.services.report.document.render_report_page_count", return_value=1,
            ),
            patch(
                "app.services.report.document.report_renderer_contract_fingerprint",
                return_value=PAGE_RENDERER_FINGERPRINT,
            ),
        ):
            await submit_assistant_message(
                str(assistant_request_id),
                ReportAssistantMessageRequest(
                    instruction="제목을 제안해 줘", operation_scope="report_title",
                ),
                object(),
            )
            response = await submit_assistant_message(
                str(assistant_request_id),
                ReportAssistantMessageRequest(
                    instruction="월간 운영 성과를 강조해 줘",
                    operation_scope="full_report",
                ),
                object(),
            )

        self.assertEqual("existing_artifact", response["change_kind"])
        self.assertEqual("waiting_patch_approval", response["session"]["phase"])
        self.assertEqual("report_title", response["session"]["operation_scope"])
        self.assertEqual("report_title", model.await_args_list[1].args[0]["operation_scope"])
        self.assertEqual(
            "report_title",
            repository.record_existing_assistant_patch_proposal.await_args.args[-1],
        )

    async def test_late_full_report_save_cannot_downgrade_concurrent_title_scope(self):
        """먼저 저장된 제목 scope를 이미 시작한 일반 요청이 역순으로 덮지 못한다."""

        assistant_request_id, repository = self._ready_message_repository()
        session = repository.get_assistant_session.return_value
        session["operation_scope"] = "full_report"
        full_model_started = asyncio.Event()
        title_saved = asyncio.Event()
        observed_scopes: list[str] = []

        async def model(payload, **_kwargs):
            scope = payload["operation_scope"]
            observed_scopes.append(scope)
            if scope == "report_title":
                await full_model_started.wait()
            else:
                full_model_started.set()
                await title_saved.wait()
            return ({
                "change_kind": "clarification", "message": "추가 정보가 필요합니다.",
                "analysis_plan": None, "patch": None, "suggestions": [],
            }, {
                "model_version": "model-v1", "prompt_id": "report.assistant.turn",
                "prompt_version": "PROMPT-v1", "prompt_hash": "b" * 64,
                "attempts": 1, "duration_ms": 10,
                "input_tokens": None, "output_tokens": None,
            })

        async def guarded_save(*args, **_kwargs):
            requested_scope = args[-1]
            if session["operation_scope"] == "report_title" and requested_scope == "full_report":
                raise ValueError("ASSISTANT_STATE_CONFLICT")
            session["operation_scope"] = requested_scope
            session["message_revision"] += 1
            if requested_scope == "report_title":
                title_saved.set()
            return dict(session)

        repository.record_assistant_proposal.side_effect = guarded_save
        gate = SimpleNamespace(
            acquire=AsyncMock(return_value=True), release=unittest.mock.Mock(),
        )
        with (
            patch(
                "app.api.report_router._router",
                return_value=SimpleNamespace(repository=repository),
            ),
            patch(
                "app.adapters.report_assistant.generate_report_change_proposal",
                new=AsyncMock(side_effect=model),
            ),
            patch("app.api.router.execution_gate", gate),
        ):
            title_task = asyncio.create_task(submit_assistant_message(
                str(assistant_request_id),
                ReportAssistantMessageRequest(
                    instruction="제목을 제안해 줘", operation_scope="report_title",
                ),
                object(),
            ))
            full_task = asyncio.create_task(submit_assistant_message(
                str(assistant_request_id),
                ReportAssistantMessageRequest(
                    instruction="본문을 새로 작성해 줘", operation_scope="full_report",
                ),
                object(),
            ))
            title_result, full_result = await asyncio.gather(
                title_task, full_task, return_exceptions=True
            )

        self.assertIsInstance(full_result, HTTPException)
        self.assertEqual(409, full_result.status_code)
        self.assertEqual("ASSISTANT_STATE_CONFLICT", full_result.detail["code"])
        self.assertEqual("report_title", title_result["session"]["operation_scope"])
        self.assertEqual("report_title", session["operation_scope"])
        self.assertCountEqual(["report_title", "full_report"], observed_scopes)
        repository.fail_assistant_request.assert_awaited_once_with(
            str(assistant_request_id),
            "ASSISTANT_STATE_CONFLICT",
            operation_scope="full_report",
            expected_phase="ready",
            expected_message_revision=0,
            model_execution_id="33333333-3333-4333-8333-333333333333",
        )

    async def test_identical_concurrent_messages_have_one_canonical_save(self):
        """같은 문장이 같은 revision에서 겹쳐도 한 응답만 canonical turn으로 저장된다."""

        assistant_request_id, repository = self._ready_message_repository()
        session = repository.get_assistant_session.return_value
        first_claim_started = asyncio.Event()
        claim_count = 0
        model_count = 0

        async def model(_payload, **_kwargs):
            nonlocal model_count
            model_count += 1
            return ({
                "change_kind": "clarification",
                "message": "기간을 알려 주세요.",
                "analysis_plan": None,
                "patch": None,
                "suggestions": [],
            }, {
                "model_version": "model-v1", "prompt_id": "report.assistant.turn",
                "prompt_version": "PROMPT-v1", "prompt_hash": "b" * 64,
                "attempts": 1, "duration_ms": 10,
                "input_tokens": None, "output_tokens": None,
            })

        async def claim_once(*_args, **_kwargs):
            nonlocal claim_count
            claim_count += 1
            if claim_count == 1:
                first_claim_started.set()
                await asyncio.sleep(0)
                return "33333333-3333-4333-8333-333333333333"
            await first_claim_started.wait()
            raise ValueError("ASSISTANT_MODEL_EXECUTION_CONFLICT")

        async def save_once(*_args, **kwargs):
            if session["message_revision"] != kwargs["expected_message_revision"]:
                raise ValueError("ASSISTANT_STATE_CONFLICT")
            session["message_revision"] += 1
            return dict(session)

        repository.record_assistant_proposal.side_effect = save_once
        repository.claim_assistant_model_execution.side_effect = claim_once
        gate = SimpleNamespace(
            acquire=AsyncMock(return_value=True), release=unittest.mock.Mock(),
        )
        with (
            patch(
                "app.api.report_router._router",
                return_value=SimpleNamespace(repository=repository),
            ),
            patch(
                "app.adapters.report_assistant.generate_report_change_proposal",
                new=AsyncMock(side_effect=model),
            ),
            patch("app.api.router.execution_gate", gate),
        ):
            results = await asyncio.gather(*(
                submit_assistant_message(
                    str(assistant_request_id),
                    ReportAssistantMessageRequest(instruction="같은 문장"),
                    object(),
                )
                for _ in range(2)
            ), return_exceptions=True)

        self.assertEqual(1, sum(isinstance(result, dict) for result in results))
        conflicts = [result for result in results if isinstance(result, HTTPException)]
        self.assertEqual(1, len(conflicts))
        self.assertEqual(409, conflicts[0].status_code)
        self.assertEqual("ASSISTANT_MODEL_EXECUTION_CONFLICT", conflicts[0].detail["code"])
        self.assertEqual(1, model_count)
        self.assertEqual(1, session["message_revision"])
        self.assertEqual(1, repository.upsert_assistant_evaluation.await_count)
        observed = repository.upsert_assistant_evaluation.await_args.kwargs
        self.assertEqual(1, observed["expected_message_revision"])

    async def test_submit_success_rejects_stale_session_hydration(self):
        """저장 뒤 revision-bound 재조회가 실패하면 과거 상태와 새 history를 섞지 않는다."""

        assistant_request_id, repository = self._ready_message_repository()
        initial = repository.get_assistant_session.return_value
        repository.get_assistant_session.side_effect = (
            initial,
            KeyError("stale message revision"),
        )
        model = AsyncMock(return_value=({
            "change_kind": "clarification",
            "message": "기간을 알려 주세요.",
            "analysis_plan": None,
            "patch": None,
            "suggestions": [],
        }, {
            "model_version": "model-v1", "prompt_id": "report.assistant.turn",
            "prompt_version": "PROMPT-v1", "prompt_hash": "b" * 64,
            "attempts": 1, "duration_ms": 10,
            "input_tokens": None, "output_tokens": None,
        }))
        with (
            patch("app.api.report_router._router", return_value=SimpleNamespace(repository=repository)),
            patch("app.adapters.report_assistant.generate_report_change_proposal", new=model),
        ):
            with self.assertRaises(HTTPException) as raised:
                await submit_assistant_message(
                    str(assistant_request_id),
                    ReportAssistantMessageRequest(instruction="기간별로 정리해 줘"),
                    object(),
                )

        self.assertEqual(409, raised.exception.status_code)
        self.assertEqual("ASSISTANT_STATE_CONFLICT", raised.exception.detail["code"])
        self.assertEqual(
            {"expected_message_revision": 1},
            repository.get_assistant_session.await_args.kwargs,
        )

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
            str(assistant_request_id),
            "ASSISTANT_COST_BUDGET_EXCEEDED",
            operation_scope="full_report",
            expected_phase="ready",
            expected_message_revision=0,
            model_execution_id="33333333-3333-4333-8333-333333333333",
        )
        repository.record_assistant_proposal.assert_not_awaited()
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
        repository.fail_assistant_request.assert_awaited_once_with(
            str(assistant_request_id),
            "REPORT_ASSISTANT_PATCH_INVALID",
            operation_scope="full_report",
            expected_phase="ready",
            expected_message_revision=0,
            model_execution_id="33333333-3333-4333-8333-333333333333",
        )
        observed = repository.upsert_assistant_evaluation.await_args.kwargs
        self.assertEqual("existing_artifact", observed["route"])
        self.assertEqual("REPORT_ASSISTANT_PATCH_INVALID", observed["error_code"])
        self.assertTrue(observed["contract_valid"])
        self.assertFalse(hasattr(repository, "finalize_existing_assistant_patch"))

    async def test_losing_ready_failure_does_not_overwrite_winner_evaluation(self):
        """같은 revision의 실패 경쟁에서 DB fail claim을 잃은 요청은 평가를 쓰지 않는다."""

        from app.adapters.report_assistant import ReportAssistantModelError

        assistant_request_id, repository = self._ready_message_repository()
        repository.fail_assistant_request.return_value = False
        with (
            patch(
                "app.api.report_router._router",
                return_value=SimpleNamespace(repository=repository),
            ),
            patch(
                "app.adapters.report_assistant.generate_report_change_proposal",
                new=AsyncMock(side_effect=ReportAssistantModelError(
                    "late failure",
                    code="REPORT_ASSISTANT_MODEL_TIMEOUT",
                    attempts=1,
                    duration_ms=10,
                )),
            ),
        ):
            with self.assertRaises(HTTPException):
                await submit_assistant_message(
                    str(assistant_request_id),
                    ReportAssistantMessageRequest(instruction="같은 요청"),
                    object(),
                )

        repository.fail_assistant_request.assert_awaited_once()
        repository.upsert_assistant_evaluation.assert_not_awaited()

    async def test_rejected_patch_invalidates_late_refinement_failure(self):
        """사용자 거절 뒤 도착한 refinement 실패는 patch/session을 실패로 되돌리지 않는다."""

        from app.adapters.report_assistant import ReportAssistantModelError

        assistant_request_id, repository = self._ready_message_repository()
        session = repository.get_assistant_session.return_value
        patch_request_id = uuid4()
        session.update({
            "phase": "waiting_patch_approval",
            "operation_scope": "report_title",
            "patch_request_id": patch_request_id,
            "report_patch_json": {
                "summary": "제목 변경",
                "operations": [{"op": "set_report_title", "title": "월간 보고서"}],
            },
        })
        started = asyncio.Event()
        release = asyncio.Event()

        async def late_failure(_payload, **_kwargs):
            started.set()
            await release.wait()
            raise ReportAssistantModelError(
                "late failure",
                code="REPORT_ASSISTANT_MODEL_TIMEOUT",
                attempts=1,
                duration_ms=10,
            )

        with (
            patch(
                "app.api.report_router._router",
                return_value=SimpleNamespace(repository=repository),
            ),
            patch(
                "app.adapters.report_assistant.generate_report_change_proposal",
                new=AsyncMock(side_effect=late_failure),
            ),
        ):
            task = asyncio.create_task(submit_assistant_message(
                str(assistant_request_id),
                ReportAssistantMessageRequest(
                    instruction="제목을 더 짧게",
                    expected_patch_request_id=patch_request_id,
                ),
                object(),
            ))
            await started.wait()
            session.update({
                "phase": "ready",
                "operation_scope": "full_report",
                "message_revision": 1,
            })
            release.set()
            with self.assertRaises(HTTPException) as raised:
                await task

        self.assertEqual(502, raised.exception.status_code)
        repository.fail_assistant_request.assert_not_awaited()
        observed = repository.upsert_assistant_evaluation.await_args.kwargs
        self.assertEqual(0, observed["expected_message_revision"])
        self.assertEqual("ready", session["phase"])
        self.assertEqual("full_report", session["operation_scope"])

    async def test_refinement_cost_and_patch_errors_preserve_waiting_patch(self):
        """refinement의 비용·patch 오류는 기존 승인 대기 상태를 실패 처리하지 않는다."""

        cases = (
            ("cost", "ASSISTANT_COST_BUDGET_EXCEEDED", 429),
            ("patch", "REPORT_ASSISTANT_PATCH_INVALID", 502),
        )
        for kind, code, status in cases:
            with self.subTest(kind=kind):
                assistant_request_id, repository = self._ready_message_repository()
                session = repository.get_assistant_session.return_value
                patch_request_id = uuid4()
                session.update({
                    "phase": "waiting_patch_approval",
                    "patch_request_id": patch_request_id,
                    "report_patch_json": {
                        "summary": "기존 제목 변경",
                        "operations": [{"op": "set_report_title", "title": "기존 제안"}],
                    },
                })
                patch_body = (
                    {"summary": "새 제목", "operations": [
                        {"op": "set_report_title", "title": "새 제안"},
                    ]}
                    if kind == "cost" else
                    {"summary": "유효하지 않은 제목", "operations": [{
                        "op": "set_report_title", "title": "",
                    }]}
                )
                model = AsyncMock(return_value=({
                    "change_kind": "existing_artifact",
                    "message": "변경안을 준비했습니다.",
                    "analysis_plan": None,
                    "patch": patch_body,
                    "suggestions": [],
                }, {
                    "model_version": "model-v1", "prompt_id": "report.assistant.turn",
                    "prompt_version": "PROMPT-v1", "prompt_hash": "b" * 64,
                    "attempts": 1, "duration_ms": 10,
                    "input_tokens": 100 if kind == "cost" else None,
                    "output_tokens": 100 if kind == "cost" else None,
                }))
                environment = {
                    "REPORT_ASSISTANT_INPUT_USD_PER_MILLION": "1000",
                    "REPORT_ASSISTANT_OUTPUT_USD_PER_MILLION": "1000",
                    "REPORT_ASSISTANT_MAX_ESTIMATED_COST_USD": "0.01",
                } if kind == "cost" else {}
                with (
                    patch(
                        "app.api.report_router._router",
                        return_value=SimpleNamespace(repository=repository),
                    ),
                    patch(
                        "app.adapters.report_assistant.generate_report_change_proposal",
                        new=model,
                    ),
                    patch.dict(os.environ, environment),
                ):
                    with self.assertRaises(HTTPException) as raised:
                        await submit_assistant_message(
                            str(assistant_request_id),
                            ReportAssistantMessageRequest(
                                instruction="제안을 고쳐 줘",
                                expected_patch_request_id=patch_request_id,
                            ),
                            object(),
                        )

                self.assertEqual(status, raised.exception.status_code)
                self.assertEqual(code, raised.exception.detail["code"])
                repository.fail_assistant_request.assert_not_awaited()
                observed = repository.upsert_assistant_evaluation.await_args.kwargs
                self.assertEqual(0, observed["expected_message_revision"])
                self.assertEqual("waiting_patch_approval", session["phase"])


if __name__ == "__main__":
    unittest.main()
