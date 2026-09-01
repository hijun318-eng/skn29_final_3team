"""MCP 예측 도구의 입력 제한·시간 제한을 적용하고 모델 결과를 관측 근거와 분리한다."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from typing import Any, Protocol

from .contracts import IntegrationContext
from .coordinator import ToolCallError


class ModelPredictionExecutor(Protocol):
    """검증된 모델 인자를 실제 예측 런타임에 전달하는 구현 규약이다."""

    def execute_arguments(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """property·기준일·기간 인자를 실행해 모델 고유 예측 payload를 반환한다."""

        ...


class PredictionToolHandler:
    """정확한 예측 인자 스키마와 짧은 실행 제한을 적용해 ML 출력을 예측 근거로 감싼다."""

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
        """property·as_of·1~7 horizon만 허용하고 시간 초과를 도구 오류로 변환해 예측 영수증을 반환한다."""

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
