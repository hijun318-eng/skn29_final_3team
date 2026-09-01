"""기존 Qwen 임베딩 호출 규격을 공통 SentenceTransformer provider에 연결한다."""

from __future__ import annotations

from pathlib import Path
import numpy as np

from .embedding_provider import SentenceTransformerEmbeddingProvider


class QwenEmbeddingProvider:
    """구형 Qwen 인터페이스를 유지하면서 검증·추론을 공통 로컬 provider에 위임한다."""

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
        """로드된 Qwen 모델에서 검증된 임베딩 벡터 차원을 반환한다."""

        return self._provider.dimension

    @property
    def device(self) -> str:
        """Qwen 모델이 실제로 추론에 사용하는 CPU 또는 CUDA 장치를 반환한다."""

        return self._provider.get_metadata()["device"]

    def embed_documents(self, texts: list[str], batch_size: int) -> np.ndarray:
        """문서 목록을 배치 단위로 임베딩하고 입력 순서의 NumPy 배열로 반환한다."""

        result = self._provider.embed_documents(texts, batch_size=batch_size)
        return np.array(result)

    def embed_query(self, query: str) -> np.ndarray:
        """단일 검색 질의에 Qwen 질의 프롬프트를 적용한 벡터를 반환한다."""

        return self.embed_queries([query])[0]

    def embed_queries(self, queries: list[str]) -> np.ndarray:
        """여러 검색 질의를 공통 provider로 임베딩해 2차원 NumPy 배열로 반환한다."""

        result = self._provider.embed_queries(queries)
        return np.array(result)

    def count_tokens(self, text: str) -> int:
        """Qwen 토크나이저 기준으로 문자열의 토큰 개수를 계산한다."""

        return self._provider.count_tokens(text)

    def encode_tokens(self, text: str) -> list[int]:
        """문자열을 Qwen 토크나이저의 토큰 식별자 배열로 변환한다."""

        return self._provider.encode_tokens(text)

    def decode_tokens(self, token_ids: list[int]) -> str:
        """Qwen 토큰 식별자 배열을 토크나이저 규칙에 따라 문자열로 복원한다."""

        return self._provider.decode_tokens(token_ids)

    def get_metadata(self) -> dict:
        """Qwen 모델 식별자·revision·장치·차원 메타데이터를 그대로 반환한다."""

        return self._provider.get_metadata()
