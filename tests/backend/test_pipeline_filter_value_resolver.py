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
    discover_dimension_values,
    resolve_filter_value,
)
from app.services.context.metric_resolver import MetricResolver


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

    first = await resolver._dimension_values("serving.operations_daily", "hotel_code")
    second = await resolver._dimension_values("serving.operations_daily", "hotel_code")

    assert first == second == ("VISTA",)
    assert adapter.execute_count == 1


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
