from __future__ import annotations

import os
from urllib.error import URLError
from urllib.request import urlopen

from sqlalchemy import create_engine, text


class AppDatabaseReadiness:
    """실제 쿼리로 migration·Template·Trino 사용 가능 상태를 확인한다."""

    def check(self) -> dict[str, str]:
        probe = self._database_probe()
        probe["trino"] = self._trino_probe()
        return probe

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
                        "WHERE status = 'APPROVED' "
                        "AND sql_text IS NOT NULL "
                        "AND source_fqns_json IS NOT NULL"
                    )
                ).scalar_one()
            engine.dispose()
            return {
                "app_postgres": "ready",
                "migration": (
                    "ready" if version == "20260731_03" else "not_ready"
                ),
                "approved_templates": (
                    "ready" if template_count > 0 else "not_ready"
                ),
            }
        except Exception:
            return {
                "app_postgres": "not_ready",
                "migration": "not_ready",
                "approved_templates": "not_ready",
            }

    @staticmethod
    def _trino_probe() -> str:
        if os.getenv("DATA_PLATFORM_MODE", "fake") == "fake":
            return "not_required"
        url = f"{os.getenv('TRINO_URL', 'http://trino:8080').rstrip('/')}/v1/info"
        try:
            with urlopen(url, timeout=2) as response:
                return "ready" if response.status == 200 else "not_ready"
        except (OSError, URLError):
            return "not_ready"
