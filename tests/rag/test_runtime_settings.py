from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest.mock import patch

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

    @patch("src.rag.runtime_device.torch.cuda.is_available", return_value=True)
    def test_auto_prefers_cuda_when_available(self, _cuda_available: object) -> None:
        self.assertEqual(RuntimeDeviceSelector.resolve("auto"), "cuda")

    @patch("src.rag.runtime_device.torch.cuda.is_available", return_value=False)
    @patch("src.rag.runtime_device.torch.backends.mps.is_available", return_value=False)
    def test_auto_falls_back_to_cpu(
        self, _mps_available: object, _cuda_available: object
    ) -> None:
        self.assertEqual(RuntimeDeviceSelector.resolve("auto"), "cpu")


if __name__ == "__main__":
    unittest.main()
