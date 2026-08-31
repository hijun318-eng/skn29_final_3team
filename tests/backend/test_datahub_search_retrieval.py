"""DataHub Core 질문 검색 경로(enumeration 분리·query plan·shadow·fail-closed)를 검증한다."""

from __future__ import annotations

import asyncio
import json
import sys
import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import httpx

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "app" / "backend") not in sys.path:
    sys.path.insert(0, str(ROOT / "app" / "backend"))

from app.adapters.datahub_catalog import (  # noqa: E402
    DataHubCatalogClient,
    DataHubCatalogError,
    DataHubSearchHit,
    DataHubSearchUnavailableError,
)
from app.adapters.datahub_query_plan import (  # noqa: E402
    DataHubQueryPlanError,
    GovernedPhraseIndex,
    escape_search_text,
    ordered_query_tokens,
    plan_search_queries,
)
from app.adapters.query_governance import (  # noqa: E402
    DEFAULT_CANDIDATE_SEARCH_COUNT,
    QueryGovernanceEngine,
)
from app.adapters.query_search_evidence import (  # noqa: E402
    compact_candidate_assets,
    governed_metric_specialization_ids,
    unicode_tokens,
)
from app.adapters.trino_async import TrinoAsyncClient  # noqa: E402
from app.adapters.governed_data_platform import GovernedDataPlatformAdapter  # noqa: E402
from app.ports.data_platform import (  # noqa: E402
    MetadataUnavailableError,
    NoEntitledAssetsError,
    NoMetricMatchError,
)
from tests.backend.test_governed_data_platform import (  # noqa: E402
    RuntimeTransport,
    _bundle,
    _candidate_assets,
)
from src.data.governance_contract import datahub_schema_sha1  # noqa: E402


