from __future__ import annotations

from pathlib import Path
import numpy as np

from .embedding_provider import SentenceTransformerEmbeddingProvider


class QwenEmbeddingProvider:
    """Backward compatibility wrapper around SentenceTransformerEmbeddingProvider."""

    def __init__(
        self,
        model_path: Path,
        device: str,
        expected_dimension: int,
        max_sequence_length: int,
        query_prompt_name: str,
    ) -> None:
        profile = {
            "model_id": "Qwen/Qwen3-Embedding-0.6B",
            "local_path": str(model_path),
            "revision": "unknown",  # We don't have this in the old interface
            "dimension": expected_dimension,
            "max_sequence_length": max_sequence_length,
            "query_prompt_name": query_prompt_name,
            "query_prefix": "",
            "document_prefix": "",
            "normalize_embeddings": True
        }
        self._provider = SentenceTransformerEmbeddingProvider(profile, device)
        self.model_id = self._provider.model_id
        self.revision = self._provider.revision

    @property
    def dimension(self) -> int:
        return self._provider.dimension

    @property
    def device(self) -> str:
        return self._provider.get_metadata()["device"]

    def embed_documents(self, texts: list[str], batch_size: int) -> np.ndarray:
        result = self._provider.embed_documents(texts, batch_size=batch_size)
        return np.array(result)

    def embed_query(self, query: str) -> np.ndarray:
        return self.embed_queries([query])[0]

    def embed_queries(self, queries: list[str]) -> np.ndarray:
        result = self._provider.embed_queries(queries)
        return np.array(result)

    def count_tokens(self, text: str) -> int:
        return self._provider.count_tokens(text)

    def encode_tokens(self, text: str) -> list[int]:
        return self._provider.encode_tokens(text)

    def decode_tokens(self, token_ids: list[int]) -> str:
        return self._provider.decode_tokens(token_ids)

    def get_metadata(self) -> dict:
        return self._provider.get_metadata()
