from __future__ import annotations

import numpy as np

from .access_policy import SearchDecision
from .pgvector_repository import PgVectorRepository
from .vector_models import VectorSearchResult


class VectorRetrievalService:
    def __init__(self, repository: PgVectorRepository) -> None:
        self._repository = repository

    def retrieve(
        self,
        query: str,
        vector: np.ndarray,
        decision: SearchDecision,
        selected_manual_ids: tuple[str, ...] = (),
        retrieval_mode: str = "HYBRID",
        maximum_chunks_per_document: int = 1,
    ) -> list[VectorSearchResult]:
        candidates = self._repository.search(
            vector=vector,
            query_text=query,
            role=decision.role,
            top_k=decision.top_k,
            minimum_vector_score=decision.candidate_minimum_score,
            allow_unresolved=decision.allow_unresolved_validity,
            selected_manual_ids=selected_manual_ids,
            retrieval_mode=retrieval_mode,
            maximum_chunks_per_document=maximum_chunks_per_document,
        )

        return [item for item in candidates if item.score >= decision.minimum_score][
            : decision.top_k
        ]
