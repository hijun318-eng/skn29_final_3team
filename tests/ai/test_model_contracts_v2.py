import copy
import unittest
from pathlib import Path

from src.ai.model_contracts import (
    canonical_json,
    model_contract_manifest,
    model_release_manifest,
    validate_node1_exchange,
    validate_node3_exchange,
    v2_response_schema,
)
from src.ai.prompt_registry import get_prompt
from src.ai.schema import ContractError, schema_version, validate_payload


NODE1_REQUEST = {
    "question": "지난달 객실 매출 보여줘",
    "allowed_intents": ["aggregate", "compare", "trend", "rank"],
    "business_terms": [
        {
            "id": "example.room_revenue",
            "kind": "metric",
            "display_name": "객실 매출",
            "definition": "객실 판매로 인식된 매출",
            "aliases": ["객실 매출", "방 매출"],
            "values": [],
        }
    ],
}

NODE1_RESPONSE = {
    "intent_candidates": ["aggregate"],
    "selected_intent": "aggregate",
    "metric_candidates": [
        {
            "id": "example.room_revenue",
            "matched_text": "객실 매출",
            "span": {"start_scalar": 4, "end_scalar": 9},
        }
    ],
    "selected_metric_id": "example.room_revenue",
    "dimension_candidates": [],
    "filter_candidates": [],
    "period_mentions": [
        {
            "role": "primary",
            "source_text": "지난달",
            "span": {"start_scalar": 0, "end_scalar": 3},
        }
    ],
    "missing_requirements": [],
    "ambiguity_codes": [],
}

NODE3_REQUEST = {
    "locale": "ko-KR",
    "metric": {"label": "객실 매출", "unit": "원"},
    "facts": [
        {
            "id": "fact-1",
            "type": "observation",
            "subject_text": "객실 매출",
            "period_text": "지난달",
            "value_text": "1,234,000원",
            "comparison_text": None,
            "required_in_summary": True,
        }
    ],
    "limitations": [],
}

NODE3_RESPONSE = {
    "sentences": [
        {
            "text": "지난달 객실 매출은 1,234,000원입니다.",
            "fact_ids": ["fact-1"],
            "limitation_codes": [],
        }
    ]
}


