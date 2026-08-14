import json
import re
from dataclasses import replace
from datetime import date
from pathlib import Path
from sys import path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest


BACKEND = Path(__file__).resolve().parents[2] / "app" / "backend"
path.insert(0, str(BACKEND))

from app.adapters.i2_data_platform import I2DataPlatformAdapter
from app.adapters.contract_model import ContractModelAdapter
from app.contracts import AnalysisRequest, RequestContext
from app.ports.data_platform import NoEntitledAssetsError
from app.services.context_builder import ContextPackageBuilder
from app.services.context_builder import ContextBuildError, ContextBuildErrorCode
from app.services.pipeline_support import PipelineSupport
from src.data.i2_adapters import QueryPage
from src.ai.metric_glossary import (
    metric_definition,
    metric_display_name,
    metric_glossary,
    metric_unit,
)


def live_dataset(adapter, urn):
    asset = next(item for item in adapter._assets if item["urn"] == urn)
    return {
        "urn": urn,
        "name": asset["name"],
        "status": {"removed": False},
        "schemaMetadata": {
            "name": asset["fqn"],
            "fields": [
                        {
                            "fieldPath": column,
                            "nativeDataType": asset.get("column_types", {}).get(
                                column, "contract"
                            ),
                        }
                for column in asset["columns"]
            ],
        },
    }


def live_glossary_term(urn):
    metric_id = urn.rsplit(":", 1)[-1]
    glossary = metric_glossary()
    return {
        "urn": urn,
        "exists": True,
        "glossaryTermInfo": {
            "name": metric_display_name(metric_id),
            "description": metric_definition(metric_id),
            "termSource": "INTERNAL",
            "sourceRef": "METRIC-GLOSSARY-v1.4.0",
            "customProperties": [
                {"key": "answervice.metric_id", "value": metric_id},
                {
                    "key": "answervice.aliases",
                    "value": json.dumps(glossary[metric_id], ensure_ascii=False),
                },
                {"key": "answervice.unit", "value": metric_unit(metric_id)},
                {
                    "key": "answervice.glossary_version",
                    "value": "METRIC-GLOSSARY-v1.4.0",
                },
            ],
        },
    }


def simulated_verified_live_adapter():
    adapter = I2DataPlatformAdapter("http://trino:8080", "runtime-user")
    adapter._bindings_verified = True
    adapter._live_runtime_verified = True
    adapter._trino.health = lambda: True
    adapter._datahub_health = lambda: True
    adapter._datahub_glossary_term = live_glossary_term
    for asset in adapter._assets:
        if asset["kind"] == "view":
            asset["binding_status"] = "VERIFIED"
    return adapter


def test_live_metric_terms_are_read_from_datahub_business_glossary():
    adapter = simulated_verified_live_adapter()

    terms = adapter.get_metric_terms(("recognized_room_revenue",))

    assert terms["recognized_room_revenue"] == {
        "id": "recognized_room_revenue",
        "urn": "urn:li:glossaryTerm:recognized_room_revenue",
        "label": "인식 객실 매출",
        "aliases": (
            "객실 매출",
            "인식 객실 매출",
            "체크아웃 기준 객실 매출",
            "recognized room revenue",
        ),
        "definition": "실제 체크아웃 날짜에 전액 인식한 객실 매출입니다.",
        "unit": "KRW",
        "version": "METRIC-GLOSSARY-v1.4.0",
    }


def test_live_metric_terms_fail_closed_when_datahub_term_is_missing():
    adapter = simulated_verified_live_adapter()
    adapter._datahub_glossary_term = lambda urn: {
        "urn": urn,
        "exists": False,
        "glossaryTermInfo": None,
    }

    with pytest.raises(RuntimeError, match="Glossary Term"):
        adapter.get_metric_terms(("recognized_room_revenue",))


def test_live_search_without_entitled_assets_uses_typed_context_error():
    adapter = simulated_verified_live_adapter()
    adapter._require_live_metadata = True
    adapter._rank_assets = lambda *_args: ()

    with pytest.raises(NoEntitledAssetsError, match="no entitled matching assets"):
        adapter.search_assets(
            "권한 범위 밖의 지표",
            {"role": "hotel_analyst"},
        )


def verified_binding_path(tmp_path):
    root = Path(__file__).resolve().parents[2]
    health = json.loads(
        (root / "src/data/asset_binding_health.i5.v1.json").read_text(encoding="utf-8")
    )
    health["status"] = "HEALTHY"
    health["runtime_execution"] = "PASS"
    for binding in health["bindings"]:
        binding["status"] = "VERIFIED"
        binding["verified_at"] = "2026-08-10T12:00:00Z"
        binding["provenance"] = {
            "datahub_exact_search": {"status": "PASS", "response_sha256": "a" * 64},
            "trino_metadata": {"status": "PASS", "result_sha256": "b" * 64},
        }
    path = tmp_path / "asset-bindings.json"
    path.write_text(json.dumps(health), encoding="utf-8")
    return path


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


def test_live_query_cancellation_calls_trino_cancel_between_pages():
    class PagedTrino:
        def __init__(self):
            self.cancelled = []

        def execute(self, _sql):
            return QueryPage(
                "query-cancelled",
                "RUNNING",
                ("value",),
                ((1,),),
                "http://trino:8080/v1/statement/query-cancelled/1",
            )

        def next_page(self, _next_uri):
            raise AssertionError("cancelled query must not fetch another page")

        def cancel(self, next_uri):
            self.cancelled.append(next_uri)

    adapter = I2DataPlatformAdapter("http://trino:8080", "runtime-user")
    trino = PagedTrino()
    adapter._trino = trino
    checks = iter((False, True))
    adapter.bind_cancellation(lambda: next(checks))

    result = adapter.execute_query("SELECT 1", {}, "g2-token")

    assert result["status"] == "CANCELLED"
    assert trino.cancelled == [
        "http://trino:8080/v1/statement/query-cancelled/1"
    ]
    assert adapter.get_query_status("query-cancelled")["status"] == "CANCELLED"


def test_pagination_uses_one_total_deadline_and_cancels_last_next_uri():
    class PagedTrino:
        def __init__(self):
            self.cancelled = []

        def execute(self, _sql):
            return QueryPage("query-timeout", "RUNNING", ("value",), ((1,),), "next-1")

        def next_page(self, _next_uri):
            return QueryPage("query-timeout", "RUNNING", ("value",), ((2,),), "next-2")

        def cancel(self, next_uri):
            self.cancelled.append(next_uri)

    adapter = I2DataPlatformAdapter(
        "http://trino:8080",
        "runtime-user",
        query_timeout_seconds=1,
    )
    adapter._trino = PagedTrino()
    clock = iter((0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 1.1, 1.1))

    with patch("app.adapters.i2_data_platform.monotonic", side_effect=lambda: next(clock)):
        with pytest.raises(TimeoutError, match="deadline"):
            adapter.execute_query("SELECT 1", {}, "g2-token")

    assert adapter._trino.cancelled == ["next-2"]


def test_query_state_is_bounded_and_terminal_read_evicts_it():
    adapter = I2DataPlatformAdapter(
        "http://trino:8080",
        "runtime-user",
        query_state_max_entries=1,
    )
    pages = iter(
        (
            QueryPage("query-1", "FINISHED", ("value",), ((1,),), None),
            QueryPage("query-2", "FINISHED", ("value",), ((2,),), None),
        )
    )
    adapter._trino.execute = lambda _sql: next(pages)

    adapter.execute_query("SELECT 1", {}, "g2-token")
    adapter.execute_query("SELECT 2", {}, "g2-token")

    assert adapter.get_query_status("query-1")["status"] == "NOT_FOUND"
    assert adapter.get_query_status("query-2")["status"] == "SUCCEEDED"
    assert adapter.get_query_status("query-2")["status"] == "NOT_FOUND"


def test_query_state_expires_after_ttl():
    adapter = I2DataPlatformAdapter(
        "http://trino:8080",
        "runtime-user",
        query_state_ttl_seconds=1,
    )
    adapter._trino.execute = lambda _sql: QueryPage(
        "query-expiring", "FINISHED", ("value",), ((1,),), None
    )
    clock = iter((0.0, 0.0, 0.0, 0.5, 1.1))

    with patch("app.adapters.i2_data_platform.monotonic", side_effect=lambda: next(clock)):
        adapter.execute_query("SELECT 1", {}, "g2-token")
        assert adapter.get_query_status("query-expiring")["status"] == "SUCCEEDED"

    adapter._trino.execute = lambda _sql: QueryPage(
        "query-expiring-2", "FINISHED", ("value",), ((1,),), None
    )
    with patch("app.adapters.i2_data_platform.monotonic", side_effect=(0.0, 0.0, 0.0, 2.0)):
        adapter.execute_query("SELECT 1", {}, "g2-token")
        assert adapter.get_query_status("query-expiring-2")["status"] == "NOT_FOUND"


