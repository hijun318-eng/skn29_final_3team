from __future__ import annotations

import os
from dataclasses import dataclass


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


@dataclass(frozen=True)
class ProbeTarget:
    key: str
    name: str
    type: str
    kind: str
    endpoint: str


@dataclass(frozen=True)
class Settings:
    database_url: str
    session_secret: str
    bootstrap_name: str
    bootstrap_email: str
    bootstrap_password: str
    frontend_origin: str
    cookie_secure: bool
    session_ttl_seconds: int
    probe_timeout_seconds: float
    existing_readiness_url: str
    probes: tuple[ProbeTarget, ...]

    @classmethod
    def load(cls) -> "Settings":
        secret = _required("ADMIN_SESSION_SECRET")
        if len(secret) < 32:
            raise RuntimeError("ADMIN_SESSION_SECRET must contain at least 32 characters")
        sources = (
            ("pms", "PMS", "PostgreSQL", "tcp", "PMS_HEALTH_DSN"),
            ("pos", "POS", "MySQL", "tcp", "POS_HEALTH_DSN"),
            ("crm", "CRM", "SQL Server", "tcp", "CRM_HEALTH_DSN"),
            ("facility", "Facility", "ClickHouse", "tcp", "FACILITY_HEALTH_DSN"),
            ("banquet", "Banquet", "PostgreSQL", "tcp", "BANQUET_HEALTH_DSN"),
            ("app-postgres", "App PostgreSQL", "PostgreSQL", "dsn", "APP_POSTGRES_HEALTH_DSN"),
            ("trino", "Trino", "HTTPS", "tcp", "TRINO_HEALTH_URL"),
            ("datahub", "DataHub", "HTTPS", "tcp", "DATAHUB_HEALTH_URL"),
            ("model", "Model API", "HTTP", "http", "MODEL_HEALTH_URL"),
        )
        probes = tuple(
            ProbeTarget(key, name, target_type, kind, os.getenv(env_name, "").strip())
            for key, name, target_type, kind, env_name in sources
        )
        return cls(
            database_url=_required("ADMIN_DATABASE_URL"),
            session_secret=secret,
            bootstrap_name=os.getenv("ADMIN_BOOTSTRAP_NAME", "System Administrator").strip(),
            bootstrap_email=_required("ADMIN_BOOTSTRAP_EMAIL").lower(),
            bootstrap_password=_required("ADMIN_BOOTSTRAP_PASSWORD"),
            frontend_origin=os.getenv("ADMIN_FRONTEND_ORIGIN", "http://localhost:28080").strip(),
            cookie_secure=os.getenv("ADMIN_COOKIE_SECURE", "false").lower() == "true",
            session_ttl_seconds=int(os.getenv("ADMIN_SESSION_TTL_SECONDS", "28800")),
            probe_timeout_seconds=float(os.getenv("ADMIN_PROBE_TIMEOUT_SECONDS", "3")),
            existing_readiness_url=os.getenv("EXISTING_READINESS_URL", "").strip(),
            probes=probes,
        )
