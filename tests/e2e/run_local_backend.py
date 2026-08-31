"""Windows Selector event loop로 로컬 E2E Backend를 실행한다."""

from __future__ import annotations

import asyncio
import os
from urllib.parse import unquote, urlsplit

import uvicorn


E2E_DATABASE = "app_db_report_assistant_e2e"
MODEL_CREDENTIAL_ENV_NAMES = ("OPENAI_API_KEY", "NODE2_MODEL_API_TOKEN")
_LOCAL_DATABASE_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
_POSTGRES_SCHEMES = frozenset({"postgresql", "postgresql+psycopg"})


def _require_read_only_environment() -> None:
    """읽기 전용 Browser audit를 격리 DB와 무 model credential 환경으로 제한한다."""

    database_url = os.getenv("APP_RUNTIME_DATABASE_URL", "").strip()
    parsed = urlsplit(database_url)
    database_name = unquote(parsed.path).lstrip("/")
    if (
        parsed.scheme not in _POSTGRES_SCHEMES
        or parsed.hostname not in _LOCAL_DATABASE_HOSTS
        or database_name != E2E_DATABASE
    ):
        raise RuntimeError(
            "APP_RUNTIME_DATABASE_URL은 localhost의 "
            f"{E2E_DATABASE}만 사용할 수 있습니다."
        )
    configured_credentials = [
        name for name in MODEL_CREDENTIAL_ENV_NAMES if os.getenv(name, "").strip()
    ]
    if configured_credentials:
        raise RuntimeError(
            "읽기 전용 Browser audit에서는 model credential을 설정할 수 없습니다: "
            + ", ".join(configured_credentials)
        )


if __name__ == "__main__":
    _require_read_only_environment()
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    uvicorn.run(
        "app.main:app", host="127.0.0.1", port=18002, loop="none", lifespan="off"
    )
