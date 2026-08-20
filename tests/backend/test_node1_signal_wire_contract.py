"""운영 Node1 클라이언트가 새 신호를 실제 전선(wire)에서 주고받는지 종단 검증.

[검증 대상]
Node1 요청에 대화 앵커(`previous_period`)가 실려 나가고, 응답의 route/표현/생략문 신호가
계약 검증을 통과해 호출자에게 전달되는지를 운영 어댑터(`ContractModelAdapter`)로 확인한다.
모델 자체의 판단 정확도는 여기서 측정하지 않는다.

[경계]
외부 호출은 `httpx.MockTransport`로만 대체한다. AGENTS.md가 명시적 주입 경계로 허용하는
유일한 방식이며, production 모듈에는 어떤 test double도 두지 않는다.
"""

from __future__ import annotations

import asyncio
import json
from functools import wraps
from pathlib import Path
import sys
from typing import Any
from unittest.mock import patch

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "app" / "backend"
for entry in (str(BACKEND), str(ROOT)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from app.adapters.model_adapter import ContractModelAdapter  # noqa: E402
from src.ai.schema import validate_payload  # noqa: E402
from tests.ai.test_contracts import VALID_PAYLOADS  # noqa: E402

def async_test(function):
    """pytest-asyncio 없이 async 테스트를 실행하는 최소 래퍼."""

    @wraps(function)
    def run(*args, **kwargs):
        return asyncio.run(function(*args, **kwargs))

    return run


ANCHOR = {
    "start": "2025-08-01T00:00:00+09:00",
    "end_exclusive": "2025-09-01T00:00:00+09:00",
}


async def _run_node1(request: dict[str, Any], response: dict[str, Any]) -> tuple[dict, dict]:
    """MockTransport로 Node1 한 번을 호출하고 (전선 요청, 파싱된 응답)을 돌려준다.

    Args:
        request: 어댑터에 넘길 node1_request 페이로드
        response: 모델이 반환할 node1_response 페이로드

    Returns:
        (모델에게 실제로 전송된 요청 JSON, 어댑터가 반환한 응답)
    """
    seen: dict[str, Any] = {}

    async def handler(http_request: httpx.Request) -> httpx.Response:
        provider_payload = json.loads(http_request.content)
        wire_request = json.loads(provider_payload["messages"][1]["content"])
        # 전선에 실린 요청이 계약을 만족하지 않으면 여기서 즉시 실패한다.
        validate_payload("node1_request", wire_request)
        seen.update(wire_request)
        return httpx.Response(
            200,
            json={
                "model": "node1-snapshot",
                "choices": [{"message": {"content": json.dumps(response)}}],
                "usage": {"prompt_tokens": 11, "completion_tokens": 7},
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        with patch(
            "app.adapters.model_transport.httpx.AsyncClient",
            side_effect=[client, httpx.AsyncClient(transport=httpx.MockTransport(handler))],
        ):
            adapter = ContractModelAdapter.from_endpoints(
                openai_endpoint="https://openai.invalid",
                openai_token="openai-token",
                openai_model="gpt-5.4-mini",
                node2_endpoint="https://node2.invalid",
                node2_token="node2-token",
                node2_model="answervice-sql",
                node2_provider="qwen",
                timeout_seconds=2,
            )
        normalized = await adapter.normalize_question(dict(request))
    finally:
        await client.aclose()
    return seen, normalized


@async_test
async def test_conversation_anchor_reaches_the_model_over_the_wire():
    """`previous_period`가 계약을 통과해 모델 요청에 실제로 실려 나가는지 검증."""
    request = dict(VALID_PAYLOADS["node1_request"])
    request["previous_period"] = dict(ANCHOR)

    wire_request, _ = await _run_node1(request, dict(VALID_PAYLOADS["node1_response"]))

    assert wire_request["previous_period"] == ANCHOR


@async_test
async def test_route_and_ellipsis_signals_survive_response_validation():
    """route·표현·생략문 신호가 응답 검증을 통과해 호출자에게 전달되는지 검증."""
    response = dict(VALID_PAYLOADS["node1_response"])
    response.update(
        {
            "requested_route": "PRESENTATION",
            "presentation_type": "LINE",
            "is_elliptical": True,
        }
    )

    _, normalized = await _run_node1(dict(VALID_PAYLOADS["node1_request"]), response)

    assert normalized["requested_route"] == "PRESENTATION"
    assert normalized["presentation_type"] == "LINE"
    assert normalized["is_elliptical"] is True


@async_test
async def test_request_without_anchor_is_still_contract_valid():
    """첫 턴처럼 앵커가 없는 요청도 전선 계약을 통과하는지 검증."""
    wire_request, _ = await _run_node1(
        dict(VALID_PAYLOADS["node1_request"]), dict(VALID_PAYLOADS["node1_response"])
    )

    assert "previous_period" not in wire_request


@async_test
async def test_out_of_contract_route_value_is_rejected_before_reaching_callers():
    """계약 밖 route 값을 모델이 반환하면 응답 검증에서 닫히는지 검증.

    모델이 임의 문자열로 라우트를 지정해 서버 분기를 흔들 수 없어야 한다.
    """
    response = dict(VALID_PAYLOADS["node1_response"])
    response["requested_route"] = "EXECUTE_RAW_SQL"

    with pytest.raises(Exception):
        await _run_node1(dict(VALID_PAYLOADS["node1_request"]), response)
