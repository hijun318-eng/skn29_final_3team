import copy
import unittest

from src.ai.prompt_registry import get_prompt
from src.ai.schema import ContractError, schema_version, validate_payload


def model_trace(prompt_id):
    return get_prompt(prompt_id).metadata()


EXECUTION_TIME = {
    "as_of": "2026-07-30T12:00:00+09:00",
    "timezone": "Asia/Seoul",
    "calendar_id": "gregorian-kr",
    "period_start": "2026-07-01T00:00:00+09:00",
    "period_end_exclusive": "2026-07-30T12:00:00+09:00",
}

CONTEXT_PACKAGE = {
    "context_version": "DRAFT-CONTEXT-v0.1",
    "policy_version": "DRAFT-POLICY-v0.1",
    "execution_time": EXECUTION_TIME,
    "assets": [
        {
            "urn": "urn:li:dataset:pms-reservations",
            "trino_fqn": "pms.public.reservations",
            "columns": ["stay_date", "room_revenue"],
        }
    ],
    "metrics": [
        {
            "id": "room_revenue",
            "field": "pms.public.reservations.room_revenue",
            "aggregation": "sum",
            "time_field": "pms.public.reservations.stay_date",
        }
    ],
    "joins": [],
}

SQL_REFERENCES = [
    {
        "urn": "urn:li:dataset:pms-reservations",
        "trino_fqn": "pms.public.reservations",
        "columns": ["stay_date", "room_revenue"],
        "join_ids": [],
        "metric_ids": ["room_revenue"],
    }
]


VALID_PAYLOADS = {
    "node1_request": {
        "question": "이번 달 객실 매출을 보여줘",
        "role_hint": "hotel_analyst",
        "as_of": "2026-07-30T12:00:00+09:00",
        "timezone": "Asia/Seoul",
        "calendar_id": "gregorian-kr",
        "allowed_routes": ["analysis"],
        "business_terms": {
            "room_revenue": {"kind": "metric", "aliases": ["객실 매출"]}
        },
    },
    "node1_response": {
        "normalized_question": "이번 달 객실 매출을 보여줘",
        "intent_candidates": ["aggregate"],
        "metric_candidates": ["room_revenue"],
        "dimension_candidates": [],
        "period_candidates": [
            {
                "start": "2026-07-01T00:00:00+09:00",
                "end_exclusive": "2026-07-30T12:00:00+09:00",
                "source_text": "이번 달",
            }
        ],
        "ambiguity": {
            "is_ambiguous": False,
            "reasons": [],
            "clarification_question": None,
        },
        "model": model_trace("node1.normalize"),
    },
    "node2_request": {"question_id": "q-1", "context_package": CONTEXT_PACKAGE},
    "node2_response": {
        "sql": "SELECT 1 LIMIT 1",
        "references": SQL_REFERENCES,
        "parameters": [],
        "model": model_trace("node2.sql"),
    },
    "node2_repair_request": {
        "trace_id": "trace-1",
        "attempt": 1,
        "rejected_sql": "SELECT bad",
        "context_package": CONTEXT_PACKAGE,
        "normalized_error_code": "UNKNOWN_COLUMN",
        "repair_scope": ["column"],
    },
    "node2_repair_response": {
        "trace_id": "trace-1",
        "attempt": 1,
        "corrected_sql": "SELECT 1 LIMIT 1",
        "references": SQL_REFERENCES,
        "parameters": [],
        "model": model_trace("node2.repair"),
    },
    "node3_request": {
        "g3_result": "pass",
        "shaped_result": {
            "columns": [{"name": "room_revenue", "type": "decimal"}],
            "rows": [{"room_revenue": 1000}],
        },
        "metric": "room_revenue",
        "period": EXECUTION_TIME,
        "filters": [],
        "unit": "KRW",
        "sampling": False,
        "masking": True,
        "partial": False,
        "source_ids": ["pms.public.reservations"],
        "result_reference": {"kind": "query_execution_id", "value": "query-1"},
    },
    "node3_response": {
        "explanation": "fixture",
        "conditions": [],
        "sources": [],
        "limitations": [],
        "model": model_trace("node3.explain"),
    },
}


class ContractTests(unittest.TestCase):
    def test_schema_version_is_explicit(self):
        self.assertEqual(schema_version(), "MODEL-v1.0.0")

    def test_valid_examples(self):
        for definition, payload in VALID_PAYLOADS.items():
            with self.subTest(definition=definition):
                validate_payload(definition, payload)

    def test_node2_accepts_optional_non_empty_normalized_question(self):
        legacy = copy.deepcopy(VALID_PAYLOADS["node2_request"])
        current = copy.deepcopy(legacy)
        current["normalized_question"] = "지난달 객실 매출을 알려줘"
        empty = copy.deepcopy(legacy)
        empty["normalized_question"] = ""

        validate_payload("node2_request", legacy)
        validate_payload("node2_request", current)
        with self.assertRaises(ContractError):
            validate_payload("node2_request", empty)

    def test_missing_and_extra_fields_are_rejected(self):
        for definition, payload in VALID_PAYLOADS.items():
            required_key = next(iter(payload))
            missing = copy.deepcopy(payload)
            missing.pop(required_key)
            extra = copy.deepcopy(payload)
            extra["unexpected"] = True
            with self.subTest(definition=definition, case="missing"):
                with self.assertRaises(ContractError):
                    validate_payload(definition, missing)
            with self.subTest(definition=definition, case="extra"):
                with self.assertRaises(ContractError):
                    validate_payload(definition, extra)

    def test_gate_and_repair_limits_are_schema_enforced(self):
        repair = copy.deepcopy(VALID_PAYLOADS["node2_repair_request"])
        repair["attempt"] = 2
        with self.assertRaises(ContractError):
            validate_payload("node2_repair_request", repair)

        explanation = copy.deepcopy(VALID_PAYLOADS["node3_request"])
        explanation["g3_result"] = "fail"
        with self.assertRaises(ContractError):
            validate_payload("node3_request", explanation)

    def test_nested_missing_and_extra_fields_are_rejected(self):
        missing = copy.deepcopy(VALID_PAYLOADS["node2_request"])
        missing["context_package"]["execution_time"].pop("timezone")
        with self.assertRaises(ContractError):
            validate_payload("node2_request", missing)

        extra = copy.deepcopy(VALID_PAYLOADS["node3_request"])
        extra["shaped_result"]["unexpected"] = True
        with self.assertRaises(ContractError):
            validate_payload("node3_request", extra)

    def test_empty_and_offsetless_boundary_values_are_rejected(self):
        empty = copy.deepcopy(VALID_PAYLOADS["node1_request"])
        empty["question"] = ""
        with self.assertRaises(ContractError):
            validate_payload("node1_request", empty)

        offsetless = copy.deepcopy(VALID_PAYLOADS["node1_request"])
        offsetless["as_of"] = "2026-07-30T12:00:00"
        with self.assertRaises(ContractError):
            validate_payload("node1_request", offsetless)


if __name__ == "__main__":
    unittest.main()