class ModelContractV2Tests(unittest.TestCase):
    def test_schema_and_manifest_are_versioned_and_deterministic(self):
        self.assertEqual("MODEL-v2.0.0", schema_version("v2"))
        self.assertFalse(v2_response_schema("node1")["additionalProperties"])
        first = model_contract_manifest("node1")
        second = model_contract_manifest("node1")
        self.assertEqual(first, second)
        self.assertEqual("answervice.node1.interpretation.v2", first["schema_id"])
        self.assertEqual(64, len(first["schema_sha256"]))
        self.assertEqual(64, len(first["prompt_sha256"]))

    def test_v2_is_candidate_only_with_explicit_v1_rollback(self):
        manifest = model_release_manifest()

        self.assertEqual("CANDIDATE", manifest["state"])
        self.assertFalse(manifest["automatic_cutover"])
        self.assertEqual("v1", manifest["active"]["node1"]["schema_contract"])
        self.assertEqual("node1.normalize", manifest["rollback"]["node1_prompt_id"])
        self.assertEqual("node3.explain", manifest["rollback"]["node3_prompt_id"])
        self.assertEqual({"NOT_RUN"}, set(manifest["cutover_gates"].values()))

    def test_runtime_prompt_assets_exactly_match_the_authoritative_document(self):
        document = (
            Path(__file__).resolve().parents[2]
            / "docs/e2e_mvp/derived/07_Node1_Node3_목표_런타임_프롬프트.txt"
        ).read_text(encoding="utf-8")
        pairs = (
            (
                "node1.interpretation.v2",
                "---------------- NODE1_RUNTIME_PROMPT_START ----------------",
                "----------------- NODE1_RUNTIME_PROMPT_END -----------------",
            ),
            (
                "node3.narrative.v2",
                "---------------- NODE3_RUNTIME_PROMPT_START ----------------",
                "----------------- NODE3_RUNTIME_PROMPT_END -----------------",
            ),
        )
        for prompt_id, start, end in pairs:
            with self.subTest(prompt_id=prompt_id):
                expected = document.split(start, 1)[1].split(end, 1)[0].strip("\r\n")
                self.assertEqual(expected, get_prompt(prompt_id).text)

    def test_canonical_json_is_stable_and_rejects_non_json_numbers(self):
        self.assertEqual('{"a":1,"한글":"값"}', canonical_json({"한글": "값", "a": 1}))
        with self.assertRaises(ValueError):
            canonical_json({"value": float("nan")})

    def test_node1_valid_exchange_and_exact_unicode_scalar_spans(self):
        validate_node1_exchange(NODE1_REQUEST, NODE1_RESPONSE)

        invalid = copy.deepcopy(NODE1_RESPONSE)
        invalid["metric_candidates"][0]["span"]["start_scalar"] = 3
        with self.assertRaisesRegex(ContractError, "span"):
            validate_node1_exchange(NODE1_REQUEST, invalid)

    def test_node1_rejects_unapproved_ids_status_and_inconsistent_selection(self):
        outside = copy.deepcopy(NODE1_RESPONSE)
        outside["metric_candidates"][0]["id"] = "outside.metric"
        outside["selected_metric_id"] = "outside.metric"
        with self.assertRaisesRegex(ContractError, "outside approved"):
            validate_node1_exchange(NODE1_REQUEST, outside)

        status = {**NODE1_RESPONSE, "status": "RESOLVED"}
        with self.assertRaisesRegex(ContractError, "unexpected fields"):
            validate_node1_exchange(NODE1_REQUEST, status)

        ambiguous = copy.deepcopy(NODE1_RESPONSE)
        ambiguous["ambiguity_codes"] = ["METRIC_AMBIGUOUS"]
        with self.assertRaisesRegex(ContractError, "must be null"):
            validate_node1_exchange(NODE1_REQUEST, ambiguous)

        competing_intents = copy.deepcopy(NODE1_RESPONSE)
        competing_intents["intent_candidates"] = ["aggregate", "trend"]
        with self.assertRaisesRegex(ContractError, "exactly one intent"):
            validate_node1_exchange(NODE1_REQUEST, competing_intents)

        competing_metrics = copy.deepcopy(NODE1_RESPONSE)
        competing_metrics["metric_candidates"].append(
            {
                "id": "example.other_metric",
                "matched_text": "객실 매출",
                "span": {"start_scalar": 4, "end_scalar": 9},
            }
        )
        competing_request = copy.deepcopy(NODE1_REQUEST)
        competing_request["business_terms"].append(
            {
                "id": "example.other_metric",
                "kind": "metric",
                "display_name": "다른 지표",
                "definition": "합성 테스트 지표",
                "aliases": ["객실 매출"],
                "values": [],
            }
        )
        with self.assertRaisesRegex(ContractError, "exactly one metric"):
            validate_node1_exchange(competing_request, competing_metrics)

    def test_node1_rejects_duplicate_or_mixed_period_roles(self):
        duplicate = copy.deepcopy(NODE1_RESPONSE)
        duplicate["period_mentions"].append(
            {
                "role": "primary",
                "source_text": "객실",
                "span": {"start_scalar": 4, "end_scalar": 6},
            }
        )
        with self.assertRaisesRegex(ContractError, "roles must be unique"):
            validate_node1_exchange(NODE1_REQUEST, duplicate)

        mixed = copy.deepcopy(NODE1_RESPONSE)
        mixed["intent_candidates"] = ["compare"]
        mixed["selected_intent"] = "compare"
        mixed["period_mentions"].append(
            {
                "role": "comparison",
                "source_text": "객실",
                "span": {"start_scalar": 4, "end_scalar": 6},
            }
        )
        mixed["missing_requirements"] = ["BASELINE_PERIOD"]
        with self.assertRaisesRegex(ContractError, "roles are mixed"):
            validate_node1_exchange(NODE1_REQUEST, mixed)

    def test_node1_schema_enforces_kind_and_collection_limits(self):
        dimension_value_on_metric = copy.deepcopy(NODE1_REQUEST)
        dimension_value_on_metric["business_terms"][0]["values"] = [
            {"id": "gold", "display_name": "골드", "aliases": []}
        ]
        with self.assertRaises(ContractError):
            validate_payload("node1_request", dimension_value_on_metric, contract="v2")

        too_many = copy.deepcopy(NODE1_RESPONSE)
        too_many["period_mentions"] *= 4
        with self.assertRaisesRegex(ContractError, "at most"):
            validate_payload("node1_response", too_many, contract="v2")

    def test_node3_valid_exchange_uses_one_sentence_per_required_source(self):
        validate_node3_exchange(NODE3_REQUEST, NODE3_RESPONSE)

    def test_node3_blocks_cross_fact_value_swap_and_optional_output(self):
        request = copy.deepcopy(NODE3_REQUEST)
        request["facts"].append(
            {
                "id": "fact-2",
                "type": "observation",
                "subject_text": "객실 판매량",
                "period_text": "지난달",
                "value_text": "20실",
                "comparison_text": None,
                "required_in_summary": False,
            }
        )
        swapped = copy.deepcopy(NODE3_RESPONSE)
        swapped["sentences"][0]["text"] = "지난달 객실 매출은 20실입니다."
        with self.assertRaisesRegex(ContractError, "not preserved|outside"):
            validate_node3_exchange(request, swapped)

        optional = copy.deepcopy(NODE3_RESPONSE)
        optional["sentences"].append(
            {
                "text": "지난달 객실 판매량은 20실입니다.",
                "fact_ids": ["fact-2"],
                "limitation_codes": [],
            }
        )
        with self.assertRaisesRegex(ContractError, "required sources"):
            validate_node3_exchange(request, optional)

    def test_node3_rejects_empty_as_zero_and_non_exact_limitation(self):
        empty = copy.deepcopy(NODE3_REQUEST)
        empty["facts"][0].update(type="empty_result", value_text=None)
        zero = {
            "sentences": [
                {
                    "text": "지난달 객실 매출은 0건입니다.",
                    "fact_ids": ["fact-1"],
                    "limitation_codes": [],
                }
            ]
        }
        with self.assertRaises(ContractError):
            validate_node3_exchange(empty, zero)

        limited = copy.deepcopy(NODE3_REQUEST)
        limited["facts"][0]["required_in_summary"] = False
        limited["limitations"] = [
            {"code": "PARTIAL", "public_text": "일부 결과만 포함했습니다.", "required_in_summary": True}
        ]
        paraphrased = {
            "sentences": [
                {"text": "결과 일부만 포함했습니다.", "fact_ids": [], "limitation_codes": ["PARTIAL"]}
            ]
        }
        with self.assertRaisesRegex(ContractError, "must be exact"):
            validate_node3_exchange(limited, paraphrased)


if __name__ == "__main__":
    unittest.main()
