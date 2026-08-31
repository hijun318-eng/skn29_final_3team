from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src.rag.runtime_device import RuntimeDeviceSelector
from src.rag.embedding_provider import OpenAIEmbeddingProvider
from src.rag.vector_settings import VectorSettings
from src.rag.retrieval_service import VectorRetrievalService
import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class RuntimeSettingsTest(unittest.TestCase):
    @patch.dict(
        os.environ,
        {
            "RAG_DATABASE_URL": "postgresql://rag_test@localhost/rag_test",
            "RAG_DEVICE": "CPU",
        },
    )
    def test_device_can_be_selected_for_local_runtime(self) -> None:
        settings = VectorSettings.load(PROJECT_ROOT)

        self.assertEqual(settings.device, "cpu")
        self.assertEqual(settings.model_id, "text-embedding-3-large")
        self.assertEqual(settings.dimension, 1024)

    @patch.dict(
        os.environ,
        {
            "RAG_DATABASE_URL": "postgresql://rag_test@localhost/rag_test",
            "RAG_EMBEDDING_PROVIDER": "openai",
            "OPENAI_EMBEDDING_DIMENSIONS": "1536",
        },
    )
    def test_openai_dimension_must_match_pgvector_schema(self) -> None:
        with self.assertRaisesRegex(ValueError, "pgvector schema"):
            VectorSettings.load(PROJECT_ROOT)

    def test_openai_provider_rejects_unapproved_embedding_models(self) -> None:
        for model_id in ("text-embedding-ada-002", "text-embedding-3-medium"):
            with self.subTest(model_id=model_id):
                with self.assertRaisesRegex(ValueError, "small or text-embedding-3-large"):
                    OpenAIEmbeddingProvider(
                        api_key="test-key",
                        model_id=model_id,
                        dimension=1024,
                        endpoint="https://api.openai.com/v1/embeddings",
                    )

    @patch.dict(
        os.environ,
        {
            "RAG_DATABASE_URL": "postgresql://rag_test@localhost/rag_test",
            "RAG_EMBEDDING_PROVIDER": "openai",
            "OPENAI_EMBEDDING_MODEL": "text-embedding-3-medium",
        },
    )
    def test_runtime_settings_reject_nonexistent_openai_embedding_model(self) -> None:
        with self.assertRaisesRegex(ValueError, "small or text-embedding-3-large"):
            VectorSettings.load(PROJECT_ROOT)

    def test_reranker_environment_names_fail_closed_in_candidate_runtime(self) -> None:
        for variable in ("RAG_RERANKER_PATH", "RERANKER_PATH"):
            with self.subTest(variable=variable):
                with patch.dict(
                    os.environ,
                    {
                        "RAG_DATABASE_URL": "postgresql://rag_test@localhost/rag_test",
                        variable: "/models/reranker",
                    },
                    clear=True,
                ):
                    with self.assertRaisesRegex(
                        ValueError, "reranker is not available"
                    ):
                        VectorSettings.load(PROJECT_ROOT)

    def test_hybrid_rerank_never_silently_falls_back_without_dependency(self) -> None:
        retrieval = VectorRetrievalService(object())  # type: ignore[arg-type]

        with self.assertRaisesRegex(RuntimeError, "reranker is not configured"):
            retrieval.retrieve(
                "query",
                np.asarray([0.1], dtype=np.float32),
                object(),  # type: ignore[arg-type]
                retrieval_mode="HYBRID_RERANK",
            )

    @patch("src.rag.embedding_provider.urlopen")
    def test_openai_provider_sends_the_pinned_model_and_vector_dimension(
        self,
        open_url: Mock,
    ) -> None:
        class Response:
            def __enter__(self) -> "Response":
                return self

            def __exit__(self, *_args: object) -> None:
                return None

            @staticmethod
            def read() -> bytes:
                return json.dumps(
                    {"data": [{"index": 0, "embedding": [0.5] * 1024}]}
                ).encode("utf-8")

        open_url.return_value = Response()
        provider = OpenAIEmbeddingProvider(
            api_key="test-key",
            model_id="text-embedding-3-large",
            dimension=1024,
            endpoint="https://api.openai.com/v1/embeddings",
            maximum_attempts=1,
        )

        vector = provider.embed_query("객실 운영 지침")

        request = open_url.call_args.args[0]
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(payload["model"], "text-embedding-3-large")
        self.assertEqual(payload["dimensions"], 1024)
        self.assertEqual(vector.shape, (1024,))
        self.assertEqual(provider.revision, "text-embedding-3-large:d1024")

    def test_auto_prefers_cuda_when_available(self) -> None:
        torch_runtime = SimpleNamespace(
            cuda=SimpleNamespace(is_available=Mock(return_value=True)),
            backends=SimpleNamespace(),
        )

        self.assertEqual(
            RuntimeDeviceSelector.resolve("auto", torch_runtime=torch_runtime),
            "cuda",
        )

    def test_auto_falls_back_to_cpu(self) -> None:
        torch_runtime = SimpleNamespace(
            cuda=SimpleNamespace(is_available=Mock(return_value=False)),
            backends=SimpleNamespace(
                mps=SimpleNamespace(is_available=Mock(return_value=False))
            ),
        )

        self.assertEqual(
            RuntimeDeviceSelector.resolve("auto", torch_runtime=torch_runtime),
            "cpu",
        )


if __name__ == "__main__":
    unittest.main()
