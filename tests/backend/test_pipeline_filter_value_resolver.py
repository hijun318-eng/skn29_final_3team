"""사용자가 지목한 dimension 값을 실제 데이터로 재확인하는 resolve_filter_value가
서버 소유 parameterized SQL만 실행하고, 일치가 하나가 아니면 fail-closed 되는지 검증한다."""

from __future__ import annotations

import asyncio
from functools import wraps
from pathlib import Path
import sys

import pytest

BACKEND = Path(__file__).resolve().parents[2] / "app" / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.services.context.filter_value_resolver import (
    FilterValueUnresolvedError,
    ResolvedFilterValue,
    discover_dimension_values,
    resolve_filter_value,
)
from app.services.context.builder import ContextBuildError, ContextBuildErrorCode
from app.services.context.metric_resolver import (
    MetricResolver,
    _reconcile_filter_only_dimensions,
)
from app.services.context.filter_candidate_resolver import (
    dimension_member_receipts,
    resolve_filter_candidates,
)
from app.services.context.service import _inject_turn_filters


def async_test(function):
    @wraps(function)
    def run(*args, **kwargs):
        return asyncio.run(function(*args, **kwargs))

    return run


class _FakeAdapter:
    def __init__(self, rows: list[dict[str, object]], status: str = "SUCCEEDED") -> None:
        self._rows = rows
        self._status = status
        self.executed_sql: str | None = None
        self.execute_count = 0

    async def execute_query(self, sql, parameters, gate_token):
        assert parameters == {}
        assert gate_token
        self.executed_sql = sql
        self.execute_count += 1
        return {"query_id": "q-1"}

    async def get_query_status(self, query_id):
        assert query_id == "q-1"
        return {"status": self._status, "rows": self._rows}


@async_test
async def test_resolve_filter_value_returns_the_single_matched_value():
    adapter = _FakeAdapter(rows=[{"matched_value": "Sunset Hotel"}])

    resolved = await resolve_filter_value(
        adapter, "serving.room_daily", "hotel_name", "neq", "sunset"
    )

    assert resolved.asset_fqn == "serving.room_daily"
    assert resolved.column == "hotel_name"
    assert resolved.operator == "neq"
    assert resolved.value == "Sunset Hotel"
    assert '"hotel_name"' in adapter.executed_sql
    assert "FROM serving.room_daily" in adapter.executed_sql
    assert "sunset" in adapter.executed_sql.lower()


@async_test
async def test_resolve_filter_value_binds_only_the_canonical_candidate():
    adapter = _FakeAdapter(rows=[{"matched_value": "VISTA"}])

    resolved = await resolve_filter_value(
        adapter, "serving.operations_daily", "property_code", "eq", "VISTA"
    )

    assert resolved.value == "VISTA"
    assert "vista" in adapter.executed_sql.lower()


@async_test
async def test_discover_dimension_values_returns_only_a_complete_bounded_live_domain():
    adapter = _FakeAdapter(
        rows=[
            {"candidate_value": "VISTA"},
            {"candidate_value": "GRAND"},
            {"candidate_value": "DOUGLAS"},
        ]
    )

    values = await discover_dimension_values(
        adapter,
        "serving.operations_daily",
        "hotel_code",
    )

    assert values == ("VISTA", "GRAND", "DOUGLAS")
    assert "LIMIT 65" in adapter.executed_sql


@async_test
async def test_discover_dimension_values_rejects_a_partial_high_cardinality_domain():
    adapter = _FakeAdapter(
        rows=[{"candidate_value": f"VALUE_{index}"} for index in range(65)]
    )

    values = await discover_dimension_values(
        adapter,
        "serving.large_dimension",
        "entity_code",
    )

    assert values == ()


@async_test
async def test_metric_resolver_caches_bounded_dimension_domains_for_its_ttl():
    adapter = _FakeAdapter(rows=[{"candidate_value": "VISTA"}])
    resolver = MetricResolver(adapter, object())

    first = await resolver._dimension_values(
        "release-a", "serving.operations_daily", "hotel_code"
    )
    second = await resolver._dimension_values(
        "release-a", "serving.operations_daily", "hotel_code"
    )

    assert first == second == ("VISTA",)
    assert adapter.execute_count == 1


@async_test
async def test_metric_resolver_dimension_cache_is_release_bound_and_single_flight():
    adapter = _FakeAdapter(rows=[{"candidate_value": "VISTA"}])
    resolver = MetricResolver(adapter, object())

    same_release = await asyncio.gather(
        resolver._dimension_values(
            "release-a", "serving.operations_daily", "hotel_code"
        ),
        resolver._dimension_values(
            "release-a", "serving.operations_daily", "hotel_code"
        ),
    )
    next_release = await resolver._dimension_values(
        "release-b", "serving.operations_daily", "hotel_code"
    )

    assert same_release == [("VISTA",), ("VISTA",)]
    assert next_release == ("VISTA",)
    assert adapter.execute_count == 2


