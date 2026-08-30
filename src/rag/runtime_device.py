from __future__ import annotations

from typing import Any


class RuntimeDeviceSelector:
    @staticmethod
    def resolve(configured_device: str, *, torch_runtime: Any | None = None) -> str:
        normalized = configured_device.strip().lower()
        if normalized != "auto":
            return normalized
        if torch_runtime is None:
            import torch as torch_runtime
        if torch_runtime.cuda.is_available():
            return "cuda"
        mps = getattr(torch_runtime.backends, "mps", None)
        if mps is not None and mps.is_available():
            return "mps"
        return "cpu"
