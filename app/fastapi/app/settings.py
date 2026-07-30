"""SensePlace Analysis API 설정."""

from __future__ import annotations

from decouple import Csv, config


DATABASE_URL: str | None = config("DATABASE_URL", default=None)

# LLM provider 설정
SENSEPLACE_LLM_PROVIDER: str = config("SENSEPLACE_LLM_PROVIDER", default="stub")

# Ollama (로컬 LLM)
OLLAMA_BASE_URL: str = config("OLLAMA_BASE_URL", default="http://localhost:11434")
OLLAMA_MODEL: str = config("OLLAMA_MODEL", default="qwen2.5:4b")

# OpenAI 호환 API (외부 LLM: OpenAI, RunPod vLLM, 로컬 vLLM)
LLM_API_BASE: str = config("LLM_API_BASE", default="https://api.openai.com/v1")
LLM_API_KEY: str = config("LLM_API_KEY", default="")
LLM_MODEL: str = config("LLM_MODEL", default="gpt-4o-mini")

INTERNAL_API_KEY: str | None = config("INTERNAL_API_KEY", default=None)
DJANGO_API_URL: str = config("DJANGO_API_URL", default="http://localhost:8000")
