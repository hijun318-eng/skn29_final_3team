"""query embedding과 접근 결정을 repository 검색·선택적 reranking으로 전달한다."""

from __future__ import annotations

import numpy as np

from .access_policy import SearchDecision
from .pgvector_repository import PgVectorRepository
from .vector_models import VectorSearchResult


class VectorRetrievalService:
    """[책임] pgvector 하이브리드 검색과 BGE Reranker 재정렬을 연계하여 최적의 지식 청크를 추출한다.
    - 입출력: 질문 텍스트, 임베딩 벡터, 권한 결정(SearchDecision) 수신 → 순위화된 VectorSearchResult 목록 반환
    - 주의조건: Reranker 미구성 상태에서 Rerank 모드 요청 시 차단, 역할별 점수 하한 미달 청크는 필터링
    """

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
        """[책임] 임베딩 벡터와 질문 텍스트로 하이브리드 검색 및 선택적 Reranking을 수행하여 관련 청크를 반환한다.
        - 입출력: query 문자열, 임베딩 vector, SearchDecision 수신 → 점수 임계값을 통과한 VectorSearchResult 리스트 반환
        - 주의조건: HYBRID_RERANK 모드 선택 시 Reranker 미설정 상태이면 RuntimeError 발생
        """

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
