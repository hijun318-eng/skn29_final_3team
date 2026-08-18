import copy

import pytest

from src.ai.schema import ContractError
from tests.ai.test_contracts import VALID_PAYLOADS
from tests.support.fakes import ContractFakeModelAdapter


def test_node3_returns_only_the_injected_schema_validated_response():
    request = copy.deepcopy(VALID_PAYLOADS["node3_request"])
    programmed = copy.deepcopy(VALID_PAYLOADS["node3_response"])
    adapter = ContractFakeModelAdapter(programmed)

    result = adapter.generate("node3", request)

    assert result == programmed
    assert result is not programmed
    assert adapter.calls == [
        {"node": "node3", "request": request, "response": programmed}
    ]
    assert adapter.remaining == 0


def test_node3_queue_is_ordered_and_never_derives_a_response_from_context():
    first = copy.deepcopy(VALID_PAYLOADS["node3_response"])
    second = copy.deepcopy(first)
    second["explanation"] = "second explicitly reviewed response"
    adapter = ContractFakeModelAdapter([first, second])

    assert adapter.generate("node3", VALID_PAYLOADS["node3_request"]) == first
    assert adapter.generate("node3", VALID_PAYLOADS["node3_request"]) == second
    with pytest.raises(AssertionError, match="no programmed response"):
        adapter.generate("node3", VALID_PAYLOADS["node3_request"])


def test_node3_transport_rejects_invalid_request_or_programmed_response():
    invalid_request = copy.deepcopy(VALID_PAYLOADS["node3_request"])
    invalid_request["g3_result"] = "fail"
    with pytest.raises(ContractError):
        ContractFakeModelAdapter(VALID_PAYLOADS["node3_response"]).generate(
            "node3", invalid_request
        )

    invalid_response = copy.deepcopy(VALID_PAYLOADS["node3_response"])
    invalid_response["sql"] = "not part of the response contract"
    with pytest.raises(ContractError):
        ContractFakeModelAdapter(invalid_response).generate(
            "node3", VALID_PAYLOADS["node3_request"]
        )
