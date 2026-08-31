"""로컬 SentenceTransformer와 OpenAI 임베딩 호출을 동일한 검색 벡터 경계로 제공한다.

로컬 모델은 고정된 모델 차원과 토크나이저를 검증하고, 원격 모델은 비밀 패턴을
차단한 뒤 HTTPS 응답의 개수·차원·유한값을 확인해 잘못된 벡터가 저장되지 않게 한다.
"""

from __future__ import annotations

import json
import math
import os
import threading
import time
from typing import Any
from urllib.parse import urlparse

import httpx
import numpy as np

from .text_processing import SecurityScanner


OPENAI_EMBEDDING_MODELS = frozenset(
    {"text-embedding-3-small", "text-embedding-3-large"}
)
EMBEDDING_TIMEOUT_MIN_SECONDS = 0.1
EMBEDDING_TIMEOUT_MAX_SECONDS = 300.0
EMBEDDING_MAXIMUM_ATTEMPTS_MIN = 1
EMBEDDING_MAXIMUM_ATTEMPTS_MAX = 4


def validate_embedding_timeout(value: Any) -> float:
    """OpenAI embedding 호출에 사용할 유한한 timeout 범위를 검증한다."""

    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or not EMBEDDING_TIMEOUT_MIN_SECONDS
        <= float(value)
        <= EMBEDDING_TIMEOUT_MAX_SECONDS
    ):
        raise ValueError(
            "OpenAI embedding timeout must be between 0.1 and 300 seconds"
        )
    return float(value)


def validate_embedding_maximum_attempts(value: Any) -> int:
    """OpenAI embedding 재시도 폭증을 막는 총 시도 횟수 범위를 검증한다."""

    if (
        type(value) is not int
        or not EMBEDDING_MAXIMUM_ATTEMPTS_MIN
        <= value
        <= EMBEDDING_MAXIMUM_ATTEMPTS_MAX
    ):
        raise ValueError(
            "OpenAI embedding maximum attempts must be between 1 and 4"
        )
    return value


