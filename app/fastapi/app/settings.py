"""SensePlace Analysis API 설정."""

from __future__ import annotations

from decouple import Csv, config


DATABASE_URL: str | None = config("DATABASE_URL", default=None)
SENSEPLACE_LLM_PROVIDER: str = config("SENSEPLACE_LLM_PROVIDER", default="stub")
INTERNAL_API_KEY: str | None = config("INTERNAL_API_KEY", default=None)
DJANGO_API_URL: str = config("DJANGO_API_URL", default="http://localhost:8000")