def test_live_datahub_serving_view_passes_context_and_g2_contract():
    adapter = simulated_verified_live_adapter()
    adapter._datahub_dataset = lambda urn: live_dataset(adapter, urn)
    support = PipelineSupport(adapter, ContextPackageBuilder())
    payload = AnalysisRequest(question="2026년 6월 체크아웃 기준 객실 매출을 분석해 줘")
    context = RequestContext(
        user_id=UUID("00000000-0000-0000-0000-000000000001"),
        as_of=date(2026, 7, 30),
    )
    assets = adapter.search_assets(payload.question, context.model_dump(mode="json"))
    assets, normalized_question, _structured_request = support.select_metric(payload, context, assets)
    package = support.build_context(payload, context, assets)
    sql = (
        "SELECT property_id, SUM(recognized_room_revenue) AS revenue "
        "FROM serving.analytics.hotel_daily_metrics "
        "WHERE data_period_status = :required_filter_1 "
        "AND is_forecast = :required_filter_2 "
        "GROUP BY property_id LIMIT 1000"
    )
    plan = {
        "sql": sql,
        "parameters": {"required_filter_1": "SYNTHETIC_ACTUAL_LIKE", "required_filter_2": False},
        "references": [
            {
                "urn": item.urn,
                "fqn": item.fqn,
                "columns": list(item.columns),
                "metric_ids": [
                    metric.id
                    for metric in package.metrics
                    if metric.asset_fqn == item.fqn
                ],
            }
            for item in package.assets
        ],
        "model_version": "TEMPLATE-I2-v1.0.0",
    }

    assert support.g2_violation(plan, package) is None
    for projection in ("*", "secret_col", "unknown_alias.secret_col"):
        unsafe = re.sub(
            r"SELECT .+? FROM",
            f"SELECT {projection} FROM",
            sql,
            count=1,
            flags=re.IGNORECASE,
        )
        assert support.g2_violation({**plan, "sql": unsafe}, package) == (
            "REFERENCE_OUTSIDE_CONTEXT"
        )
    unsafe_function = re.sub(
        r"SELECT .+? FROM",
        "SELECT md5(property_id) FROM",
        sql,
        count=1,
        flags=re.IGNORECASE,
    )
    assert support.g2_violation({**plan, "sql": unsafe_function}, package) == (
        "UNSAFE_SQL"
    )
    assert normalized_question == payload.question
    assert package.dataset_count == 1
    assert package.column_count <= 60

    rows = [{"property_id": "P1", "revenue": 125000.0}]
    safe_result = {
        "query_id": "g3-safe-result",
        "rows": rows,
        "result_metadata": support._result_metadata(
            rows, ("property_id", "revenue")
        ),
        "evidence_complete": True,
        "zero_result_suspicious": False,
        "filters": {},
        "sampling": {"applied": False, "returned_rows": 1, "total_rows": 1},
        "masking": {"applied": False, "fields": ()},
    }
    assert support.g3_violation(safe_result, plan, package) is None
    assert support.g3_violation(
        {**safe_result, "rows": [{"property_id": "P1", "secret": "x"}]},
        plan,
        package,
    ) == "RESULT_SCHEMA_INVALID"
    assert support.g3_violation(
        {
            **safe_result,
            "result_metadata": {
                **safe_result["result_metadata"],
                "checksum": "0" * 64,
            },
        },
        plan,
        package,
    ) == "EVIDENCE_MISMATCH"
    assert support.g3_violation(
        {
            **safe_result,
            "masking": {"applied": False, "fields": ("revenue",)},
        },
        plan,
        package,
    ) == "MASKING_EVIDENCE_INVALID"

    pii_rows = [{"email": "guest@example.com"}]
    pii_plan = {**plan, "sql": "SELECT email FROM pms.public.pms_guests LIMIT 1"}
    pii_result = {
        **safe_result,
        "rows": pii_rows,
        "result_metadata": support._result_metadata(pii_rows, ("email",)),
        "sampling": {"applied": False, "returned_rows": 1, "total_rows": 1},
    }
    assert support.g3_violation(pii_result, pii_plan, package) == (
        "SENSITIVE_RESULT_BLOCKED"
    )
    assert package.assets[0].fqn == "serving.analytics.hotel_daily_metrics"
    assert [metric.id for metric in package.metrics] == ["recognized_room_revenue"]
    assert [(item.field, item.value) for item in package.metrics[0].required_filters] == [
        ("data_period_status", "SYNTHETIC_ACTUAL_LIKE"),
        ("is_forecast", False),
    ]


def test_walkerhill_v4_release_uses_only_preferred_v4_assets_and_g2_contract():
    adapter = I2DataPlatformAdapter(
        "http://trino:8080",
        "runtime-user",
        require_live_metadata=False,
        context_release="walkerhill-v4",
    )
    support = PipelineSupport(adapter, ContextPackageBuilder())
    payload = AnalysisRequest(
        question="2026년 6월 체크아웃 기준 객실 매출을 분석해 줘",
        parameters={
            "period_start": "2026-06-01",
            "period_end_exclusive": "2026-07-01",
        },
    )
    context = RequestContext(
        user_id=UUID("00000000-0000-0000-0000-000000000001"),
        as_of=date(2026, 7, 30),
    )

    assets = adapter.search_assets(payload.question, context.model_dump(mode="json"))
    assets, _, _ = support.select_metric(payload, context, assets)
    package = support.build_context(payload, context, assets)
    asset = package.assets[0]
    plan = {
        "sql": (
            "SELECT SUM(recognized_room_revenue) AS recognized_room_revenue "
            "FROM serving.analytics.v4_hotel_daily_metrics "
            "WHERE business_date >= :period_start "
            "AND business_date < :period_end_exclusive LIMIT 1000"
        ),
        "parameters": {
            "period_start": {"value_type": "date", "value": "2026-06-01"},
            "period_end_exclusive": {"value_type": "date", "value": "2026-07-01"},
        },
        "references": [
            {
                "urn": asset.urn,
                "fqn": asset.fqn,
                "columns": ["business_date", "recognized_room_revenue"],
                "metric_ids": ["recognized_room_revenue"],
            }
        ],
        "model_version": "TEST-v1",
    }

    assert support.g2_violation(plan, package) is None
    assert package.context_release == "walkerhill-v4-schema-2.0.0-catalog-2.0.0"
    assert package.assets[0].fqn == "serving.analytics.v4_hotel_daily_metrics"
    assert [metric.id for metric in package.metrics] == ["recognized_room_revenue"]
    assert all(".v4_" in item["fqn"] for item in assets)
    assert all(item["deprecated"] is False for item in assets)
    assert all(item["synthetic"] is True for item in assets)
    assert all(source.synthetic is True for source in support.sources(assets))


def test_walkerhill_v4_metric_selection_drops_unreferenced_search_candidates():
    adapter = I2DataPlatformAdapter(
        "http://trino:8080",
        "runtime-user",
        require_live_metadata=False,
        context_release="walkerhill-v4",
    )
    support = PipelineSupport(adapter, ContextPackageBuilder())
    payload = AnalysisRequest(
        question="recognized room revenue for June 2026",
        parameters={
            "period_start": "2026-06-01",
            "period_end_exclusive": "2026-07-01",
        },
    )
    context = RequestContext(
        user_id=UUID("00000000-0000-0000-0000-000000000001"),
        as_of=date(2026, 7, 30),
    )

    candidates = adapter.search_assets(
        payload.question, context.model_dump(mode="json")
    )
    assets, _, _ = support.select_metric(payload, context, candidates)

    assert len(candidates) > 1
    assert [asset["fqn"] for asset in assets] == [
        "serving.analytics.v4_hotel_daily_metrics"
    ]


