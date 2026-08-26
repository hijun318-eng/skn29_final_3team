from __future__ import annotations

import torch


class RuntimeDeviceSelector:
    @staticmethod
    def resolve(configured_device: str) -> str:
        normalized = configured_device.strip().lower()
        if normalized != "auto":
            return normalized
        if torch.cuda.is_available():
            return "cuda"
        mps = getattr(torch.backends, "mps", None)
        if mps is not None and mps.is_available():
            return "mps"
        return "cpu"
