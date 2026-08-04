import json
from datetime import date
from pathlib import Path
from sys import path
from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest


BACKEND = Path(__file__).resolve().parents[2] / "app" / "backend"
path.insert(0, str(BACKEND))

from app.adapters.i2_data_platform import I2DataPlatformAdapter
from app.contracts import AnalysisRequest, RequestContext
from app.services.context_builder import ContextPackageBuilder
from app.services.pipeline_support import PipelineSupport


def live_dataset(adapter, urn):
    asset = next(item for item in adapter._assets if item["urn"] == urn)
    return {
        "urn": urn,
        "name": asset["name"],
        "schemaMetadata": {
            "name": asset["fqn"],
            "fields": [
                {"fieldPath": column, "nativeDataType": "contract"}
                for column in asset["columns"]
            ],
        },
    }


def test_trino_transport_sends_required_user_header():
    response = MagicMock()
    response.read.return_value = json.dumps(
        {"id": "query-1", "stats": {"state": "FINISHED"}}
    ).encode()
    response.__enter__.return_value = response
    adapter = I2DataPlatformAdapter("http://trino:8080", "runtime-user")

    with patch("app.adapters.i2_data_platform.urlopen", return_value=response) as call:
        payload = adapter._request(
            "POST",
            "http://trino:8080/v1/statement",
            "SELECT 1",
        )

    request = call.call_args.args[0]
    assert request.get_header("X-trino-user") == "runtime-user"
    assert request.data == b"SELECT 1"
    assert payload["id"] == "query-1"


def test_finished_query_with_warnings_is_preserved_as_partial():
    adapter = I2DataPlatformAdapter("http://trino:8080", "runtime-user")
    adapter._trino.transport = lambda _method, _url, _body: {
        "id": "query-partial",
        "stats": {"state": "FINISHED"},
        "columns": [{"name": "synthetic_value"}],
        "data": [[1]],
        "warnings": [{"message": "one source returned partial data"}],
    }

    result = adapter.execute_query(
        "SELECT 1 AS synthetic_value LIMIT 1",
        {},
        "g2-token",
    )

    assert result["query_id"] == "query-partial"
    assert result["status"] == "PARTIAL"
    assert result["rows"] == [{"synthetic_value": 1}]


def test_live_datahub_serving_view_passes_context_and_g2_contract():
    adapter = I2DataPlatformAdapter("http://trino:8080", "runtime-user")
    adapter._datahub_dataset = lambda urn: live_dataset(adapter, urn)
    support = PipelineSupport(adapter, ContextPackageBuilder())
    payload = AnalysisRequest(
        question="호텔 객실 점유와 매출을 분석해 줘",
    )
    context = RequestContext(
        user_id=UUID("00000000-0000-0000-0000-000000000001"),
        as_of=date(2026, 7, 30),
    )
    assets = adapter.search_assets(payload.question, context.model_dump(mode="json"))
    package = support.build_context(payload, context, assets)
    sql = (
        "SELECT property_id, SUM(room_revenue) AS revenue "
        "FROM serving.analytics.hotel_daily_metrics "
        "GROUP BY property_id LIMIT 1000"
    )
    plan = {
        "sql": sql,
        "parameters": {},
        "references": [
            {"urn": item.urn, "fqn": item.fqn, "columns": list(item.columns)}
            for item in package.assets
        ],
        "model_version": "TEMPLATE-I2-v1.0.0",
    }

    assert support.g2_violation(plan, package) is None
    assert package.dataset_count == 1
    assert package.column_count <= 60
    assert package.assets[0].fqn == "serving.analytics.hotel_daily_metrics"


def test_crm_question_uses_only_approved_raw_asset():
    adapter = I2DataPlatformAdapter("http://trino:8080", "runtime-user")
    adapter._datahub_dataset = lambda urn: live_dataset(adapter, urn)

    assets = adapter.search_assets(
        "현재 등급별 활성 회원 수를 알려줘",
        {"role": "hotel_analyst"},
    )

    assert [asset["fqn"] for asset in assets] == ["crm.dbo.crm_members"]


def test_raw_live_extra_columns_are_not_exposed():
    adapter = I2DataPlatformAdapter("http://trino:8080", "runtime-user")

    def raw_live_dataset(urn):
        payload = live_dataset(adapter, urn)
        asset = next(item for item in adapter._assets if item["urn"] == urn)
        payload["schemaMetadata"]["name"] = "crm_db." + ".".join(asset["fqn"].split(".")[1:])
        payload["schemaMetadata"]["fields"].append(
            {"fieldPath": "source_updated_at", "nativeDataType": "timestamp"}
        )
        return payload

    adapter._datahub_dataset = raw_live_dataset
    assets = adapter.search_assets("crm active members", {"role": "hotel_analyst"})
    schema = adapter.get_asset_schema(assets[0]["urn"])

    assert "source_updated_at" not in {column["name"] for column in schema["columns"]}


