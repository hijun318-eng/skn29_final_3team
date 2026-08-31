"""격리 PostgreSQL에서 Report Assistant 승인·재수정 CAS 경쟁을 검증한다."""

from __future__ import annotations

import asyncio
from dataclasses import replace
import inspect
import os
import unittest
from uuid import UUID, uuid4

import psycopg
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.main import app as _app  # noqa: F401
from app.adapters.report_repository import PostgresReportRepository
from tests.e2e.prepare_report_assistant_e2e import (
    E2E_ATOMIC_CHART_CONTENT,
    E2E_DATABASE,
    E2E_PERMISSION_SNAPSHOT_ID,
    E2E_PRODUCT_RELEASE_ID,
    E2E_SEMANTIC_RELEASE_ID,
    _analyst_subject,
    _canonical_sha256,
    _deployment_values,
    _dsn,
    _release_fixture,
    _seed,
)


if os.name == "nt":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


@unittest.skipUnless(
    os.getenv("ANSWERVICE_DEPLOY_ENV_FILE"),
    "ANSWERVICE_DEPLOY_ENV_FILE이 지정된 격리 PostgreSQL 검증에서만 실행합니다.",
)
class ReportAssistantPostgresConcurrencyTest(unittest.IsolatedAsyncioTestCase):
    """운영·공용 DB를 건드리지 않고 전용 E2E DB의 실제 row lock을 검증한다."""

    async def asyncSetUp(self) -> None:
        values = _deployment_values()
        self.owner = _analyst_subject(values)
        self.database_url = _dsn(
            values["APP_MIGRATION_USER"],
            values["APP_MIGRATION_PASSWORD"],
            E2E_DATABASE,
        )
        if self.database_url.rsplit("/", 1)[-1] != E2E_DATABASE:
            self.fail("Report Assistant 동시성 테스트는 격리 E2E DB에서만 실행할 수 있습니다.")
        self.engine = create_async_engine(
            self.database_url.replace("postgresql://", "postgresql+psycopg://", 1),
            pool_pre_ping=True,
        )
        self.factory = async_sessionmaker(self.engine, expire_on_commit=False)
        self.repository = PostgresReportRepository(
            self.database_url,
            self.owner,
            session_factory=self.factory,
        )
        self.definition_id = uuid4()
        self.block_id = uuid4()
        self.assistant_request_id = uuid4()
        self.patch_request_id = uuid4()
        self.artifact_id = self._prepare_report()

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()
        with psycopg.connect(self.database_url) as connection:
            connection.execute(
                "DELETE FROM report_v1.report_assistant_requests "
                "WHERE retry_of_assistant_request_id = %s",
                (self.assistant_request_id,),
            )
            connection.execute(
                "DELETE FROM report_v1.report_assistant_requests WHERE assistant_request_id = %s",
                (self.assistant_request_id,),
            )
            connection.execute(
                "DELETE FROM report_v1.report_blocks WHERE definition_id = %s",
                (self.definition_id,),
            )
            connection.execute(
                "DELETE FROM report_v1.report_definition_versions WHERE definition_id = %s",
                (self.definition_id,),
            )
            connection.execute(
                "DELETE FROM report_v1.report_definitions WHERE definition_id = %s",
                (self.definition_id,),
            )
            connection.execute(
                "ALTER TABLE governance.product_release_bindings "
                "DISABLE TRIGGER product_release_bindings_immutable"
            )
            try:
                connection.execute(
                    "DELETE FROM governance.product_release_bindings "
                    "WHERE object_kind = 'REPORT' AND object_id IN (%s, %s)",
                    (
                        f"definition:{self.definition_id}:v1",
                        f"definition:{self.definition_id}:v2",
                    ),
                )
            finally:
                connection.execute(
                    "ALTER TABLE governance.product_release_bindings "
                    "ENABLE TRIGGER product_release_bindings_immutable"
                )

    def _prepare_report(self) -> UUID:
        """현재 owner의 승인 Artifact 하나를 새 전용 Report v1에 결속한다."""

        with psycopg.connect(self.database_url) as connection:
            artifact_id = connection.execute(
                """
                SELECT a.artifact_id
                FROM artifact.analysis_artifacts a
                JOIN chat.analysis_requests r ON r.request_id = a.request_id
                JOIN query.query_executions q ON q.query_execution_id = a.query_execution_id
                WHERE r.user_id = %s AND r.status IN ('SUCCEEDED', 'PARTIAL')
                  AND a.status = 'APPROVED' AND a.artifact_checksum ~ '^[0-9a-f]{64}$'
                  AND q.trino_query_id IS NOT NULL
                  AND a.product_release_id IS NOT NULL
                  AND a.permission_snapshot_id IS NOT NULL
                  AND a.semantic_release_id IS NOT NULL
                ORDER BY a.artifact_id
                LIMIT 1
                """,
                (self.owner,),
            ).fetchone()
            if artifact_id is None:
                self.fail("격리 E2E DB에 owner 범위의 승인 Artifact가 없습니다.")
            artifact_uuid = artifact_id[0]
            lineage = connection.execute(
                """
                SELECT q.trino_query_id, l.definition_id, l.definition_version,
                       a.product_release_id, a.permission_snapshot_id,
                       a.semantic_release_id
                FROM artifact.analysis_artifacts a
                JOIN query.query_executions q ON q.query_execution_id = a.query_execution_id
                JOIN analysis_v1.analysis_run_links l ON l.request_id = a.request_id
                WHERE a.artifact_id = %s
                  AND a.product_release_id IS NOT NULL
                  AND a.permission_snapshot_id IS NOT NULL
                  AND a.semantic_release_id IS NOT NULL
                """,
                (artifact_uuid,),
            ).fetchone()
            if lineage is None:
                self.fail("격리 E2E Artifact에 완전한 release receipt가 없습니다.")
            query_id, analysis_id, analysis_version, *receipt = lineage
            connection.execute(
                "INSERT INTO report_v1.report_definitions (definition_id, owner_id) VALUES (%s, %s)",
                (self.definition_id, self.owner),
            )
            connection.execute(
                """
                INSERT INTO report_v1.report_definition_versions
                    (definition_id, version, status, title, orientation,
                     currency_display_unit, product_release_id,
                     permission_snapshot_id, semantic_release_id)
                VALUES (%s, 1, 'draft', '동시성 검증 보고서', 'portrait', 'auto',
                        %s, %s, %s)
                """,
                (self.definition_id, *receipt),
            )
            connection.execute(
                """
                INSERT INTO report_v1.report_blocks
                    (definition_id, definition_version, block_id, title, artifact_id,
                     query_id, columns, block_type, x, y, w, h, content,
                     analysis_definition_id, analysis_definition_version)
                VALUES (%s, 1, %s, '승인 Artifact', %s, %s, 12, 'chart',
                        0, 0, 12, 7, %s, %s, %s)
                """,
                (
                    self.definition_id, self.block_id, artifact_uuid, query_id,
                    E2E_ATOMIC_CHART_CONTENT, analysis_id, analysis_version,
                ),
            )
            connection.execute(
                """
                INSERT INTO governance.product_release_bindings (
                    object_kind, object_id, product_release_id,
                    permission_snapshot_id, semantic_release_id,
                    capability_release_vector_json, evidence_refs_json
                ) VALUES (
                    'REPORT', %s, %s, %s, %s,
                    '{"report.lifecycle":"1.0.0"}'::jsonb, '[]'::jsonb
                )
                """,
                (f"definition:{self.definition_id}:v1", *receipt),
            )
        return artifact_uuid

    async def _waiting_patch(self) -> tuple[dict[str, object], object]:
        await self.repository.start_assistant_session(
            str(self.assistant_request_id),
            str(self.definition_id),
            1,
            str(self.artifact_id),
            "a" * 64,
            "report.assistant.turn",
            "PROMPT-v1.8.6",
            "b" * 64,
        )
        patch = {
            "summary": "보고서 제목을 변경합니다.",
            "operations": [{"op": "set_report_title", "title": "동시 승인 완료"}],
        }
        await self.repository.record_existing_assistant_patch_proposal(
            str(self.assistant_request_id),
            str(self.patch_request_id),
            "c" * 64,
            "d" * 64,
            "MODEL-RELEASE-v1.38.0",
            "report.assistant.turn",
            "PROMPT-v1.8.6",
            "e" * 64,
            patch,
            (),
            "제목을 바꿔줘",
            "제목 변경안을 준비했습니다.",
            expected_message_revision=0,
        )
        source = await self.repository.get_version(str(self.definition_id), 1)
        return patch, replace(source, title="동시 승인 완료")

    async def test_concurrent_duplicate_finalize_returns_one_completed_revision(self) -> None:
        """같은 승인 저장 두 건은 모두 같은 completed Revision을 반환한다."""

        patch, patched = await self._waiting_patch()
        decisions = await asyncio.gather(*(
            self.repository.decide_existing_assistant_patch(
                str(self.assistant_request_id), str(self.patch_request_id), True, (0,)
            )
            for _ in range(2)
        ))
        self.assertEqual([False, True], sorted(claimed for _, claimed in decisions))
        results = await asyncio.gather(*(
            self.repository.finalize_existing_assistant_patch(
                str(self.assistant_request_id),
                "c" * 64,
                "d" * 64,
                "MODEL-RELEASE-v1.38.0",
                "report.assistant.turn",
                "PROMPT-v1.8.6",
                "e" * 64,
                patch,
                patched,
                expected_phase="saving_revision",
            )
            for _ in range(2)
        ))
        self.assertEqual({"completed"}, {str(result["phase"]) for result in results})
        self.assertEqual(1, len({int(result["result_revision"]) for result in results}))
        with psycopg.connect(self.database_url) as connection:
            versions = connection.execute(
                "SELECT count(*) FROM report_v1.report_definition_versions WHERE definition_id = %s",
                (self.definition_id,),
            ).fetchone()[0]
        self.assertEqual(2, versions)

    async def test_concurrent_patch_replacement_has_one_cas_winner(self) -> None:
        """같은 이전 patch ID를 교체하는 두 요청 중 하나만 DB에 저장한다."""

        await self._waiting_patch()
        replacements = (uuid4(), uuid4())

        async def replace(index: int) -> dict[str, object]:
            title = f"재수정안 {index}"
            return await self.repository.replace_existing_assistant_patch_proposal(
                str(self.assistant_request_id),
                str(self.patch_request_id),
                str(replacements[index]),
                "f" * 64,
                str(index + 1) * 64,
                "MODEL-RELEASE-v1.38.0",
                "report.assistant.turn",
                "PROMPT-v1.8.6",
                "9" * 64,
                {
                    "summary": title,
                    "operations": [{"op": "set_report_title", "title": title}],
                },
                (),
                title,
                f"{title}을 준비했습니다.",
                expected_message_revision=1,
            )

        results = await asyncio.gather(replace(0), replace(1), return_exceptions=True)
        self.assertEqual(1, sum(isinstance(result, dict) for result in results))
        self.assertEqual(1, sum(isinstance(result, ValueError) for result in results))
        current = await self.repository.get_assistant_session(str(self.assistant_request_id))
        self.assertIn(UUID(str(current["patch_request_id"])), replacements)

    async def test_late_full_report_save_cannot_downgrade_title_scope(self) -> None:
        """제목 명확화가 먼저 저장되면 늦은 일반 응답은 서버 범위를 넓히지 못한다."""

        await self.repository.start_assistant_session(
            str(self.assistant_request_id),
            str(self.definition_id),
            1,
            str(self.artifact_id),
            "a" * 64,
            "report.assistant.turn",
            "PROMPT-v1.10.0",
            "b" * 64,
        )
        stored = await self.repository.record_assistant_proposal(
            str(self.assistant_request_id),
            "c" * 64,
            "d" * 64,
            "MODEL-RELEASE-v1.49.0",
            "report.assistant.turn",
            "PROMPT-v1.10.0",
            "e" * 64,
            None,
            "제목을 제안해 줘",
            "제목의 대상 기간을 알려 주세요.",
            "clarification",
            "report_title",
            expected_message_revision=0,
        )
        self.assertEqual("report_title", stored["operation_scope"])

        with self.assertRaisesRegex(ValueError, "ASSISTANT_STATE_CONFLICT"):
            await self.repository.record_assistant_proposal(
                str(self.assistant_request_id),
                "f" * 64,
                "1" * 64,
                "MODEL-RELEASE-v1.49.0",
                "report.assistant.turn",
                "PROMPT-v1.10.0",
                "2" * 64,
                None,
                "본문을 다시 써 줘",
                "일반 보고서 변경안을 준비했습니다.",
                "clarification",
                "full_report",
                expected_message_revision=1,
            )

        current = await self.repository.get_assistant_session(str(self.assistant_request_id))
        self.assertEqual("report_title", current["operation_scope"])

    async def test_retry_preserves_failed_title_scope(self) -> None:
        """제목 요청 실패를 재시도해도 새 세션은 제목 변경 범위만 유지한다."""

        await self.repository.start_assistant_session(
            str(self.assistant_request_id),
            str(self.definition_id),
            1,
            str(self.artifact_id),
            "a" * 64,
            "report.assistant.turn",
            "PROMPT-v1.10.0",
            "b" * 64,
        )
        await self.repository.fail_assistant_request(
            str(self.assistant_request_id),
            "REPORT_ASSISTANT_MODEL_TIMEOUT",
            operation_scope="report_title",
        )
        retry_request_id = uuid4()
        retried = await self.repository.retry_assistant_session(
            str(self.assistant_request_id),
            str(retry_request_id),
            "c" * 64,
            "report.assistant.turn",
            "PROMPT-v1.10.0",
            "d" * 64,
        )

        self.assertEqual(retry_request_id, retried["assistant_request_id"])
        self.assertEqual("ready", retried["phase"])
        self.assertEqual("report_title", retried["operation_scope"])

    async def test_late_model_failure_cannot_terminate_newer_successful_turn(self) -> None:
        """먼저 저장된 다음 turn의 성공 결과를 늦은 이전 실패가 덮지 못한다."""

        started = await self.repository.start_assistant_session(
            str(self.assistant_request_id),
            str(self.definition_id),
            1,
            str(self.artifact_id),
            "a" * 64,
            "report.assistant.turn",
            "PROMPT-v1.10.0",
            "b" * 64,
        )
        start_revision = int(started["message_revision"])
        saved = await self.repository.record_assistant_proposal(
            str(self.assistant_request_id),
            "c" * 64,
            "d" * 64,
            "MODEL-RELEASE-v1.49.0",
            "report.assistant.turn",
            "PROMPT-v1.10.0",
            "e" * 64,
            None,
            "어느 기간인지 확인해 줘",
            "분석할 기간을 알려 주세요.",
            "clarification",
            "full_report",
            expected_message_revision=start_revision,
        )
        self.assertEqual("ready", saved["phase"])

        await self.repository.fail_assistant_request(
            str(self.assistant_request_id),
            "REPORT_ASSISTANT_MODEL_TIMEOUT",
            operation_scope="report_title",
            expected_phase="ready",
            expected_message_revision=start_revision,
        )

        current = await self.repository.get_assistant_session(str(self.assistant_request_id))
        self.assertEqual("running", current["status"])
        self.assertEqual("ready", current["phase"])
        self.assertEqual("full_report", current["operation_scope"])
        self.assertEqual("c" * 64, current["instruction_hash"])
        self.assertIsNone(current["error_code"])

    async def test_identical_message_has_one_revision_cas_winner(self) -> None:
        """같은 문장·같은 revision의 동시 저장도 한 turn만 canonical 상태가 된다."""

        await self.repository.start_assistant_session(
            str(self.assistant_request_id), str(self.definition_id), 1,
            str(self.artifact_id), "a" * 64, "report.assistant.turn",
            "PROMPT-v1.10.0", "b" * 64,
        )

        async def save_same_message() -> dict[str, object]:
            return await self.repository.record_assistant_proposal(
                str(self.assistant_request_id), "c" * 64, "d" * 64,
                "MODEL-RELEASE-v1.49.0", "report.assistant.turn",
                "PROMPT-v1.10.0", "e" * 64, None,
                "같은 문장", "같은 답변", "clarification", "full_report",
                expected_message_revision=0,
            )

        results = await asyncio.gather(
            save_same_message(), save_same_message(), return_exceptions=True,
        )
        self.assertEqual(1, sum(isinstance(result, dict) for result in results))
        self.assertEqual(1, sum(isinstance(result, ValueError) for result in results))
        current = await self.repository.get_assistant_session(str(self.assistant_request_id))
        self.assertEqual(1, current["message_revision"])
        history = await self.repository.get_assistant_turn_history(str(self.assistant_request_id))
        self.assertEqual(2, len(history))
        self.assertEqual(history, current["turn_history"])

    async def test_reject_invalidates_late_refinement_and_evaluation(self) -> None:
        """patch 거절은 revision을 올려 늦은 교체·실패·평가를 모두 no-op으로 만든다."""

        await self._waiting_patch()
        rejected, claimed = await self.repository.decide_existing_assistant_patch(
            str(self.assistant_request_id), str(self.patch_request_id), False,
        )
        self.assertTrue(claimed)
        self.assertEqual("ready", rejected["phase"])
        self.assertEqual("full_report", rejected["operation_scope"])
        self.assertEqual(2, rejected["message_revision"])

        with self.assertRaisesRegex(ValueError, "ASSISTANT_STATE_CONFLICT"):
            await self.repository.replace_existing_assistant_patch_proposal(
                str(self.assistant_request_id), str(self.patch_request_id), str(uuid4()),
                "f" * 64, "1" * 64, "MODEL-RELEASE-v1.49.0",
                "report.assistant.turn", "PROMPT-v1.10.0", "2" * 64,
                {
                    "summary": "늦은 제안",
                    "operations": [{"op": "set_report_title", "title": "늦은 제목"}],
                },
                (), "늦은 문장", "늦은 답변", expected_message_revision=1,
            )
        failed = await self.repository.fail_assistant_request(
            str(self.assistant_request_id), "REPORT_ASSISTANT_MODEL_TIMEOUT",
            operation_scope="report_title", expected_phase="ready",
            expected_message_revision=1,
        )
        self.assertFalse(failed)
        with self.assertRaises(KeyError):
            await self.repository.upsert_assistant_evaluation(
                str(self.assistant_request_id),
                error_code="REPORT_ASSISTANT_MODEL_TIMEOUT",
                expected_message_revision=1,
            )

        current = await self.repository.get_assistant_session(str(self.assistant_request_id))
        self.assertEqual("ready", current["phase"])
        self.assertEqual("running", current["status"])
        self.assertIsNone(current["error_code"])

    async def test_concurrent_failures_only_claim_one_evaluation_writer(self) -> None:
        """동일 revision의 실패 둘은 fail claim 승자 한 건만 평가를 기록한다."""

        await self.repository.start_assistant_session(
            str(self.assistant_request_id), str(self.definition_id), 1,
            str(self.artifact_id), "a" * 64, "report.assistant.turn",
            "PROMPT-v1.10.0", "b" * 64,
        )

        async def fail(code: str) -> tuple[str, bool]:
            claimed = await self.repository.fail_assistant_request(
                str(self.assistant_request_id), code,
                expected_phase="ready", expected_message_revision=0,
            )
            if claimed:
                await self.repository.upsert_assistant_evaluation(
                    str(self.assistant_request_id), error_code=code,
                    expected_message_revision=0,
                )
            return code, claimed

        results = await asyncio.gather(fail("FAILURE_A"), fail("FAILURE_B"))
        winners = [code for code, claimed in results if claimed]
        self.assertEqual(1, len(winners))
        evaluation = await self.repository.get_assistant_evaluation(
            str(self.assistant_request_id)
        )
        self.assertEqual(winners[0], evaluation["error_code"])

    async def test_late_review_cannot_overwrite_newer_message_evaluation(self) -> None:
        """ready revision을 캡처한 review는 새 message 저장 뒤 평가를 덮지 못한다."""

        await self.repository.start_assistant_session(
            str(self.assistant_request_id), str(self.definition_id), 1,
            str(self.artifact_id), "a" * 64, "report.assistant.turn",
            "PROMPT-v1.10.0", "b" * 64,
        )
        review_started = asyncio.Event()
        message_saved = asyncio.Event()

        async def late_review() -> str:
            review_started.set()
            await message_saved.wait()
            with self.assertRaises(KeyError):
                await self.repository.upsert_assistant_evaluation(
                    str(self.assistant_request_id),
                    contract_valid=False,
                    error_code="STALE_REVIEW",
                    expected_message_revision=0,
                )
            return "blocked"

        async def newer_message() -> str:
            await review_started.wait()
            try:
                saved = await self.repository.record_assistant_proposal(
                    str(self.assistant_request_id), "c" * 64, "d" * 64,
                    "MODEL-RELEASE-v1.49.0", "report.assistant.turn",
                    "PROMPT-v1.10.0", "e" * 64, None,
                    "최신 문장", "최신 답변", "clarification",
                    expected_message_revision=0,
                )
                await self.repository.upsert_assistant_evaluation(
                    str(self.assistant_request_id),
                    contract_valid=True,
                    error_code="NEWER_MESSAGE",
                    expected_message_revision=int(saved["message_revision"]),
                )
                return "saved"
            finally:
                message_saved.set()

        self.assertCountEqual(
            ["blocked", "saved"],
            await asyncio.gather(late_review(), newer_message()),
        )
        evaluation = await self.repository.get_assistant_evaluation(
            str(self.assistant_request_id)
        )
        self.assertEqual("NEWER_MESSAGE", evaluation["error_code"])
        current = await self.repository.get_assistant_session(
            str(self.assistant_request_id), expected_message_revision=1,
        )
        self.assertEqual(1, current["message_revision"])
        self.assertEqual(2, len(current["turn_history"]))
        with self.assertRaises(KeyError):
            await self.repository.get_assistant_session(
                str(self.assistant_request_id), expected_message_revision=0,
            )

    async def test_refresh_recovery_finishes_selected_patch_once(self) -> None:
        """선택 승인 도중 새 요청으로 복구해도 선택 항목만 한 Revision에 저장한다."""

        await self.repository.start_assistant_session(
            str(self.assistant_request_id),
            str(self.definition_id),
            1,
            str(self.artifact_id),
            "a" * 64,
            "report.assistant.turn",
            "PROMPT-v1.8.6",
            "b" * 64,
        )
        patch = {
            "summary": "제목 변경과 요약 블록 추가를 제안합니다.",
            "operations": [
                {"op": "set_report_title", "title": "복구 후 저장된 보고서"},
                {
                    "op": "add_text",
                    "title": "미선택 요약",
                    "content": "선택하지 않은 변경입니다.",
                    "evidence_refs": ["artifact_narrative"],
                },
            ],
        }
        proposed = await self.repository.record_existing_assistant_patch_proposal(
            str(self.assistant_request_id),
            str(self.patch_request_id),
            "c" * 64,
            "d" * 64,
            "MODEL-RELEASE-v1.38.0",
            "report.assistant.turn",
            "PROMPT-v1.8.6",
            "e" * 64,
            patch,
            (),
            "제목만 바꿔줘",
            "두 가지 변경안을 준비했습니다.",
            expected_message_revision=0,
        )
        self.assertEqual("waiting_patch_approval", proposed["phase"])

        waiting_after_refresh = await PostgresReportRepository(
            self.database_url,
            self.owner,
            session_factory=self.factory,
        ).get_assistant_session(str(self.assistant_request_id))
        self.assertEqual("waiting_patch_approval", waiting_after_refresh["phase"])
        self.assertEqual(2, len(waiting_after_refresh["report_patch_json"]["operations"]))

        saving, claimed = await self.repository.decide_existing_assistant_patch(
            str(self.assistant_request_id),
            str(self.patch_request_id),
            True,
            (0,),
        )
        self.assertTrue(claimed)
        self.assertEqual("saving_revision", saving["phase"])
        self.assertEqual(2, saving["message_revision"])
        self.assertEqual((0,), tuple(saving["approved_operation_indexes"]))

        recovered_repository = PostgresReportRepository(
            self.database_url,
            self.owner,
            session_factory=self.factory,
        )
        recovered = await recovered_repository.get_assistant_session(
            str(self.assistant_request_id)
        )
        self.assertEqual("saving_revision", recovered["phase"])
        self.assertEqual((0,), tuple(recovered["approved_operation_indexes"]))

        resumed, claimed_again = await recovered_repository.decide_existing_assistant_patch(
            str(self.assistant_request_id),
            str(self.patch_request_id),
            True,
            (0,),
        )
        self.assertFalse(claimed_again)
        self.assertEqual("saving_revision", resumed["phase"])

        source = await recovered_repository.get_version(str(self.definition_id), 1)
        patched = replace(source, title="복구 후 저장된 보고서")
        completed = await recovered_repository.finalize_existing_assistant_patch(
            str(self.assistant_request_id),
            "c" * 64,
            "d" * 64,
            "MODEL-RELEASE-v1.38.0",
            "report.assistant.turn",
            "PROMPT-v1.8.6",
            "e" * 64,
            patch,
            patched,
            expected_phase="saving_revision",
        )
        self.assertEqual("completed", completed["phase"])
        self.assertEqual(2, completed["result_revision"])

        completed_after_refresh = await PostgresReportRepository(
            self.database_url,
            self.owner,
            session_factory=self.factory,
        ).get_assistant_session(str(self.assistant_request_id))
        self.assertEqual("completed", completed_after_refresh["phase"])
        self.assertEqual(2, completed_after_refresh["result_revision"])

        saved = await recovered_repository.get_version(str(self.definition_id), 2)
        self.assertEqual("복구 후 저장된 보고서", saved.title)
        self.assertEqual(source.blocks, saved.blocks)

        repeated = await recovered_repository.finalize_existing_assistant_patch(
            str(self.assistant_request_id),
            "c" * 64,
            "d" * 64,
            "MODEL-RELEASE-v1.38.0",
            "report.assistant.turn",
            "PROMPT-v1.8.6",
            "e" * 64,
            patch,
            patched,
            expected_phase="saving_revision",
        )
        self.assertEqual(2, repeated["result_revision"])
        with psycopg.connect(self.database_url) as connection:
            versions = connection.execute(
                "SELECT count(*) FROM report_v1.report_definition_versions WHERE definition_id = %s",
                (self.definition_id,),
            ).fetchone()[0]
        self.assertEqual(2, versions)


