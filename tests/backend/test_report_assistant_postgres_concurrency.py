"""격리 PostgreSQL에서 Report Assistant 승인·재수정 CAS 경쟁을 검증한다."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import inspect
import json
import os
from pathlib import Path
import unittest
from uuid import UUID, uuid4

import httpx
import psycopg
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.main import app as _app  # noqa: F401
from app.adapters.analysis_repository import PostgresAnalysisRepository
from app.adapters.report_repository import PostgresReportRepository
from app.authorization import permission_snapshot_id
from app.context import analysis_context
from app.contracts import RequestContext, Role
from app.database import dispose_database
from tests.e2e.prepare_report_assistant_e2e import (
    E2E_ATOMIC_CHART_CONTENT,
    E2E_DATABASE,
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

PAGE_RENDERER_FINGERPRINT = "f" * 64


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
        self.runtime_database_url = _dsn(
            values["APP_DB_USER"],
            values["APP_DB_PASSWORD"],
            E2E_DATABASE,
        )
        self.runtime_database_user = values["APP_DB_USER"]
        if self.database_url.rsplit("/", 1)[-1] != E2E_DATABASE:
            self.fail("Report Assistant 동시성 테스트는 격리 E2E DB에서만 실행할 수 있습니다.")
        self.engine = create_async_engine(
            self.database_url.replace("postgresql://", "postgresql+psycopg://", 1),
            pool_pre_ping=True,
        )
        self.runtime_engine = create_async_engine(
            self.runtime_database_url.replace(
                "postgresql://", "postgresql+psycopg://", 1
            ),
            pool_pre_ping=True,
        )
        self.factory = async_sessionmaker(self.engine, expire_on_commit=False)
        self.runtime_factory = async_sessionmaker(
            self.runtime_engine, expire_on_commit=False
        )
        self.repository = PostgresReportRepository(
            self.database_url,
            self.owner,
            session_factory=self.factory,
        )
        self.runtime_repository = PostgresReportRepository(
            self.runtime_database_url,
            self.owner,
            session_factory=self.runtime_factory,
        )
        self.definition_id = uuid4()
        self.block_id = uuid4()
        self.assistant_request_id = uuid4()
        self.patch_request_id = uuid4()
        self.artifact_id = self._prepare_report()

    async def asyncTearDown(self) -> None:
        await dispose_database()
        await self.runtime_engine.dispose()
        await self.engine.dispose()
        with psycopg.connect(self.database_url) as connection:
            transfer_tables = (
                "report_assistant_transfer_receipts",
                "report_assistant_external_consents",
                "report_assistant_transfer_disclosures",
            )
            for table in transfer_tables:
                connection.execute(
                    f"ALTER TABLE report_v1.{table} DISABLE TRIGGER {table}_immutable"
                )
            try:
                connection.execute(
                    "DELETE FROM report_v1.report_assistant_transfer_receipts "
                    "WHERE assistant_request_id = %s",
                    (self.assistant_request_id,),
                )
                connection.execute(
                    "DELETE FROM report_v1.report_assistant_external_consents "
                    "WHERE assistant_request_id = %s",
                    (self.assistant_request_id,),
                )
                connection.execute(
                    "DELETE FROM report_v1.report_assistant_transfer_disclosures "
                    "WHERE assistant_request_id = %s",
                    (self.assistant_request_id,),
                )
            finally:
                for table in reversed(transfer_tables):
                    connection.execute(
                        f"ALTER TABLE report_v1.{table} ENABLE TRIGGER {table}_immutable"
                    )
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
                "DELETE FROM artifact.user_artifact_lifecycle "
                "WHERE owner_id = %s AND artifact_id = %s",
                (self.owner, self.artifact_id),
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

    async def test_external_transfer_receipt_is_owner_bound_one_shot_and_fail_closed(
        self,
    ) -> None:
        """runtime role의 외부 전송 lease·동의·receipt를 실제 PostgreSQL에서 검증한다."""

        started = await self.runtime_repository.start_assistant_session(
            str(self.assistant_request_id),
            str(self.definition_id),
            1,
            str(self.artifact_id),
            "a" * 64,
            "report.assistant.turn",
            "PROMPT-v1.10.0",
            "b" * 64,
        )
        message_revision = int(started["message_revision"])
        report_revision = int(started["base_revision"])
        node = "report_assistant_turn"
        policy_version = "EXTERNAL-TRANSFER-v1.0.0"
        route_fingerprint = "1" * 64
        binding_hash = "2" * 64
        scope_hash = "3" * 64
        payload_hash = "4" * 64
        disclosure_hash = "5" * 64
        data_scopes = ("report_structure", "artifact_aggregates")
        route = {
            "manifest_version": "MODEL-RUNTIME-MANIFEST-v1.4.0",
            "provider_routes": [
                {
                    "node": node,
                    "route_id": "report-assistant-external",
                    "provider": "openai",
                    "model": "gpt-5.4-mini",
                    "data_boundary": "external",
                    "destination_origin": "https://api.openai.com",
                }
            ],
        }
        disclosure_id = uuid4()
        disclosure = await self.runtime_repository.create_assistant_transfer_disclosure(
            str(self.assistant_request_id),
            disclosure_id=str(disclosure_id),
            policy_version=policy_version,
            node=node,
            route=route,
            route_fingerprint=route_fingerprint,
            binding_hash=binding_hash,
            data_scopes=data_scopes,
            scope_hash=scope_hash,
            excluded_data=("credentials", "raw_query_results"),
            content_warning="보고서 문맥이 외부 모델 처리 경계로 전송됩니다.",
            disclosure_hash=disclosure_hash,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )
        self.assertEqual(disclosure_id, disclosure["disclosure_id"])

        foreign_owner = uuid4()
        foreign_repository = PostgresReportRepository(
            self.runtime_database_url,
            foreign_owner,
            session_factory=self.runtime_factory,
        )
        with self.assertRaises(KeyError):
            await foreign_repository.get_assistant_transfer_disclosure(
                str(self.assistant_request_id), str(disclosure_id)
            )

        # runtime INSERT 권한이 있어도 DB owner trigger가 타 소유자 disclosure를 거부한다.
        with self.assertRaises(psycopg.Error):
            with psycopg.connect(self.runtime_database_url) as connection:
                connection.execute(
                    """
                    INSERT INTO report_v1.report_assistant_transfer_disclosures
                        (disclosure_id, assistant_request_id, owner_id, policy_version,
                         node, route_json, route_fingerprint, binding_hash,
                         data_scopes_json, scope_hash, excluded_data_json, content_warning,
                         disclosure_hash, expires_at)
                    SELECT %s, assistant_request_id, %s, policy_version, node, route_json,
                           route_fingerprint, binding_hash, data_scopes_json, scope_hash,
                           excluded_data_json, content_warning, %s, expires_at
                    FROM report_v1.report_assistant_transfer_disclosures
                    WHERE disclosure_id = %s
                    """,
                    (uuid4(), foreign_owner, "6" * 64, disclosure_id),
                )

        consent = await self.runtime_repository.accept_assistant_external_transfer(
            str(self.assistant_request_id), str(disclosure_id), disclosure_hash
        )
        consent_id = consent["consent_id"]
        with self.assertRaises(psycopg.Error):
            with psycopg.connect(self.runtime_database_url) as connection:
                connection.execute(
                    """
                    INSERT INTO report_v1.report_assistant_external_consents
                        (consent_id, disclosure_id, assistant_request_id, owner_id,
                         policy_version, disclosure_hash, route_fingerprint,
                         binding_hash, scope_hash, accepted)
                    SELECT %s, disclosure_id, assistant_request_id, %s, policy_version,
                           disclosure_hash, route_fingerprint, binding_hash, scope_hash, TRUE
                    FROM report_v1.report_assistant_external_consents
                    WHERE consent_id = %s
                    """,
                    (uuid4(), foreign_owner, consent_id),
                )

        execution_id = await self.runtime_repository.claim_assistant_model_execution(
            str(self.assistant_request_id),
            node=node,
            expected_phase="ready",
            expected_message_revision=message_revision,
            expected_report_revision=report_revision,
            lease_seconds=300,
        )
        with psycopg.connect(self.database_url) as connection:
            lease = connection.execute(
                """
                SELECT model_execution_id, model_execution_node,
                       model_execution_message_revision,
                       model_execution_expires_at > now(), base_revision
                FROM report_v1.report_assistant_requests
                WHERE assistant_request_id = %s
                """,
                (self.assistant_request_id,),
            ).fetchone()
        self.assertEqual(UUID(execution_id), lease[0])
        self.assertEqual(node, lease[1])
        self.assertEqual(message_revision, lease[2])
        self.assertTrue(lease[3])
        self.assertEqual(report_revision, lease[4])
        self.assertFalse(
            await self.runtime_repository.release_assistant_model_execution(
                str(self.assistant_request_id), str(uuid4())
            )
        )

        receipt_id = await self.runtime_repository.insert_assistant_transfer_receipt(
            str(self.assistant_request_id),
            disclosure_id=str(disclosure_id),
            consent_id=str(consent_id),
            policy_version=policy_version,
            node=node,
            attempt=1,
            data_boundary="external",
            manifest_version="MODEL-RUNTIME-MANIFEST-v1.4.0",
            route_id="report-assistant-external",
            provider="openai",
            model="gpt-5.4-mini",
            model_snapshot="gpt-5.4-mini-2026-08-01",
            endpoint="https://api.openai.com/v1/responses",
            route_fingerprint=route_fingerprint,
            binding_hash=binding_hash,
            data_scopes=data_scopes,
            scope_hash=scope_hash,
            payload_hash=payload_hash,
            model_execution_id=execution_id,
            minimum_lease_seconds=30,
        )
        with self.assertRaises(KeyError):
            await self.runtime_repository.insert_assistant_transfer_receipt(
                str(self.assistant_request_id),
                disclosure_id=str(disclosure_id),
                consent_id=str(consent_id),
                policy_version=policy_version,
                node=node,
                attempt=1,
                data_boundary="external",
                manifest_version="MODEL-RUNTIME-MANIFEST-v1.4.0",
                route_id="report-assistant-external",
                provider="openai",
                model="gpt-5.4-mini",
                model_snapshot="gpt-5.4-mini-2026-08-01",
                endpoint="https://api.openai.com/v1/responses",
                route_fingerprint=route_fingerprint,
                binding_hash=binding_hash,
                data_scopes=data_scopes,
                scope_hash=scope_hash,
                payload_hash=payload_hash,
                model_execution_id=execution_id,
                minimum_lease_seconds=30,
            )

        # INSERT trigger는 같은 동의라도 현재 lease token이 아니면 호출을 거부한다.
        with self.assertRaises(psycopg.Error):
            with psycopg.connect(self.runtime_database_url) as connection:
                connection.execute(
                    """
                    INSERT INTO report_v1.report_assistant_transfer_receipts
                        (transfer_receipt_id, assistant_request_id, owner_id,
                         disclosure_id, consent_id, policy_version, node, attempt,
                         data_boundary, manifest_version, route_id, provider, model,
                         model_snapshot, endpoint, route_fingerprint, binding_hash,
                         data_scopes_json, scope_hash, payload_hash, model_execution_id)
                    SELECT %s, assistant_request_id, owner_id, disclosure_id, consent_id,
                           policy_version, node, 2, data_boundary, manifest_version,
                           route_id, provider, model, model_snapshot, endpoint,
                           route_fingerprint, binding_hash, data_scopes_json, scope_hash,
                           payload_hash, %s
                    FROM report_v1.report_assistant_transfer_receipts
                    WHERE transfer_receipt_id = %s
                    """,
                    (uuid4(), uuid4(), UUID(receipt_id)),
                )

        with psycopg.connect(self.database_url) as connection:
            receipt = connection.execute(
                """
                SELECT count(*), min(payload_hash),
                       bool_and(model_execution_id = %s),
                       bool_and(data_boundary = 'external')
                FROM report_v1.report_assistant_transfer_receipts
                WHERE assistant_request_id = %s
                """,
                (UUID(execution_id), self.assistant_request_id),
            ).fetchone()
            receipt_columns = {
                row[0]
                for row in connection.execute(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema = 'report_v1'
                      AND table_name = 'report_assistant_transfer_receipts'
                    """
                ).fetchall()
            }
        self.assertEqual((1, payload_hash, True, True), receipt)
        self.assertTrue(
            {
                "payload_json", "request_payload", "prompt", "authorization_header",
                "api_key", "access_token", "credential",
            }.isdisjoint(receipt_columns)
        )

        # runtime role은 append-only receipt에 UPDATE·DELETE할 수 없다.
        with psycopg.connect(self.runtime_database_url) as connection:
            privileges = connection.execute(
                """
                SELECT has_table_privilege(current_user,
                           'report_v1.report_assistant_transfer_receipts', 'UPDATE'),
                       has_table_privilege(current_user,
                           'report_v1.report_assistant_transfer_receipts', 'DELETE')
                """
            ).fetchone()
        self.assertEqual((False, False), privileges)
        for statement in (
            "UPDATE report_v1.report_assistant_transfer_receipts "
            "SET payload_hash = payload_hash WHERE transfer_receipt_id = %s",
            "DELETE FROM report_v1.report_assistant_transfer_receipts "
            "WHERE transfer_receipt_id = %s",
        ):
            with self.assertRaises(psycopg.Error):
                with psycopg.connect(self.runtime_database_url) as connection:
                    connection.execute(statement, (UUID(receipt_id),))

        # 시간을 기다리지 않고 fixture lease만 과거로 이동한 뒤 실제 takeover CAS를 실행한다.
        with psycopg.connect(self.database_url) as connection:
            connection.execute(
                "ALTER TABLE report_v1.report_assistant_requests "
                "DISABLE TRIGGER report_assistant_model_execution_guard"
            )
            try:
                connection.execute(
                    "UPDATE report_v1.report_assistant_requests "
                    "SET model_execution_expires_at = now() - interval '1 second' "
                    "WHERE assistant_request_id = %s",
                    (self.assistant_request_id,),
                )
            finally:
                connection.execute(
                    "ALTER TABLE report_v1.report_assistant_requests "
                    "ENABLE TRIGGER report_assistant_model_execution_guard"
                )

        with self.assertRaisesRegex(ValueError, "EXTERNAL_TRANSFER_OUTCOME_UNKNOWN"):
            await self.runtime_repository.claim_assistant_model_execution(
                str(self.assistant_request_id),
                node=node,
                expected_phase="ready",
                expected_message_revision=message_revision,
                expected_report_revision=report_revision,
                lease_seconds=300,
            )
        terminal = await self.runtime_repository.get_assistant_session(
            str(self.assistant_request_id)
        )
        self.assertEqual("failed", terminal["status"])
        self.assertEqual("failed", terminal["phase"])
        self.assertEqual(
            "EXTERNAL_TRANSFER_OUTCOME_UNKNOWN", terminal["error_code"]
        )
        with psycopg.connect(self.database_url) as connection:
            cleared_lease = connection.execute(
                """
                SELECT model_execution_id, model_execution_node,
                       model_execution_message_revision, model_execution_expires_at
                FROM report_v1.report_assistant_requests
                WHERE assistant_request_id = %s
                """,
                (self.assistant_request_id,),
            ).fetchone()
        self.assertEqual((None, None, None, None), cleared_lease)
        with self.assertRaises(KeyError):
            await self.runtime_repository.insert_assistant_transfer_receipt(
                str(self.assistant_request_id),
                disclosure_id=str(disclosure_id),
                consent_id=str(consent_id),
                policy_version=policy_version,
                node=node,
                attempt=2,
                data_boundary="external",
                manifest_version="MODEL-RUNTIME-MANIFEST-v1.4.0",
                route_id="report-assistant-external",
                provider="openai",
                model="gpt-5.4-mini",
                model_snapshot="gpt-5.4-mini-2026-08-01",
                endpoint="https://api.openai.com/v1/responses",
                route_fingerprint=route_fingerprint,
                binding_hash=binding_hash,
                data_scopes=data_scopes,
                scope_hash=scope_hash,
                payload_hash="7" * 64,
                model_execution_id=execution_id,
                minimum_lease_seconds=30,
            )

    async def test_http_admission_receipt_allows_atomic_title_and_layout_save(self) -> None:
        """실제 runtime DB role의 HTTP 저장과 stale CAS rollback 원자성을 검증한다."""

        source = await self.repository.get_version(str(self.definition_id), 1)
        fitted_block = replace(
            source.blocks[0],
            h=9,
            content='{"visibleViews":["chart"],"sizeMode":"auto"}',
        )
        block_payload = {
            "block_id": fitted_block.block_id,
            "title": fitted_block.title,
            "artifact_id": fitted_block.artifact_id,
            "columns": fitted_block.columns,
            "type": fitted_block.type.value,
            "x": fitted_block.x,
            "y": fitted_block.y,
            "w": fitted_block.w,
            "h": fitted_block.h,
            "content": fitted_block.content,
            "evidence_refs": list(fitted_block.evidence_refs),
        }
        payload = {
            "blocks": [block_payload],
            "title": "브라우저 저장 검증 보고서",
            "orientation": "portrait",
            "currency_display_unit": "auto",
            "expected_draft_revision": source.draft_revision,
        }
        context = RequestContext(
            user_id=self.owner,
            role=Role.ANALYST,
            permission_snapshot_id=permission_snapshot_id(self.owner, Role.ANALYST),
        )

        async def context_override() -> RequestContext:
            return context

        previous_url = os.environ.get("APP_RUNTIME_DATABASE_URL")
        previous_overrides = dict(_app.dependency_overrides)
        os.environ["APP_RUNTIME_DATABASE_URL"] = self.runtime_database_url
        _app.dependency_overrides[analysis_context] = context_override
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=_app),
                base_url="http://backend.test",
            ) as client:
                saved_response = await client.put(
                    f"/reports/definitions/{self.definition_id}/versions/1/blocks",
                    json=payload,
                )
                stale_response = await client.put(
                    f"/reports/definitions/{self.definition_id}/versions/1/blocks",
                    json={**payload, "title": "오래된 화면의 제목"},
                )
        finally:
            _app.dependency_overrides.clear()
            _app.dependency_overrides.update(previous_overrides)
            if previous_url is None:
                os.environ.pop("APP_RUNTIME_DATABASE_URL", None)
            else:
                os.environ["APP_RUNTIME_DATABASE_URL"] = previous_url

        self.assertEqual(200, saved_response.status_code, saved_response.text)
        saved_body = saved_response.json()
        self.assertEqual(2, saved_body["draft_revision"])
        self.assertEqual("브라우저 저장 검증 보고서", saved_body["title"])
        self.assertEqual(9, saved_body["blocks"][0]["h"])
        self.assertEqual(
            json.loads(fitted_block.content),
            json.loads(saved_body["blocks"][0]["content"]),
        )
        self.assertEqual(409, stale_response.status_code, stale_response.text)
        stored = await self.repository.get_version(str(self.definition_id), 1)
        self.assertEqual("브라우저 저장 검증 보고서", stored.title)
        self.assertEqual(2, stored.draft_revision)
        self.assertEqual(9, stored.blocks[0].h)

        with psycopg.connect(self.runtime_database_url) as connection:
            role, can_select, can_update = connection.execute(
                "SELECT current_user, "
                "has_table_privilege(current_user, 'artifact.analysis_artifacts', 'SELECT'), "
                "has_table_privilege(current_user, 'artifact.analysis_artifacts', 'UPDATE')"
            ).fetchone()
        self.assertEqual(self.runtime_database_user, role)
        self.assertTrue(can_select)
        self.assertFalse(can_update)

    async def test_runtime_role_serializes_assistant_and_archive_without_artifact_update(self) -> None:
        """runtime role로 Assistant 결속·Artifact 보관·복원을 같은 lock 계약에서 실행한다."""

        report_repository = PostgresReportRepository(
            self.runtime_database_url,
            self.owner,
            permission_snapshot_id=permission_snapshot_id(self.owner, Role.ANALYST),
        )
        analysis_repository = PostgresAnalysisRepository(
            self.runtime_database_url,
            self.owner,
        )
        session = await report_repository.start_assistant_session(
            str(self.assistant_request_id),
            str(self.definition_id),
            1,
            str(self.artifact_id),
            "1" * 64,
            "report-assistant",
            "v1",
            "2" * 64,
        )
        self.assertEqual("ready", session["phase"])
        cancelled, claimed = await report_repository.cancel_assistant_session(
            str(self.assistant_request_id)
        )
        self.assertTrue(claimed)
        self.assertEqual("cancelled", cancelled["phase"])

        archived = await analysis_repository.archive_artifact(
            self.artifact_id,
            actor_role="analyst",
            trace_id="runtime-role-archive",
        )
        self.assertTrue(archived.archived)
        restored = await analysis_repository.restore_artifact(
            self.artifact_id,
            actor_role="analyst",
            trace_id="runtime-role-restore",
        )
        self.assertFalse(restored.archived)

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
            source_instruction="제목을 바꿔줘",
            verified_page_count=1,
            page_renderer_fingerprint=PAGE_RENDERER_FINGERPRINT,
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

    async def test_full_approval_without_indexes_is_idempotent(self) -> None:
        """operation_indexes null의 전체 승인도 재호출에서 같은 저장 claim을 재사용한다."""

        await self._waiting_patch()
        first, first_claimed = await self.repository.decide_existing_assistant_patch(
            str(self.assistant_request_id), str(self.patch_request_id), True, None,
            verified_page_count=1,
            page_renderer_fingerprint=PAGE_RENDERER_FINGERPRINT,
            approval_decision_hash="f" * 64,
        )
        second, second_claimed = await self.repository.decide_existing_assistant_patch(
            str(self.assistant_request_id), str(self.patch_request_id), True, None,
            verified_page_count=1,
            page_renderer_fingerprint=PAGE_RENDERER_FINGERPRINT,
            approval_decision_hash="0" * 64,
        )

        self.assertTrue(first_claimed)
        self.assertFalse(second_claimed)
        self.assertEqual("saving_revision", first["phase"])
        self.assertEqual("saving_revision", second["phase"])
        self.assertEqual("f" * 64, second["decision_hash"])

    async def test_saving_revision_refreshes_a_stale_renderer_receipt(self) -> None:
        """배포 중 renderer 계약이 바뀌어도 같은 frozen 승인은 새 receipt로만 재개한다."""

        patch, patched = await self._waiting_patch()
        first, first_claimed = await self.repository.decide_existing_assistant_patch(
            str(self.assistant_request_id),
            str(self.patch_request_id),
            True,
            (0,),
            verified_page_count=1,
            page_renderer_fingerprint=PAGE_RENDERER_FINGERPRINT,
            approval_decision_hash="1" * 64,
        )
        refreshed_fingerprint = "a" * 64
        second, second_claimed = await self.repository.decide_existing_assistant_patch(
            str(self.assistant_request_id),
            str(self.patch_request_id),
            True,
            (0,),
            verified_page_count=2,
            page_renderer_fingerprint=refreshed_fingerprint,
            approval_decision_hash="2" * 64,
        )

        self.assertTrue(first_claimed)
        self.assertFalse(second_claimed)
        self.assertEqual("saving_revision", first["phase"])
        self.assertEqual("saving_revision", second["phase"])
        self.assertEqual(2, second["verified_page_count"])
        self.assertEqual(refreshed_fingerprint, second["page_renderer_fingerprint"])
        self.assertEqual("2" * 64, second["decision_hash"])

        with self.assertRaisesRegex(ValueError, "REPORT_REVISION_CONFLICT"):
            await self.repository.finalize_existing_assistant_patch(
                str(self.assistant_request_id),
                "c" * 64,
                "1" * 64,
                "MODEL-RELEASE-v1.38.0",
                "report.assistant.turn",
                "PROMPT-v1.8.6",
                "e" * 64,
                patch,
                patched,
                expected_phase="saving_revision",
            )
        completed = await self.repository.finalize_existing_assistant_patch(
            str(self.assistant_request_id),
            "c" * 64,
            "2" * 64,
            "MODEL-RELEASE-v1.38.0",
            "report.assistant.turn",
            "PROMPT-v1.8.6",
            "e" * 64,
            patch,
            patched,
            expected_phase="saving_revision",
        )
        self.assertEqual("completed", completed["phase"])

    async def test_rejected_new_data_patch_clears_ephemeral_result_lineage(self) -> None:
        """거절된 result Artifact는 원 Artifact를 지우지 않고 session 입력에서만 분리한다."""

        await self._waiting_patch()
        with psycopg.connect(self.database_url) as connection:
            connection.execute(
                """
                UPDATE report_v1.report_assistant_requests
                SET result_artifact_id = %s, result_query_id = 'ephemeral-query',
                    result_artifact_checksum = %s,
                    analysis_plan_json = '{"question":"ephemeral"}'::jsonb
                WHERE assistant_request_id = %s
                """,
                (self.artifact_id, "a" * 64, self.assistant_request_id),
            )

        rejected, claimed = await self.repository.decide_existing_assistant_patch(
            str(self.assistant_request_id), str(self.patch_request_id), False,
        )

        self.assertTrue(claimed)
        self.assertEqual("ready", rejected["phase"])
        for field in (
            "result_artifact_id", "analysis_plan_json", "data_request_id", "source_instruction",
            "exact_page_count", "verified_page_count", "page_renderer_fingerprint",
        ):
            self.assertIsNone(rejected[field])
        with psycopg.connect(self.database_url) as connection:
            internal_lineage = connection.execute(
                """
                SELECT result_query_id, result_artifact_checksum
                FROM report_v1.report_assistant_requests
                WHERE assistant_request_id = %s
                """,
                (self.assistant_request_id,),
            ).fetchone()
        self.assertEqual((None, None), internal_lineage)
        self.assertEqual(1, len(await self.repository.get_assistant_artifacts(
            str(self.assistant_request_id)
        )))

    async def test_saving_revision_rejects_mismatched_exact_page_receipt(self) -> None:
        """exact와 renderer actual이 다른 saving row는 DB CHECK에서 원자 거부된다."""

        await self._waiting_patch()
        with psycopg.connect(self.database_url) as connection:
            with self.assertRaises(psycopg.errors.CheckViolation):
                connection.execute(
                    """
                    UPDATE report_v1.report_assistant_requests
                    SET phase = 'saving_revision', source_instruction = '2페이지 요청',
                        exact_page_count = 2, verified_page_count = 1,
                        page_renderer_fingerprint = %s
                    WHERE assistant_request_id = %s
                    """,
                    (PAGE_RENDERER_FINGERPRINT, self.assistant_request_id),
                )

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
                source_instruction="제목을 바꿔줘",
                verified_page_count=1,
                page_renderer_fingerprint=PAGE_RENDERER_FINGERPRINT,
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
            source_instruction="제목만 바꿔줘",
            verified_page_count=1,
            page_renderer_fingerprint=PAGE_RENDERER_FINGERPRINT,
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

        owner = UUID("d9cd9e8f-913d-4a6e-b57d-48ae36b5f950")
        release = _release_fixture(owner)
        manifest = release["manifest"]
        self.assertIsInstance(manifest, dict)
        checksum_payload = {
            key: manifest[key]
            for key in ("schema_version", "product_release_id", "evidence", "created_at")
        }
        self.assertEqual(E2E_PRODUCT_RELEASE_ID, release["product_release_id"])
        self.assertEqual(
            permission_snapshot_id(owner, Role.ANALYST),
            release["permission_snapshot_id"],
        )
        self.assertEqual(E2E_SEMANTIC_RELEASE_ID, release["semantic_release_id"])
        self.assertEqual(
            E2E_SEMANTIC_RELEASE_ID,
            manifest["evidence"]["release_vector"]["semantic_release_id"],
        )
        self.assertEqual(
            manifest["evidence"]["catalog"]["projection_sha256"],
            release["projection"]["projection_sha256"],
        )
        self.assertEqual(_canonical_sha256(checksum_payload), manifest["manifest_sha256"])

    def test_prepare_seed_is_guarded_and_binds_artifact_and_report(self) -> None:
        """fixture write는 격리 DB guard 뒤 complete receipt와 두 object binding을 저장한다."""

        source = inspect.getsource(_seed)
        self.assertIn("_require_e2e_connection(connection)", source)
        self.assertIn("governance.product_release_manifests", source)
        self.assertIn("governance.runtime_catalog_projections", source)
        self.assertIn("governance.runtime_catalog_active_pointer", source)
        self.assertIn("_release_fixture(owner)", source)
        self.assertIn(
            "permission_snapshot_id(owner, Role.ANALYST)",
            inspect.getsource(_release_fixture),
        )
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

    def test_artifact_lifecycle_lock_uses_existing_runtime_request_privilege(self) -> None:
        """Artifact UPDATE grant 없이 report·assistant·archive·trigger가 request row를 공유한다."""

        root = Path(__file__).resolve().parents[2]
        definition = (root / "app/backend/app/adapters/report_definition_repository.py").read_text(
            encoding="utf-8"
        )
        assistant = (root / "app/backend/app/adapters/report_artifact_repository.py").read_text(
            encoding="utf-8"
        )
        lifecycle = (
            root / "app/backend/app/adapters/analysis_artifact_lifecycle_repository.py"
        ).read_text(encoding="utf-8")
        migration = (
            root
            / "app/backend/migrations/versions/20260831_69_analysis_artifact_runtime_lock.py"
        ).read_text(encoding="utf-8")

        self.assertNotIn("FOR KEY SHARE OF a", definition)
        self.assertNotIn("FOR KEY SHARE OF a", assistant)
        self.assertNotIn("FOR UPDATE OF a", lifecycle)
        self.assertIn("FOR KEY SHARE OF r", definition)
        self.assertEqual(2, assistant.count("FOR KEY SHARE OF r"))
        self.assertIn("FOR UPDATE OF r", lifecycle)
        self.assertIn('lock_targets = "a, r" if artifact_lock else "r"', migration)
        self.assertNotIn("GRANT UPDATE", migration.upper())


if __name__ == "__main__":
    unittest.main()
