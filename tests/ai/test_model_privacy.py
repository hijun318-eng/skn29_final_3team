from __future__ import annotations

import json

import pytest

from src.ai.node3 import explain_result
from src.modelops.privacy import OutboundPrivacyError, prepare_outbound
from src.modelops.runtime import ModelUnavailableError, ProductionModelClient
from tests.ai.test_contracts import VALID_PAYLOADS


def test_question_is_redacted_before_transport_and_only_hash_evidence_is_retained():
    captured = {}

    def transport(_node, payload, _timeout):
        captured.update(payload)
        return explain_result(VALID_PAYLOADS["node3_request"])

    request = dict(VALID_PAYLOADS["node3_request"])
    request["filters"] = ["contact=user@example.com", "phone=010-1234-5678"]
    client = ProductionModelClient(transport)
    client.generate("node3", request)

    serialized = json.dumps(captured, ensure_ascii=False)
    assert "user@example.com" not in serialized
    assert "010-1234-5678" not in serialized
    assert client.last_outbound_evidence == {
        "policy_version": "MODEL-OUTBOUND-v1",
        "decision": "ALLOW",
        "classifications": ["AGGREGATED"],
        "redaction_count": 2,
        "payload_sha256": client.last_outbound_evidence["payload_sha256"],
        "g3_required": True,
    }
    assert len(client.last_outbound_evidence["payload_sha256"]) == 64


@pytest.mark.parametrize("field", ["token", "authorization", "password"])
def test_secret_fields_are_rejected_without_transport(field):
    with pytest.raises(OutboundPrivacyError):
        prepare_outbound("node3", {"shaped_result": {"rows": [{field: "secret"}]}})


def test_unapproved_sensitivity_and_direct_identifier_are_fail_closed():
    with pytest.raises(OutboundPrivacyError):
        prepare_outbound("node2", {"asset": {"sensitivity": "RESTRICTED"}})
    with pytest.raises(OutboundPrivacyError):
        prepare_outbound("node3", {"shaped_result": {"rows": [{"guest_id": "g-1"}]}})
    with pytest.raises(OutboundPrivacyError):
        prepare_outbound(
            "node3",
            {"shaped_result": {"columns": [{"name": "guest_id"}], "rows": []}},
        )


def test_privacy_denial_never_calls_model_transport_or_records_payload():
    calls = []
    client = ProductionModelClient(lambda *_args: calls.append(_args))
    request = dict(VALID_PAYLOADS["node3_request"])
    request["shaped_result"] = {
        "columns": [{"name": "guest_id", "type": "scalar"}],
        "rows": [{"guest_id": "g-1"}],
    }

    with pytest.raises(ModelUnavailableError, match="PRIVACY_DENIED"):
        client.generate("node3", request)

    assert calls == []
    assert client.last_outbound_evidence == {
        "policy_version": "MODEL-OUTBOUND-v1",
        "decision": "DENY",
    }