class ReportAssistantPostgresFixtureContractTest(unittest.TestCase):
    """실제 DB가 없어 skip돼도 fixture의 release receipt·binding 정리를 정적으로 검증한다."""

    def test_prepare_fixture_seals_one_complete_e2e_release_receipt(self) -> None:
        """prepare fixture의 product·permission·semantic receipt는 하나의 manifest와 일치한다."""

        release = _release_fixture()
        manifest = release["manifest"]
        self.assertIsInstance(manifest, dict)
        checksum_payload = {
            key: manifest[key]
            for key in ("schema_version", "product_release_id", "evidence", "created_at")
        }
        self.assertEqual(E2E_PRODUCT_RELEASE_ID, release["product_release_id"])
        self.assertEqual(
            E2E_PERMISSION_SNAPSHOT_ID,
            release["permission_snapshot_id"],
        )
        self.assertEqual(E2E_SEMANTIC_RELEASE_ID, release["semantic_release_id"])
        self.assertEqual(
            E2E_SEMANTIC_RELEASE_ID,
            manifest["evidence"]["release_vector"]["semantic_release_id"],
        )
        self.assertEqual(_canonical_sha256(checksum_payload), manifest["manifest_sha256"])

    def test_prepare_seed_is_guarded_and_binds_artifact_and_report(self) -> None:
        """fixture write는 격리 DB guard 뒤 complete receipt와 두 object binding을 저장한다."""

        source = inspect.getsource(_seed)
        self.assertIn("_require_e2e_connection(connection)", source)
        self.assertIn("governance.product_release_manifests", source)
        for field in (
            "product_release_id", "permission_snapshot_id", "semantic_release_id",
        ):
            self.assertIn(field, source)
        self.assertIn('(\"ARTIFACT\", str(ids[\"artifact\"])', source)
        self.assertIn('"REPORT",', source)
        self.assertIn("count(binding.binding_id) = 2", source)

    def test_fixture_pins_receipt_and_removes_report_bindings(self) -> None:
        prepare = inspect.getsource(ReportAssistantPostgresConcurrencyTest._prepare_report)
        teardown = inspect.getsource(ReportAssistantPostgresConcurrencyTest.asyncTearDown)

        for field in (
            "product_release_id", "permission_snapshot_id", "semantic_release_id",
        ):
            self.assertIn(field, prepare)
        self.assertIn("governance.product_release_bindings", prepare)
        self.assertIn("definition:{self.definition_id}:v1", prepare)
        self.assertIn("DELETE FROM governance.product_release_bindings", teardown)
        self.assertIn("definition:{self.definition_id}:v2", teardown)
        self.assertIn("ENABLE TRIGGER product_release_bindings_immutable", teardown)


if __name__ == "__main__":
    unittest.main()