class SentenceTransformerEmbeddingProvider:
    """승인된 로컬 모델 경로에서 SentenceTransformer를 로드해 정규화 벡터를 만든다.

    모델 파일이 없거나 실제 출력 차원이 프로필과 다르면 초기화 단계에서 실패한다.
    모델 추론은 내부 잠금으로 직렬화해 동시 호출 중 모델 상태가 섞이지 않게 한다.
    """

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
        """로컬 모델의 실제 토크나이저로 입력 문자열의 토큰 수를 반환한다."""

        return len(self.model.tokenizer.encode(text))

    def encode_tokens(self, text: str) -> list[int]:
        """문자열을 로컬 임베딩 모델이 사용하는 토큰 식별자 배열로 변환한다."""

        return self.model.tokenizer.encode(text)

    def decode_tokens(self, token_ids: list[int]) -> str:
        """로컬 모델의 토큰 식별자 배열을 토크나이저 규칙에 따라 문자열로 복원한다."""

        return self.model.tokenizer.decode(token_ids)

    def embed_query(self, query: str) -> list[float]:
        """단일 검색 질의를 모델의 질의 프롬프트를 적용한 벡터로 변환한다."""

        return self.embed_queries([query])[0]

    def embed_queries(self, queries: list[str]) -> list[list[float]]:
        """여러 검색 질의를 입력 순서와 동일한 정규화 벡터 목록으로 반환한다."""

        with self._lock:
            if self.query_prompt_name:
                result = self.model.encode(queries, prompt_name=self.query_prompt_name, normalize_embeddings=self.normalize_embeddings, show_progress_bar=False, convert_to_numpy=True)
            else:
                result = self.model.encode([f"{self.query_prefix}{q}" for q in queries], normalize_embeddings=self.normalize_embeddings, show_progress_bar=False, convert_to_numpy=True)
        return result.tolist()

    def embed_documents(self, documents: list[str], batch_size: int = 8) -> list[list[float]]:
        """문서 접두어와 배치 크기를 적용해 각 문서의 정규화 벡터를 생성한다."""

        with self._lock:
            result = self.model.encode([f"{self.document_prefix}{doc}" for doc in documents], batch_size=batch_size, normalize_embeddings=self.normalize_embeddings, show_progress_bar=True, convert_to_numpy=True)
        return result.tolist()

    def get_metadata(self) -> dict[str, Any]:
        """현재 로컬 모델의 식별자·revision·실행 장치·벡터 차원을 반환한다."""

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
        self.timeout_seconds = validate_embedding_timeout(timeout_seconds)
        self.maximum_attempts = validate_embedding_maximum_attempts(
            maximum_attempts
        )
        self.device = "openai-api"
        self._scanner = SecurityScanner()

    def embed_query(self, query: str) -> np.ndarray:
        """단일 질의를 보안 검사 후 OpenAI 임베딩 벡터 한 개로 반환한다."""

        return self.embed_queries([query])[0]

    def embed_queries(self, queries: list[str]) -> np.ndarray:
        """질의 목록을 입력 순서가 보존된 2차원 OpenAI 임베딩 배열로 반환한다.

        비밀 패턴, 최종 HTTP 실패, 응답 개수·차원 불일치 또는 비유한 벡터는 예외로
        종료하며 불완전한 배열을 반환하지 않는다.
        """

        return self._embed(queries)

    def embed_documents(self, documents: list[str], batch_size: int = 8) -> np.ndarray:
        """문서를 지정한 배치 크기로 나눠 OpenAI에 전송하고 하나의 벡터 배열로 합친다."""

        batches = [documents[index:index + batch_size] for index in range(0, len(documents), batch_size)]
        vectors = [vector for batch in batches for vector in self._embed(batch)]
        return np.asarray(vectors, dtype=np.float32)

    def get_metadata(self) -> dict[str, Any]:
        """원격 provider·모델·차원과 API 실행 장치를 release 메타데이터로 반환한다."""

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
            try:
                with httpx.Client(
                    timeout=httpx.Timeout(float(self.timeout_seconds)),
                    follow_redirects=False,
                    trust_env=False,
                ) as client:
                    response = client.post(
                        self.endpoint,
                        content=payload,
                        headers={
                            "Authorization": f"Bearer {self.api_key}",
                            "Content-Type": "application/json",
                            "User-Agent": "answervice-rag/1.0",
                        },
                    )
                if response.is_redirect:
                    raise RuntimeError("OpenAI embedding redirect is not allowed")
                if response.status_code >= 400:
                    if (
                        response.status_code not in self._RETRYABLE
                        or attempt == self.maximum_attempts
                    ):
                        raise RuntimeError(
                            "OpenAI embedding request failed with HTTP "
                            f"{response.status_code}"
                        )
                    time.sleep(0.5 * (2 ** (attempt - 1)))
                    continue
                result = response.json()
                rows = result.get("data", []) if isinstance(result, dict) else []
                if not isinstance(rows, list) or len(rows) != len(safe_texts):
                    raise ValueError("OpenAI embedding response shape mismatch")
                indices = [
                    row.get("index") if isinstance(row, dict) else None
                    for row in rows
                ]
                if (
                    any(type(index) is not int for index in indices)
                    or sorted(indices) != list(range(len(safe_texts)))
                ):
                    raise ValueError("OpenAI embedding response index mismatch")
                rows = sorted(rows, key=lambda item: item["index"])
                vectors = [row.get("embedding") for row in rows]
                if len(vectors) != len(safe_texts) or any(len(vector or []) != self.dimension for vector in vectors):
                    raise ValueError("OpenAI embedding response shape mismatch")
                array = np.asarray(vectors, dtype=np.float32)
                if not np.isfinite(array).all() or any(math.isclose(float(np.linalg.norm(vector)), 0.0) for vector in array):
                    raise ValueError("OpenAI embedding response contains an invalid vector")
                return array
            except httpx.RequestError as error:
                if attempt == self.maximum_attempts:
                    raise RuntimeError("OpenAI embedding request failed") from error
            time.sleep(0.5 * (2 ** (attempt - 1)))
        raise RuntimeError("OpenAI embedding request failed")
