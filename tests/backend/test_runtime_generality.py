"""독립 표현·조건 변화가 같은 runtime 후보 계약을 따르는지 검증한다.

질문은 production 분기나 prompt의 입력으로 재사용하지 않는 test-only Gold probe다.
정답 SQL·KPI 대신 Metric 순위, release receipt, 권한 실패만 비교한다.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import httpx
import pytest


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "app" / "backend"
for entry in (str(ROOT), str(BACKEND)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from app.adapters.datahub_catalog import DataHubCatalogClient
from app.adapters.governed_data_platform import GovernedDataPlatformAdapter
from app.adapters.trino_async import TrinoAsyncClient
from app.ports.data_platform import NoEntitledAssetsError
from tests.backend.test_governed_data_platform import (
    RuntimeTransport,
    _bundle_with_ratio,
)


# 세 의도마다 독립 표현·대상·기간 변화와 권한 변화를 한 번씩 검증한다.
_AUTHORIZED_CASES = (
    ("helium_total", "wording", "What is the total measured helium value?", "helium_yield"),
    ("helium_total", "entity", "Compare Helium aggregate by facility", "helium_yield"),
    ("helium_total", "period", "Show the previous quarter Helium aggregate", "helium_yield"),
    ("argon_total", "wording", "What is the total measured argon value?", "argon_yield"),
    ("argon_total", "entity", "Compare Argon output by facility", "argon_yield"),
    ("argon_total", "period", "Show the previous quarter Argon aggregate", "argon_yield"),
    (
        "helium_average",
        "wording",
        "What is the average helium yield per observation?",
        "helium_rate",
    ),
    ("helium_average", "entity", "Compare Helium rate by facility", "helium_rate"),
    ("helium_average", "period", "Show the previous quarter Helium average yield", "helium_rate"),
)

_UNENTITLED_CASES = (
    ("helium_total", "Helium yield for this month"),
    ("argon_total", "Argon output for this month"),
    ("helium_average", "Helium rate for this month"),
)


def _ranked_selectable_metric_ids(candidate_set) -> tuple[str, ...]:
    ranked = [
        (int(metric["candidate_rank"]), str(metric["id"]))
        for asset in candidate_set.assets
        for metric in asset.get("metrics", ())
        if metric.get("candidate_selectable") is True
    ]
    return tuple(metric_id for _rank, metric_id in sorted(ranked))


async def _exercise_runtime_generality() -> None:
    transport = RuntimeTransport(_bundle_with_ratio())
    datahub_http = httpx.AsyncClient(
        transport=httpx.MockTransport(transport.datahub)
    )
    trino_http = httpx.AsyncClient(
        transport=httpx.MockTransport(transport.trino)
    )
    adapter = GovernedDataPlatformAdapter(
        "https://trino.test",
        "runtime",
        datahub_client=DataHubCatalogClient(
            "http://datahub.test",
            client=datahub_http,
            page_size=2,
            max_entities=20,
        ),
        trino_client=TrinoAsyncClient(
            "https://trino.test",
            "runtime",
            "test-password",
            client=trino_http,
        ),
        search_mode="lexical",
    )
    receipts: set[tuple[str, str, str]] = set()
    try:
        for intent, variant, question, expected_metric_id in _AUTHORIZED_CASES:
            candidates = await adapter.search_asset_candidates(
                question,
                {"role": "analyst", "domains": [], "parameters": {}},
            )
            ranked_ids = _ranked_selectable_metric_ids(candidates)
            assert ranked_ids and ranked_ids[0] == expected_metric_id, (
                f"{intent}/{variant} resolved to {ranked_ids}"
            )
            receipts.add(
                (
                    candidates.context_release,
                    candidates.catalog_checksum,
                    candidates.canonical_checksum,
                )
            )

        assert len(receipts) == 1
        for _intent, question in _UNENTITLED_CASES:
            with pytest.raises(NoEntitledAssetsError):
                await adapter.search_asset_candidates(
                    question,
                    {
                        "role": "report_admin",
                        "domains": [],
                        "parameters": {},
                    },
                )
    finally:
        await adapter.aclose()
        await datahub_http.aclose()
        await trino_http.aclose()
        assert transport.trino_statements == []


def test_runtime_generality_uses_one_production_path_without_sql_fixtures() -> None:
    """12개 probe가 한 release-bound 후보 경로에서 일반화되거나 안전하게 닫힌다."""

    asyncio.run(_exercise_runtime_generality())
