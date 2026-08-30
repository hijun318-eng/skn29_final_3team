from __future__ import annotations

import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from src.rag.runtime_device import RuntimeDeviceSelector
from src.rag.vector_settings import VectorSettings


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
