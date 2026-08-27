from __future__ import annotations

import os
import subprocess
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "app" / "backend"
sys.path.insert(0, str(BACKEND))

from app.adapters.context_registry_repository import (
    ContextRegistryConflict,
    PostgresContextRegistryRepository,
    canonical_checksum,
)
from app.database import dispose_database
from app.context_registry_contracts import (
    CreateContextPackage,
    CreateContextRecord,
    CreateContextRelease,
    RecordReference,
)
from app.services.context.registry_service import ContextRegistryService


class CanonicalChecksumTest(unittest.TestCase):
    def test_object_key_order_does_not_change_checksum(self) -> None:
        self.assertEqual(
            canonical_checksum({"asset": "pms", "columns": ["day", "revenue"]}),
            canonical_checksum({"columns": ["day", "revenue"], "asset": "pms"}),
        )

    def test_payload_change_changes_checksum(self) -> None:
        self.assertNotEqual(
            canonical_checksum({"metric": "revenue"}),
            canonical_checksum({"metric": "occupancy"}),
        )


class ContextRegistryServiceTest(unittest.IsolatedAsyncioTestCase):
    async def test_service_uses_only_injected_repository(self) -> None:
        expected = object()

        class RecordingRepository:
            async def create_record(self, command):
                self.command = command
                return expected

        repository = RecordingRepository()
        service = ContextRegistryService(repository)
        command = CreateContextRecord(
            record_type="ASSET_BINDING",
            record_key="hotel-pms",
            version_no=1,
            payload={"asset": "pms"},
            owner_role="admin",
            valid_from=datetime.now(timezone.utc),
            idempotency_key="record-1",
        )

        self.assertIs(expected, await service.create_record(command))
        self.assertIs(command, repository.command)


@unittest.skipUnless(
    os.getenv("MIGRATION_TEST_DATABASE_URL"),
    "MIGRATION_TEST_DATABASE_URL is not configured",
)
class PostgresContextRegistryTest(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.base_url = make_url(os.environ["MIGRATION_TEST_DATABASE_URL"])
        cls.database = f"context_registry_{uuid4().hex[:8]}"
        admin = create_engine(
            cls.base_url.set(database="postgres"), isolation_level="AUTOCOMMIT"
        )
        with admin.connect() as connection:
            connection.exec_driver_sql(f"CREATE DATABASE {cls.database}")
        admin.dispose()
        cls.url = cls.base_url.set(database=cls.database).render_as_string(
            hide_password=False
        )
        environment = os.environ.copy()
        environment["APP_DATABASE_URL"] = cls.url
        environment["APP_DB_USER"] = cls.base_url.username or "migration_test"
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=BACKEND,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode:
            raise RuntimeError(result.stdout + result.stderr)

    async def asyncSetUp(self) -> None:
        self.repository = PostgresContextRegistryRepository(self.url)

    async def asyncTearDown(self) -> None:
        await dispose_database()

    @classmethod
    def tearDownClass(cls) -> None:
        admin = create_engine(
            cls.base_url.set(database="postgres"), isolation_level="AUTOCOMMIT"
        )
        with admin.connect() as connection:
            connection.exec_driver_sql(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()",
                (cls.database,),
            )
            connection.exec_driver_sql(f"DROP DATABASE {cls.database}")
        admin.dispose()

    def _record_command(self, **changes) -> CreateContextRecord:
        values = {
            "record_type": "ASSET_BINDING",
            "record_key": f"hotel-pms-{uuid4().hex[:8]}",
            "version_no": 1,
            "payload": {"asset": "pms", "columns": ["day", "revenue"]},
            "owner_role": "admin",
            "valid_from": datetime.now(timezone.utc),
            "idempotency_key": f"record-{uuid4()}",
        }
        values.update(changes)
        return CreateContextRecord(**values)

    async def test_record_idempotency_conflict_and_released_immutability(self) -> None:
        command = self._record_command()
        first = await self.repository.create_record(command)
        repeated = await self.repository.create_record(command)
        self.assertEqual(first.context_record_id, repeated.context_record_id)
        with self.assertRaises(ContextRegistryConflict):
            await self.repository.create_record(
                command.model_copy(update={"payload": {"asset": "different"}})
            )
        with self.assertRaises(ContextRegistryConflict):
            await self.repository.create_record(
                command.model_copy(update={"idempotency_key": f"record-{uuid4()}"})
            )

        approved = await self.repository.approve_record(first.context_record_id, uuid4())
        release = await self.repository.create_release(
            CreateContextRelease(
                release_key=f"demo-{uuid4().hex[:8]}",
                version_no=1,
                included_records=[
                    RecordReference(
                        context_record_id=approved.context_record_id,
                        checksum=approved.checksum,
                    )
                ],
                idempotency_key=f"release-{uuid4()}",
            )
        )
        published = await self.repository.publish_release(release.context_release_id, uuid4())
        engine = create_engine(self.url)
        with self.assertRaises(DBAPIError), engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE context.context_releases "
                    "SET included_record_refs_json = '[]'::jsonb "
                    "WHERE context_release_id = :id"
                ),
                {"id": published.context_release_id},
            )
        engine.dispose()

    async def test_package_requires_published_release_and_is_idempotent(self) -> None:
        record = await self.repository.create_record(self._record_command())
        record = await self.repository.approve_record(record.context_record_id, uuid4())
        release = await self.repository.create_release(
            CreateContextRelease(
                release_key=f"package-{uuid4().hex[:8]}",
                version_no=1,
                included_records=[
                    RecordReference(
                        context_record_id=record.context_record_id,
                        checksum=record.checksum,
                    )
                ],
                idempotency_key=f"release-{uuid4()}",
            )
        )
        request_id = uuid4()
        draft_command = self._package_command(request_id, release.context_release_id)
        with self.assertRaises(ContextRegistryConflict):
            await self.repository.create_package(draft_command)
        release = await self.repository.publish_release(release.context_release_id, uuid4())
        self._insert_request(request_id, release.context_release_id)
        first = await self.repository.create_package(draft_command)
        repeated = await self.repository.create_package(draft_command)
        self.assertEqual(first.context_package_id, repeated.context_package_id)
        with self.assertRaises(ContextRegistryConflict):
            await self.repository.create_package(
                draft_command.model_copy(update={"assets": [{"urn": "different"}]})
            )

    def _package_command(self, request_id, release_id) -> CreateContextPackage:
        return CreateContextPackage(
            request_id=request_id,
            context_release_id=release_id,
            user_scope={"role": "analyst"},
            assets=[{"urn": "urn:li:dataset:pms"}],
            metrics=[{"id": "room_revenue"}],
            joins=[],
            policies=[{"version": "policy-v1"}],
            dataset_count=1,
            column_count=2,
            token_count=200,
            idempotency_key=f"package-{uuid4()}",
        )

    def _insert_request(self, request_id, release_id) -> None:
        engine = create_engine(self.url)
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO chat.analysis_requests
                        (request_id, request_type, user_id, user_role,
                         question_text_redacted, question_hash, ambiguity_status,
                         context_release_id, sql_policy_version, status, trace_id,
                         started_at)
                    VALUES (:request_id, 'CHAT', :user_id, 'analyst',
                            '합성 매출', :hash, 'CLEAR', :release_id,
                            'policy-v1', 'RECEIVED', :trace_id, now())
                    """
                ),
                {
                    "request_id": request_id,
                    "user_id": uuid4(),
                    "hash": canonical_checksum("합성 매출"),
                    "release_id": release_id,
                    "trace_id": f"trace-{uuid4()}",
                },
            )
        engine.dispose()


if __name__ == "__main__":
    unittest.main()
