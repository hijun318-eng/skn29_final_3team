from __future__ import annotations

import json
import math
import os
import threading
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import numpy as np

from .text_processing import SecurityScanner


OPENAI_EMBEDDING_MODELS = frozenset(
    {"text-embedding-3-small", "text-embedding-3-large"}
)


class SentenceTransformerEmbeddingProvider:
    def __init__(self, profile: dict[str, Any], device: str = "auto"):
        self.profile = profile
        self.model_id = profile["model_id"]
        self.local_path = profile["local_path"]
        self.revision = profile["revision"]
        self.dimension = profile["dimension"]
        self.normalize_embeddings = profile.get("normalize_embeddings", True)
        self.query_prompt_name = profile.get("query_prompt_name")
        self.query_prefix = profile.get("query_prefix", "")
        self.document_prefix = profile.get("document_prefix", "")
        self.max_sequence_length = profile.get("max_sequence_length", 2048)
        if not os.path.exists(self.local_path):
            raise FileNotFoundError(f"Model path not found: {self.local_path}")
        from sentence_transformers import SentenceTransformer
        from src.rag.runtime_device import RuntimeDeviceSelector
        resolved_device = RuntimeDeviceSelector.resolve(device)
        self.model = SentenceTransformer(self.local_path, device=resolved_device, local_files_only=True)
        self.model.max_seq_length = self.max_sequence_length
        actual_dim = int(self.model.get_sentence_embedding_dimension())
        if actual_dim != self.dimension:
            raise ValueError(f"Model dimension mismatch. Expected {self.dimension}, got {actual_dim}")
        self._lock = threading.Lock()

    def count_tokens(self, text: str) -> int:
        return len(self.model.tokenizer.encode(text))

    def encode_tokens(self, text: str) -> list[int]:
        return self.model.tokenizer.encode(text)

    def decode_tokens(self, token_ids: list[int]) -> str:
        return self.model.tokenizer.decode(token_ids)

    def embed_query(self, query: str) -> list[float]:
        return self.embed_queries([query])[0]

    def embed_queries(self, queries: list[str]) -> list[list[float]]:
        with self._lock:
            if self.query_prompt_name:
                result = self.model.encode(queries, prompt_name=self.query_prompt_name, normalize_embeddings=self.normalize_embeddings, show_progress_bar=False, convert_to_numpy=True)
            else:
                result = self.model.encode([f"{self.query_prefix}{q}" for q in queries], normalize_embeddings=self.normalize_embeddings, show_progress_bar=False, convert_to_numpy=True)
        return result.tolist()

    def embed_documents(self, documents: list[str], batch_size: int = 8) -> list[list[float]]:
        with self._lock:
            result = self.model.encode([f"{self.document_prefix}{doc}" for doc in documents], batch_size=batch_size, normalize_embeddings=self.normalize_embeddings, show_progress_bar=True, convert_to_numpy=True)
        return result.tolist()

    def get_metadata(self) -> dict[str, Any]:
        return {"provider": "qwen", "model_id": self.model_id, "revision": self.revision, "device": str(self.model.device), "dimension": self.dimension}


class OpenAIEmbeddingProvider:
    """민감 입력을 차단·마스킹한 뒤 OpenAI Embeddings API를 제한 재시도로 호출한다."""

    _RETRYABLE = {408, 409, 429, 500, 502, 503, 504}

    def __init__(
        self,
        api_key: str,
        model_id: str,
        dimension: int,
        endpoint: str,
        timeout_seconds: float = 30,
        maximum_attempts: int = 3,
    ) -> None:
        if not api_key.strip():
            raise ValueError("OPENAI_API_KEY is required for OpenAI embeddings")
        if model_id not in OPENAI_EMBEDDING_MODELS:
            raise ValueError(
                "OPENAI_EMBEDDING_MODEL must be text-embedding-3-small or "
                "text-embedding-3-large"
            )
        parsed = urlparse(endpoint)
        if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
            raise ValueError("OPENAI_EMBEDDING_ENDPOINT must be an authenticated HTTPS endpoint")
        if not 1 <= dimension <= 3072:
            raise ValueError("OPENAI_EMBEDDING_DIMENSIONS is invalid")
        self.api_key = api_key
        self.model_id = model_id
        self.revision = f"{model_id}:d{dimension}"
        self.dimension = dimension
        self.endpoint = endpoint
        self.timeout_seconds = timeout_seconds
        self.maximum_attempts = maximum_attempts
        self.device = "openai-api"
        self._scanner = SecurityScanner()

    def embed_query(self, query: str) -> np.ndarray:
        return self.embed_queries([query])[0]

    def embed_queries(self, queries: list[str]) -> np.ndarray:
        return self._embed(queries)

    def embed_documents(self, documents: list[str], batch_size: int = 8) -> np.ndarray:
        batches = [documents[index:index + batch_size] for index in range(0, len(documents), batch_size)]
        vectors = [vector for batch in batches for vector in self._embed(batch)]
        return np.asarray(vectors, dtype=np.float32)

    def get_metadata(self) -> dict[str, Any]:
        return {"provider": "openai", "model_id": self.model_id, "revision": self.revision, "device": self.device, "dimension": self.dimension}

    def _embed(self, texts: list[str]) -> np.ndarray:
        safe_texts = []
        for text in texts:
            status, safe = self._scanner.inspect(text)
            if status == "REJECTED_SECRET":
                raise ValueError("Embedding input contains a secret pattern")
            safe_texts.append(safe)
        payload = json.dumps({"input": safe_texts, "model": self.model_id, "dimensions": self.dimension, "encoding_format": "float"}, ensure_ascii=False).encode("utf-8")
        for attempt in range(1, self.maximum_attempts + 1):
            request = Request(self.endpoint, data=payload, method="POST", headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json", "User-Agent": "answervice-rag/1.0"})
            try:
                with urlopen(request, timeout=self.timeout_seconds) as response:
                    result = json.loads(response.read().decode("utf-8"))
                rows = sorted(result.get("data", []), key=lambda item: item.get("index", -1))
                vectors = [row.get("embedding") for row in rows]
                if len(vectors) != len(safe_texts) or any(len(vector or []) != self.dimension for vector in vectors):
                    raise ValueError("OpenAI embedding response shape mismatch")
                array = np.asarray(vectors, dtype=np.float32)
                if not np.isfinite(array).all() or any(math.isclose(float(np.linalg.norm(vector)), 0.0) for vector in array):
                    raise ValueError("OpenAI embedding response contains an invalid vector")
                return array
            except HTTPError as error:
                if error.code not in self._RETRYABLE or attempt == self.maximum_attempts:
                    raise RuntimeError(f"OpenAI embedding request failed with HTTP {error.code}") from error
            except URLError as error:
                if attempt == self.maximum_attempts:
                    raise RuntimeError("OpenAI embedding request failed") from error
            time.sleep(0.5 * (2 ** (attempt - 1)))
        raise RuntimeError("OpenAI embedding request failed")