def test_pms_crm_question_uses_exact_approved_join_assets():
    adapter = I2DataPlatformAdapter("http://trino:8080", "runtime-user")
    adapter._datahub_dataset = lambda urn: live_dataset(adapter, urn)

    assets = adapter.search_assets(
        "투숙 완료 객실 매출을 회원 등급별로 알려줘",
        {"role": "hotel_analyst"},
    )

    assert {asset["fqn"] for asset in assets} == {
        "pms.public.pms_stays",
        "pms.public.pms_reservations",
        "pms.public.pms_guests",
        "crm.dbo.crm_customer_map",
        "crm.dbo.crm_member_grade_history",
    }
    assert sum(len(adapter._live_schemas[asset["urn"]]) for asset in assets) <= 60
    assert {join_id for asset in assets for join_id in asset["join_ids"]} == {
        "pms_stay_to_crm_membership_grade_event_time_v1"
    }


def test_g2_allows_only_the_approved_pms_crm_join_id():
    adapter = I2DataPlatformAdapter("http://trino:8080", "runtime-user")
    adapter._datahub_dataset = lambda urn: live_dataset(adapter, urn)
    support = PipelineSupport(adapter, ContextPackageBuilder())
    payload = AnalysisRequest(question="투숙 완료 객실 매출을 회원 등급별로 알려줘")
    context = RequestContext(
        user_id=UUID("00000000-0000-0000-0000-000000000001"),
        as_of=date(2026, 7, 30),
    )
    assets = adapter.search_assets(payload.question, context.model_dump(mode="json"))
    package = support.build_context(payload, context, assets)
    join_id = "pms_stay_to_crm_membership_grade_event_time_v1"
    sql = (
        "SELECT gh.grade_code, SUM(s.room_revenue) FROM pms.public.pms_stays s "
        "JOIN pms.public.pms_reservations r ON r.reservation_id = s.reservation_id "
        "JOIN pms.public.pms_guests g ON g.guest_id = r.guest_id "
        "JOIN crm.dbo.crm_customer_map cm ON cm.pms_guest_id = g.guest_id "
        "JOIN crm.dbo.crm_member_grade_history gh ON gh.member_no = cm.member_no "
        "GROUP BY gh.grade_code LIMIT 1000"
    )
    references = [
        {
            "urn": item.urn,
            "fqn": item.fqn,
            "columns": list(item.columns),
            "join_ids": [join_id],
        }
        for item in package.assets
    ]

    assert support.g2_violation({"sql": sql, "parameters": {}, "references": references}, package) is None
    for reference in references:
        reference["join_ids"] = []
    assert support.g2_violation({"sql": sql, "parameters": {}, "references": references}, package) == "UNAPPROVED_JOIN"


def test_role_entitlement_excludes_serving_views_before_live_lookup():
    adapter = I2DataPlatformAdapter("http://trino:8080", "runtime-user")
    adapter._datahub_dataset = MagicMock()

    assets = adapter.search_assets(
        "호텔 객실 매출",
        {"role": "data_admin"},
    )

    assert assets == []
    adapter._datahub_dataset.assert_not_called()


def test_live_datahub_contract_mismatch_fails_closed():
    adapter = I2DataPlatformAdapter("http://trino:8080", "runtime-user")
    adapter._datahub_dataset = lambda urn: {
        **live_dataset(adapter, urn),
        "schemaMetadata": {"name": "serving.analytics.unapproved", "fields": []},
    }

    with pytest.raises(ValueError, match="does not match"):
        adapter.search_assets("호텔 객실 매출", {"role": "hotel_analyst"})


def test_g2_rejects_fqn_outside_live_context():
    adapter = I2DataPlatformAdapter("http://trino:8080", "runtime-user")
    adapter._datahub_dataset = lambda urn: live_dataset(adapter, urn)
    support = PipelineSupport(adapter, ContextPackageBuilder())
    payload = AnalysisRequest(question="호텔 객실 매출")
    context = RequestContext(
        user_id=UUID("00000000-0000-0000-0000-000000000001"),
        as_of=date(2026, 7, 30),
    )
    package = support.build_context(
        payload,
        context,
        adapter.search_assets(payload.question, context.model_dump(mode="json")),
    )

    plan = {
        "sql": "SELECT * FROM serving.analytics.unapproved_view LIMIT 1000",
        "parameters": {},
        "references": [{"urn": "unapproved", "fqn": "serving.analytics.unapproved_view"}],
        "model_version": "MODEL-v1.0.0",
    }

    assert support.g2_violation(plan, package) == "REFERENCE_OUTSIDE_CONTEXT"


def test_template_dates_are_bound_without_changing_the_approved_query_shape():
    sql = (
        "SELECT 1 WHERE event_at >= TIMESTAMP ':period_start 00:00:00 Asia/Seoul' "
        "AND event_at < TIMESTAMP ':period_end_exclusive 00:00:00 Asia/Seoul' "
        "LIMIT 1000"
    )

    bound = I2DataPlatformAdapter._bind_date_parameters(
        sql,
        {
            "period_start": "2026-05-01",
            "period_end_exclusive": "2026-07-01",
        },
    )

    assert ":period_" not in bound
    assert "2026-05-01" in bound
    assert "2026-07-01" in bound
    assert bound.endswith("LIMIT 1000")


@pytest.mark.parametrize(
    "parameters",
    [
        {"period_start": "2026-05-01' OR 1=1 --"},
        {"period_start": "2026-02-30"},
        {},
    ],
)
def test_template_date_binding_rejects_invalid_or_missing_values(parameters):
    with pytest.raises(ValueError):
        I2DataPlatformAdapter._bind_date_parameters(
            "SELECT 1 WHERE event_at >= TIMESTAMP ':period_start'",
            parameters,
        )
