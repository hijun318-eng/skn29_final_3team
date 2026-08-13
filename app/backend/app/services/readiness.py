from __future__ import annotations

import os
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text


class AppDatabaseReadiness:
    """실제 쿼리로 migration·Template·Trino 사용 가능 상태를 확인한다."""

    def check(self) -> dict[str, str]:
        probe = self._database_probe()
        probe["trino"] = self._trino_probe()
        probe["datahub"] = self._datahub_probe()
        probe["model"] = self._model_probe()
        probe["report_scheduler"] = self._report_scheduler_probe()
        return probe

    @staticmethod
    def _report_scheduler_probe() -> str:
        from app.services.report_scheduler import report_scheduler

        return report_scheduler.status

    @staticmethod
    def _database_probe() -> dict[str, str]:
        database_url = os.getenv("APP_RUNTIME_DATABASE_URL")
        if not database_url:
            return {
                "app_postgres": "not_configured",
                "migration": "not_ready",
                "approved_templates": "not_ready",
            }
        try:
            engine = create_engine(database_url, pool_pre_ping=True)
            with engine.connect() as connection:
                version = connection.execute(
                    text("SELECT version_num FROM governance.alembic_version")
                ).scalar_one_or_none()
                template_count = connection.execute(
                    text(
                        "SELECT count(*) FROM context.analysis_templates "
                        "WHERE template_id = 'weekly-room-operations' "
                        "AND version = 'I2-v1.0.0' "
                        "AND status = 'APPROVED' "
                        "AND sql_text IS NOT NULL "
                        "AND source_fqns_json IS NOT NULL"
                    )
                ).scalar_one()
            engine.dispose()
            return {
                "app_postgres": "ready",
                "migration": AppDatabaseReadiness._migration_status(version),
                "approved_templates": (
                    "ready" if template_count == 1 else "not_ready"
                ),
            }
        except Exception:
            return {
                "app_postgres": "not_ready",
                "migration": "not_ready",
                "approved_templates": "not_ready",
            }

    @staticmethod
    def _migration_status(version: str | None) -> str:
        backend = Path(__file__).resolve().parents[2]
        config = Config(str(backend / "alembic.ini"))
        config.set_main_option("script_location", str(backend / "migrations"))
        heads = ScriptDirectory.from_config(config).get_heads()
        if len(heads) != 1:
            raise RuntimeError("Alembic migration graph must have exactly one head")
        return "ready" if version == heads[0] else "not_ready"

    @staticmethod
    def _trino_probe() -> str:
        url = f"{os.getenv('TRINO_URL', 'http://trino:8080').rstrip('/')}/v1/info"
        try:
            with urlopen(url, timeout=2) as response:
                return "ready" if response.status == 200 else "not_ready"
        except (OSError, URLError):
            return "not_ready"

    @staticmethod
    def _datahub_probe() -> str:
        url = f"{os.getenv('DATAHUB_GMS_URL', 'http://datahub-gms:8080').rstrip('/')}/config"
        try:
            with urlopen(url, timeout=2) as response:
                return "ready" if response.status == 200 else "not_ready"
        except (OSError, URLError):
            return "not_ready"

    @staticmethod
    def _model_probe() -> str:
        endpoint = os.getenv("OPENAI_ENDPOINT", "").rstrip("/")
        token = os.getenv("OPENAI_API_KEY", "")
        if not endpoint or not token or not os.getenv("OPENAI_MODEL", ""):
            return "not_ready"
        request = Request(
            f"{endpoint}/v1/models",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
                "User-Agent": "answervice-readiness/1.0",
            },
        )
        for _ in range(3):
            try:
                with urlopen(request, timeout=5) as response:
                    if response.status == 200:
                        return "ready"
            except (OSError, URLError):
                pass
        return "not_ready"