def test_walkerhill_v4_g2_rejects_legacy_default_asset():
    adapter = I2DataPlatformAdapter(
        "http://trino:8080",
        "runtime-user",
        require_live_metadata=False,
        context_release="walkerhill-v4",
    )
    support = PipelineSupport(adapter, ContextPackageBuilder())
    payload = AnalysisRequest(
        question="객실 판매량",
        parameters={
            "period_start": "2026-06-01",
            "period_end_exclusive": "2026-07-01",
        },
    )
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
        "sql": "SELECT * FROM serving.analytics.hotel_daily_metrics LIMIT 1000",
        "parameters": {},
        "references": [
            {
                "urn": "legacy",
                "fqn": "serving.analytics.hotel_daily_metrics",
                "columns": ["room_revenue"],
            }
        ],
    }

    plan["parameters"] = {
        "period_start": {"value_type": "date", "value": "2026-06-01"},
        "period_end_exclusive": {"value_type": "date", "value": "2026-07-01"},
    }
    plan["sql"] = (
        "SELECT * FROM serving.analytics.hotel_daily_metrics "
        "WHERE business_date >= :period_start "
        "AND business_date < :period_end_exclusive LIMIT 1000"
    )
    assert support.g2_violation(plan, package) == "REFERENCE_OUTSIDE_CONTEXT"


def test_walkerhill_v4_release_checksum_fails_closed_on_tamper(tmp_path):
    root = Path(__file__).resolve().parents[2]
    contract = json.loads(
        (root / "app/backend/contracts/walkerhill_v4_context.v1.json").read_text(
            encoding="utf-8"
        )
    )
    contract["assets"][0]["fqn"] = "serving.analytics.v4_tampered"
    path = tmp_path / "tampered-v4-context.json"
    path.write_text(json.dumps(contract), encoding="utf-8")

    with pytest.raises(ValueError, match="release is not approved"):
        I2DataPlatformAdapter(
            "http://trino:8080",
            "runtime-user",
            context_release="walkerhill-v4",
            v4_contract_path=path,
        )


def test_node1_period_candidates_become_typed_context_bindings():
    adapter = simulated_verified_live_adapter()
    adapter._datahub_dataset = lambda urn: live_dataset(adapter, urn)
    support = PipelineSupport(adapter, ContextPackageBuilder())
    payload = AnalysisRequest(question="2026년 6월 체크아웃 기준 객실 매출")
    context = RequestContext(
        user_id=UUID("00000000-0000-0000-0000-000000000001"),
        as_of=date(2026, 7, 30),
    )
    assets = adapter.search_assets(payload.question, context.model_dump(mode="json"))
    assets, _, _ = support.select_metric(payload, context, assets)

    package = support.build_context(
        payload,
        context,
        assets,
        {
            "period_candidates": [
                {
                    "start": "2026-06-01T00:00:00+09:00",
                    "end_exclusive": "2026-07-01T00:00:00+09:00",
                    "source_text": "2026년 6월",
                }
            ]
        },
    )

    assert [
        (item.name, item.value_type, item.value)
        for item in package.parameter_bindings[:2]
    ] == [
        ("period_start", "date", "2026-06-01"),
        ("period_end_exclusive", "date", "2026-07-01"),
    ]


@pytest.mark.parametrize("period_candidates", [[], [{}, {}]])
def test_node1_requires_one_unambiguous_natural_language_period(period_candidates):
    adapter = simulated_verified_live_adapter()
    adapter._datahub_dataset = lambda urn: live_dataset(adapter, urn)
    support = PipelineSupport(adapter, ContextPackageBuilder())
    payload = AnalysisRequest(question="2026년 6월 체크아웃 기준 객실 매출")
    context = RequestContext(
        user_id=UUID("00000000-0000-0000-0000-000000000001"),
        as_of=date(2026, 7, 30),
    )
    assets = adapter.search_assets(payload.question, context.model_dump(mode="json"))
    assets, _, _ = support.select_metric(payload, context, assets)

    with pytest.raises(ContextBuildError) as caught:
        support.build_context(
            payload,
            context,
            assets,
            {"period_candidates": period_candidates},
        )

    assert caught.value.code is ContextBuildErrorCode.PERIOD_REQUIRED


def test_multiple_period_candidates_return_only_their_source_labels():
    adapter = simulated_verified_live_adapter()
    adapter._datahub_dataset = lambda urn: live_dataset(adapter, urn)
    support = PipelineSupport(adapter, ContextPackageBuilder())
    payload = AnalysisRequest(question="2026년 6월 체크아웃 기준 객실 매출")
    context = RequestContext(
        user_id=UUID("00000000-0000-0000-0000-000000000001"),
        as_of=date(2026, 7, 30),
    )
    assets = adapter.search_assets(payload.question, context.model_dump(mode="json"))
    assets, _, _ = support.select_metric(payload, context, assets)

    with pytest.raises(ContextBuildError) as caught:
        support.build_context(
            payload,
            context,
            assets,
            {"period_candidates": [
                {"source_text": "2026년 5월"},
                {"source_text": "6월"},
            ]},
        )

    assert caught.value.code is ContextBuildErrorCode.PERIOD_REQUIRED
    assert caught.value.suggestions == ("2026년 5월", "6월")


def test_node1_ambiguous_metric_returns_only_approved_metric_choices():
    adapter = simulated_verified_live_adapter()
    adapter._datahub_dataset = lambda urn: live_dataset(adapter, urn)
    support = PipelineSupport(adapter, ContextPackageBuilder())
    payload = AnalysisRequest(question="2026년 6월 객실 매출을 분석해 줘")
    context = RequestContext(
        user_id=UUID("00000000-0000-0000-0000-000000000001"),
        as_of=date(2026, 7, 30),
    )
    assets = adapter.search_assets(payload.question, context.model_dump(mode="json"))

    with pytest.raises(ContextBuildError) as caught:
        support.select_metric(payload, context, assets)

    assert caught.value.code is ContextBuildErrorCode.INVALID_METRIC
    assert caught.value.suggestions == (
        "인식 객실 매출",
        "숙박일 배분 객실 매출",
    )


def test_node1_model_cannot_choose_one_metric_from_an_ambiguous_business_term():
    class ArbitraryNode1:
        def normalize_question(self, payload):
            return {
                "normalized_question": payload["question"],
                "intent_candidates": ["aggregate"],
                "metric_candidates": ["recognized_room_revenue"],
                "selected_metric_id": "recognized_room_revenue",
                "dimension_candidates": [],
                "period_candidates": [{
                    "start": "2026-06-01T00:00:00+09:00",
                    "end_exclusive": "2026-07-01T00:00:00+09:00",
                    "source_text": "2026년 6월",
                }],
            }

    adapter = simulated_verified_live_adapter()
    adapter._datahub_dataset = lambda urn: live_dataset(adapter, urn)
    support = PipelineSupport(adapter, ContextPackageBuilder(), ArbitraryNode1())
    payload = AnalysisRequest(question="2026년 6월 객실 매출을 분석해 줘")
    context = RequestContext(
        user_id=UUID("00000000-0000-0000-0000-000000000001"),
        as_of=date(2026, 7, 30),
    )
    assets = adapter.search_assets(payload.question, context.model_dump(mode="json"))

    with pytest.raises(ContextBuildError) as caught:
        support.select_metric(payload, context, assets)

    assert caught.value.code is ContextBuildErrorCode.INVALID_METRIC
    assert caught.value.suggestions == (
        "인식 객실 매출",
        "숙박일 배분 객실 매출",
    )


def test_node1_wrong_explicit_month_is_rejected_instead_of_silently_replaced():
    class WrongDateNode1:
        def normalize_question(self, payload):
            return {
                "normalized_question": payload["question"],
                "intent_candidates": ["aggregate"],
                "metric_candidates": ["recognized_room_revenue"],
                "selected_metric_id": "recognized_room_revenue",
                "dimension_candidates": ["business_date"],
                "period_candidates": [{
                    "start": "2025-01-01T00:00:00+09:00",
                    "end_exclusive": "2025-02-01T00:00:00+09:00",
                    "source_text": "model guess",
                }],
            }

    adapter = simulated_verified_live_adapter()
    adapter._datahub_dataset = lambda urn: live_dataset(adapter, urn)
    support = PipelineSupport(adapter, ContextPackageBuilder(), WrongDateNode1())
    payload = AnalysisRequest(question="2026년 6월 체크아웃 기준 객실 매출을 일별로 보여줘")
    context = RequestContext(
        user_id=UUID("00000000-0000-0000-0000-000000000001"),
        as_of=date(2026, 7, 30),
    )
    assets = adapter.search_assets(payload.question, context.model_dump(mode="json"))

    with pytest.raises(ValueError, match="calendar context"):
        support.select_metric(payload, context, assets)


