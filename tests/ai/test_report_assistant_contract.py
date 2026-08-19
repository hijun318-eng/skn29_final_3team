import copy
import unittest

from src.ai.schema import ContractError, schema_definition, validate_payload


REPORT_ASSISTANT_REQUEST = {
    "instruction": "Build a concise management report from the approved artifact.",
    "artifact": {
        "artifact_id": "artifact-quartz",
        "query_id": "query-ember",
        "title": "Approved analysis",
        "narrative": "The approved evidence describes the measured result.",
        "evidence": {"metric_values": [], "cached": False},
        "chart_spec": {
            "chart_type": "bar",
            "x_field": "category_code",
            "y_fields": ["resolved_measure"],
        },
        "checksum": "a" * 64,
    },
}

REPORT_ASSISTANT_RESPONSE = {
    "title": "Management report",
    "executive_summary": "The approved evidence is summarized without new facts.",
    "table_title": "Evidence detail",
    "chart_title": "Evidence overview",
}


class ReportAssistantContractTests(unittest.TestCase):
    def test_request_and_response_preserve_the_live_api_fields(self):
        validate_payload("report_assistant_request", REPORT_ASSISTANT_REQUEST)
        validate_payload("report_assistant_response", REPORT_ASSISTANT_RESPONSE)

        request_schema = schema_definition("report_assistant_request")
        response_schema = schema_definition("report_assistant_response")
        self.assertEqual(
            {"instruction", "artifact"},
            set(request_schema["required"]),
        )
        self.assertEqual(
            {
                "artifact_id",
                "query_id",
                "title",
                "narrative",
                "evidence",
                "chart_spec",
                "checksum",
            },
            set(request_schema["$defs"]["report_assistant_artifact"]["required"]),
        )
        self.assertEqual(
            {"title", "executive_summary", "table_title", "chart_title"},
            set(response_schema["required"]),
        )

    def test_report_assistant_contracts_reject_missing_and_extra_fields(self):
        for definition, payload in (
            ("report_assistant_request", REPORT_ASSISTANT_REQUEST),
            ("report_assistant_response", REPORT_ASSISTANT_RESPONSE),
        ):
            missing = copy.deepcopy(payload)
            missing.pop(next(iter(missing)))
            extra = {**copy.deepcopy(payload), "model": {"version": "untrusted"}}
            with self.subTest(definition=definition, case="missing"):
                with self.assertRaises(ContractError):
                    validate_payload(definition, missing)
            with self.subTest(definition=definition, case="extra"):
                with self.assertRaises(ContractError):
                    validate_payload(definition, extra)

    def test_artifact_shape_and_checksum_are_fail_closed(self):
        missing_artifact_field = copy.deepcopy(REPORT_ASSISTANT_REQUEST)
        missing_artifact_field["artifact"].pop("evidence")
        extra_artifact_field = copy.deepcopy(REPORT_ASSISTANT_REQUEST)
        extra_artifact_field["artifact"]["raw_sql"] = "SELECT secret"
        invalid_checksum = copy.deepcopy(REPORT_ASSISTANT_REQUEST)
        invalid_checksum["artifact"]["checksum"] = "not-a-checksum"
        runtime_model_trace = copy.deepcopy(REPORT_ASSISTANT_RESPONSE)
        runtime_model_trace["model"] = {"model_version": "provider-owned"}

        for invalid in (
            missing_artifact_field,
            extra_artifact_field,
            invalid_checksum,
        ):
            with self.subTest(payload=invalid):
                with self.assertRaises(ContractError):
                    validate_payload("report_assistant_request", invalid)
        with self.assertRaises(ContractError):
            validate_payload("report_assistant_response", runtime_model_trace)

    def test_all_provider_responses_reject_server_trace_metadata(self):
        from tests.ai.test_contracts import VALID_PAYLOADS

        for definition in (
            "node1_response",
            "node2_response",
            "node2_repair_response",
            "node3_response",
            "report_assistant_response",
        ):
            payload = copy.deepcopy(
                REPORT_ASSISTANT_RESPONSE
                if definition == "report_assistant_response"
                else VALID_PAYLOADS[definition]
            )
            payload["model"] = {"model_version": "must-stay-in-last-trace"}
            with self.subTest(definition=definition):
                with self.assertRaises(ContractError):
                    validate_payload(definition, payload)


if __name__ == "__main__":
    unittest.main()