class KoreanQueryPlanTests(unittest.TestCase):
    def test_plan_keeps_bounds_and_generates_recall_variants(self) -> None:
        variants = plan_search_queries("지난달 객실 매출 보여줘")

        self.assertEqual(["phrase", "tokens", "compounds"], [item.label for item in variants])
        self.assertEqual('"지난달 객실 매출 보여줘"', variants[0].query)
        # AND 결합으로 recall이 0이 되지 않도록 token 변형은 OR로 결합한다.
        self.assertIn(" OR ", variants[1].query)
        # 띄어쓰기 없는 한국어 복합어를 특정 지표 사전 없이 일반 규칙으로 만든다.
        self.assertIn("객실매출", variants[2].query)

    def test_variant_and_token_bounds_are_enforced(self) -> None:
        question = " ".join(f"토큰{index}" for index in range(30))

        variants = plan_search_queries(question, max_variants=2, max_tokens=3)

        self.assertEqual(2, len(variants))
        self.assertEqual(3, len(ordered_query_tokens(question, max_tokens=3)))

    def test_query_syntax_injection_is_escaped(self) -> None:
        variants = plan_search_queries('urn:li:dataset:* OR name:"secret"')

        for variant in variants:
            body = variant.query.strip('"')
            self.assertNotIn(":", body)
            self.assertNotIn("*", body)
        self.assertEqual("\\+a\\:b", escape_search_text("+a:b"))
        token_query = next(item.query for item in variants if item.label == "tokens")
        self.assertIn('"or"', token_query)

    def test_connector_acronym_is_preserved_without_metric_specific_mapping(self) -> None:
        variants = plan_search_queries("F&B Revenue")

        self.assertEqual(("f&b", "revenue"), ordered_query_tokens("F&B Revenue"))
        self.assertIn("f&b", variants[0].query)
        self.assertIn("f&b", variants[1].query)

    def test_release_phrase_index_matches_spaced_compound_and_ascii_boundaries(self) -> None:
        index = GovernedPhraseIndex(("객실 매출", "룸 매출", "ADR", "F&B Revenue"))

        self.assertEqual(("객실 매출",), index.match("지난달 객실 매출을 보여줘"))
        self.assertEqual(("객실매출",), index.match("지난달 객실매출을 보여줘"))
        self.assertEqual((), index.match("address 목록"))
        self.assertEqual(("adr",), index.match("ADR은 얼마야"))

    def test_governed_phrase_is_planned_first_without_question_specific_rules(self) -> None:
        variants = plan_search_queries(
            "지난달 객실 매출을 보여줘",
            governed_phrases=("객실 매출",),
        )

        self.assertEqual("governed-1", variants[0].label)
        self.assertEqual('"객실 매출"', variants[0].query)
        self.assertEqual(2, len(variants))

    def test_two_independent_unicode_token_relations_form_a_bounded_hint(self) -> None:
        index = GovernedPhraseIndex(
            ("객실 점유율", "식음료 매출", "객실 매출", "ADR")
        )

        self.assertEqual(
            ("객실 점유율",),
            index.match("점유된 객실박의 비율이 궁금해"),
        )
        self.assertEqual(
            ("식음료 매출",),
            index.match("환불을 반영한 식음료 순매출을 알려줘"),
        )
        # 단일 공통 업무어만으로는 임의 Metric phrase를 query hint로 만들지 않는다.
        self.assertEqual((), index.match("객실 상태를 알려줘"))
        # ASCII identifier는 부분문자열 fuzzy evidence로 승격하지 않는다.
        self.assertEqual((), index.match("address field"))

    def test_more_specific_release_phrase_survives_base_phrase_substring(self) -> None:
        """짧은 exact alias가 더 강한 승인 phrase 증거를 숨기지 않는다."""

        index = GovernedPhraseIndex(
            ("Helium yield", "Helium average yield", "Argon yield")
        )

        self.assertEqual(
            ("helium yield", "helium average yield"),
            index.match("What is the average helium yield per observation?"),
        )
        self.assertEqual(
            ("helium yield",),
            index.match("Show Helium yield"),
        )

    def test_multiple_governed_metrics_keep_the_request_bound(self) -> None:
        variants = plan_search_queries(
            "객실 매출과 식음 매출을 비교해줘",
            governed_phrases=("객실 매출", "식음 매출", "시설 매출"),
        )

        self.assertEqual(3, len(variants))
        self.assertEqual(
            ["governed-1", "governed-2", "governed-3"],
            [item.label for item in variants],
        )

    def test_single_character_noun_is_kept_when_longer_context_exists(self) -> None:
        self.assertEqual(("룸", "매출"), ordered_query_tokens("룸 매출"))
        self.assertIn("룸매출", plan_search_queries("룸 매출")[2].query)

    def test_single_character_noise_and_empty_questions_are_rejected(self) -> None:
        self.assertEqual((), ordered_query_tokens("가 을 를"))
        with self.assertRaises(DataHubQueryPlanError):
            plan_search_queries("!!!")
        with self.assertRaises(DataHubQueryPlanError):
            plan_search_queries("질문" * 1025)


