import copy
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from src.ai.prompt_registry import get_prompt
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

REPORT_ASSISTANT_TURN_REQUEST = {
    **copy.deepcopy(REPORT_ASSISTANT_REQUEST),
    "artifact": {
        "artifact_id": "source_artifact",
        "title": "Approved analysis",
        "narrative": "The approved evidence describes the measured result.",
        "evidence": {"catalog": [{
            "ref": "artifact_narrative",
            "kind": "narrative",
            "label": "Artifact summary",
            "content": "The approved evidence describes the measured result.",
            "value": None,
            "unit": None,
        }]},
        "chart_spec": {
            "chart_type": "bar",
            "x_field": "category_code",
            "y_fields": ["resolved_measure"],
        },
    },
    "current_patch": None,
    "selected_block": None,
    "additional_artifacts": [],
    "history": [],
    "report": {
        "title": "현재 보고서",
        "orientation": "portrait",
        "currency_display_unit": "auto",
        "blocks": [{
            "block_id": "block-one",
            "title": "현재 차트",
            "type": "chart",
            "content": "",
            "artifact_ref": "source_artifact",
            "x": 0,
            "y": 0,
            "w": 12,
            "h": 7,
        }],
    },
}

REPORT_ASSISTANT_TURN_RESPONSE = {
    "change_kind": "new_data",
    "message": "직전 월 비교에는 새 분석 결과가 필요합니다.",
    "analysis_plan": {
        "question": "현재 기간 지표를 직전 월과 비교해 줘",
        "reason": "승인 Artifact에는 직전 월 값이 없습니다.",
        "scope": {
            "period": "현재 기간과 직전 월",
            "metrics": ["현재 보고서의 승인 지표"],
            "dimensions": [],
        },
    },
    "patch": None,
    "suggestions": ["현재 보고서 제목을 더 간결하게 바꿔 줘"],
}

REPORT_ASSISTANT_EXISTING_RESPONSE = {
    "change_kind": "existing_artifact",
    "message": "승인된 근거로 차트를 추가합니다.",
    "analysis_plan": None,
    "patch": {
        "summary": "기존 근거 차트 추가",
        "operations": [{
            "op": "add_artifact_view",
            "block_id": None,
            "artifact_ref": "source_artifact",
            "view": "chart",
            "title": "승인 지표 차트",
            "content": None,
            "after_block_id": "block-one",
            "width": "full",
            "evidence_refs": [],
        }],
    },
    "suggestions": ["선택한 차트 제목을 더 간결하게 바꿔 줘"],
}

REPORT_ASSISTANT_CLARIFICATION_RESPONSE = {
    "change_kind": "clarification",
    "message": "어느 기간을 기준으로 비교할까요?",
    "analysis_plan": None,
    "patch": None,
    "suggestions": [],
}

