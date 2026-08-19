from __future__ import annotations

from collections import deque
from collections.abc import Callable, Iterable, Mapping
from copy import deepcopy
from typing import Any

from src.ai.schema import validate_payload


class ContractFakeModelAdapter:
    """Schema-checking response queue; it never interprets Context or writes SQL."""

    version = "MODEL-FIXTURE-v1.0.0"

    def __init__(
        self,
        responses: (
            Mapping[str, Any]
            | Iterable[
                Mapping[str, Any]
                | Callable[[str, dict[str, Any]], Mapping[str, Any]]
            ]
            | None
        ) = None,
    ) -> None:
        if responses is None:
            queued = ()
        elif isinstance(responses, Mapping):
            queued = (responses,)
        else:
            queued = responses
        self._responses = deque(queued)
        self.calls: list[dict[str, Any]] = []

    @property
    def remaining(self) -> int:
        return len(self._responses)

    def generate(self, node: str, payload: dict[str, Any]) -> dict[str, Any]:
        validate_payload(f"{node}_request", payload)
        if not self._responses:
            raise AssertionError(f"no programmed response for {node}")
        programmed = self._responses.popleft()
        request_copy = deepcopy(payload)
        response = (
            programmed(node, request_copy)
            if callable(programmed)
            else deepcopy(programmed)
        )
        if not isinstance(response, Mapping):
            raise TypeError("programmed model response must be a mapping")
        response = dict(response)
        validate_payload(f"{node}_response", response)
        completed = deepcopy(response)
        self.calls.append(
            {
                "node": node,
                "request": deepcopy(payload),
                "response": deepcopy(completed),
            }
        )
        return completed
