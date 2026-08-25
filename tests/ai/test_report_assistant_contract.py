import copy
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

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
        }],
    },
}

REPORT_ASSISTANT_CLARIFICATION_RESPONSE = {
    "change_kind": "clarification",
    "message": "어느 기간을 기준으로 비교할까요?",
    "analysis_plan": None,
    "patch": None,
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

    def test_turn_serving_schema_keeps_analysis_plan_nullable(self):
        """OpenAI strict 변환 뒤에도 existing_artifact가 null 계획을 반환할 수 있어야 한다."""

        from app.adapters.model_schemas import openai_serving_schema

        plan_schema = openai_serving_schema("report_assistant_turn")["properties"][
            "analysis_plan"
        ]

        self.assertEqual(["object", "null"], plan_schema["type"])

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