REPORT_ASSISTANT_REVIEW_RESPONSE = {
    "summary": "보고서 품질 문제 한 건을 찾았습니다.",
    "findings": [{
        "category": "title_mismatch",
        "severity": "warning",
        "block_id": "block-one",
        "title": "차트 제목 확인",
        "detail": "차트 제목이 승인된 지표 표현과 다릅니다.",
        "suggested_instruction": "차트 제목을 승인된 지표 표현에 맞춰 바꿔 줘",
        "evidence_refs": ["artifact_narrative"],
    }],
    "suggestions": ["선택한 차트 제목을 승인 지표에 맞춰 바꿔 줘"],
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

    def test_turn_contract_accepts_only_strict_change_proposal(self):
        """멀티턴 계약은 기존 artifact 입력을 재사용하고 승인·SQL 같은 추가 출력을 거부한다."""

        validate_payload("report_assistant_turn_request", REPORT_ASSISTANT_TURN_REQUEST)
        validate_payload("report_assistant_turn_response", REPORT_ASSISTANT_TURN_RESPONSE)
        validate_payload("report_assistant_turn_response", REPORT_ASSISTANT_EXISTING_RESPONSE)
        validate_payload("report_assistant_turn_response", REPORT_ASSISTANT_CLARIFICATION_RESPONSE)
        invalid = copy.deepcopy(REPORT_ASSISTANT_TURN_RESPONSE)
        invalid["approved"] = True

        with self.assertRaises(ContractError):
            validate_payload("report_assistant_turn_response", invalid)

    def test_review_contract_is_read_only_and_rejects_hidden_outputs(self):
        """품질 검토는 기존 안전 입력을 재사용하고 patch·SQL·원시 응답을 출력하지 못한다."""

        validate_payload("report_assistant_review_request", REPORT_ASSISTANT_TURN_REQUEST)
        validate_payload("report_assistant_review_response", REPORT_ASSISTANT_REVIEW_RESPONSE)
        for field in ("patch", "sql", "raw_model_response"):
            invalid = {**copy.deepcopy(REPORT_ASSISTANT_REVIEW_RESPONSE), field: "hidden"}
            with self.subTest(field=field):
                with self.assertRaises(ContractError):
                    validate_payload("report_assistant_review_response", invalid)

    def test_contextual_suggestions_are_bounded_and_receive_selected_block(self):
        """현재 선택 블록은 typed 입력이며 후속 제안은 고유한 세 문장 이하만 허용한다."""

        request = copy.deepcopy(REPORT_ASSISTANT_TURN_REQUEST)
        request["selected_block"] = {
            "block_id": "block-one", "title": "현재 차트", "type": "chart",
        }
        validate_payload("report_assistant_turn_request", request)

        invalid = copy.deepcopy(REPORT_ASSISTANT_EXISTING_RESPONSE)
        invalid["suggestions"] = ["하나", "둘", "셋", "넷"]
        with self.assertRaises(ContractError):
            validate_payload("report_assistant_turn_response", invalid)

        duplicate = copy.deepcopy(REPORT_ASSISTANT_REVIEW_RESPONSE)
        duplicate["suggestions"] = ["같은 요청", "같은 요청"]
        with self.assertRaises(ContractError):
            validate_payload("report_assistant_review_response", duplicate)

    def test_review_contract_bounds_categories_and_safe_references(self):
        """지원하지 않는 품질 판단과 원시 식별자 형태는 strict schema 단계에서 거부한다."""

        invalid_category = copy.deepcopy(REPORT_ASSISTANT_REVIEW_RESPONSE)
        invalid_category["findings"][0]["category"] = "business_prediction"
        with self.assertRaises(ContractError):
            validate_payload("report_assistant_review_response", invalid_category)

        invalid_reference = copy.deepcopy(REPORT_ASSISTANT_REVIEW_RESPONSE)
        invalid_reference["findings"][0]["evidence_refs"] = ["query:id"]
        with self.assertRaises(ContractError):
            validate_payload("report_assistant_review_response", invalid_reference)

    def test_turn_contract_accepts_bounded_additional_artifact_aliases(self):
        """다중 근거는 서버 별칭과 이름이 겹치지 않는 evidence ref만 strict 계약에 통과한다."""

        request = copy.deepcopy(REPORT_ASSISTANT_TURN_REQUEST)
        secondary = copy.deepcopy(request["artifact"])
        secondary["artifact_id"] = "source_artifact_2"
        secondary["evidence"]["catalog"][0]["ref"] = "artifact_2_artifact_narrative"
        request["additional_artifacts"] = [secondary]
        validate_payload("report_assistant_turn_request", request)

        response = copy.deepcopy(REPORT_ASSISTANT_EXISTING_RESPONSE)
        response["patch"]["operations"][0]["artifact_ref"] = "source_artifact_2"
        validate_payload("report_assistant_turn_response", response)

        request["additional_artifacts"] *= 5
        with self.assertRaises(ContractError):
            validate_payload("report_assistant_turn_request", request)

    def test_text_patch_requires_evidence_refs_but_structural_patch_does_not(self):
        """생성 본문은 근거 별칭을 요구하고 구조 연산은 근거를 가장하지 못하게 빈 배열만 허용한다."""

        text_response = copy.deepcopy(REPORT_ASSISTANT_EXISTING_RESPONSE)
        text_response["patch"]["operations"] = [{
            "op": "add_text",
            "block_id": None,
            "artifact_ref": None,
            "view": None,
            "title": "근거 요약",
            "content": "승인된 근거를 요약합니다.",
            "after_block_id": None,
            "width": "full",
            "evidence_refs": ["artifact_narrative"],
        }]
        validate_payload("report_assistant_turn_response", text_response)

        text_response["patch"]["operations"][0]["evidence_refs"] = []
        with self.assertRaises(ContractError):
            validate_payload("report_assistant_turn_response", text_response)

        structural = copy.deepcopy(REPORT_ASSISTANT_EXISTING_RESPONSE)
        structural["patch"]["operations"][0]["evidence_refs"] = ["artifact_narrative"]
        with self.assertRaises(ContractError):
            validate_payload("report_assistant_turn_response", structural)

    def test_evidence_catalog_hides_lineage_and_rejects_unknown_refs(self):
        """서버 catalog는 실제 lineage를 제외하고 현재 Artifact에 없는 별칭을 patch 적용 전에 거부한다."""

        from app.adapters.report_assistant import report_evidence_catalog, validate_report_patch_evidence
        from app.report_contracts import ReportAssistantPatch

        artifact = {
            "artifact_id": "private-artifact",
            "trino_query_id": "private-query",
            "artifact_checksum": "a" * 64,
            "narrative_markdown": "승인된 요약",
            "evidence_json": {"metric_values": [{
                "label": "매출",
                "definition": "승인 매출",
                "value": 120,
                "unit": "KRW",
            }]},
        }
        catalog = report_evidence_catalog(artifact)
        serialized = repr(catalog)
        self.assertEqual(("artifact_narrative", "metric_1"), tuple(item["ref"] for item in catalog))
        self.assertNotIn("private-artifact", serialized)
        self.assertNotIn("private-query", serialized)
        self.assertNotIn("a" * 64, serialized)

        patch = ReportAssistantPatch.model_validate({
            "summary": "허용되지 않은 근거",
            "operations": [{
                "op": "add_text",
                "title": "요약",
                "content": "본문",
                "evidence_refs": ["metric_2"],
            }],
        })
        with self.assertRaises(ValueError):
            validate_report_patch_evidence(patch, catalog)

    def test_turn_request_accepts_only_typed_current_patch_for_refinement(self):
        """승인 대기 재수정 입력은 현재 strict patch를 받되 누락·원시 식별자를 거부한다."""

        request = copy.deepcopy(REPORT_ASSISTANT_TURN_REQUEST)
        request["current_patch"] = copy.deepcopy(REPORT_ASSISTANT_EXISTING_RESPONSE["patch"])
        validate_payload("report_assistant_turn_request", request)

        missing = copy.deepcopy(request)
        missing.pop("current_patch")
        with self.assertRaises(ContractError):
            validate_payload("report_assistant_turn_request", missing)

        invalid = copy.deepcopy(request)
        invalid["current_patch"]["operations"][0]["artifact_id"] = "raw-artifact"
        with self.assertRaises(ContractError):
            validate_payload("report_assistant_turn_request", invalid)

    def test_turn_plan_requires_nonempty_metric_scope(self):
        """새 데이터 제안은 사용자에게 공개할 하나 이상의 지표 범위를 반드시 포함한다."""

        invalid = copy.deepcopy(REPORT_ASSISTANT_TURN_RESPONSE)
        invalid["analysis_plan"]["scope"]["metrics"] = []

        with self.assertRaises(ContractError):
            validate_payload("report_assistant_turn_response", invalid)

    def test_existing_turn_patch_rejects_raw_identifiers_and_coordinates(self):
        """모델 patch는 서버 별칭과 상대 배치만 사용하고 원시 lineage·좌표를 출력하지 않는다."""

        invalid = copy.deepcopy(REPORT_ASSISTANT_EXISTING_RESPONSE)
        invalid["patch"]["operations"][0]["artifact_id"] = "invented"
        with self.assertRaises(ContractError):
            validate_payload("report_assistant_turn_response", invalid)

        invalid_alias = copy.deepcopy(REPORT_ASSISTANT_EXISTING_RESPONSE)
        invalid_alias["patch"]["operations"][0]["artifact_ref"] = "other_artifact"
        with self.assertRaises(ContractError):
            validate_payload("report_assistant_turn_response", invalid_alias)

    def test_existing_turn_can_reposition_only_a_known_relative_block(self):
        """기존 block 재배치는 상대 기준과 제한 폭만 허용하고 원시 좌표를 계속 거부한다."""

        response = copy.deepcopy(REPORT_ASSISTANT_EXISTING_RESPONSE)
        response["patch"]["operations"] = [{
            "op": "reposition_block",
            "block_id": "block-one",
            "artifact_ref": None,
            "view": None,
            "title": None,
            "content": None,
            "after_block_id": None,
            "width": "half",
            "evidence_refs": [],
        }]
        validate_payload("report_assistant_turn_response", response)

        response["patch"]["operations"][0]["width"] = None
        with self.assertRaises(ContractError):
            validate_payload("report_assistant_turn_response", response)

    def test_existing_turn_supports_remove_duplicate_and_revision_restore(self):
        """삭제·복제는 기존 block만 가리키고 revision 복원은 식별자 없는 단독 의도로 전달한다."""

        base = {
            "artifact_ref": None,
            "view": None,
            "title": None,
            "content": None,
            "after_block_id": None,
            "width": None,
            "evidence_refs": [],
        }
        for operation in (
            {"op": "remove_block", "block_id": "block-one", **base},
            {"op": "duplicate_block", "block_id": "block-one", **base},
            {"op": "restore_previous_revision", "block_id": None, **base},
        ):
            with self.subTest(operation=operation["op"]):
                response = copy.deepcopy(REPORT_ASSISTANT_EXISTING_RESPONSE)
                response["patch"]["operations"] = [operation]
                validate_payload("report_assistant_turn_response", response)

        invalid_restore = copy.deepcopy(REPORT_ASSISTANT_EXISTING_RESPONSE)
        invalid_restore["patch"]["operations"] = [{
            "op": "restore_previous_revision",
            "block_id": "model-owned",
            **base,
        }]
        with self.assertRaises(ContractError):
            validate_payload("report_assistant_turn_response", invalid_restore)

    def test_turn_history_is_bounded_and_clarification_has_no_action(self):
        """최근 대화는 role/content만 허용하고 clarification은 실행 계획과 patch를 갖지 않는다."""

        request = copy.deepcopy(REPORT_ASSISTANT_TURN_REQUEST)
        request["history"] = [
            {"role": "user", "content": "지난달과 비교해 줘"},
            {"role": "assistant", "content": "어느 지표를 비교할까요?"},
        ]
        validate_payload("report_assistant_turn_request", request)

        invalid = copy.deepcopy(REPORT_ASSISTANT_CLARIFICATION_RESPONSE)
        invalid["patch"] = REPORT_ASSISTANT_EXISTING_RESPONSE["patch"]
        with self.assertRaises(ContractError):
            validate_payload("report_assistant_turn_response", invalid)

        too_long = copy.deepcopy(request)
        too_long["history"] *= 7
        with self.assertRaises(ContractError):
            validate_payload("report_assistant_turn_request", too_long)

    def test_turn_prompt_prioritizes_new_intent_and_whole_artifact_operation(self):
        """현재 새 지시와 단일 Artifact 묶음은 과거 clarification·분해 operation보다 우선한다."""

        prompt = get_prompt("report.assistant.turn")
        self.assertEqual("PROMPT-v1.8.5", prompt.version)
        self.assertIn("current instruction is authoritative", prompt.text)
        self.assertIn("ignore any unresolved earlier clarification", prompt.text)
        self.assertIn("exactly one add_artifact_view operation with view artifact", prompt.text)
        self.assertIn("Account for every requested effect", prompt.text)
        self.assertIn("never silently omit the unsupported part", prompt.text)
        self.assertIn("a block is positioned relative to itself", prompt.text)
        self.assertIn("preserve and remove the same report element", prompt.text)
        self.assertIn("do not treat preserve or stay unchanged as a no-op", prompt.text)
        self.assertIn("Evidence refs and their ordering are server-managed", prompt.text)
        self.assertIn("never reinterpret it as block movement", prompt.text)

    def test_turn_serving_schema_keeps_analysis_plan_nullable(self):
        """OpenAI strict 변환 뒤에도 existing_artifact가 null 계획을 반환할 수 있어야 한다."""

        from app.adapters.model_schemas import openai_serving_schema

        plan_schema = openai_serving_schema("report_assistant_turn")["properties"][
            "analysis_plan"
        ]

        self.assertEqual(["object", "null"], plan_schema["type"])

    def test_turn_serving_schema_removes_openai_unsupported_composition(self):
        """Pydantic 조건식의 allOf가 OpenAI strict response_format에 남지 않아야 한다."""

        from app.adapters.model_schemas import openai_serving_schema

        def contains_all_of(value):
            if isinstance(value, dict):
                return "allOf" in value or any(contains_all_of(item) for item in value.values())
            if isinstance(value, list):
                return any(contains_all_of(item) for item in value)
            return False

        self.assertFalse(contains_all_of(openai_serving_schema("report_assistant_turn")))

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
            "report_assistant_turn_response",
        ):
            payload = copy.deepcopy(
                REPORT_ASSISTANT_RESPONSE if definition == "report_assistant_response"
                else REPORT_ASSISTANT_TURN_RESPONSE if definition == "report_assistant_turn_response"
                else VALID_PAYLOADS[definition]
            )
            payload["model"] = {"model_version": "must-stay-in-last-trace"}
            with self.subTest(definition=definition):
                with self.assertRaises(ContractError):
                    validate_payload(definition, payload)

