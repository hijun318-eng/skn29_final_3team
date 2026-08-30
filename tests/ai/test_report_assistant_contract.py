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

REPORT_ASSISTANT_WIRE_OPERATION = {
    "op": None,
    "block_id": None,
    "artifact_ref": None,
    "view": None,
    "title": None,
    "content": None,
    "orientation": None,
    "currency_display_unit": None,
    "after_block_id": None,
    "width": None,
    "block_width": None,
    "block_height": None,
    "chart_type": None,
    "show_legend": None,
    "density": None,
    "show_row_numbers": None,
    "size_mode": None,
    "evidence_refs": [],
}

REPORT_ASSISTANT_EXISTING_RESPONSE = {
    "change_kind": "existing_artifact",
    "message": "승인된 근거로 차트를 추가합니다.",
    "analysis_plan": None,
    "patch": {
        "summary": "기존 근거 차트 추가",
        "operations": [{
            **REPORT_ASSISTANT_WIRE_OPERATION,
            "op": "add_artifact_view",
            "artifact_ref": "source_artifact",
            "view": "chart",
            "title": "승인 지표 차트",
            "after_block_id": "block-one",
            "width": "full",
        }],
    },
    "suggestions": ["승인 지표를 설명하는 텍스트 블록을 추가해 줘"],
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
        "suggested_instruction": "보고서 요약을 승인된 지표 표현에 맞춰 바꿔 줘",
        "evidence_refs": ["artifact_narrative"],
    }],
    "suggestions": ["보고서 요약을 승인 지표에 맞춰 바꿔 줘"],
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
            **REPORT_ASSISTANT_WIRE_OPERATION,
            "op": "add_text",
            "title": "근거 요약",
            "content": "승인된 근거를 요약합니다.",
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
            **REPORT_ASSISTANT_WIRE_OPERATION,
            "op": "reposition_block",
            "block_id": "block-one",
            "width": "half",
        }]
        validate_payload("report_assistant_turn_response", response)

        response["patch"]["operations"][0]["width"] = None
        with self.assertRaises(ContractError):
            validate_payload("report_assistant_turn_response", response)

    def test_existing_turn_supports_remove_duplicate_and_revision_restore(self):
        """삭제·복제는 기존 block만 가리키고 revision 복원은 식별자 없는 단독 의도로 전달한다."""

        base = {**REPORT_ASSISTANT_WIRE_OPERATION}
        for operation in (
            {**base, "op": "remove_block", "block_id": "block-one"},
            {**base, "op": "duplicate_block", "block_id": "block-one"},
            {**base, "op": "restore_previous_revision", "block_id": None},
        ):
            with self.subTest(operation=operation["op"]):
                response = copy.deepcopy(REPORT_ASSISTANT_EXISTING_RESPONSE)
                response["patch"]["operations"] = [operation]
                validate_payload("report_assistant_turn_response", response)

        invalid_restore = copy.deepcopy(REPORT_ASSISTANT_EXISTING_RESPONSE)
        invalid_restore["patch"]["operations"] = [{
            **base,
            "op": "restore_previous_revision",
            "block_id": "model-owned",
        }]
        with self.assertRaises(ContractError):
            validate_payload("report_assistant_turn_response", invalid_restore)

    def test_existing_turn_supports_report_orientation_change(self):
        """가로·세로 변경은 block 식별자 없이 문서 전체 방향만 전달한다."""

        response = copy.deepcopy(REPORT_ASSISTANT_EXISTING_RESPONSE)
        response["patch"]["operations"] = [{
            **REPORT_ASSISTANT_WIRE_OPERATION,
            "op": "set_report_orientation",
            "orientation": "landscape",
        }]
        validate_payload("report_assistant_turn_response", response)

        response["patch"]["operations"][0]["orientation"] = None
        with self.assertRaises(ContractError):
            validate_payload("report_assistant_turn_response", response)

    def test_existing_turn_supports_one_blank_page_addition(self):
        """빈 페이지 추가는 모델 식별자나 filler block 없이 단일 구조 operation으로 전달한다."""

        response = copy.deepcopy(REPORT_ASSISTANT_EXISTING_RESPONSE)
        response["patch"]["operations"] = [{
            **REPORT_ASSISTANT_WIRE_OPERATION,
            "op": "add_report_page",
        }]
        validate_payload("report_assistant_turn_response", response)

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
        self.assertEqual("PROMPT-v1.9.7", prompt.version)
        self.assertIn("requests no other effect, return clarification with patch null", prompt.text)
        self.assertIn("current instruction is authoritative", prompt.text)
        self.assertIn("ignore any unresolved earlier clarification", prompt.text)
        self.assertIn("exactly one add_artifact_view operation with view artifact", prompt.text)
        self.assertIn("Use set_report_orientation with portrait or landscape", prompt.text)
        self.assertIn("return exactly one operation total: add_report_page", prompt.text)
        self.assertIn("Account for every requested effect", prompt.text)
        self.assertIn("never silently omit the unsupported part", prompt.text)
        self.assertIn("a block is positioned relative to itself", prompt.text)
        self.assertIn("preserve and remove the same report element", prompt.text)
        self.assertIn("do not treat preserve or stay unchanged as a no-op", prompt.text)
        self.assertIn("Evidence refs and their ordering are server-managed", prompt.text)
        self.assertIn("never reinterpret it as block movement", prompt.text)
        self.assertIn("Use update_block_title for any existing text, chart, table, or Artifact block title", prompt.text)
        self.assertIn("Use update_chart_settings only for chart blocks", prompt.text)
        self.assertIn("Every add_text must include a non-empty title", prompt.text)
        self.assertIn("duplicate_block is an exact copy", prompt.text)
        self.assertIn("do not ask whether those values should remain the same", prompt.text)
        self.assertIn("require only duplicate_block", prompt.text)
        self.assertIn("Never add reposition_block for the source", prompt.text)

    def test_turn_contract_supports_persisted_editor_settings(self):
        """문서·블록·차트·표 설정은 임의 JSON 없이 strict typed operation으로 표현한다."""

        operations = (
            {"op": "set_currency_display_unit", "currency_display_unit": "million"},
            {"op": "compact_report_layout"},
            {"op": "update_block_title", "block_id": "block-one", "title": "월간 매출 추이"},
            {"op": "resize_block", "block_id": "block-one", "block_width": 12, "block_height": 9},
            {
                "op": "update_chart_settings", "block_id": "block-one",
                "chart_type": "horizontal-bar", "show_legend": False, "size_mode": "auto",
            },
            {"op": "set_block_size_mode", "block_id": "block-one", "size_mode": "manual"},
        )
        for values in operations:
            with self.subTest(operation=values["op"]):
                response = copy.deepcopy(REPORT_ASSISTANT_EXISTING_RESPONSE)
                response["patch"]["operations"] = [{**REPORT_ASSISTANT_WIRE_OPERATION, **values}]
                validate_payload("report_assistant_turn_response", response)

        invalid = copy.deepcopy(REPORT_ASSISTANT_EXISTING_RESPONSE)
        invalid["patch"]["operations"] = [{
            **REPORT_ASSISTANT_WIRE_OPERATION,
            "op": "update_chart_settings",
            "block_id": "block-one",
            "chart_type": "radar",
        }]
        with self.assertRaises(ContractError):
            validate_payload("report_assistant_turn_response", invalid)

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
            **REPORT_ASSISTANT_WIRE_OPERATION,
            "op": "reposition_block",
            "block_id": "block-one",
            "width": "half",
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

    async def test_non_text_update_becomes_evidence_bound_text_addition(self):
        """비-text 본문은 변조하지 않고 승인 대기 add_text로 정규화한다."""

        from app.adapters.report_assistant import generate_report_change_proposal

        response = copy.deepcopy(REPORT_ASSISTANT_EXISTING_RESPONSE)
        response["patch"]["operations"] = [{
            **REPORT_ASSISTANT_WIRE_OPERATION,
            "op": "update_text",
            "block_id": "block-one",
            "artifact_ref": None,
            "view": None,
            "title": None,
            "content": "승인된 근거를 세 문장으로 요약했습니다.",
            "after_block_id": None,
            "width": None,
            "evidence_refs": ["artifact_narrative"],
        }]
        route = SimpleNamespace(
            endpoint="https://model.invalid/v1",
            token="test-token",
            model="test-model",
            provider="openai",
        )
        transport = AsyncMock(return_value=response)
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
                new=transport,
            ),
        ):
            proposal, _trace = await generate_report_change_proposal(
                copy.deepcopy(REPORT_ASSISTANT_TURN_REQUEST)
            )

        self.assertEqual(
            {
                "op": "add_text",
                "title": "핵심 요약",
                "content": "승인된 근거를 세 문장으로 요약했습니다.",
                "evidence_refs": ["artifact_narrative"],
                "placement": {"after_block_id": "block-one", "width": "full"},
            },
            proposal["patch"]["operations"][0],
        )
        self.assertEqual(1, transport.await_count)
        self.assertEqual(1, _trace["attempts"])

    async def test_non_text_title_only_update_becomes_block_title_update(self):
        """비-text 제목 변경은 본문 연산 대신 공통 block 제목 연산으로 정규화한다."""

        from app.adapters.report_assistant import generate_report_change_proposal

        response = copy.deepcopy(REPORT_ASSISTANT_EXISTING_RESPONSE)
        response["patch"]["operations"] = [{
            **REPORT_ASSISTANT_WIRE_OPERATION,
            "op": "update_text",
            "block_id": "block-one",
            "title": "월간 매출 차트",
            "content": None,
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
                "op": "update_block_title",
                "block_id": "block-one",
                "title": "월간 매출 차트",
            },
            proposal["patch"]["operations"][0],
        )

    async def test_existing_text_block_update_is_preserved(self):
        """실제 text block에 대한 수정은 기존 update_text 의미를 유지한다."""

        from app.adapters.report_assistant import generate_report_change_proposal

        request = copy.deepcopy(REPORT_ASSISTANT_TURN_REQUEST)
        request["report"]["blocks"][0]["type"] = "text"
        request["report"]["blocks"][0]["artifact_ref"] = None
        response = copy.deepcopy(REPORT_ASSISTANT_EXISTING_RESPONSE)
        response["patch"]["operations"] = [{
            **REPORT_ASSISTANT_WIRE_OPERATION,
            "op": "update_text",
            "block_id": "block-one",
            "artifact_ref": None,
            "view": None,
            "title": None,
            "content": "기존 텍스트를 간결하게 수정했습니다.",
            "after_block_id": None,
            "width": None,
            "evidence_refs": ["artifact_narrative"],
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
            proposal, _trace = await generate_report_change_proposal(request)

        self.assertEqual(
            {
                "op": "update_text",
                "block_id": "block-one",
                "title": None,
                "content": "기존 텍스트를 간결하게 수정했습니다.",
                "evidence_refs": ["artifact_narrative"],
            },
            proposal["patch"]["operations"][0],
        )

    async def test_add_text_drops_unused_wire_union_fields(self):
        """serving schema가 채운 타 operation 필드는 typed add_text 경계에서 제거한다."""

        from app.adapters.report_assistant import generate_report_change_proposal

        response = copy.deepcopy(REPORT_ASSISTANT_EXISTING_RESPONSE)
        response["patch"]["operations"] = [{
            **REPORT_ASSISTANT_WIRE_OPERATION,
            "op": "add_text",
            "block_id": "block-one",
            "artifact_ref": "source_artifact",
            "view": "artifact",
            "title": "핵심 요약",
            "content": "승인된 근거를 간결하게 요약했습니다.",
            "after_block_id": "block-one",
            "width": "full",
            "evidence_refs": ["artifact_narrative"],
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
                "op": "add_text",
                "title": "핵심 요약",
                "content": "승인된 근거를 간결하게 요약했습니다.",
                "placement": {"after_block_id": "block-one", "width": "full"},
                "evidence_refs": ["artifact_narrative"],
            },
            proposal["patch"]["operations"][0],
        )

    async def test_add_text_with_content_but_no_title_gets_safe_default(self):
        """모델이 add_text 제목만 누락해도 본문·근거는 보존하고 승인 대기로 보낸다."""

        from app.adapters.report_assistant import generate_report_change_proposal

        response = copy.deepcopy(REPORT_ASSISTANT_EXISTING_RESPONSE)
        response["patch"]["operations"] = [{
            **REPORT_ASSISTANT_WIRE_OPERATION,
            "op": "add_text",
            "title": None,
            "content": "승인된 근거를 두 문장으로 요약했습니다.",
            "after_block_id": "block-one",
            "width": "full",
            "evidence_refs": ["artifact_narrative"],
        }]
        route = SimpleNamespace(
            endpoint="https://model.invalid/v1",
            token="test-token",
            model="test-model",
            provider="openai",
        )
        transport = AsyncMock(return_value=response)
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
                new=transport,
            ),
        ):
            proposal, trace = await generate_report_change_proposal(
                copy.deepcopy(REPORT_ASSISTANT_TURN_REQUEST)
            )

        self.assertEqual(
            {
                "op": "add_text",
                "title": "핵심 요약",
                "content": "승인된 근거를 두 문장으로 요약했습니다.",
                "placement": {"after_block_id": "block-one", "width": "full"},
                "evidence_refs": ["artifact_narrative"],
            },
            proposal["patch"]["operations"][0],
        )
        self.assertEqual(1, transport.await_count)
        self.assertEqual(1, trace["attempts"])

    async def test_english_patch_summary_gets_operation_based_korean_label(self):
        """모델이 영문 변경 요약을 반환해도 사용자 검토 화면에는 한국어를 보낸다."""

        from app.adapters.report_assistant import generate_report_change_proposal

        response = copy.deepcopy(REPORT_ASSISTANT_EXISTING_RESPONSE)
        response["patch"]["summary"] = (
            "Add a concise three-sentence summary below the selected artifact block."
        )
        response["patch"]["operations"] = [{
            **REPORT_ASSISTANT_WIRE_OPERATION,
            "op": "add_text",
            "title": "핵심 요약",
            "content": "승인된 근거를 세 문장으로 요약했습니다.",
            "after_block_id": "block-one",
            "width": "full",
            "evidence_refs": ["artifact_narrative"],
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

        self.assertEqual("텍스트 블록 추가", proposal["patch"]["summary"])

    async def test_editor_setting_wire_operation_becomes_typed_patch(self):
        """GPT의 strict 차트 설정은 임의 settings 객체 없이 typed 서버 patch로 변환된다."""

        from app.adapters.report_assistant import generate_report_change_proposal

        response = copy.deepcopy(REPORT_ASSISTANT_EXISTING_RESPONSE)
        response["patch"]["operations"] = [{
            **REPORT_ASSISTANT_WIRE_OPERATION,
            "op": "update_chart_settings",
            "block_id": "block-one",
            "title": "operation과 무관한 wire 값",
            "chart_type": "horizontal-bar",
            "show_legend": False,
            "size_mode": "auto",
        }]
        route = SimpleNamespace(
            endpoint="https://model.invalid/v1", token="test-token",
            model="test-model", provider="openai",
        )
        with (
            patch("app.adapters.report_assistant.resolve_active_model_routes", return_value=object()),
            patch("app.adapters.report_assistant.active_route_for_node", return_value=route),
            patch("app.adapters.report_assistant.openai_transport", new=AsyncMock(return_value=response)),
        ):
            proposal, _trace = await generate_report_change_proposal(
                copy.deepcopy(REPORT_ASSISTANT_TURN_REQUEST)
            )

        self.assertEqual(
            {
                "op": "update_chart_settings", "block_id": "block-one",
                "chart_type": "horizontal-bar", "show_legend": False,
                "size_mode": "auto",
            },
            proposal["patch"]["operations"][0],
        )

    async def test_table_view_drops_irrelevant_chart_wire_fields(self):
        """표 추가 응답의 chart용 nullable 오염값은 table typed patch에 전달하지 않는다."""

        from app.adapters.report_assistant import generate_report_change_proposal

        response = copy.deepcopy(REPORT_ASSISTANT_EXISTING_RESPONSE)
        response["patch"]["operations"] = [{
            **REPORT_ASSISTANT_WIRE_OPERATION,
            "op": "add_artifact_view", "artifact_ref": "source_artifact",
            "view": "table", "title": "승인 매출 표", "chart_type": "bar",
            "density": "compact", "show_row_numbers": True, "size_mode": "auto",
        }]
        route = SimpleNamespace(
            endpoint="https://model.invalid/v1", token="test-token",
            model="test-model", provider="openai",
        )
        with (
            patch("app.adapters.report_assistant.resolve_active_model_routes", return_value=object()),
            patch("app.adapters.report_assistant.active_route_for_node", return_value=route),
            patch("app.adapters.report_assistant.openai_transport", new=AsyncMock(return_value=response)),
        ):
            proposal, _trace = await generate_report_change_proposal(
                copy.deepcopy(REPORT_ASSISTANT_TURN_REQUEST)
            )

        operation = proposal["patch"]["operations"][0]
        self.assertEqual("table", operation["view"])
        self.assertEqual("compact", operation["density"])
        self.assertTrue(operation["show_row_numbers"])
        self.assertIsNone(operation["chart_type"])


if __name__ == "__main__":
    unittest.main()