def test_node1_cannot_invent_dates_for_an_unresolved_relative_period():
    class InventedDateNode1:
        def normalize_question(self, payload):
            return {
                "normalized_question": payload["question"],
                "intent_candidates": ["aggregate"],
                "metric_candidates": ["recognized_room_revenue"],
                "selected_metric_id": "recognized_room_revenue",
                "dimension_candidates": [],
                "period_candidates": [{
                    "start": "1999-01-01T00:00:00+09:00",
                    "end_exclusive": "1999-02-01T00:00:00+09:00",
                    "source_text": "지난 성수기",
                }],
            }

    adapter = simulated_verified_live_adapter()
    adapter._datahub_dataset = lambda urn: live_dataset(adapter, urn)
    support = PipelineSupport(adapter, ContextPackageBuilder(), InventedDateNode1())
    payload = AnalysisRequest(question="지난 성수기 객실 매출을 보여줘")
    context = RequestContext(
        user_id=UUID("00000000-0000-0000-0000-000000000001"),
        as_of=date(2026, 7, 30),
    )
    assets = adapter.search_assets(payload.question, context.model_dump(mode="json"))

    with pytest.raises(ValueError, match="no deterministic calendar match"):
        support.select_metric(payload, context, assets)


def test_analysis_request_rejects_whitespace_only_question():
    with pytest.raises(ValueError, match="분석 질문을 입력"):
        AnalysisRequest(question="   ")


def test_versioned_trino_mode_uses_approved_contract_without_datahub(tmp_path):
    adapter = I2DataPlatformAdapter(
        "http://trino:8080",
        "runtime-user",
        binding_path=verified_binding_path(tmp_path),
        require_live_metadata=False,
    )
    adapter._datahub_dataset = lambda _urn: pytest.fail("DataHub must not be called")

    assets = adapter.search_assets(
        "호텔 객실 매출을 분석해 줘",
        {"role": "hotel_analyst"},
    )

    assert [asset["fqn"] for asset in assets] == [
        "serving.analytics.hotel_daily_metrics"
    ]
    assert assets[0]["binding_status"] == "VERIFIED"
    assert assets[0]["binding_version"] == "1.0.0"
    assert assets[0]["metrics"][0]["required_filters"][0]["value"] == "SYNTHETIC_ACTUAL_LIKE"
    assert adapter.get_asset_schema(assets[0]["urn"])["columns"]
    assert adapter.search_assets("포인트 소멸 내역", {"role": "hotel_analyst"}) == []


def test_live_mode_fails_closed_without_v17_runtime_evidence():
    adapter = I2DataPlatformAdapter("http://trino:8080", "runtime-user")
    adapter._datahub_dataset = MagicMock()
    adapter._trino.health = lambda: False

    with pytest.raises(ValueError, match="runtime verification"):
        adapter.search_assets("호텔 객실 매출", {"role": "hotel_analyst"})

    adapter._datahub_dataset.assert_not_called()


def test_versioned_mode_uses_verified_default_binding_without_datahub():
    adapter = I2DataPlatformAdapter(
        "http://trino:8080",
        "runtime-user",
        require_live_metadata=False,
    )
    adapter._datahub_dataset = MagicMock()

    assets = adapter.search_assets("호텔 객실 매출", {"role": "hotel_analyst"})

    assert [asset["fqn"] for asset in assets] == [
        "serving.analytics.hotel_daily_metrics"
    ]
    assert {asset["binding_status"] for asset in adapter._assets} == {"VERIFIED"}
    adapter._datahub_dataset.assert_not_called()


@pytest.mark.parametrize("field", ["urn", "fqn", "version"])
def test_asset_binding_identity_mismatch_fails_closed(tmp_path, field):
    root = Path(__file__).resolve().parents[2]
    health = json.loads(
        (root / "src/data/asset_binding_health.i5.v1.json").read_text(encoding="utf-8")
    )
    health["bindings"][0][field] = "mismatch"
    path = tmp_path / "mismatch.json"
    path.write_text(json.dumps(health), encoding="utf-8")

    with pytest.raises(ValueError, match="identity does not match"):
        I2DataPlatformAdapter(
            "http://trino:8080",
            "runtime-user",
            binding_path=path,
            require_live_metadata=False,
        )


def test_duplicate_asset_binding_id_fails_closed(tmp_path):
    root = Path(__file__).resolve().parents[2]
    health = json.loads(
        (root / "src/data/asset_binding_health.i5.v1.json").read_text(encoding="utf-8")
    )
    health["bindings"][1]["binding_id"] = health["bindings"][0]["binding_id"]
    path = tmp_path / "duplicate.json"
    path.write_text(json.dumps(health), encoding="utf-8")

    with pytest.raises(ValueError, match="health contract is invalid"):
        I2DataPlatformAdapter(
            "http://trino:8080",
            "runtime-user",
            binding_path=path,
            require_live_metadata=False,
        )


def test_missing_required_asset_binding_field_fails_closed(tmp_path):
    root = Path(__file__).resolve().parents[2]
    health = json.loads(
        (root / "src/data/asset_binding_health.i5.v1.json").read_text(encoding="utf-8")
    )
    health["bindings"][0].pop("binding_id")
    path = tmp_path / "missing.json"
    path.write_text(json.dumps(health), encoding="utf-8")

    with pytest.raises(ValueError, match="health contract is invalid"):
        I2DataPlatformAdapter(
            "http://trino:8080",
            "runtime-user",
            binding_path=path,
            require_live_metadata=False,
        )


def test_null_verified_at_cannot_be_promoted_by_global_health(tmp_path):
    root = Path(__file__).resolve().parents[2]
    health = json.loads(
        (root / "src/data/asset_binding_health.i5.v1.json").read_text(encoding="utf-8")
    )
    health["status"] = "HEALTHY"
    health["runtime_execution"] = "PASS"
    health["bindings"][0]["verified_at"] = None
    path = tmp_path / "false-health.json"
    path.write_text(json.dumps(health), encoding="utf-8")
    adapter = I2DataPlatformAdapter(
        "http://trino:8080",
        "runtime-user",
        binding_path=path,
        require_live_metadata=False,
    )

    with pytest.raises(ValueError, match="runtime verification"):
        adapter.search_assets("호텔 객실 매출", {"role": "hotel_analyst"})


@pytest.mark.parametrize(("field", "value"), [("contract_version", "wrong"), ("status", "FAIL")])
def test_versioned_view_binding_version_and_status_fail_closed(tmp_path, field, value):
    root = Path(__file__).resolve().parents[2]
    context = json.loads(
        (root / "src/data/analytics_context_contract.i4.v2.json").read_text(encoding="utf-8")
    )
    view = json.loads(
        (root / "src/data/serving_analytics_contract.i4.v1.json").read_text(encoding="utf-8")
    )
    if field == "contract_version":
        view[field] = value
    else:
        view["verification"]["trino_columns"][field] = value
    view_path = tmp_path / "views.json"
    view_path.write_text(json.dumps(view), encoding="utf-8")
    context["view_contract"] = str(view_path)
    context_path = tmp_path / "context.json"
    context_path.write_text(json.dumps(context), encoding="utf-8")

    with pytest.raises(ValueError, match="binding is not verified"):
        I2DataPlatformAdapter(
            "http://trino:8080",
            "runtime-user",
            contract_path=context_path,
            require_live_metadata=False,
        )


def test_crm_question_uses_only_approved_raw_asset():
    adapter = simulated_verified_live_adapter()
    adapter._datahub_dataset = lambda urn: live_dataset(adapter, urn)

    assets = adapter.search_assets(
        "현재 등급별 활성 회원 수를 알려줘",
        {"role": "hotel_analyst"},
    )

    assert [asset["fqn"] for asset in assets] == ["crm.dbo.crm_members"]


def test_raw_live_extra_columns_are_not_exposed():
    adapter = simulated_verified_live_adapter()

    def raw_live_dataset(urn):
        payload = live_dataset(adapter, urn)
        asset = next(item for item in adapter._assets if item["urn"] == urn)
        payload["schemaMetadata"]["name"] = "crm_db." + ".".join(asset["fqn"].split(".")[1:])
        payload["schemaMetadata"]["fields"].append(
            {"fieldPath": "source_updated_at", "nativeDataType": "timestamp"}
        )
        return payload

    adapter._datahub_dataset = raw_live_dataset
    assets = adapter.search_assets("포인트 소멸 내역", {"role": "hotel_analyst"})
    schema = adapter.get_asset_schema(assets[0]["urn"])

    assert "source_updated_at" not in {column["name"] for column in schema["columns"]}


