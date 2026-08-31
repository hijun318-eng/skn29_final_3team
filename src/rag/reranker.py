import os
from pathlib import Path
from typing import List, Dict, Any
from sentence_transformers import CrossEncoder

from .vector_models import VectorSearchResult
from .runtime_device import RuntimeDeviceSelector

class RerankerProvider:
    def __init__(self, model_path: str, device: str = "auto", cache_dir: str = None):
        self.model_path = model_path
        self.device = RuntimeDeviceSelector.resolve(device)
        self.model = CrossEncoder(
            self.model_path,
            device=self.device,
            max_length=512
        )
        self._cache = {}  # Optional: Simple in-memory cache

    def score_candidates(self, query: str, candidates: List[VectorSearchResult]) -> List[VectorSearchResult]:
        if not candidates:
            return []

        pairs = [[query, candidate.content if hasattr(candidate, "content") else candidate.snippet] for candidate in candidates]

        # CrossEncoder returns logits, we can apply sigmoid to get scores between 0 and 1
        scores = self.model.predict(pairs, apply_softmax=False)

        # Normalize scores using sigmoid if they are raw logits
        import numpy as np
        normalized_scores = 1 / (1 + np.exp(-np.array(scores)))

        reranked_candidates = []
        for i, candidate in enumerate(candidates):
            # We must create a new VectorSearchResult to avoid mutating frozen dataclasses
            import dataclasses
            updated_candidate = dataclasses.replace(
                candidate,
                ranking_stage="reranker",
                reranker_score=float(normalized_scores[i]),
                score=float(normalized_scores[i])
            )
            reranked_candidates.append(updated_candidate)

        # Sort by reranker score descending
        reranked_candidates.sort(key=lambda x: x.reranker_score, reverse=True)
        return reranked_candidates
