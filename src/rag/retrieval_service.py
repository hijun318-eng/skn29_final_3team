"""query embedding과 접근 결정을 repository 검색·선택적 reranking으로 전달한다."""

from __future__ import annotations

import numpy as np

from .access_policy import SearchDecision
from .pgvector_repository import PgVectorRepository
from .vector_models import VectorSearchResult


class VectorRetrievalService:
    """HYBRID mode와 reranker 가용성을 검증해 반환 점수·개수 Gate를 적용한다."""

    def __init__(self, repository: PgVectorRepository, reranker: 'RerankerProvider | None' = None) -> None:
        self._repository = repository
        self._reranker = reranker

    def retrieve(
        self,
        query: str,
        vector: np.ndarray,
        decision: SearchDecision,
        selected_manual_ids: tuple[str, ...] = (),
        retrieval_mode: str = "HYBRID",
        maximum_chunks_per_document: int = 1,
    ) -> list[VectorSearchResult]:
        """질문·vector·role·score·문서 제한을 적용해 순위 검색 결과를 반환한다."""

        if retrieval_mode == "HYBRID_RERANK" and self._reranker is None:
            raise RuntimeError("RAG reranker is not configured in this runtime")
        # Handle rerank top_k logic
        db_top_k = decision.top_k
        if retrieval_mode == "HYBRID_RERANK":
            db_top_k = max(decision.top_k * 4, 12)

        candidates = self._repository.search(
            vector=vector,
            query_text=query,
            role=decision.role,
            top_k=db_top_k,
            minimum_vector_score=decision.candidate_minimum_score,
            allow_unresolved=decision.allow_unresolved_validity,
            selected_manual_ids=selected_manual_ids,
            retrieval_mode=retrieval_mode,
            maximum_chunks_per_document=maximum_chunks_per_document,
        )

        # Apply reranking if requested
        if retrieval_mode == "HYBRID_RERANK" and self._reranker:
            candidates = self._reranker.score_candidates(query, candidates)
            # Reranker 점수와 벡터 유사도는 스케일이 다르다. 후보 단계에서 이미
            # 벡터 하한을 적용했으므로 재정렬 결과에는 벡터 임계값을 다시 쓰지 않는다.
            return candidates[: decision.top_k]

        return [item for item in candidates if item.score >= decision.minimum_score][
            : decision.top_k
        ]
