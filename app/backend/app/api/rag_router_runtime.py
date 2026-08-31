"""내부지침 query use case의 운영 의존성을 조립한다."""

from __future__ import annotations

import os

from app.adapters.conversation_repository import ConversationRepository
from app.contracts import RuntimeFeature
from app.database import get_sessionmaker
from app.runtime_features import runtime_feature_enabled
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
    return InternalManualQueryService(
        repository,
        executor_factory,
        enabled=runtime_feature_enabled(RuntimeFeature.INTERNAL_GUIDELINE),
    )


def internal_manual_capability_searcher() -> InternalManualAgent:
    """자동 route probe가 답변 생성 없이 RAG 검색 receipt만 읽는 adapter를 만든다."""

    database_url = os.getenv("APP_RUNTIME_DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError("APP_RUNTIME_DATABASE_URL is required for RAG capability routing")
    return InternalManualAgent(database_url)