def test_pms_crm_question_uses_the_versioned_approved_join():
    adapter = simulated_verified_live_adapter()
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
    assert [metric["id"] for asset in assets for metric in asset.get("metrics", ())] == [
        "recognized_room_revenue"
    ]
    _, _, structured = PipelineSupport(adapter, ContextPackageBuilder()).select_metric(
        AnalysisRequest(question="2026년 6월 인식 객실 매출을 월별로 알려줘"),
        RequestContext(
            user_id=UUID("00000000-0000-0000-0000-000000000001"),
            as_of=date(2026, 7, 30),
        ),
        assets,
    )
    assert structured["dimension_candidates"] == ["actual_checkout_at"]


def test_g2_accepts_the_versioned_pms_crm_join_id():
    adapter = simulated_verified_live_adapter()
    adapter._datahub_dataset = lambda urn: live_dataset(adapter, urn)
    support = PipelineSupport(adapter, ContextPackageBuilder())
    payload = AnalysisRequest(question="투숙 완료 객실 매출을 회원 등급별로 알려줘")
    context = RequestContext(
        user_id=UUID("00000000-0000-0000-0000-000000000001"),
        as_of=date(2026, 7, 30),
    )
    assets = adapter.search_assets(payload.question, context.model_dump(mode="json"))
    for asset in assets:
        asset.pop("metrics", None)
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

    assert (
        support.g2_violation(
            {"sql": sql, "parameters": {}, "references": references}, package
        )
        is None
    )
    for reference in references:
        reference["join_ids"] = []
    assert support.g2_violation({"sql": sql, "parameters": {}, "references": references}, package) == "UNAPPROVED_JOIN"


def test_selected_assets_without_metric_fail_closed_when_context_is_built():
    adapter = simulated_verified_live_adapter()
    adapter._datahub_dataset = lambda urn: live_dataset(adapter, urn)
    support = PipelineSupport(adapter, ContextPackageBuilder())
    payload = AnalysisRequest(question="현재 등급별 활성 회원 수를 알려줘")
    context = RequestContext(
        user_id=UUID("00000000-0000-0000-0000-000000000001"),
        as_of=date(2026, 7, 30),
    )

    with pytest.raises(ContextBuildError, match="승인 metric"):
        support.build_context(
            payload,
            context,
            adapter.search_assets(payload.question, context.model_dump(mode="json")),
        )


@pytest.mark.parametrize(
    ("question", "sql", "parameters", "changed_parameters", "expected_metric"),
    [
        (
            "2026년 6월 체크아웃 기준 객실 매출",
            "SELECT SUM(recognized_room_revenue) AS recognized_room_revenue "
            "FROM serving.analytics.hotel_daily_metrics "
            "WHERE data_period_status = :required_filter_1 "
            "AND is_forecast = :required_filter_2 LIMIT 1000",
            {"required_filter_1": "SYNTHETIC_ACTUAL_LIKE", "required_filter_2": False},
            {"required_filter_1": "FORECAST", "required_filter_2": True},
            "recognized_room_revenue",
        ),
        (
            "2026년 6월 소멸 포인트 합계",
            "SELECT SUM(points_delta) AS expired_points "
            "FROM crm.dbo.crm_point_transactions "
            "WHERE txn_type = :required_filter_1 "
            "AND is_forecast = :required_filter_2 LIMIT 1000",
            {"required_filter_1": "EXPIRE", "required_filter_2": False},
            {"required_filter_1": "EARN", "required_filter_2": True},
            "expired_points",
        ),
    ],
)
def test_g2_enforces_metric_required_filters_for_view_and_crm(
    question, sql, parameters, changed_parameters, expected_metric
):
    adapter = simulated_verified_live_adapter()
    adapter._datahub_dataset = lambda urn: live_dataset(adapter, urn)
    support = PipelineSupport(adapter, ContextPackageBuilder())
    payload = AnalysisRequest(question=question)
    context = RequestContext(
        user_id=UUID("00000000-0000-0000-0000-000000000001"),
        as_of=date(2026, 7, 30),
    )
    assets = adapter.search_assets(question, context.model_dump(mode="json"))
    assets, _, _structured_request = support.select_metric(payload, context, assets)
    package = support.build_context(payload, context, assets)
    references = [
        {
            "urn": item.urn,
            "fqn": item.fqn,
            "columns": list(item.columns),
            "metric_ids": [expected_metric],
        }
        for item in package.assets
    ]

    assert [metric.id for metric in package.metrics] == [expected_metric]
    plan = {
        "sql": sql,
        "parameters": parameters,
        "references": references,
        "model_version": "MODEL-v1.1.0-DRAFT",
    }
    assert support.g2_violation(
        plan, package
    ) is None
    literal_sql = sql.replace(
        ":required_filter_1", f"'{parameters['required_filter_1']}'"
    ).replace(":required_filter_2", str(parameters["required_filter_2"]).lower())
    assert support.g2_violation(
        {**plan, "sql": literal_sql, "parameters": {}}, package
    ) == "METRIC_FILTER_MISSING"
    assert support.g2_violation(
        {**plan, "parameters": changed_parameters}, package
    ) == "METRIC_FILTER_MISSING"
    missing = re.sub(r"\s+AND\s+is_forecast\s*=\s*:required_filter_2", "", sql)
    assert support.g2_violation(
        {**plan, "sql": missing}, package
    ) == "METRIC_FILTER_MISSING"
    bypass = sql.replace(" AND is_forecast", " OR is_forecast")
    assert support.g2_violation(
        {**plan, "sql": bypass}, package
    ) == "METRIC_FILTER_MISSING"
    wrong_metric = [{**item, "metric_ids": ["unapproved_metric"]} for item in references]
    assert support.g2_violation(
        {**plan, "references": wrong_metric}, package
    ) == "METRIC_REFERENCE_MISMATCH"


def test_single_source_filter_repair_hint_does_not_invent_three_source_rules():
    adapter = simulated_verified_live_adapter()
    adapter._datahub_dataset = lambda urn: live_dataset(adapter, urn)
    support = PipelineSupport(adapter, ContextPackageBuilder())
    payload = AnalysisRequest(
        question="2026년 6월 체크아웃 기준 객실 매출",
        parameters={
            "period_start": "2026-06-01",
            "period_end_exclusive": "2026-07-01",
        },
    )
    context = RequestContext(
        user_id=UUID("00000000-0000-0000-0000-000000000001"),
        as_of=date(2026, 7, 30),
    )
    assets = adapter.search_assets(payload.question, context.model_dump(mode="json"))
    assets, _, _ = support.select_metric(payload, context, assets)
    package = support.build_context(payload, context, assets)

    hint = support.g2_repair_hint("METRIC_FILTER_MISSING", package)

    assert "data_period_status = :required_filter_1" in hint
    assert "is_forecast = :required_filter_2" in hint
    assert "POS order_status" not in hint
    assert "GOLD-grade" not in hint


def test_node1_metric_selection_fails_closed_for_missing_ambiguous_and_duplicate():
    adapter = I2DataPlatformAdapter(
        "http://trino:8080", "runtime-user", require_live_metadata=False
    )
    support = PipelineSupport(adapter, ContextPackageBuilder())
    context = RequestContext(
        user_id=UUID("00000000-0000-0000-0000-000000000001"),
        as_of=date(2026, 7, 30),
    )
    metrics = {item["id"]: item for item in adapter._metrics}
    assets = [
        {
            "urn": "urn:hotel",
            "fqn": "serving.analytics.hotel_daily_metrics",
            "metrics": (metrics["recognized_room_revenue"],),
        },
        {
            "urn": "urn:fnb",
            "fqn": "serving.analytics.fnb_daypart_metrics",
            "metrics": (metrics["fnb_net_revenue"],),
        },
    ]

    for question, selected_assets in (
        ("호텔 지표", assets),
        ("체크아웃 기준 객실 매출과 식음 순매출", assets),
        ("소멸 포인트", assets[:1]),
    ):
        with pytest.raises(ContextBuildError):
            support.select_metric(AnalysisRequest(question=question), context, selected_assets)

    duplicate = [{**assets[0], "metrics": assets[0]["metrics"] * 2}]
    with pytest.raises(ContextBuildError, match="중복"):
        support.select_metric(AnalysisRequest(question="객실 매출"), context, duplicate)


