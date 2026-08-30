"""격리 PostgreSQL에서 Report Assistant 승인·재수정 CAS 경쟁을 검증한다."""

from __future__ import annotations

import asyncio
from dataclasses import replace
import os
import unittest
from uuid import UUID, uuid4

import psycopg
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.main import app as _app  # noqa: F401
from app.adapters.report_repository import PostgresReportRepository
from tests.e2e.prepare_report_assistant_e2e import (
    E2E_DATABASE,
    _analyst_subject,
    _deployment_values,
    _dsn,
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
                SELECT q.trino_query_id, l.definition_id, l.definition_version
                FROM artifact.analysis_artifacts a
                JOIN query.query_executions q ON q.query_execution_id = a.query_execution_id
                JOIN analysis_v1.analysis_run_links l ON l.request_id = a.request_id
                WHERE a.artifact_id = %s
                """,
                (artifact_uuid,),
            ).fetchone()
            connection.execute(
                "INSERT INTO report_v1.report_definitions (definition_id, owner_id) VALUES (%s, %s)",
                (self.definition_id, self.owner),
            )
            connection.execute(
                """
                INSERT INTO report_v1.report_definition_versions
                    (definition_id, version, status, title, orientation, currency_display_unit)
                VALUES (%s, 1, 'draft', '동시성 검증 보고서', 'portrait', 'auto')
                """,
                (self.definition_id,),
            )
            connection.execute(
                """
                INSERT INTO report_v1.report_blocks
                    (definition_id, definition_version, block_id, title, artifact_id,
                     query_id, columns, block_type, x, y, w, h, content,
                     analysis_definition_id, analysis_definition_version)
                VALUES (%s, 1, %s, '승인 Artifact', %s, %s, 12, 'chart', 0, 0, 12, 7, '', %s, %s)
                """,
                (self.definition_id, self.block_id, artifact_uuid, *lineage),
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
            )

        results = await asyncio.gather(replace(0), replace(1), return_exceptions=True)
        self.assertEqual(1, sum(isinstance(result, dict) for result in results))
        self.assertEqual(1, sum(isinstance(result, ValueError) for result in results))
        current = await self.repository.get_assistant_session(str(self.assistant_request_id))
        self.assertIn(UUID(str(current["patch_request_id"])), replacements)

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


if __name__ == "__main__":
    unittest.main()