class ReportAssistantRepositionAdapterTests(unittest.IsolatedAsyncioTestCase):
    """strict wire 연산이 서버 ReportPatch 타입으로 손실 없이 변환되는지 검증한다."""

    async def test_reposition_wire_operation_becomes_typed_patch(self):
        """nullable wire 필드를 제거하고 상대 배치 필드만 typed patch에 보존한다."""

        from app.adapters.report_assistant import generate_report_change_proposal

        response = copy.deepcopy(REPORT_ASSISTANT_EXISTING_RESPONSE)
        response["patch"]["operations"] = [{
            "op": "reposition_block",
            "block_id": "block-one",
            "artifact_ref": None,
            "view": None,
            "title": None,
            "content": None,
            "after_block_id": None,
            "width": "half",
            "evidence_refs": [],
        }]
        route = SimpleNamespace(
            endpoint="https://model.invalid/v1",
            token="test-token",
            model="test-model",
            provider="openai",
        )
        with (
            patch(
                "app.adapters.report_assistant.resolve_active_model_routes",
                return_value=object(),
            ),
            patch(
                "app.adapters.report_assistant.active_route_for_node",
                return_value=route,
            ),
            patch(
                "app.adapters.report_assistant.openai_transport",
                new=AsyncMock(return_value=response),
            ),
        ):
            proposal, _trace = await generate_report_change_proposal(
                copy.deepcopy(REPORT_ASSISTANT_TURN_REQUEST)
            )

        self.assertEqual(
            {
                "op": "reposition_block",
                "block_id": "block-one",
                "after_block_id": None,
                "width": "half",
            },
            proposal["patch"]["operations"][0],
        )


if __name__ == "__main__":
    unittest.main()