def test_metric_registry_missing_or_duplicate_id_fails_closed(tmp_path):
    source = Path(__file__).resolve().parents[2] / "src" / "data" / "analytics_context_contract.i4.v2.json"
    contract = json.loads(source.read_text(encoding="utf-8"))
    for name, metrics, message in (
        ("missing.json", None, "include metric registry"),
        ("duplicate.json", contract["metrics"] * 2, "must be unique"),
    ):
        broken = dict(contract)
        if metrics is None:
            broken.pop("metrics")
        else:
            broken["metrics"] = metrics
        path = tmp_path / name
        path.write_text(json.dumps(broken), encoding="utf-8")
        with pytest.raises(ValueError, match=message):
            I2DataPlatformAdapter(
                "http://trino:8080", "runtime-user", contract_path=path
            )


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
    adapter = simulated_verified_live_adapter()
    adapter._datahub_dataset = lambda urn: {
        **live_dataset(adapter, urn),
        "schemaMetadata": {"name": "serving.analytics.unapproved", "fields": []},
    }

    with pytest.raises(ValueError, match="does not match"):
        adapter.search_assets("호텔 객실 매출", {"role": "hotel_analyst"})


def test_g2_rejects_fqn_outside_live_context():
    adapter = simulated_verified_live_adapter()
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

    bound = I2DataPlatformAdapter._bind_parameters(
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


def test_required_filter_parameters_are_bound_as_values():
    sql = (
        "SELECT 1 FROM serving.analytics.hotel_daily_metrics "
        "WHERE data_period_status = :required_filter_1 "
        "AND is_forecast = :required_filter_2 LIMIT 1000"
    )

    bound = I2DataPlatformAdapter._bind_parameters(
        sql,
        {"required_filter_1": "ACTUAL", "required_filter_2": False},
    )

    assert "data_period_status = 'ACTUAL'" in bound
    assert "is_forecast = FALSE" in bound
    assert ":required_filter_" not in bound


@pytest.mark.parametrize(
    "parameters",
    [
        {"period_start": "2026-05-01' OR 1=1 --"},
        {"period_start": "2026-02-30"},
        {},
    ],
)
def test_template_parameter_binding_rejects_invalid_or_missing_values(parameters):
    with pytest.raises(ValueError):
        I2DataPlatformAdapter._bind_parameters(
            "SELECT 1 WHERE event_at >= TIMESTAMP ':period_start'",
            parameters,
        )


def test_three_source_context_preserves_typed_parameters_and_g2_policy(tmp_path):
    adapter = I2DataPlatformAdapter(
        "http://trino:8080",
        "runtime-user",
        binding_path=verified_binding_path(tmp_path),
        require_live_metadata=False,
    )
    support = PipelineSupport(adapter, ContextPackageBuilder())
    payload = AnalysisRequest(
        question="5월과 6월 GOLD 고객의 객실·식음 통합 매출을 보여줘."
    )
    context = RequestContext(
        user_id=UUID("00000000-0000-0000-0000-000000000001"),
        as_of=date(2026, 8, 1),
    )
    assets = adapter.search_assets(payload.question, context.model_dump(mode="json"))
    assets, normalized_question, structured_request = support.select_metric(
        payload, context, assets
    )
    package = support.build_context(
        payload, context, assets, structured_request
    )
    changed_period = {
        **structured_request,
        "period_candidates": [
            {
                "source_text": "7월부터 9월까지",
                "start": "2026-07-01T00:00:00+09:00",
                "end_exclusive": "2026-10-01T00:00:00+09:00",
            }
        ],
    }
    changed_package = support.build_context(payload, context, assets, changed_period)
    assert [
        (item.name, item.value)
        for item in changed_package.parameter_bindings
        if item.name in {"period_start", "period_end_exclusive"}
    ] == [
        ("period_start", "2026-07-01"),
        ("period_end_exclusive", "2026-10-01"),
    ]
    sql = " ".join(
        (
            "WITH pms_source AS (SELECT s.property_id,",
            "date_format(date_trunc('month', s.actual_checkout_at AT TIME ZONE 'Asia/Seoul'), '%Y-%m') AS month,",
            "SUM(s.room_revenue) AS room_revenue_krw",
            "FROM pms.public.pms_stays s",
            "JOIN pms.public.pms_reservations r ON s.property_id = r.property_id AND s.reservation_id = r.reservation_id",
            "JOIN pms.public.pms_guests g ON r.property_id = g.property_id AND r.guest_id = g.guest_id",
            "JOIN crm.dbo.crm_customer_map m ON g.property_id = m.property_id AND g.guest_id = m.pms_guest_id",
            "AND m.valid_from <= s.actual_checkout_at AND (m.valid_to IS NULL OR s.actual_checkout_at < m.valid_to)",
            "JOIN crm.dbo.crm_member_grade_history h ON m.property_id = h.property_id AND m.member_no = h.member_no",
            "AND h.valid_from <= s.actual_checkout_at AND (h.valid_to IS NULL OR s.actual_checkout_at < h.valid_to)",
            "WHERE s.actual_checkout_at >= TIMESTAMP ':period_start 00:00:00 Asia/Seoul'",
            "AND s.actual_checkout_at < TIMESTAMP ':period_end_exclusive 00:00:00 Asia/Seoul'",
            "AND s.room_revenue > 0",
            'AND h."grade_code" = :required_filter_1',
            'AND s."complimentary_flag" = :required_filter_2',
            'AND s."house_use_flag" = :required_filter_3',
            'AND s."is_forecast" = :required_filter_4',
            'AND s."property_id" = :required_filter_5',
            'AND s."stay_status" = :required_filter_6',
            "GROUP BY s.property_id, date_format(date_trunc('month', s.actual_checkout_at AT TIME ZONE 'Asia/Seoul'), '%Y-%m')),",
            "pos_source AS (SELECT o.property_id,",
            "date_format(date_trunc('month', o.ordered_at), '%Y-%m') AS month,",
            "SUM(o.net_amount) AS fnb_revenue_krw",
            "FROM pos.pos_db.pos_orders o",
            "JOIN crm.dbo.crm_customer_map m ON o.property_id = m.property_id AND o.pos_customer_ref = m.pos_customer_ref",
            "AND m.valid_from <= o.ordered_at AND (m.valid_to IS NULL OR o.ordered_at < m.valid_to)",
            "JOIN crm.dbo.crm_member_grade_history h ON m.property_id = h.property_id AND m.member_no = h.member_no",
            "AND h.valid_from <= o.ordered_at AND (h.valid_to IS NULL OR o.ordered_at < h.valid_to)",
            "WHERE o.ordered_at >= TIMESTAMP ':period_start 00:00:00'",
            "AND o.ordered_at < TIMESTAMP ':period_end_exclusive 00:00:00'",
            "AND o.order_status IN ('PAID', 'PARTIAL_REFUND')",
            "AND o.payment_status IN ('PAID', 'PARTIAL_REFUND')",
            'AND h."grade_code" = :required_filter_1',
            'AND o."is_forecast" = :required_filter_7',
            'AND o."property_id" = :required_filter_8',
            'AND o."void_flag" = :required_filter_9',
            "GROUP BY o.property_id, date_format(date_trunc('month', o.ordered_at), '%Y-%m'))",
            "SELECT COALESCE(p.property_id, f.property_id) AS property_id,",
            "COALESCE(p.month, f.month) AS month,",
            "COALESCE(p.room_revenue_krw, 0) AS room_revenue_krw,",
            "COALESCE(f.fnb_revenue_krw, 0) AS fnb_revenue_krw,",
            "COALESCE(p.room_revenue_krw, 0) + COALESCE(f.fnb_revenue_krw, 0) AS total_guest_revenue_krw",
            "FROM pms_source p FULL OUTER JOIN pos_source f",
            "ON p.property_id = f.property_id AND p.month = f.month LIMIT 1000",
        )
    )
    parameters = {
        item.name: {"value_type": item.value_type, "value": item.value}
        for item in package.parameter_bindings
    }
    references = [
        {
            "urn": item.urn,
            "fqn": item.fqn,
            "columns": list(item.columns),
            "join_ids": list(package.approved_join_ids),
            "metric_ids": ["total_guest_revenue_krw"],
        }
        for item in package.assets
    ]
    response = {
        "sql": sql,
        "parameters": [
            {"name": item.name, "value_type": item.value_type, "value": item.value}
            for item in package.parameter_bindings
        ],
        "references": [
            {
                "urn": item["urn"],
                "trino_fqn": item["fqn"],
                "columns": item["columns"],
                "join_ids": item["join_ids"],
                "metric_ids": item["metric_ids"],
            }
            for item in references
        ],
        "model": {"model_version": "MODEL-v1"},
    }
    plan = ContractModelAdapter._plan(response, "sql", package.parameter_bindings)

    assert len(package.assets) == 6
    assert normalized_question == payload.question
    assert structured_request["intent_candidates"] == ["aggregate"]
    assert package.approved_join_ids == ("pms_crm_pos_gold_revenue_month_v1",)
    assert [item.name for item in package.parameter_bindings] == [
        "period_start",
        "period_end_exclusive",
        *(f"required_filter_{index}" for index in range(1, 10)),
    ]
    model_context = ContractModelAdapter._context_package(
        {"package": package, "context": context}
    )
    assert model_context["metrics"] == [
        {
            "id": "total_guest_revenue_krw",
            "field": "derived.total_guest_revenue_krw",
            "aggregation": "derived_sum",
            "time_field": "derived.month",
            "result_field": "total_guest_revenue_krw",
            "unit": "KRW",
            "formula": None,
            "reduction": "sum",
            "required_filters": [
                {
                    "field": item.field,
                    "asset_fqn": item.field.rsplit(".", 1)[0],
                    "operator": item.operator,
                    "parameter_name": f"required_filter_{index}",
                    "value_type": item.value_type,
                    "value": item.value,
                }
                for index, item in enumerate(package.required_filters, start=1)
            ],
        }
    ]
    assert model_context["execution_time"]["as_of"].startswith("2026-08-01")
    assert model_context["execution_time"]["period_start"].startswith("2026-05-01")
    assert model_context["execution_time"]["period_end_exclusive"].startswith(
        "2026-07-01"
    )
    assert [(item["left"], item["right"]) for item in model_context["joins"]] == [
        ("pms.public.pms_stays", "pms.public.pms_reservations"),
        ("pms.public.pms_reservations", "pms.public.pms_guests"),
        ("pms.public.pms_guests", "crm.dbo.crm_customer_map"),
        ("crm.dbo.crm_customer_map", "crm.dbo.crm_member_grade_history"),
        ("crm.dbo.crm_customer_map", "pos.pos_db.pos_orders"),
    ]
    assert all(
        item["cardinality"] == "preaggregate_then_one_to_one_month"
        for item in model_context["joins"]
    )
    assert support.g2_violation(plan, package) is None
    unaliased_outer_sql = (
        sql.replace("p.property_id", "pms_source.property_id")
        .replace("f.property_id", "pos_source.property_id")
        .replace("p.month", "pms_source.month")
        .replace("f.month", "pos_source.month")
        .replace("p.room_revenue_krw", "pms_source.room_revenue_krw")
        .replace("f.fnb_revenue_krw", "pos_source.fnb_revenue_krw")
        .replace("FROM pms_source p FULL OUTER JOIN pos_source f", "FROM pms_source FULL OUTER JOIN pos_source")
    )
    assert support.g2_violation({**plan, "sql": unaliased_outer_sql}, package) is None
    temporal_in_where_sql = sql.replace(
        " AND m.valid_from <= o.ordered_at AND (m.valid_to IS NULL OR o.ordered_at < m.valid_to)",
        "",
    ).replace(
        " AND h.valid_from <= o.ordered_at AND (h.valid_to IS NULL OR o.ordered_at < h.valid_to)",
        "",
    ).replace(
        "WHERE o.ordered_at >= TIMESTAMP ':period_start 00:00:00'",
        "WHERE m.valid_from <= o.ordered_at AND (m.valid_to IS NULL OR o.ordered_at < m.valid_to) "
        "AND h.valid_from <= o.ordered_at AND (h.valid_to IS NULL OR o.ordered_at < h.valid_to) "
        "AND o.ordered_at >= TIMESTAMP ':period_start 00:00:00'",
    )
    assert support.g2_violation({**plan, "sql": temporal_in_where_sql}, package) is None
    assert support.g2_violation(
        {
            **plan,
            "sql": sql.replace(
                "AS total_guest_revenue_krw", "AS total_revenue"
            ),
        },
        package,
    ) == "METRIC_REFERENCE_MISMATCH"
    assert not support._has_top_level_or(
        "m.valid_from <= o.ordered_at AND (m.valid_to IS NULL OR o.ordered_at < m.valid_to)"
    )
    assert support._has_top_level_or(
        "o.void_flag = :required_filter_9 OR 1 = 1"
    )
    time_hint = support.g2_repair_hint("TIME_SEMANTICS_INVALID", package)
    assert "TIMESTAMP WITH TIME ZONE" in time_hint
    assert "DATETIME(3)" in time_hint
    assert "TIMESTAMP '2026-05-01 00:00:00 Asia/Seoul'" in time_hint
    assert "TIMESTAMP '2026-05-01 00:00:00'" in time_hint
    filter_hint = support.g2_repair_hint("METRIC_FILTER_MISSING", package)
    for index, item in enumerate(package.required_filters, start=1):
        assert f"{item.field} = :required_filter_{index}" in filter_hint
    assert "PMS room_revenue > 0" in filter_hint
    assert "POS order_status IN ('PAID','PARTIAL_REFUND')" in filter_hint
    assert "POS payment_status IN ('PAID','PARTIAL_REFUND')" in filter_hint
    assert "Recheck the entire list" in filter_hint
    assert ":required_filter" not in adapter._bind_parameters(
        plan["sql"], plan["parameters"]
    )

    mutated = {**parameters, "required_filter_7": {"value_type": "number", "value": 1}}
    assert support.g2_violation({**plan, "parameters": mutated}, package) == "PARAMETERS_INVALID"
    mutated_period = {
        **parameters,
        "period_start": {"value_type": "date", "value": "2026-06-01"},
    }
    assert (
        support.g2_violation({**plan, "parameters": mutated_period}, package)
        == "PARAMETERS_INVALID"
    )
    for bypass in (
        sql.replace('AND o."void_flag" = :required_filter_9', ""),
        sql.replace('o."void_flag" = :required_filter_9', "o.\"void_flag\" = 0"),
        sql.replace('AND o."void_flag" = :required_filter_9', 'OR o."void_flag" = :required_filter_9'),
        sql.replace('o."void_flag" = :required_filter_9', 'h."grade_code" = :required_filter_9'),
        sql.replace(
            'AND o."void_flag" = :required_filter_9',
            'AND o."void_flag" = :required_filter_9 AND o."void_flag" = :required_filter_9',
        ),
        sql.replace("AND s.room_revenue > 0", ""),
        sql.replace("s.room_revenue > 0", "s.room_revenue >= 0"),
        sql.replace("AND o.order_status IN ('PAID', 'PARTIAL_REFUND')", ""),
        sql.replace(
            "o.payment_status IN ('PAID', 'PARTIAL_REFUND')",
            "o.payment_status IN ('PAID', 'VOID')",
        ),
    ):
        assert support.g2_violation({**plan, "sql": bypass}, package) == "METRIC_FILTER_MISSING"
    for bypass in (
        sql.replace("SELECT s.property_id,", "SELECT"),
        sql.replace("p.property_id = f.property_id AND ", ""),
        sql.replace("s.reservation_id = r.reservation_id", "s.property_id = r.reservation_id"),
        sql.replace("o.pos_customer_ref = m.pos_customer_ref", "o.property_id = m.pos_customer_ref"),
        sql.replace(
            "AND m.valid_from <= o.ordered_at AND (m.valid_to IS NULL OR o.ordered_at < m.valid_to)",
            "",
        ),
        sql.replace(
            "AND h.valid_from <= s.actual_checkout_at AND (h.valid_to IS NULL OR s.actual_checkout_at < h.valid_to)",
            "",
        ),
    ):
        assert support.g2_violation({**plan, "sql": bypass}, package) == "UNAPPROVED_JOIN"
    for bypass in (
        sql.replace(
            "date_format(date_trunc('month', s.actual_checkout_at AT TIME ZONE 'Asia/Seoul'), '%Y-%m')",
            "date_format(date_trunc('month', s.actual_checkout_at), '%Y-%m')",
        ),
        sql.replace(
            "date_format(date_trunc('month', o.ordered_at), '%Y-%m')",
            "date_format(date_trunc('month', o.ordered_at AT TIME ZONE 'Asia/Seoul'), '%Y-%m')",
        ),
        sql.replace(
            "date_format(date_trunc('month', o.ordered_at), '%Y-%m') AS month",
            "date_trunc('month', o.ordered_at) AS month",
        ),
        sql.replace(
            "TIMESTAMP ':period_start 00:00:00'",
            "TIMESTAMP ':period_start 00:00:00 Asia/Seoul'",
        ),
    ):
        assert (
            support.g2_violation({**plan, "sql": bypass}, package)
            == "TIME_SEMANTICS_INVALID"
        )
    assert support.g2_violation(
        {**plan, "parameters": {**parameters, "unknown": "value"}}, package
    ) == "PARAMETERS_INVALID"
    duplicate = {**response, "parameters": [*response["parameters"], response["parameters"][-1]]}
    with pytest.raises(ValueError, match="unique"):
        ContractModelAdapter._plan(duplicate, "sql", package.parameter_bindings)


@pytest.mark.parametrize(
    "periods",
    (
        (
            SimpleNamespace(
                name="period_start", value_type="date", value="2026-05-01"
            ),
        ),
        (
            SimpleNamespace(
                name="period_start", value_type="date", value="2026-05-01"
            ),
            SimpleNamespace(
                name="period_start", value_type="date", value="2026-05-01"
            ),
        ),
        (
            SimpleNamespace(
                name="period_start", value_type="string", value="2026-05-01"
            ),
            SimpleNamespace(
                name="period_end_exclusive", value_type="date", value="2026-07-01"
            ),
        ),
        (
            SimpleNamespace(
                name="period_start", value_type="date", value="2026-02-30"
            ),
            SimpleNamespace(
                name="period_end_exclusive", value_type="date", value="2026-07-01"
            ),
        ),
        (
            SimpleNamespace(
                name="period_start", value_type="date", value="20260501"
            ),
            SimpleNamespace(
                name="period_end_exclusive", value_type="date", value="2026-07-01"
            ),
        ),
        (
            SimpleNamespace(
                name="period_start", value_type="date", value="2026-07-01"
            ),
            SimpleNamespace(
                name="period_end_exclusive", value_type="date", value="2026-05-01"
            ),
        ),
    ),
    ids=("missing", "duplicate", "type", "invalid-date", "invalid-format", "reversed"),
)
def test_three_source_context_rejects_invalid_period_bindings(tmp_path, periods):
    adapter = I2DataPlatformAdapter(
        "http://trino:8080",
        "runtime-user",
        binding_path=verified_binding_path(tmp_path),
        require_live_metadata=False,
    )
    support = PipelineSupport(adapter, ContextPackageBuilder())
    payload = AnalysisRequest(question="5월과 6월 GOLD 고객의 통합 매출")
    context = RequestContext(as_of=date(2026, 8, 1))
    assets = adapter.search_assets(payload.question, context.model_dump(mode="json"))
    package = support.build_context(payload, context, assets)
    filters = tuple(
        item
        for item in package.parameter_bindings
        if item.name not in {"period_start", "period_end_exclusive"}
    )

    with pytest.raises(ValueError, match="period"):
        ContractModelAdapter._context_package(
            {
                "package": replace(
                    package, parameter_bindings=(*periods, *filters)
                ),
                "context": context,
            }
        )


def test_versioned_three_source_uses_runtime_verified_contract_and_live_checks_runtime():
    adapter = I2DataPlatformAdapter(
        "http://trino:8080", "runtime-user", require_live_metadata=False
    )
    assets = adapter.search_assets(
        "5월과 6월 GOLD 고객의 객실·식음 통합 매출을 보여줘.",
        {"role": "hotel_analyst"},
    )

    assert len(assets) == 6
    assert {join_id for asset in assets for join_id in asset["join_ids"]} == {
        "pms_crm_pos_gold_revenue_month_v1"
    }

    live = I2DataPlatformAdapter("http://trino:8080", "runtime-user")
    live._trino.health = lambda: False
    with pytest.raises(ValueError, match="live Trino runtime verification"):
        live.search_assets(
            "5월과 6월 GOLD 고객의 객실·식음 통합 매출을 보여줘.",
            {"role": "hotel_analyst"},
        )


def test_live_mode_uses_current_datahub_response_instead_of_stale_evidence():
    live = I2DataPlatformAdapter("http://trino:8080", "runtime-user")
    live._trino.health = lambda: True
    live._datahub_health = lambda: True
    live._datahub_dataset = lambda urn: live_dataset(live, urn)

    assets = live.search_assets(
        "5월과 6월 GOLD 고객의 객실 매출을 보여줘.",
        {"role": "hotel_analyst"},
    )

    assert len(assets) == 5
    assert all(live.get_asset_schema(item["urn"])["columns"] for item in assets)


def test_live_raw_asset_accepts_datahub_name_without_catalog_prefix():
    live = I2DataPlatformAdapter("http://trino:8080", "runtime-user")
    live._trino.health = lambda: True
    live._datahub_health = lambda: True

    def dataset_without_catalog(urn):
        asset = next(item for item in live._three_source_assets if item["urn"] == urn)
        return {
            "urn": urn,
            "name": asset["name"],
            "status": {"removed": False},
            "schemaMetadata": {
                "name": ".".join(asset["fqn"].split(".")[1:]),
                "fields": [
                    {
                        "fieldPath": column,
                        "nativeDataType": asset.get("column_types", {}).get(
                            column, "contract"
                        ),
                    }
                    for column in asset["columns"]
                ],
            },
        }

    live._datahub_dataset = dataset_without_catalog

    assets = live.search_assets(
        "5월과 6월 GOLD 고객의 객실·식음 통합 매출을 보여줘.",
        {"role": "hotel_analyst"},
    )

    assert {item["fqn"] for item in assets} == {
        item["fqn"] for item in live._three_source_assets
    }


def test_live_datahub_removed_asset_fails_closed():
    live = simulated_verified_live_adapter()

    def removed_dataset(urn):
        dataset = live_dataset(live, urn)
        dataset["status"]["removed"] = True
        return dataset

    live._datahub_dataset = removed_dataset

    with pytest.raises(ValueError, match="metadata does not match"):
        live.search_assets("호텔 객실 매출", {"role": "hotel_analyst"})


def test_approved_pms_crm_join_includes_its_versioned_metric_registry():
    adapter = simulated_verified_live_adapter()
    adapter._datahub_dataset = lambda urn: live_dataset(adapter, urn)

    assets = adapter.search_assets(
        "GOLD 고객의 객실 매출",
        {"role": "hotel_analyst"},
    )

    assert len(assets) == 5
    metrics = [metric for asset in assets for metric in asset.get("metrics", ())]
    assert [metric["id"] for metric in metrics] == ["recognized_room_revenue"]
    assert metrics[0]["asset_fqn"] == "pms.public.pms_stays"


def test_live_raw_columns_do_not_evict_approved_contract_assets():
    adapter = simulated_verified_live_adapter()

    def dataset_with_unapproved_columns(urn):
        dataset = live_dataset(adapter, urn)
        dataset["schemaMetadata"]["fields"].extend(
            {"fieldPath": f"raw_extra_{index}"} for index in range(20)
        )
        return dataset

    adapter._datahub_dataset = dataset_with_unapproved_columns

    assets = adapter.search_assets(
        "GOLD 고객의 객실 매출",
        {"role": "hotel_analyst"},
    )

    assert len(assets) == 5
    assert all(
        not any(
            column["name"].startswith("raw_extra_")
            for column in adapter.get_asset_schema(asset["urn"])["columns"]
        )
        for asset in assets
    )


def test_versioned_three_source_requires_real_trino_pass(tmp_path):
    root = Path(__file__).resolve().parents[2]
    contract = json.loads(
        (root / "src/data/pms_crm_pos_context.i5.v1.json").read_text(encoding="utf-8")
    )
    contract["gold_evidence"]["runtime"]["status"] = "NOT_RUN"
    path = tmp_path / "not-verified.json"
    path.write_text(json.dumps(contract), encoding="utf-8")

    with pytest.raises(ValueError, match="three-source Context contract is invalid"):
        I2DataPlatformAdapter(
            "http://trino:8080",
            "runtime-user",
            three_source_path=path,
            require_live_metadata=False,
        )


def test_single_binder_supports_only_approved_typed_values():
    sql = (
        "SELECT 1 WHERE name = :required_filter_1 "
        "AND active = :required_filter_2 AND amount = :required_filter_3 "
        "AND business_date = :required_filter_4 LIMIT 1"
    )
    bound = I2DataPlatformAdapter._bind_parameters(
        sql,
        {
            "required_filter_1": {"value_type": "string", "value": "O'Brien"},
            "required_filter_2": {"value_type": "boolean", "value": False},
            "required_filter_3": {"value_type": "number", "value": 12.5},
            "required_filter_4": {"value_type": "date", "value": "2026-05-01"},
        },
    )

    assert "'O''Brien'" in bound
    assert "active = FALSE" in bound
    assert "amount = 12.5" in bound
    assert "business_date = DATE '2026-05-01'" in bound
    for value in (True, float("inf"), float("nan")):
        with pytest.raises(ValueError):
            I2DataPlatformAdapter._bind_parameters(
                "SELECT :required_filter_1",
                {"required_filter_1": {"value_type": "number", "value": value}},
            )
