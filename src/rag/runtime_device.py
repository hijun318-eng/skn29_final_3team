"""embedding runtime의 CPU·CUDA·MPS 장치 선택을 결정한다."""

from __future__ import annotations

from typing import Any


class RuntimeDeviceSelector:
    """명시 장치는 유지하고 auto일 때 torch accelerator 가용성을 순서 판정한다."""

    @staticmethod
    def resolve(configured_device: str, *, torch_runtime: Any | None = None) -> str:
        """설정 문자열과 torch runtime을 받아 실행에 사용할 device 이름을 반환한다."""

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
