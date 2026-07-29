from __future__ import annotations

import os
import socket


class AppDatabaseReadiness:
    """Network-only probe; credentials are never read, logged, or returned."""

    def check(self) -> dict[str, str]:
        host = os.getenv("APP_DB_HOST", "app-postgres")
        port = int(os.getenv("APP_DB_PORT", "5432"))
        try:
            with socket.create_connection((host, port), timeout=2):
                return {"app_postgres": "reachable"}
        except OSError:
            return {"app_postgres": "unreachable"}
