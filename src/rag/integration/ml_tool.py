from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from typing import Any, Protocol

from .contracts import IntegrationContext
from .coordinator import ToolCallError


class ModelPredictionExecutor(Protocol):
    def execute_arguments(self, arguments: dict[str, Any]) -> dict[str, Any]: ...


class PredictionToolHandler:
    """MCP adapter that keeps model predictions distinct from observed evidence."""

    DEFAULT_REQUIRED_ARGUMENTS = frozenset(
        {
            "property_id",
            "as_of",
            "horizon",
        }
    )

    def __init__(
        self,
        executor: ModelPredictionExecutor,
        timeout_seconds: float = 2.0,
        required_arguments: frozenset[str] | None = None,
    ) -> None:
        self._executor = executor
        self._timeout_seconds = timeout_seconds
        self._required_arguments = required_arguments or self.DEFAULT_REQUIRED_ARGUMENTS
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="room-demand-ml")

    def call(
        self, arguments: dict[str, Any], context: IntegrationContext
    ) -> dict[str, Any]:
        if set(arguments) != self._required_arguments:
            raise ToolCallError("TOOL_INPUT_SCHEMA_INVALID")
        if (
            not isinstance(arguments.get("property_id"), str)
            or not isinstance(arguments.get("as_of"), str)
            or not isinstance(arguments.get("horizon"), int)
            or isinstance(arguments.get("horizon"), bool)
            or not 1 <= arguments["horizon"] <= 7
        ):
            raise ToolCallError("TOOL_INPUT_SCHEMA_INVALID")
        future = self._pool.submit(self._executor.execute_arguments, arguments)
        try:
            prediction = future.result(timeout=self._timeout_seconds)
        except FutureTimeout as error:
            future.cancel()
            raise ToolCallError("TOOL_TIMEOUT") from error
        return {
            "evidence_type": "MODEL_PREDICTION",
            "fact_status": "PREDICTION_NOT_OBSERVED",
            "request_id": context.request_id,
            "trace_id": context.trace_id,
            "prediction": prediction,
        }
