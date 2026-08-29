"""내부지침 query use case의 운영 의존성을 조립한다."""

from __future__ import annotations

import os

from app.adapters.conversation_repository import ConversationRepository
from app.database import get_sessionmaker
from app.services.internal_manual_query import InternalManualQueryService
from app.services.rag_gateway import InternalManualAgent


def internal_manual_query_service() -> InternalManualQueryService:
    """현재 App DB와 RAG Gateway 설정으로 요청 단위 use case를 만든다."""

    database_url = os.getenv("APP_RUNTIME_DATABASE_URL", "")
    repository = (
        ConversationRepository(get_sessionmaker(database_url))
        if database_url
        else None
    )
    executor_factory = (
        (lambda: InternalManualAgent(database_url))
        if database_url
        else None
    )
    enabled = os.getenv("RAG_FEATURE_ENABLED", "0").strip().lower() in {
        "1",
        "true",
        "yes",
    }
    return InternalManualQueryService(
        repository,
        executor_factory,
        enabled=enabled,
    )
