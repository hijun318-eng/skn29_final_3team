"""v2 BUSINESS/SUPPORT 권한과 Node1 노출 경계를 일반 release fixture로 검증한다."""

from __future__ import annotations

import asyncio
import sys
from copy import deepcopy
from datetime import date
from pathlib import Path
from uuid import UUID

import pytest


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "app" / "backend"
DATAHUB = ROOT / "infrastructure" / "database" / "datahub"
DATA_TESTS = ROOT / "tests" / "data"
for entry in (str(ROOT), str(BACKEND), str(DATAHUB), str(DATA_TESTS)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from app.adapters.catalog_snapshot import (  # noqa: E402
    CatalogSnapshot,
    _active_term_records,
)
from app.adapters.datahub_metric_governance import runtime_metric_permitted  # noqa: E402
from app.adapters.datahub_metadata import parse_dataset, parse_glossary_term  # noqa: E402
from app.adapters.datahub_metadata_values import GovernedMetadataError  # noqa: E402
from app.adapters.query_governance import QueryGovernanceEngine  # noqa: E402
from app.adapters.model_context import metric_selection  # noqa: E402
from app.contracts import AnalysisRequest, RequestContext, ResolvedSlots, Role  # noqa: E402
from app.ports.data_platform import NoEntitledAssetsError  # noqa: E402
from app.services.analysis.responses import _business_metrics  # noqa: E402
from app.services.context.metric_resolver import (  # noqa: E402
    MetricResolver,
    _unique_business_metric_ids_from_sources,
    _validated_scoped_dimension_ids,
)
from app.services.context.metric_execution_scope import select_assets_for_metrics  # noqa: E402
from app.services.context.builder import (  # noqa: E402
    ContextBuildError,
    ContextBuildErrorCode,
    ContextPackageBuilder,
)
from app.services.context.service import PipelineContextService  # noqa: E402
from metadata_aspects import iter_aspects  # noqa: E402
from metadata_contract import validate_bundle  # noqa: E402
from test_datahub_metadata_publication import (  # noqa: E402
    _graphql_dataset,
    _graphql_term,
)
from test_metric_governance_v2 import _v2_bundle  # noqa: E402
from src.data.metric_governance import RUNTIME_GOVERNANCE_VERSION_V1  # noqa: E402


def test_metric_source_matching_uses_only_unique_live_aliases() -> None:
    """DataHub alias가 측정 구간에서 고유할 때만 모델 판정과 독립적으로 확정한다."""

    glossary = {
        "total_operating_revenue_krw": (
            "합성 통합 운영매출",
            "합성 운영매출",
        ),
        "other_metric": ("다른 지표", "공통 별칭"),
        "third_metric": ("세 번째 지표", "공통 별칭"),
    }

    assert _unique_business_metric_ids_from_sources(
        ["합성 통합 운영매출"], glossary
    ) == ["total_operating_revenue_krw"]
    assert _unique_business_metric_ids_from_sources(
        ["TOTAL_OPERATING_REVENUE_KRW"], glossary
    ) == ["total_operating_revenue_krw"]
    assert _unique_business_metric_ids_from_sources(
        ["호텔별 합성 통합 운영매출"], glossary
    ) == ["total_operating_revenue_krw"]
    assert _unique_business_metric_ids_from_sources(
        ["통합 운영매출"], glossary
    ) is None
    assert _unique_business_metric_ids_from_sources(["공통 별칭"], glossary) is None


def test_dimension_column_is_resolved_only_inside_selected_metric_asset() -> None:
    """동일 column을 가진 다른 asset 차원이 선택 metric의 차원을 덮지 못한다."""

    terms = {
        "operations_hotel_code": {
            "field": {
                "asset_fqn": "serving.analytics_v4_3.hotel_operations_daily",
                "column": "hotel_code",
            }
        },
        "banquet_hotel_code": {
            "field": {
                "asset_fqn": "serving.analytics_v4_3.banquet_daily",
                "column": "hotel_code",
            }
        },
    }

    assert _validated_scoped_dimension_ids(
        ["hotel_code"],
        terms,
        {"serving.analytics_v4_3.hotel_operations_daily"},
    ) == ["operations_hotel_code"]


def _runtime_bundle(
    *,
    asset_roles: tuple[str, ...] = ("analyst",),
    metric_roles: tuple[str, ...] = ("analyst",),
    contains_pii: bool = False,
) -> dict:
    bundle = _v2_bundle()
    for asset in bundle["schema_context"]["assets"]:
        asset["entitlements"]["roles"] = list(asset_roles)
    for rule in bundle["metric_rules"]:
        permission = rule["governance"]["permission"]
        permission["roles"] = list(metric_roles)
        permission["contains_pii"] = contains_pii
    validate_bundle(bundle)
    return bundle


def _snapshot(bundle: dict) -> CatalogSnapshot:
    aspects = {
        (entity_type, urn, aspect): value
        for entity_type, urn, aspect, value in iter_aspects(bundle)
    }
    # publication test helper가 요구하는 URN -> aspect map을 같은 fixture에서 재구성한다.
    aspect_index: dict[str, dict[str, object]] = {}
    for (_entity_type, urn, name), value in aspects.items():
        aspect_index.setdefault(urn, {})[name] = value
    datasets = tuple(
        parse_dataset(_graphql_dataset(asset, bundle, aspect_index))
        for asset in bundle["schema_context"]["assets"]
    )
    terms = []
    for definition in bundle["metric_terms"]:
        raw = _graphql_term(definition, aspect_index)
        raw["status"] = {
            "removed": False,
            "lifecycleStage": {
                "urn": definition["approved_lifecycle_urn"],
                "name": "APPROVED",
            },
        }
        terms.append(parse_glossary_term(raw))
    return CatalogSnapshot(
        datasets_by_urn={item.urn: item for item in datasets},
        datasets_by_fqn={item.fqn: item for item in datasets},
        terms_by_urn={item.urn: item for item in terms},
        terms_by_id={item.id: item for item in terms},
        governance_entities={
            name: tuple(deepcopy(values))
            for name, values in bundle["governance_entities"].items()
        },
    )


class _Loader:
    def __init__(self, snapshot: CatalogSnapshot) -> None:
        self.snapshot = snapshot

    async def load(self) -> CatalogSnapshot:
        return self.snapshot


class _Schema:
    async def verify(self, _datasets) -> None:
        return None


def _engine(bundle: dict) -> QueryGovernanceEngine:
    engine = QueryGovernanceEngine(object(), _Schema(), search_mode="lexical")
    engine._loader = _Loader(_snapshot(bundle))
    return engine


def test_v1_metric_is_read_compatible_but_never_runtime_permitted() -> None:
    legacy_metric = {
        "governance_version": RUNTIME_GOVERNANCE_VERSION_V1,
        "allowed_roles": ("analyst",),
        "contains_pii": False,
    }

    assert runtime_metric_permitted(legacy_metric, "analyst") is False
    assert runtime_metric_permitted(legacy_metric, "platform_admin") is False


def test_soft_deleted_historical_term_is_excluded_from_runtime_candidates() -> None:
    active = {"urn": "urn:li:glossaryTerm:active", "status": {"removed": False}}
    retired = {"urn": "urn:li:glossaryTerm:retired", "status": {"removed": True}}

    assert _active_term_records((active, retired)) == (active,)
    with pytest.raises(GovernedMetadataError, match="status is incomplete"):
        _active_term_records(({"urn": "urn:li:glossaryTerm:incomplete"},))


def test_support_operands_execute_but_are_not_business_candidates() -> None:
    engine = _engine(_runtime_bundle())

    assets = asyncio.run(
        engine.search_assets(
            "Amount per Event",
            {"role": "analyst", "parameters": {"active": True}},
        )
    )
    metrics = {
        item["id"]: item
        for asset in assets
        for item in asset["metrics"]
    }

    assert set(metrics) == {"amount_total", "event_count", "amount_per_event"}
    assert metrics["amount_total"]["visibility"] == "SUPPORT"
    assert metrics["event_count"]["visibility"] == "SUPPORT"
    assert metrics["amount_per_event"]["visibility"] == "BUSINESS"
    assert assets[0]["entitled_metric_ids"] == ["amount_per_event"]


def test_platform_admin_inherits_existing_metric_and_asset_entitlements() -> None:
    engine = _engine(_runtime_bundle())

    assets = asyncio.run(
        engine.search_assets(
            "Amount per Event",
            {"role": "platform_admin", "parameters": {"active": True}},
        )
    )

    assert assets[0]["entitled_metric_ids"] == ["amount_per_event"]
    assert {item["id"] for item in assets[0]["metrics"]} == {
        "amount_total",
        "event_count",
        "amount_per_event",
    }


def test_metric_role_and_pii_policy_fail_closed_after_asset_entitlement() -> None:
    role_restricted = _engine(
        _runtime_bundle(
            asset_roles=("analyst", "data_admin"),
            metric_roles=("data_admin",),
        )
    )
    with pytest.raises(NoEntitledAssetsError, match="business metric"):
        asyncio.run(
            role_restricted.search_assets(
                "Amount per Event",
                {"role": "analyst", "parameters": {"active": True}},
            )
        )

    pii = _engine(_runtime_bundle(contains_pii=True))
    with pytest.raises(NoEntitledAssetsError, match="business metric"):
        asyncio.run(
            pii.search_assets(
                "Amount per Event",
                {"role": "analyst", "parameters": {"active": True}},
            )
        )
    with pytest.raises(NoEntitledAssetsError, match="business metric"):
        asyncio.run(
            pii.search_assets(
                "Amount per Event",
                {"role": "platform_admin", "parameters": {"active": True}},
            )
        )


class _Normalizer:
    def __init__(self) -> None:
        self.input: dict | None = None

    async def normalize_question(self, payload: dict) -> dict:
        self.input = deepcopy(payload)
        return {
            "normalized_question": "Amount per Event for the selected period",
            "intent_candidates": ["aggregate"],
            "measurement_source_text": "Amount per Event",
            "measurement_source_texts": ["Amount per Event"],
            "metric_candidates": ["amount_per_event"],
            "metric_resolution": "selected",
            "selected_metric_id": "amount_per_event",
            "selected_metric_ids": ["amount_per_event"],
            "analysis_operation": "aggregate",
            "result_limit": None,
            "dimension_candidates": [],
            "filter_candidates": [],
            "period_candidates": [
                {
                    "start": "2026-08-01T00:00:00+09:00",
                    "end_exclusive": "2026-08-02T00:00:00+09:00",
                    "source_text": "2026-08-01",
                }
            ],
            "period_relationship": "single",
            "requested_route": "general",
            "presentation_type": "table",
            "is_elliptical": False,
        }


class _AmbiguousNormalizer(_Normalizer):
    async def normalize_question(self, payload: dict) -> dict:
        result = await super().normalize_question(payload)
        result["measurement_source_text"] = "measurement"
        result["measurement_source_texts"] = ["measurement"]
        result["metric_candidates"] = ["amount_per_event", "account_count"]
        result["metric_resolution"] = "ambiguous"
        result["selected_metric_id"] = None
        result["selected_metric_ids"] = []
        return result


class _MultiMetricNormalizer(_Normalizer):
    async def normalize_question(self, payload: dict) -> dict:
        result = await super().normalize_question(payload)
        result.update(
            {
                "normalized_question": "Amount per Event and Account Count for the selected period",
                "measurement_source_text": None,
                "measurement_source_texts": ["Amount per Event", "Account Count"],
                "metric_candidates": ["amount_per_event", "account_count"],
                "metric_resolution": "selected",
                "selected_metric_id": None,
                "selected_metric_ids": ["amount_per_event", "account_count"],
            }
        )
        return result


class _InconsistentCompatibilityProjectionNormalizer(_MultiMetricNormalizer):
    async def normalize_question(self, payload: dict) -> dict:
        """권위 목록은 맞지만 단일 호환 projection만 잘못 반환하는 모델 응답."""

        result = await super().normalize_question(payload)
        result["selected_metric_id"] = "amount_per_event"
        result["measurement_source_text"] = "Amount per Event"
        return result


class _CrossMetricComparisonNormalizer(_MultiMetricNormalizer):
    async def normalize_question(self, payload: dict) -> dict:
        result = await super().normalize_question(payload)
        result.update(
            {
                "intent_candidates": ["period_comparison"],
                "analysis_operation": "period_comparison",
                "period_candidates": [],
                "period_relationship": "comparison",
                "ambiguity": {
                    "is_ambiguous": False,
                    "reasons": [],
                    "clarification_question": None,
                },
            }
        )
        return result


class _TwoPeriodMultiMetricNormalizer(_CrossMetricComparisonNormalizer):
    async def normalize_question(self, payload: dict) -> dict:
        result = await super().normalize_question(payload)
        result["period_candidates"] = [
            {
                "start": "2026-07-01T00:00:00+09:00",
                "end_exclusive": "2026-08-01T00:00:00+09:00",
                "source_text": "first period",
            },
            {
                "start": "2026-08-01T00:00:00+09:00",
                "end_exclusive": "2026-08-19T00:00:00+09:00",
                "source_text": "second period",
            },
        ]
        return result


class _InconsistentSelectedNormalizer(_Normalizer):
    async def normalize_question(self, payload: dict) -> dict:
        result = await super().normalize_question(payload)
        result.update(
            {
                "normalized_question": "Ambiguous measurement for the selected period",
                "measurement_source_text": "ambiguous measurement",
                "measurement_source_texts": ["ambiguous measurement"],
                "metric_candidates": ["amount_per_event", "account_count"],
                "metric_resolution": "selected",
                "selected_metric_id": "amount_per_event",
                "selected_metric_ids": ["amount_per_event"],
            }
        )
        return result


class _SupportNormalizer(_Normalizer):
    async def normalize_question(self, payload: dict) -> dict:
        result = await super().normalize_question(payload)
        result["normalized_question"] = "Support amount_total for the selected period"
        result["measurement_source_text"] = "Support amount_total"
        result["measurement_source_texts"] = ["Support amount_total"]
        result["metric_candidates"] = ["amount_total"]
        result["metric_resolution"] = "unsupported"
        result["selected_metric_id"] = None
        result["selected_metric_ids"] = []
        result["analysis_operation"] = None
        return result


class _UnsupportedNormalizer(_Normalizer):
    async def normalize_question(self, payload: dict) -> dict:
        result = await super().normalize_question(payload)
        result["normalized_question"] = "Unapproved measurement for the selected period"
        result["measurement_source_text"] = "Unapproved measurement"
        result["measurement_source_texts"] = ["Unapproved measurement"]
        result["metric_candidates"] = []
        result["metric_resolution"] = "unsupported"
        result["selected_metric_id"] = None
        result["selected_metric_ids"] = []
        result["analysis_operation"] = None
        return result


class _MissingNormalizer(_Normalizer):
    async def normalize_question(self, payload: dict) -> dict:
        result = await super().normalize_question(payload)
        result["normalized_question"] = "Selected period only"
        result["measurement_source_text"] = None
        result["measurement_source_texts"] = []
        result["metric_candidates"] = []
        result["metric_resolution"] = "missing"
        result["selected_metric_id"] = None
        result["selected_metric_ids"] = []
        result["analysis_operation"] = None
        return result


def test_node1_can_identify_support_metric_but_only_business_metric_is_selectable() -> None:
    engine = _engine(_runtime_bundle())
    assets = asyncio.run(
        engine.search_assets(
            "Amount per Event",
            {"role": "analyst", "parameters": {"active": True}},
        )
    )
    model = _Normalizer()
    resolver = MetricResolver(engine, model)
    context = RequestContext(
        request_id=UUID("10000000-0000-0000-0000-000000000001"),
        trace_id="v2-runtime-governance",
        user_id=UUID("20000000-0000-0000-0000-000000000002"),
        role=Role.ANALYST,
        as_of=date(2026, 8, 19),
    )

    selected_assets, _question, structured = asyncio.run(
        resolver.resolve(
            AnalysisRequest(question="Amount per Event", parameters={"active": True}),
            context,
            assets,
        )
    )

    assert model.input is not None
    assert {
        identifier
        for identifier, term in model.input["business_terms"].items()
        if term["kind"] == "metric"
    } == {"amount_per_event"}
    assert {
        identifier
        for identifier, term in model.input["business_terms"].items()
        if term["kind"] == "support_metric"
    } == {"amount_total", "event_count"}
    assert structured["selected_metric_id"] == "amount_per_event"
    assert set(structured["metric_ids"]) == {
        "amount_total",
        "event_count",
        "amount_per_event",
    }
    assert set(structured["metric_terms"]) == {"amount_per_event"}
    assert {
        metric["id"]
        for asset in selected_assets
        for metric in asset["metrics"]
    } == {"amount_total", "event_count", "amount_per_event"}

    package = asyncio.run(
        PipelineContextService(engine, ContextPackageBuilder()).build(
            AnalysisRequest(
                question="Amount per Event",
                parameters={"active": True},
            ),
            context,
            selected_assets,
            structured,
        )
    )
    assert {metric.id for metric in package.metrics} == {
        "amount_total",
        "event_count",
        "amount_per_event",
    }
    assert {term.id for term in package.metric_terms} == {"amount_per_event"}
    assert {metric.id for metric in _business_metrics(package)} == {
        "amount_per_event"
    }
    assert metric_selection(selected_assets, package)["selected_metric_id"] == (
        "amount_per_event"
    )


def test_node1_preserves_multiple_explicit_business_metrics_as_one_analysis_scope() -> None:
    engine = _engine(_runtime_bundle())
    question = "Amount per Event and Account Count"
    assets = asyncio.run(
        engine.search_assets(
            question,
            {"role": "analyst", "parameters": {"active": True}},
        )
    )
    resolver = MetricResolver(engine, _MultiMetricNormalizer())
    context = RequestContext(
        request_id=UUID("10000000-0000-0000-0000-000000000001"),
        trace_id="v2-runtime-multi-metric",
        user_id=UUID("20000000-0000-0000-0000-000000000002"),
        role=Role.ANALYST,
        as_of=date(2026, 8, 19),
    )

    selected_assets, _question, structured = asyncio.run(
        resolver.resolve(
            AnalysisRequest(question=question, parameters={"active": True}),
            context,
            assets,
        )
    )

    assert structured["selected_metric_id"] is None
    assert structured["selected_metric_ids"] == [
        "amount_per_event",
        "account_count",
    ]
    assert set(structured["metric_ids"]) == {
        "amount_total",
        "event_count",
        "amount_per_event",
        "account_count",
    }
    assert set(structured["metric_terms"]) == {
        "amount_per_event",
        "account_count",
    }
    assert {
        metric["id"]
        for asset in selected_assets
        for metric in asset["metrics"]
    } == set(structured["metric_ids"])


def test_node1_compatibility_projections_are_derived_from_authoritative_lists() -> None:
    """중복 단일 필드 불일치는 유효한 복수 지표 요청을 서비스 장애로 만들지 않는다."""

    engine = _engine(_runtime_bundle())
    question = "Amount per Event and Account Count"
    assets = asyncio.run(
        engine.search_assets(
            question,
            {"role": "analyst", "parameters": {"active": True}},
        )
    )
    resolver = MetricResolver(engine, _InconsistentCompatibilityProjectionNormalizer())
    context = RequestContext(
        request_id=UUID("10000000-0000-0000-0000-000000000001"),
        trace_id="v2-runtime-projection-reconciliation",
        user_id=UUID("20000000-0000-0000-0000-000000000002"),
        role=Role.ANALYST,
        as_of=date(2026, 8, 19),
    )

    _selected_assets, _question, structured = asyncio.run(
        resolver.resolve(
            AnalysisRequest(question=question, parameters={"active": True}),
            context,
            assets,
        )
    )

    assert structured["selected_metric_id"] is None
    assert structured["selected_metric_ids"] == [
        "amount_per_event",
        "account_count",
    ]


def test_cross_metric_comparison_uses_one_shared_period_without_requesting_a_second() -> None:
    engine = _engine(_runtime_bundle())
    question = "Amount per Event and Account Count"
    assets = asyncio.run(
        engine.search_assets(
            question,
            {"role": "analyst", "parameters": {"active": True}},
        )
    )
    resolver = MetricResolver(engine, _CrossMetricComparisonNormalizer())
    context = RequestContext(
        request_id=UUID("10000000-0000-0000-0000-000000000001"),
        trace_id="v2-runtime-cross-metric-comparison",
        user_id=UUID("20000000-0000-0000-0000-000000000002"),
        role=Role.ANALYST,
        as_of=date(2026, 8, 19),
    )

    _selected_assets, _question, structured = asyncio.run(
        resolver.resolve(
            AnalysisRequest(
                question=question,
                parameters={"active": True},
                resolved_slots=ResolvedSlots(
                    period_start="2026-08-01",
                    period_end_exclusive="2026-08-19",
                ),
            ),
            context,
            assets,
        )
    )

    assert structured["selected_metric_ids"] == [
        "amount_per_event",
        "account_count",
    ]
    assert structured["analysis_operation"] == "aggregate"
    assert structured["intent_candidates"] == ["aggregate"]
    assert structured["period_relationship"] == "single"
    assert structured["period_candidates"] == [
        {
            "start": "2026-08-01",
            "end_exclusive": "2026-08-19",
            "source_text": "2026-08-01 ~ 2026-08-19",
        }
    ]


def test_two_period_multi_metric_comparison_remains_period_comparison() -> None:
    engine = _engine(_runtime_bundle())
    question = "Amount per Event and Account Count across two periods"
    assets = asyncio.run(
        engine.search_assets(
            question,
            {"role": "analyst", "parameters": {"active": True}},
        )
    )
    resolver = MetricResolver(engine, _TwoPeriodMultiMetricNormalizer())
    context = RequestContext(
        request_id=UUID("10000000-0000-0000-0000-000000000001"),
        trace_id="v2-runtime-two-period-comparison",
        user_id=UUID("20000000-0000-0000-0000-000000000002"),
        role=Role.ANALYST,
        as_of=date(2026, 8, 19),
    )

    with pytest.raises(ContextBuildError, match="Ratio metric"):
        asyncio.run(
            resolver.resolve(
                AnalysisRequest(question=question, parameters={"active": True}),
                context,
                assets,
            )
        )


def test_support_metric_search_reaches_asset_and_returns_typed_unavailable_error() -> None:
    engine = _engine(_runtime_bundle())
    assets = asyncio.run(
        engine.search_assets(
            "Support amount_total",
            {"role": "analyst", "parameters": {"active": True}},
        )
    )
    resolver = MetricResolver(engine, _SupportNormalizer())
    context = RequestContext(
        request_id=UUID("10000000-0000-0000-0000-000000000001"),
        trace_id="v2-runtime-support-metric",
        user_id=UUID("20000000-0000-0000-0000-000000000002"),
        role=Role.ANALYST,
        as_of=date(2026, 8, 20),
    )

    with pytest.raises(ContextBuildError) as raised:
        asyncio.run(
            resolver.resolve(
                AnalysisRequest(
                    question="Support amount_total",
                    parameters={"active": True},
                ),
                context,
                assets,
            )
        )

    assert raised.value.code is ContextBuildErrorCode.METRIC_NOT_AVAILABLE
    assert "Support amount_total" in str(raised.value)
    assert raised.value.suggestions == ()


def test_support_metric_model_signal_must_be_internally_consistent() -> None:
    class _InconsistentSupportNormalizer(_SupportNormalizer):
        async def normalize_question(self, payload: dict) -> dict:
            result = await super().normalize_question(payload)
            result["metric_resolution"] = "ambiguous"
            return result

    engine = _engine(_runtime_bundle())
    assets = asyncio.run(
        engine.search_assets(
            "Support amount_total",
            {"role": "analyst", "parameters": {"active": True}},
        )
    )
    resolver = MetricResolver(engine, _InconsistentSupportNormalizer())
    context = RequestContext(
        request_id=UUID("10000000-0000-0000-0000-000000000001"),
        trace_id="v2-runtime-inconsistent-support-metric",
        user_id=UUID("20000000-0000-0000-0000-000000000002"),
        role=Role.ANALYST,
        as_of=date(2026, 8, 20),
    )

    with pytest.raises(ValueError, match="support 지표 판정과 후보"):
        asyncio.run(
            resolver.resolve(
                AnalysisRequest(
                    question="Support amount_total",
                    parameters={"active": True},
                ),
                context,
                assets,
            )
        )


def test_unresolved_metric_returns_typed_options_instead_of_internal_error() -> None:
    engine = _engine(_runtime_bundle())
    amount_assets = asyncio.run(
        engine.search_assets(
            "Amount per Event",
            {"role": "analyst", "parameters": {"active": True}},
        )
    )
    account_assets = asyncio.run(
        engine.search_assets(
            "account",
            {"role": "analyst", "parameters": {"active": True}},
        )
    )
    assets = amount_assets + account_assets
    resolver = MetricResolver(engine, _AmbiguousNormalizer())
    context = RequestContext(
        request_id=UUID("10000000-0000-0000-0000-000000000001"),
        trace_id="v2-runtime-ambiguous-metric",
        user_id=UUID("20000000-0000-0000-0000-000000000002"),
        role=Role.ANALYST,
        as_of=date(2026, 8, 20),
    )

    with pytest.raises(ContextBuildError) as raised:
        asyncio.run(
            resolver.resolve(
                AnalysisRequest(
                    question="ambiguous measurement",
                    parameters={"active": True},
                ),
                context,
                assets,
            )
        )

    assert {
        option.metric_id for option in raised.value.disambiguation_options
    } == {"amount_per_event", "account_count"}
    assert raised.value.partial_context is not None
    assert raised.value.partial_context["period_candidates"][0]["start"].startswith(
        "2026-08-01"
    )
    assert raised.value.partial_context["selected_metric_id"] is None


def test_inconsistent_selected_metric_is_downgraded_to_safe_clarification() -> None:
    engine = _engine(_runtime_bundle())
    amount_assets = asyncio.run(
        engine.search_assets(
            "Amount per Event",
            {"role": "analyst", "parameters": {"active": True}},
        )
    )
    account_assets = asyncio.run(
        engine.search_assets(
            "account",
            {"role": "analyst", "parameters": {"active": True}},
        )
    )
    resolver = MetricResolver(engine, _InconsistentSelectedNormalizer())
    context = RequestContext(
        request_id=UUID("10000000-0000-0000-0000-000000000001"),
        trace_id="v2-runtime-inconsistent-selected-metric",
        user_id=UUID("20000000-0000-0000-0000-000000000002"),
        role=Role.ANALYST,
        as_of=date(2026, 8, 20),
    )

    with pytest.raises(ContextBuildError) as raised:
        asyncio.run(
            resolver.resolve(
                AnalysisRequest(
                    question="ambiguous measurement",
                    parameters={"active": True},
                ),
                context,
                amount_assets + account_assets,
            )
        )

    assert raised.value.code is ContextBuildErrorCode.INVALID_METRIC
    assert {
        option.metric_id for option in raised.value.disambiguation_options
    } == {"amount_per_event", "account_count"}
    assert raised.value.partial_context is not None
    assert raised.value.partial_context["selected_metric_id"] is None
    assert raised.value.partial_context["selected_metric_ids"] == []
    assert raised.value.partial_context["metric_resolution"] == "ambiguous"


def test_unsupported_measurement_does_not_fall_back_to_all_business_metrics() -> None:
    engine = _engine(_runtime_bundle())
    assets = asyncio.run(
        engine.search_assets(
            "Amount per Event",
            {"role": "analyst", "parameters": {"active": True}},
        )
    )
    resolver = MetricResolver(engine, _UnsupportedNormalizer())
    context = RequestContext(
        request_id=UUID("10000000-0000-0000-0000-000000000001"),
        trace_id="v2-runtime-unsupported-metric",
        user_id=UUID("20000000-0000-0000-0000-000000000002"),
        role=Role.ANALYST,
        as_of=date(2026, 8, 20),
    )

    with pytest.raises(ContextBuildError) as raised:
        asyncio.run(
            resolver.resolve(
                AnalysisRequest(
                    question="Unapproved measurement",
                    parameters={"active": True},
                ),
                context,
                assets,
            )
        )

    assert raised.value.code is ContextBuildErrorCode.METRIC_NOT_AVAILABLE
    assert raised.value.disambiguation_options == ()
    assert raised.value.suggestions == ()


def test_missing_measurement_alone_offers_approved_business_metrics() -> None:
    engine = _engine(_runtime_bundle())
    assets = asyncio.run(
        engine.search_assets(
            "Amount per Event",
            {"role": "analyst", "parameters": {"active": True}},
        )
    )
    resolver = MetricResolver(engine, _MissingNormalizer())
    context = RequestContext(
        request_id=UUID("10000000-0000-0000-0000-000000000001"),
        trace_id="v2-runtime-missing-metric",
        user_id=UUID("20000000-0000-0000-0000-000000000002"),
        role=Role.ANALYST,
        as_of=date(2026, 8, 20),
    )

    with pytest.raises(ContextBuildError) as raised:
        asyncio.run(
            resolver.resolve(
                AnalysisRequest(
                    question="Selected period only",
                    parameters={"active": True},
                ),
                context,
                assets,
            )
        )

    assert raised.value.code is ContextBuildErrorCode.INVALID_METRIC
    assert [
        option.metric_id for option in raised.value.disambiguation_options
    ] == ["amount_per_event"]


def test_selected_v2_metric_prunes_unapproved_join_edges() -> None:
    metric = {
        "id": "governed_value",
        "visibility": "BUSINESS",
        "governance_version": "ANSWERVICE-RUNTIME-GOVERNANCE-v2",
        "allowed_join_ids": ["approved_edge"],
        "join_required": True,
    }
    assets = [
        {
            "fqn": "generic.core.fact",
            "metrics": [metric],
            "join_ids": ["approved_edge", "unapproved_edge"],
            "join_graph": {
                "edges": [
                    {"id": "approved_edge"},
                    {"id": "unapproved_edge"},
                ]
            },
        },
        {
            "fqn": "generic.core.dimension",
            "metrics": [],
            "join_ids": ["approved_edge", "unapproved_edge"],
            "join_graph": {
                "edges": [
                    {"id": "approved_edge"},
                    {"id": "unapproved_edge"},
                ]
            },
        },
    ]

    selected = select_assets_for_metrics(assets, {"governed_value"}, None)

    assert all(asset["join_ids"] == ["approved_edge"] for asset in selected)
    assert all(
        [edge["id"] for edge in asset["join_graph"]["edges"]]
        == ["approved_edge"]
        for asset in selected
    )

    missing = deepcopy(assets)
    for asset in missing:
        asset["join_ids"] = ["unapproved_edge"]
    with pytest.raises(ContextBuildError, match="요구한 승인 join edge"):
        select_assets_for_metrics(missing, {"governed_value"}, None)