class CandidateRankingTests(unittest.TestCase):
    def test_single_token_metric_name_does_not_create_a_broad_specialization_family(self) -> None:
        terms = {
            "base": SimpleNamespace(label="Yield", aliases=()),
            "qualified": SimpleNamespace(label="Segment Yield", aliases=()),
        }

        self.assertEqual(
            (),
            governed_metric_specialization_ids(terms, ("yield",), 10),
        )

    def test_release_phrase_evidence_outranks_definition_token_density(self) -> None:
        """승인 alias hit을 긴 질문의 공통 definition token보다 강하게 보존한다."""

        asset_fqn = "approved.analytics.observations"
        assets = [
            {
                "fqn": asset_fqn,
                "metrics": [
                    {
                        "id": "target_rate",
                        "result_field": "target_rate",
                        "visibility": "BUSINESS",
                        "dimensions": [],
                    },
                    {
                        "id": "generic_count",
                        "result_field": "generic_count",
                        "visibility": "BUSINESS",
                        "dimensions": [],
                    },
                ],
                "dimensions": [],
            }
        ]
        column_rule = {"source": {"kind": "column"}}
        terms = {
            "target_rate": SimpleNamespace(
                label="Alpha rate",
                aliases=("Alpha rate",),
                definition="approved measure",
                searchable_text="Alpha rate approved measure",
                metric_rule=column_rule,
            ),
            "generic_count": SimpleNamespace(
                label="Generic count",
                aliases=("Generic count",),
                definition="governed alpha observation count context",
                searchable_text="governed alpha observation count context",
                metric_rule=column_rule,
            ),
        }
        question = "Show governed alpha observation count context for Alpha rate"

        ranked_assets = compact_candidate_assets(
            assets,
            terms,
            question,
            unicode_tokens(question),
            {asset_fqn: 1},
            2,
            require_search_metric=True,
            governed_phrases=("alpha rate",),
        )
        ranked = sorted(
            (
                int(metric["candidate_rank"]),
                str(metric["id"]),
            )
            for asset in ranked_assets
            for metric in asset["metrics"]
            if metric["candidate_selectable"] is True
        )

        self.assertEqual(
            ["target_rate", "generic_count"],
            [metric_id for _rank, metric_id in ranked],
        )

    def test_full_definition_evidence_outranks_component_phrase_hint(self) -> None:
        """복합 지표 정의 전체가 맞으면 질문 속 구성 지표 이름에 선점되지 않는다."""

        asset_fqn = "approved.analytics.revenue"
        assets = [
            {
                "fqn": asset_fqn,
                "metrics": [
                    {
                        "id": "combined_total",
                        "result_field": "combined_total",
                        "visibility": "BUSINESS",
                        "dimensions": [],
                    },
                    {
                        "id": "component_amount",
                        "result_field": "component_amount",
                        "visibility": "BUSINESS",
                        "dimensions": [],
                    },
                ],
                "dimensions": [],
            }
        ]
        column_rule = {"source": {"kind": "column"}}
        terms = {
            "combined_total": SimpleNamespace(
                label="Combined total",
                aliases=("Combined total",),
                definition="component amount plus combined total",
                searchable_text="Combined total component amount plus combined total",
                metric_rule=column_rule,
            ),
            "component_amount": SimpleNamespace(
                label="Component amount",
                aliases=("Component amount",),
                definition="component amount",
                searchable_text="Component amount component amount",
                metric_rule=column_rule,
            ),
        }
        question = "component amount plus combined total"

        ranked_assets = compact_candidate_assets(
            assets,
            terms,
            question,
            unicode_tokens(question),
            {asset_fqn: 1},
            2,
            governed_phrases=("component amount",),
        )
        ranked = sorted(
            (
                int(metric["candidate_rank"]),
                str(metric["id"]),
            )
            for asset in ranked_assets
            for metric in asset["metrics"]
            if metric["candidate_selectable"] is True
        )

        self.assertEqual(
            ["combined_total", "component_amount"],
            [metric_id for _rank, metric_id in ranked],
        )

    def test_exact_dimension_query_is_not_promoted_by_metric_phrase_hint(self) -> None:
        """Dimension-only 질의는 유사 BUSINESS 문구 힌트가 있어도 Metric으로 바뀌지 않는다."""

        asset_fqn = "approved.analytics.feedback"
        assets = [
            {
                "fqn": asset_fqn,
                "metrics": [
                    {
                        "id": "average_rating",
                        "result_field": "average_rating",
                        "visibility": "BUSINESS",
                        "dimensions": [],
                    }
                ],
                "dimensions": [
                    {
                        "id": "sentiment_label",
                        "name": "Sentiment",
                        "asset_fqn": asset_fqn,
                        "column": "sentiment_label",
                        "aliases": ["VOC sentiment"],
                    }
                ],
            }
        ]
        terms = {
            "average_rating": SimpleNamespace(
                label="Average rating",
                aliases=("VOC average sentiment rating",),
                definition="average feedback rating by sentiment",
                searchable_text="Average rating VOC average sentiment rating",
                metric_rule={"source": {"kind": "column"}},
            )
        }

        ranked_assets = compact_candidate_assets(
            assets,
            terms,
            "VOC sentiment",
            unicode_tokens("VOC sentiment"),
            {asset_fqn: 1},
            2,
            governed_phrases=("VOC average sentiment rating",),
        )

        self.assertFalse(
            any(
                metric.get("candidate_selectable") is True
                for asset in ranked_assets
                for metric in asset["metrics"]
            )
        )


