"""선택형 Neo4j Graph adapter의 기본 OFF 환경 계약을 정의한다."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from urllib.parse import urlsplit


def _environment_bool(name: str, default: str = "false") -> bool:
    value = os.getenv(name, default).strip().lower()
    if value not in {"true", "false"}:
        raise ValueError(f"{name} must be true or false")
    return value == "true"


@dataclass(frozen=True)
class Neo4jGraphSettings:
    """기본 OFF이며 활성화할 때만 연결·보안 설정을 요구하는 환경 계약이다."""

    enabled: bool
    uri: str = ""
    username: str = ""
    password: str = field(default="", repr=False)
    database: str = "neo4j"
    timeout_seconds: float = 2.0
    pool_size: int = 5
    allow_insecure: bool = False

    @classmethod
    def from_env(cls) -> "Neo4jGraphSettings":
        """Neo4j 환경값을 읽되 OFF 상태에서는 driver나 secret을 요구하지 않는다."""

        enabled = _environment_bool("NEO4J_GRAPH_ENABLED")
        settings = cls(
            enabled=enabled,
            uri=os.getenv("NEO4J_URI", "").strip(),
            username=os.getenv("NEO4J_USERNAME", "").strip(),
            password=os.getenv("NEO4J_PASSWORD", ""),
            database=os.getenv("NEO4J_DATABASE", "neo4j").strip(),
            timeout_seconds=float(os.getenv("NEO4J_TIMEOUT_SECONDS", "2")),
            pool_size=int(os.getenv("NEO4J_POOL_SIZE", "5")),
            allow_insecure=_environment_bool("NEO4J_ALLOW_INSECURE"),
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        """활성 설정의 URI·secret·budget을 외부 연결 전에 검증한다."""

        if not self.enabled:
            return
        if (
            not self.uri
            or not self.username
            or not self.password
            or not self.database
            or not 0.1 <= self.timeout_seconds <= 30
            or not 1 <= self.pool_size <= 20
        ):
            raise ValueError("enabled Neo4j graph settings are incomplete or unbounded")
        parsed = urlsplit(self.uri)
        secure_schemes = {"neo4j+s", "bolt+s"}
        insecure_schemes = {"neo4j", "bolt", "neo4j+ssc", "bolt+ssc"}
        if (
            parsed.scheme not in secure_schemes | insecure_schemes
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
        ):
            raise ValueError("NEO4J_URI is invalid or contains credentials")
        if parsed.scheme in insecure_schemes and not self.allow_insecure:
            raise ValueError("unencrypted Neo4j URI requires NEO4J_ALLOW_INSECURE=true")