def _governed_metric_family():
    base_field = lambda column: {
        "asset_fqn": "serving.science.general_yields",
        "column": column,
    }
    segment_field = lambda column: {
        "asset_fqn": "serving.science.segment_yields",
        "column": column,
    }
    candidates = [
        {
            "id": "helium_yield",
            "dimensions": [base_field("station_id")],
            "candidate_rank": 1,
        },
        {
            "id": "argon_yield",
            "dimensions": [base_field("station_id")],
            "candidate_rank": 2,
        },
        {
            "id": "segment_helium_yield",
            "dimensions": [
                segment_field("station_id"),
                segment_field("observation_segment"),
            ],
            "candidate_rank": 3,
        },
        {
            "id": "segment_argon_yield",
            "dimensions": [
                segment_field("station_id"),
                segment_field("observation_segment"),
            ],
            "candidate_rank": 4,
        },
    ]
    glossary = {
        "helium_yield": ("Helium Yield",),
        "argon_yield": ("Argon Yield",),
        "segment_helium_yield": ("Segment Helium Yield",),
        "segment_argon_yield": ("Segment Argon Yield",),
    }
    dimension_terms = {
        "observation_segment": {
            "kind": "dimension",
            "aliases": ["Observation Segment"],
            "field": segment_field("observation_segment"),
        }
    }
    normalized = {
        "metric_resolution": "selected",
        "selected_metric_ids": ["helium_yield", "argon_yield"],
        "filter_candidates": [],
    }
    return candidates, glossary, dimension_terms, normalized


def _governed_family_business_terms(glossary):
    terms = {
        metric_id: {"kind": "metric", "aliases": list(aliases)}
        for metric_id, aliases in glossary.items()
    }
    terms["observation_segment"] = {
        "kind": "dimension",
        "aliases": ["Observation Segment"],
    }
    return terms


def test_filter_dimension_is_not_duplicated_as_a_period_comparison_group():
    normalized = {
        "analysis_operation": "period_comparison",
        "dimension_candidates": ["observation_segment"],
        "filter_candidates": [
            {
                "dimension_id": "observation_segment",
                "value_text": "OMEGA",
                "exclude": False,
            }
        ],
    }

    reconciled = _reconcile_filter_only_dimensions(normalized)

    assert reconciled["dimension_candidates"] == []
    assert reconciled["filter_candidates"] == normalized["filter_candidates"]
    assert _reconcile_filter_only_dimensions(
        {**normalized, "analysis_operation": "breakdown"}
    )["dimension_candidates"] == ["observation_segment"]


@async_test
async def test_metric_resolver_rechecks_one_omitted_governed_value_for_the_metric_family():
    adapter = _FakeAdapter(
        rows=[{"candidate_value": "OMEGA"}, {"candidate_value": "SIGMA"}]
    )
    resolver = MetricResolver(adapter, object())
    candidates, glossary, dimension_terms, normalized = _governed_metric_family()
    business_terms = _governed_family_business_terms(glossary)

    async def normalize():
        assert business_terms["observation_segment"]["value_candidates"] == [
            "OMEGA",
            "SIGMA",
        ]
        return {
            **normalized,
            "selected_metric_ids": [
                "segment_helium_yield",
                "segment_argon_yield",
            ],
            "filter_candidates": [
                {
                    "dimension_id": "observation_segment",
                    "value_text": "OMEGA",
                    "exclude": False,
                }
            ],
        }

    rechecked = await resolver._recheck_omitted_filter(
        normalized=normalized,
        question="Compare OMEGA Helium Yield and Argon Yield",
        candidates=candidates,
        glossary=glossary,
        dimension_terms=dimension_terms,
        business_terms=business_terms,
        cache_namespace="release-a",
        normalize=normalize,
    )

    assert rechecked["selected_metric_ids"] == [
        "segment_helium_yield",
        "segment_argon_yield",
    ]
    assert adapter.execute_count == 1


