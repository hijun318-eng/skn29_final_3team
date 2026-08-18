import copy

import pytest

from src.ai.schema import ContractError
from tests.ai.test_contracts import VALID_PAYLOADS
from tests.support.fakes import ContractFakeModelAdapter


def test_node1_uses_an_explicit_schema_validated_transport_response():
    request = copy.deepcopy(VALID_PAYLOADS["node1_request"])
    programmed = copy.deepcopy(VALID_PAYLOADS["node1_response"])
    adapter = ContractFakeModelAdapter(programmed)

    result = adapter.generate("node1", request)

    assert result == programmed
    assert result is not programmed
    assert adapter.calls == [
        {"node": "node1", "request": request, "response": programmed}
    ]
    assert adapter.remaining == 0


def test_node1_callable_receives_a_copy_and_must_return_the_contract():
    request = copy.deepcopy(VALID_PAYLOADS["node1_request"])
    observed = {}

    def programmed(node, payload):
        observed.update({"node": node, "payload": payload})
        payload["question"] = "transport-local mutation"
        return VALID_PAYLOADS["node1_response"]

    result = ContractFakeModelAdapter([programmed]).generate("node1", request)

    assert result == VALID_PAYLOADS["node1_response"]
    assert observed["node"] == "node1"
    assert request == VALID_PAYLOADS["node1_request"]


def test_node1_transport_rejects_invalid_request_or_programmed_response():
    invalid_request = copy.deepcopy(VALID_PAYLOADS["node1_request"])
    invalid_request.pop("business_terms")
    with pytest.raises(ContractError):
        ContractFakeModelAdapter(VALID_PAYLOADS["node1_response"]).generate(
            "node1", invalid_request
        )

    invalid_response = copy.deepcopy(VALID_PAYLOADS["node1_response"])
    invalid_response["unexpected"] = True
    with pytest.raises(ContractError):
        ContractFakeModelAdapter(invalid_response).generate(
            "node1", VALID_PAYLOADS["node1_request"]
        )
