from __future__ import annotations

from typing import Any, Protocol


class ModelAdapter(Protocol):
    """R3-owned contract. It cannot authorize SQL or make Gate decisions."""

    def invoke(self, payload: dict[str, Any], timeout_seconds: float) -> dict[str, Any]: ...