@async_test
async def test_approved_dimension_member_avoids_domain_distinct_and_keeps_receipt():
    adapter = _FakeAdapter(rows=[])
    resolver = MetricResolver(adapter, object())
    candidates, glossary, dimension_terms, normalized = _governed_metric_family()
    dimension_terms["observation_segment"]["members"] = [
        {
            "id": "omega",
            "term_urn": "urn:li:glossaryTerm:observation_segment_omega",
            "canonical_value": "OMEGA",
            "aliases": ["OMEGA", "오메가"],
            "version": "glossary-r4",
            "semantic_sha256": "a" * 64,
        }
    ]
    business_terms = _governed_family_business_terms(glossary)

    async def normalize():
        assert business_terms["observation_segment"]["value_candidates"] == [
            "OMEGA"
        ]
        assert {
            identifier
            for identifier, term in business_terms.items()
            if term["kind"] == "metric"
        } == {"segment_helium_yield", "segment_argon_yield"}
        return {
            **normalized,
            "selected_metric_ids": [
                "segment_helium_yield",
                "segment_argon_yield",
            ],
            "filter_candidates": [
                {
                    "dimension_id": "observation_segment",
                    "value_text": "OMEGA",
                    "exclude": False,
                }
            ],
        }

    rechecked = await resolver._recheck_omitted_filter(
        normalized=normalized,
        question="오메가 Helium Yield와 Argon Yield를 비교해줘",
        candidates=candidates,
        glossary=glossary,
        dimension_terms=dimension_terms,
        business_terms=business_terms,
        cache_namespace="release-a",
        normalize=normalize,
    )
    filters = resolve_filter_candidates(
        rechecked["filter_candidates"],
        {"observation_segment"},
        dimension_terms,
    )
    receipts = dimension_member_receipts(filters, dimension_terms)

    assert adapter.execute_count == 0
    assert filters[0]["value_text"] == "OMEGA"
    assert receipts[0]["term_urn"] == (
        "urn:li:glossaryTerm:observation_segment_omega"
    )


@async_test
async def test_metric_resolver_fails_closed_when_recheck_still_drops_the_governed_filter():
    adapter = _FakeAdapter(rows=[{"candidate_value": "OMEGA"}])
    resolver = MetricResolver(adapter, object())
    candidates, glossary, dimension_terms, normalized = _governed_metric_family()
    business_terms = _governed_family_business_terms(glossary)

    async def normalize():
        return dict(normalized)

    with pytest.raises(ContextBuildError) as raised:
        await resolver._recheck_omitted_filter(
            normalized=normalized,
            question="Compare OMEGA Helium Yield and Argon Yield",
            candidates=candidates,
            glossary=glossary,
            dimension_terms=dimension_terms,
            business_terms=business_terms,
            cache_namespace="release-a",
            normalize=normalize,
        )

    assert raised.value.code is ContextBuildErrorCode.QUERY_STRATEGY_NOT_APPROVED


@async_test
async def test_resolve_filter_value_rejects_no_match():
    adapter = _FakeAdapter(rows=[])

    with pytest.raises(FilterValueUnresolvedError):
        await resolve_filter_value(
            adapter, "serving.room_daily", "hotel_name", "eq", "nowhere"
        )


@async_test
async def test_resolve_filter_value_rejects_ambiguous_match():
    adapter = _FakeAdapter(
        rows=[{"matched_value": "Sunset Hotel"}, {"matched_value": "Sunset Resort"}]
    )

    with pytest.raises(FilterValueUnresolvedError):
        await resolve_filter_value(
            adapter, "serving.room_daily", "hotel_name", "eq", "sunset"
        )


@async_test
async def test_resolve_filter_value_rejects_non_succeeded_query():
    adapter = _FakeAdapter(rows=[{"matched_value": "Sunset Hotel"}], status="FAILED")

    with pytest.raises(FilterValueUnresolvedError):
        await resolve_filter_value(
            adapter, "serving.room_daily", "hotel_name", "eq", "sunset"
        )


def test_turn_filter_is_applied_to_ratio_operands_but_not_ratio_metric():
    """사용자 필터가 ratio 실행 operand에는 적용되고 ratio 정의 자체는 바꾸지 않는지 검증한다."""

    asset_fqn = "serving.analytics.hotel_operations_daily"
    assets = [
        {
            "fqn": asset_fqn,
            "metrics": [
                {
                    "id": "occupied_room_nights",
                    "aggregation": "sum",
                    "required_filters": [],
                },
                {
                    "id": "available_room_nights",
                    "aggregation": "sum",
                    "required_filters": [],
                },
                {
                    "id": "occupancy_rate",
                    "aggregation": "ratio",
                    "required_filters": [],
                },
            ],
        }
    ]

    filtered = _inject_turn_filters(
        assets,
        [
            ResolvedFilterValue(
                asset_fqn=asset_fqn,
                column="hotel_code",
                operator="eq",
                value="VISTA",
            )
        ],
    )

    metrics = {item["id"]: item for item in filtered[0]["metrics"]}
    expected = [
        {
            "field": "hotel_code",
            "operator": "eq",
            "value": "VISTA",
            "value_type": "string",
            "parameter": "user_filter_0",
        }
    ]
    assert metrics["occupied_room_nights"]["required_filters"] == expected
    assert metrics["available_room_nights"]["required_filters"] == expected
    assert metrics["occupancy_rate"]["required_filters"] == []
