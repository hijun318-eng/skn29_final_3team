"""Node1 live 평가가 이전 결과 형태의 보존·교체를 실제로 채점하는지 검증한다."""

from __future__ import annotations

from copy import deepcopy

from evals.nlu_live_node1 import (
    PREVIOUS_RESULT_SHAPE,
    LiveCase,
    build_request,
    judge,
)
from tests.ai.test_contracts import VALID_PAYLOADS


def _elliptical_response(operation: str | None) -> dict[str, object]:
    """지표는 생략하고 결과 형태만 선택적으로 명시한 계약 응답을 만든다."""

    response = deepcopy(VALID_PAYLOADS["node1_response"])
    response.update(
        {
            "normalized_question": "elliptical governed analysis",
            "intent_candidates": [operation] if operation else [],
            "measurement_source_text": None,
            "measurement_source_texts": [],
            "metric_candidates": [],
            "metric_resolution": "missing",
            "selected_metric_id": None,
            "selected_metric_ids": [],
            "analysis_operation": operation,
            "result_limit": None,
            "dimension_candidates": [],
            "filter_candidates": [],
            "period_candidates": [],
            "period_relationship": "single",
            "requested_route": "ANALYSIS",
            "presentation_type": None,
            "is_elliptical": True,
        }
    )
    return response


def test_live_eval_request_carries_the_typed_previous_result_shape() -> None:
    """유료 호출 전에 구성하는 요청도 운영과 같은 직전 shape 계약을 사용해야 한다."""

    request = build_request(
        LiveCase(
            "임의의 전체값 전환 발화",
            "ANALYSIS",
            True,
            operation="aggregate",
        )
    )

    assert request["previous_result_shape"] == PREVIOUS_RESULT_SHAPE


def test_live_eval_judges_shape_preservation_and_explicit_replacement() -> None:
    """모델 원신호가 아니라 서버 합성 뒤의 최종 연산을 품질 기준으로 삼는다."""

    preserved = judge(
        LiveCase(
            "임의의 기간만 바꾸는 발화",
            "ANALYSIS",
            True,
            operation="breakdown",
        ),
        _elliptical_response(None),
    )
    replaced = judge(
        LiveCase(
            "임의의 전체값 전환 발화",
            "ANALYSIS",
            True,
            operation="aggregate",
        ),
        _elliptical_response("aggregate"),
    )

    assert preserved["operation_resolved"] == "breakdown"
    assert preserved["operation_ok"] is True
    assert replaced["operation_resolved"] == "aggregate"
    assert replaced["operation_ok"] is True
