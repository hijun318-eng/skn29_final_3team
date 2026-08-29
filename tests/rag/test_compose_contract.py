from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RAG_COMPOSE = PROJECT_ROOT / "infrastructure" / "rag" / "compose.fragment.yml"
RAG_API_COMPOSE = PROJECT_ROOT / "infrastructure" / "rag" / "compose.api.fragment.yml"


def test_inactive_profiles_do_not_require_rag_secrets_during_interpolation() -> None:
    compose = RAG_COMPOSE.read_text(encoding="utf-8")
    api_compose = RAG_API_COMPOSE.read_text(encoding="utf-8")

    assert "RAG_DB_PASSWORD:?" not in compose
    assert "RAG_DB_PASSWORD:?" not in api_compose
    assert "RAG_GATEWAY_HMAC_SECRET:?" not in api_compose
    assert "POSTGRES_PASSWORD: ${RAG_DB_PASSWORD:-}" in compose
    assert "RAG_GATEWAY_HMAC_SECRET: ${RAG_GATEWAY_HMAC_SECRET:-}" in api_compose