class CandidateSearchRequestTests(unittest.IsolatedAsyncioTestCase):
    def _client(self, handler, **kwargs) -> tuple[DataHubCatalogClient, httpx.AsyncClient]:
        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        client = DataHubCatalogClient(
            "http://datahub.test", client=http, page_size=2, max_entities=100, **kwargs
        )
        self.addAsyncCleanup(http.aclose)
        return client, http

    async def test_bounded_search_requests_explicit_types_and_count(self) -> None:
        requests: list[dict] = []

        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            requests.append(body)
            return httpx.Response(200, json={"data": {"searchAcrossEntities": {
                "start": 0,
                # DataHub Core 1.7은 실제 1건을 반환해도 요청 window를 count로 보존한다.
                "count": 5,
                "total": 1,
                "searchResults": [{
                    "entity": {"urn": "urn:li:dataset:a", "type": "DATASET"},
                    "matchedFields": [{"name": "name", "value": "a"}],
                }],
            }}})

        client, _http = self._client(handler)
        hits = await client.search_candidates(
            "매출", entity_types=("DATASET", "GLOSSARY_TERM"), count=5
        )

        self.assertEqual(1, len(requests))
        request_input = requests[0]["variables"]["input"]
        self.assertEqual(["DATASET", "GLOSSARY_TERM"], request_input["types"])
        self.assertEqual(5, request_input["count"])
        self.assertEqual(0, request_input["start"])
        self.assertEqual(
            {"skipAggregates": True, "skipHighlighting": True},
            request_input["searchFlags"],
        )
        # 후보 검색은 aggregate·highlight·중첩 필드를 요청하지 않는다.
        self.assertNotIn("orFilters", request_input)
        self.assertNotIn("aggregate", requests[0]["query"])
        self.assertNotIn("matchedFields", requests[0]["query"])
        # fake 응답이 값을 보내더라도 entitlement 전 candidate에는 보존하지 않는다.
        self.assertEqual((), hits[0].matched_fields)

    async def test_oversized_or_wrong_typed_results_fail_closed(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"data": {"searchAcrossEntities": {
                "start": 0,
                "count": 1,
                "total": 1,
                "searchResults": [{
                    "entity": {"urn": "urn:li:chart:a", "type": "CHART"},
                    "matchedFields": [],
                }],
            }}})

        client, _http = self._client(handler)
        with self.assertRaises(DataHubSearchUnavailableError):
            await client.search_candidates("매출", entity_types=("DATASET",), count=3)

    async def test_candidate_request_and_response_bounds_are_exact(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"data": {"searchAcrossEntities": {
                "start": 0,
                "count": 2,
                "total": 2,
                "searchResults": [{
                    "entity": {"urn": "urn:li:dataset:a", "type": "DATASET"}
                }],
            }}})

        client, _http = self._client(handler)
        with self.assertRaises(DataHubSearchUnavailableError):
            await client.search_candidates("매출", entity_types=("DATASET",), count=3)
        with self.assertRaises(ValueError):
            await client.search_candidates(
                "x" * (client.MAX_CANDIDATE_QUERY_CHARACTERS + 1),
                entity_types=("DATASET",),
                count=3,
            )
        with self.assertRaises(ValueError):
            await client.search_candidates("매출", entity_types=("DATASET",), count=True)

    async def test_transport_failure_carries_category(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(503, json={})

        client, _http = self._client(handler)
        with self.assertRaises(DataHubSearchUnavailableError) as raised:
            await client.search_candidates("매출", entity_types=("DATASET",), count=3)
        self.assertEqual("transport", raised.exception.category)

    async def test_timeout_is_classified_as_timeout(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("timeout", request=request)

        client, _http = self._client(handler)
        with self.assertRaises(DataHubSearchUnavailableError) as raised:
            await client.search_candidates("매출", entity_types=("DATASET",), count=3)
        self.assertEqual("timeout", raised.exception.category)


class ScrollEnumerationTests(unittest.IsolatedAsyncioTestCase):
    def _client(self, handler, **kwargs) -> DataHubCatalogClient:
        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        self.addAsyncCleanup(http.aclose)
        return DataHubCatalogClient(
            "http://datahub.test", client=http, page_size=2, max_entities=10, **kwargs
        )

    @staticmethod
    def _page(
        urns: list[str],
        next_scroll_id: str | None,
        *,
        count: int | None = None,
    ) -> httpx.Response:
        return httpx.Response(200, json={"data": {"scrollAcrossEntities": {
            "count": len(urns) if count is None else count,
            "nextScrollId": next_scroll_id,
            "searchResults": [
                {"entity": {"urn": urn, "type": "DATASET"}, "matchedFields": []}
                for urn in urns
            ],
        }}})

    async def test_scroll_follows_cursor_until_exhausted(self) -> None:
        cursors: list[str | None] = []
        request_inputs: list[dict] = []

        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            self.assertIn("scrollAcrossEntities", body["query"])
            request_input = body["variables"]["input"]
            request_inputs.append(request_input)
            cursor = request_input.get("scrollId")
            cursors.append(cursor)
            if cursor is None:
                return self._page(["urn:li:dataset:a", "urn:li:dataset:b"], "cursor-2")
            # 마지막 page도 요청 window를 count로 돌려주는 live 1.7 응답을 허용한다.
            return self._page(["urn:li:dataset:c"], None, count=2)

        hits = await self._client(handler).list_datasets()

        self.assertEqual([None, "cursor-2"], cursors)
        for request_input in request_inputs:
            self.assertEqual(
                {"sortCriteria": [{"field": "urn", "sortOrder": "ASCENDING"}]},
                request_input["sortInput"],
            )
            self.assertEqual(
                {"skipAggregates": True, "skipHighlighting": True},
                request_input["searchFlags"],
            )
        self.assertEqual(
            ["urn:li:dataset:a", "urn:li:dataset:b", "urn:li:dataset:c"],
            [hit.urn for hit in hits],
        )

    async def test_metric_enumeration_uses_the_same_bounded_scroll_contract(self) -> None:
        request_inputs: list[dict] = []

        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            request_input = body["variables"]["input"]
            request_inputs.append(request_input)
            return httpx.Response(200, json={"data": {"scrollAcrossEntities": {
                "count": 1,
                "nextScrollId": None,
                "searchResults": [{
                    "entity": {"urn": "urn:li:metric:room_revenue", "type": "METRIC"},
                    "matchedFields": [],
                }],
            }}})

        hits = await self._client(handler).list_metrics()

        self.assertEqual(["METRIC"], request_inputs[0]["types"])
        self.assertEqual(["urn:li:metric:room_revenue"], [hit.urn for hit in hits])

    async def test_empty_page_with_cursor_fails_closed(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return self._page([], "cursor-forever")

        with self.assertRaisesRegex(DataHubCatalogError, "no progress"):
            await self._client(handler).list_datasets()

    async def test_repeated_cursor_fails_closed(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            cursor = body["variables"]["input"].get("scrollId")
            urn = "urn:li:dataset:a" if cursor is None else "urn:li:dataset:b"
            return self._page([urn], "same-cursor")

        with self.assertRaisesRegex(DataHubCatalogError, "did not advance"):
            await self._client(handler).list_datasets()

    async def test_entity_bound_is_enforced(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            cursor = body["variables"]["input"].get("scrollId") or "0"
            start = int(cursor) if cursor.isdigit() else 0
            return self._page(
                [f"urn:li:dataset:{start}", f"urn:li:dataset:{start + 1}"],
                str(start + 2),
            )

        with self.assertRaisesRegex(DataHubCatalogError, "entity bound"):
            await self._client(handler).list_datasets()

    async def test_duplicate_urn_across_pages_fails_closed(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            cursor = body["variables"]["input"].get("scrollId")
            return self._page(["urn:li:dataset:a"], None if cursor else "cursor-2")

        with self.assertRaisesRegex(DataHubCatalogError, "duplicate"):
            await self._client(handler).list_datasets()

    async def test_scroll_count_smaller_than_results_fails_closed(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"data": {"scrollAcrossEntities": {
                "count": 0,
                "nextScrollId": None,
                "searchResults": [
                    {"entity": {"urn": "urn:li:dataset:a", "type": "DATASET"}}
                ],
            }}})

        with self.assertRaisesRegex(DataHubCatalogError, "pagination is invalid"):
            await self._client(handler).list_datasets()


class SearchModeRuntimeTests(unittest.IsolatedAsyncioTestCase):
    """실제 runtime bundle로 mode별 production/shadow 경계를 검증한다."""

    def _adapter(self, *, search_mode: str) -> GovernedDataPlatformAdapter:
        datahub_http = httpx.AsyncClient(
            transport=httpx.MockTransport(self.transport.datahub)
        )
        trino_http = httpx.AsyncClient(
            transport=httpx.MockTransport(self.transport.trino)
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
                "https://trino.test", "runtime", "test-password", client=trino_http
            ),
            search_mode=search_mode,
        )
        self.addAsyncCleanup(datahub_http.aclose)
        self.addAsyncCleanup(trino_http.aclose)
        self.addAsyncCleanup(adapter.aclose)
        return adapter

    def setUp(self) -> None:
        self.transport = RuntimeTransport(_bundle())
        self.context = {"role": "analyst", "parameters": {}}

    async def test_lexical_mode_never_calls_question_search(self) -> None:
        adapter = self._adapter(search_mode="lexical")

        assets = await _candidate_assets(adapter, "helium", self.context)

        self.assertTrue(assets)
        self.assertEqual([], self.transport.candidate_queries)

    async def test_shadow_mode_measures_search_without_changing_decision(self) -> None:
        shadow = self._adapter(search_mode="lexical_shadow")
        baseline = self._adapter(search_mode="lexical")

        shadow_assets = await _candidate_assets(shadow, "helium", self.context)
        await shadow._governance._drain_shadow_tasks()
        shadow_queries = tuple(self.transport.candidate_queries)
        self.transport.candidate_queries.clear()
        baseline_assets = await _candidate_assets(baseline, "helium", self.context)

        self.assertEqual(
            [item["fqn"] for item in baseline_assets],
            [item["fqn"] for item in shadow_assets],
        )
        self.assertTrue(shadow_queries)
        self.assertEqual([], self.transport.candidate_queries)

    async def test_shadow_search_failure_does_not_fail_the_request(self) -> None:
        adapter = self._adapter(search_mode="lexical_shadow")
        self.transport.candidate_search_status = 503

        assets = await _candidate_assets(adapter, "helium", self.context)
        await adapter._governance._drain_shadow_tasks()

        self.assertTrue(assets)

    async def test_shadow_search_never_blocks_the_production_response(self) -> None:
        adapter = self._adapter(search_mode="lexical_shadow")
        # Snapshot을 먼저 캐시에 올려 아래 대기가 candidate search에만 적용되게 한다.
        await _candidate_assets(adapter, "helium", self.context)
        await adapter._governance._drain_shadow_tasks()
        search_started = asyncio.Event()
        release_search = asyncio.Event()

        async def blocked_search(*_args, **_kwargs):
            search_started.set()
            await release_search.wait()
            return ()

        adapter._governance._catalog.search_candidates = blocked_search
        assets = await asyncio.wait_for(
            _candidate_assets(adapter, "helium", self.context),
            timeout=0.2,
        )

        self.assertTrue(assets)
        await asyncio.wait_for(search_started.wait(), timeout=1.0)
        release_search.set()
        await adapter._governance._drain_shadow_tasks()

    async def test_shadow_search_capacity_is_bounded(self) -> None:
        adapter = self._adapter(search_mode="lexical_shadow")
        adapter._governance._max_shadow_searches = 1
        search_started = asyncio.Event()
        release_search = asyncio.Event()
        calls = 0

        async def blocked_search(*_args, **_kwargs):
            nonlocal calls
            calls += 1
            search_started.set()
            await release_search.wait()
            return ()

        adapter._governance._catalog.search_candidates = blocked_search
        self.assertTrue(await _candidate_assets(adapter, "helium", self.context))
        await asyncio.wait_for(search_started.wait(), timeout=1.0)

        self.assertTrue(await _candidate_assets(adapter, "helium", self.context))
        self.assertEqual(1, len(adapter._governance._shadow_tasks))
        self.assertLessEqual(calls, 3)
        release_search.set()
        await adapter._governance._drain_shadow_tasks()

    async def test_shutdown_cancels_pending_shadow_search(self) -> None:
        adapter = self._adapter(search_mode="lexical_shadow")
        search_started = asyncio.Event()
        search_cancelled = asyncio.Event()

        async def blocked_search(*_args, **_kwargs):
            search_started.set()
            try:
                await asyncio.Event().wait()
            finally:
                search_cancelled.set()

        adapter._governance._catalog.search_candidates = blocked_search
        self.assertTrue(await _candidate_assets(adapter, "helium", self.context))
        await asyncio.wait_for(search_started.wait(), timeout=1.0)

        await adapter.aclose()

        await asyncio.wait_for(search_cancelled.wait(), timeout=1.0)
        self.assertEqual(set(), adapter._governance._shadow_tasks)

    async def test_caller_cancellation_propagates_to_candidate_search(self) -> None:
        adapter = self._adapter(search_mode="datahub_lexical")
        search_started = asyncio.Event()
        search_cancelled = asyncio.Event()

        async def blocked_search(*_args, **_kwargs):
            search_started.set()
            try:
                await asyncio.Event().wait()
            finally:
                search_cancelled.set()

        adapter._governance._catalog.search_candidates = blocked_search
        request = asyncio.create_task(
            _candidate_assets(adapter, "helium", self.context)
        )
        # Event가 행위를 결정하고 timeout은 CI scheduler 정체만 제한한다.
        await asyncio.wait_for(search_started.wait(), timeout=1.0)
        request.cancel()

        with self.assertRaises(asyncio.CancelledError):
            await request
        await asyncio.wait_for(search_cancelled.wait(), timeout=1.0)

    async def test_datahub_lexical_mode_fails_closed_on_search_failure(self) -> None:
        adapter = self._adapter(search_mode="datahub_lexical")
        self.transport.candidate_search_status = 503

        with self.assertRaises(MetadataUnavailableError):
            await _candidate_assets(adapter, "helium", self.context)

    async def test_datahub_lexical_mode_uses_bounded_question_search(self) -> None:
        adapter = self._adapter(search_mode="datahub_lexical")

        assets = await _candidate_assets(adapter, "helium yield", self.context)

        self.assertTrue(assets)
        self.assertTrue(self.transport.candidate_queries)
        self.assertLessEqual(len(self.transport.candidate_queries), 3)

    async def test_dataset_hit_uses_only_local_evidence_inside_that_hit(self) -> None:
        """Dataset 검색 hit은 그 자산 안의 승인 용어만 구분하고 전체 snapshot으로 후퇴하지 않는다."""

        adapter = self._adapter(search_mode="datahub_lexical")
        helium_urn = next(
            urn for urn in self.transport.datasets if "helium_fact" in urn
        )
        self.transport.candidate_hits = [(helium_urn, "DATASET")]

        assets = await _candidate_assets(adapter, "helium yield", self.context)
        selectable = {
            metric["id"]
            for asset in assets
            for metric in asset["metrics"]
            if metric["candidate_selectable"] is True
        }

        self.assertEqual({"helium_yield"}, selectable)
        self.assertNotIn("argon_yield", selectable)

    async def test_datahub_anchor_adds_only_reviewed_metric_specializations_and_their_dimensions(self) -> None:
        """검색된 일반 measure의 승인된 구체화만 후보로 닫고 값·도메인 분기는 만들지 않는다."""

        bundle = deepcopy(_bundle())
        qualified_asset = next(
            item
            for item in bundle["schema_context"]["assets"]
            if item["fqn"] == "orbit.lake.argon_fact"
        )
        qualified_asset["columns"].append(
            {
                "name": "segment_code",
                "native_type": "varchar",
                "logical_type": "string",
                "ordinal_position": 4,
                "nullable": False,
                "is_part_of_key": False,
                "role": "dimension",
                "description": "Approved observation segment.",
            }
        )
        qualified_asset["datahub_schema_hash"] = datahub_schema_sha1(
            qualified_asset
        )
        qualified_rule = next(
            item for item in bundle["metric_rules"] if item["id"] == "argon_yield"
        )
        qualified_term = next(
            item for item in bundle["metric_terms"] if item["id"] == "argon_yield"
        )
        aliases = ["Segment Helium yield", "Qualified Helium yield"]
        definition = "Approved Helium yield attributed to an observation segment."
        qualified_rule["dimensions"] = [
            {"asset_fqn": qualified_asset["fqn"], "column": "segment_code"}
        ]
        qualified_rule["governance"]["semantic"] = {
            "name": aliases[0],
            "definition": definition,
            "aliases": aliases,
        }
        qualified_rule["governance"]["grain"]["dimensions"] = ["segment_code"]
        qualified_term.update(
            {"name": aliases[0], "definition": definition, "aliases": aliases}
        )
        bundle["dimensions"].append(
            {
                "id": "observation_segment",
                "aliases": ["Observation segment", "Segment category"],
                "definition": "Approved segment observed with the measurement.",
                "asset_fqn": qualified_asset["fqn"],
                "column": "segment_code",
            }
        )

        self.transport = RuntimeTransport(bundle)
        adapter = self._adapter(search_mode="datahub_lexical")
        helium_term_urn = next(
            item["urn"]
            for item in bundle["metric_terms"]
            if item["id"] == "helium_yield"
        )
        self.transport.candidate_hits = [(helium_term_urn, "GLOSSARY_TERM")]

        assets = await _candidate_assets(adapter, "Helium yield", self.context)
        ranked = sorted(
            (
                int(metric["candidate_rank"]),
                str(metric["id"]),
            )
            for asset in assets
            for metric in asset["metrics"]
            if metric["candidate_selectable"] is True
        )
        dimensions = {
            str(dimension["id"])
            for asset in assets
            for dimension in asset["dimensions"]
        }

        self.assertEqual(
            ["helium_yield", "argon_yield"],
            [metric_id for _rank, metric_id in ranked],
        )
        self.assertEqual({"observation_segment"}, dimensions)

    async def test_search_hits_outside_the_release_never_reach_candidates(self) -> None:
        """검색 결과는 snapshot 멤버십·권한 검증을 통과한 뒤에만 후보가 된다."""

        adapter = self._adapter(search_mode="datahub_lexical")
        self.transport.candidate_hits = [
            ("urn:li:dataset:(urn:li:dataPlatform:trino,secret.private.table,PROD)", "DATASET"),
        ]

        with self.assertRaises((NoMetricMatchError, NoEntitledAssetsError)):
            await _candidate_assets(adapter, "helium", self.context)

    async def test_unknown_search_mode_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            QueryGovernanceEngine(object(), object(), search_mode="datahub_semantic")
        self.assertEqual(20, DEFAULT_CANDIDATE_SEARCH_COUNT)

    def test_engine_default_is_the_promoted_datahub_lexical_mode(self) -> None:
        engine = QueryGovernanceEngine(object(), object())

        self.assertEqual("datahub_lexical", engine._search_mode)

    def test_variant_ranks_are_deduplicated_with_reciprocal_rank_fusion(self) -> None:
        first = DataHubSearchHit("urn:li:dataset:first", "DATASET")
        repeated = DataHubSearchHit("urn:li:dataset:repeated", "DATASET")

        fused = QueryGovernanceEngine._fuse_candidate_hits(
            ((first, repeated), (repeated,))
        )

        self.assertEqual(
            ["urn:li:dataset:repeated", "urn:li:dataset:first"],
            [item.urn for item in fused],
        )

    def test_conflicting_entity_types_for_one_urn_fail_closed(self) -> None:
        with self.assertRaises(MetadataUnavailableError):
            QueryGovernanceEngine._fuse_candidate_hits(
                (
                    (DataHubSearchHit("urn:li:dataset:a", "DATASET"),),
                    (DataHubSearchHit("urn:li:dataset:a", "GLOSSARY_TERM"),),
                )
            )


if __name__ == "__main__":  # pragma: no cover - 직접 실행 편의용이다.
    unittest.main()
