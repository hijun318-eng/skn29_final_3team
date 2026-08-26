from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "app" / "backend"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(BACKEND))

from app.adapters.neo4j_graph import Neo4jGraphAdapter  # noqa: E402
from app.adapters.neo4j_graph_queries import AWAIT_INDEXES, SCHEMA_STATEMENTS  # noqa: E402
from app.adapters.neo4j_graph_settings import Neo4jGraphSettings  # noqa: E402
from app.adapters.neo4j_projection import compile_neo4j_projection  # noqa: E402
from app.ports.graph_candidates import (  # noqa: E402
    GraphCandidateRequest,
    GraphEntity,
    GraphEntityKind,
    GraphProjectionMismatchError,
    GraphRelationKind,
    GraphSecurityError,
    GraphUnavailableError,
)


CHECKSUM = "a" * 64


class _Result:
    def __init__(self, records):
        self._records = list(records)

    async def single(self, *, strict=False):
        if strict and len(self._records) != 1:
            raise ValueError("result does not contain exactly one record")
        return self._records[0] if self._records else None

    async def consume(self):
        return None

    def __aiter__(self):
        self._iterator = iter(self._records)
        return self

    async def __anext__(self):
        try:
            return next(self._iterator)
        except StopIteration as error:
            raise StopAsyncIteration from error


class _Transaction:
    def __init__(self, driver):
        self.driver = driver

    async def __aenter__(self):
        return self

    async def __aexit__(self, _type, _value, _traceback):
        return False

    async def run(self, query, parameters):
        text = str(query)
        self.driver.calls.append((text, dict(parameters)))
        if "UNWIND $entities" in text:
            return _Result([{"processed": len(parameters["entities"])}])
        if "UNWIND $relations" in text:
            return _Result([{"processed": len(parameters["relations"])}])
        if "WITH count(entity) AS entity_count" in text:
            return _Result(
                [
                    {
                        "entity_count": len(parameters["entities"]),
                        "relation_count": len(parameters["relations"]),
                    }
                ]
            )
        if "RETURN count(seed) AS seed_count" in text:
            count = self.driver.seed_count
            return _Result(
                [{"seed_count": len(parameters["seed_keys"]) if count is None else count}]
            )
        return _Result(self.driver.candidates)


class _Session:
    def __init__(self, driver, access_mode):
        self.driver = driver
        self.access_mode = access_mode

    async def __aenter__(self):
        self.driver.access_modes.append(self.access_mode)
        return self

    async def __aexit__(self, _type, _value, _traceback):
        return False

    async def begin_transaction(self, *, timeout):
        self.driver.transaction_timeouts.append(timeout)
        return _Transaction(self.driver)


class _Driver:
    def __init__(self):
        self.calls = []
        self.access_modes = []
        self.transaction_timeouts = []
        self.candidates = [
            {"entity_kind": "DATASET", "entity_id": "catalog.sales"},
            {"entity_kind": "METRIC", "entity_id": "revenue"},
        ]
        self.seed_count = None
        self.connectivity_error = None
        self.closed = False

    def session(self, *, database, default_access_mode):
        if database != "neo4j":
            raise AssertionError("unexpected database")
        return _Session(self, default_access_mode)

    async def verify_connectivity(self):
        if self.connectivity_error is not None:
            raise self.connectivity_error

    async def close(self):
        self.closed = True


class _TransientDriverError(Exception):
    pass


class _SecurityDriverError(Exception):
    code = "Neo.ClientError.Security.Forbidden"


def _runtime_projection():
    release = SimpleNamespace(
        assets=(
            SimpleNamespace(fqn="catalog.sales"),
            SimpleNamespace(fqn="catalog.calendar"),
        ),
        metrics=(
            SimpleNamespace(id="revenue", source_assets=("catalog.sales",)),
        ),
        dimensions=(
            SimpleNamespace(id="business_date", asset_fqn="catalog.calendar"),
        ),
        joins=(
            SimpleNamespace(left="catalog.sales", right="catalog.calendar"),
        ),
    )
    return SimpleNamespace(projection_sha256=CHECKSUM, release=release)


class Neo4jGraphSettingsTest(unittest.TestCase):
    def test_default_is_disabled_without_driver_or_secret(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            settings = Neo4jGraphSettings.from_env()
        self.assertFalse(settings.enabled)
        with patch("importlib.import_module") as importer:
            with self.assertRaisesRegex(ValueError, "disabled"):
                Neo4jGraphAdapter.from_settings(settings)
        importer.assert_not_called()

    def test_enabled_insecure_uri_requires_explicit_local_override(self) -> None:
        values = {
            "NEO4J_GRAPH_ENABLED": "true",
            "NEO4J_URI": "bolt://127.0.0.1:17687",
            "NEO4J_USERNAME": "neo4j",
            "NEO4J_PASSWORD": "external-secret",
        }
        with patch.dict(os.environ, values, clear=True):
            with self.assertRaisesRegex(ValueError, "ALLOW_INSECURE"):
                Neo4jGraphSettings.from_env()
        values["NEO4J_ALLOW_INSECURE"] = "true"
        with patch.dict(os.environ, values, clear=True):
            self.assertTrue(Neo4jGraphSettings.from_env().enabled)


class Neo4jProjectionCompilerTest(unittest.TestCase):
    def test_compiler_keeps_only_ids_and_allowlisted_relations(self) -> None:
        projection = compile_neo4j_projection(
            _runtime_projection(), product_release_id="product-release-1"
        )

        self.assertEqual(4, len(projection.entities))
        self.assertEqual(3, len(projection.relations))
        self.assertEqual(
            {"key", "kind", "entity_id"},
            set(projection.entity_records()[0]),
        )
        self.assertRegex(projection.projection_checksum, r"^[0-9a-f]{64}$")


class Neo4jGraphAdapterTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.driver = _Driver()
        self.adapter = Neo4jGraphAdapter(
            self.driver,
            database="neo4j",
            timeout_seconds=2,
            read_access="READ",
            write_access="WRITE",
            driver_error_types=(_TransientDriverError, _SecurityDriverError),
            security_error_types=(_SecurityDriverError,),
            transient_error_types=(_TransientDriverError,),
        )
        self.projection = compile_neo4j_projection(
            _runtime_projection(), product_release_id="product-release-1"
        )

    async def test_schema_bootstrap_uses_only_fixed_idempotent_statements(self) -> None:
        await self.adapter.ensure_schema()

        self.assertEqual(
            [*SCHEMA_STATEMENTS, AWAIT_INDEXES],
            [query for query, _parameters in self.driver.calls],
        )
        self.assertEqual(["WRITE"], self.driver.access_modes)
        self.assertEqual([2, 2], self.driver.transaction_timeouts)

    async def test_projection_is_parameterized_idempotent_and_exact_read_back(self) -> None:
        first = await self.adapter.project(self.projection)
        second = await self.adapter.project(self.projection)

        self.assertEqual(first, second)
        self.assertEqual(["WRITE", "WRITE"], self.driver.access_modes)
        self.assertEqual([2, 2], self.driver.transaction_timeouts)
        for query, parameters in self.driver.calls:
            self.assertNotIn("catalog.sales", query)
            self.assertEqual(self.projection.projection_checksum, parameters["graph_projection_checksum"])

    async def test_candidate_query_uses_bounded_fixed_template_and_receipt(self) -> None:
        request = GraphCandidateRequest(
            seed_keys=(GraphEntity(GraphEntityKind.METRIC, "seed_metric").key,),
            product_release_id=self.projection.product_release_id,
            source_projection_checksum=self.projection.source_projection_checksum,
            graph_projection_checksum=self.projection.projection_checksum,
            relation_kinds=(GraphRelationKind.SOURCE_ASSET,),
            max_hops=1,
            limit=5,
        )

        result = await self.adapter.resolve_candidates(request)

        self.assertEqual(("catalog.sales", "revenue"), tuple(item.entity_id for item in result.candidates))
        self.assertEqual("READ", self.driver.access_modes[-1])
        candidate_query, parameters = self.driver.calls[-1]
        self.assertIn("[:RELATED_TO*1]", candidate_query)
        self.assertNotIn("seed_metric", candidate_query)
        self.assertEqual(["METRIC:seed_metric"], parameters["seed_keys"])

    async def test_seed_receipt_mismatch_fails_closed(self) -> None:
        self.driver.seed_count = 0
        request = GraphCandidateRequest(
            seed_keys=("METRIC:missing",),
            product_release_id=self.projection.product_release_id,
            source_projection_checksum=self.projection.source_projection_checksum,
            graph_projection_checksum=self.projection.projection_checksum,
        )
        with self.assertRaises(GraphProjectionMismatchError):
            await self.adapter.resolve_candidates(request)

    async def test_driver_failures_keep_security_distinct_from_availability(self) -> None:
        for error, expected in (
            (_TransientDriverError(), GraphUnavailableError),
            (_SecurityDriverError(), GraphSecurityError),
        ):
            with self.subTest(error=type(error).__name__):
                self.driver.connectivity_error = error
                with self.assertRaises(expected):
                    await self.adapter.verify_connectivity()

    async def test_close_releases_driver_pool(self) -> None:
        await self.adapter.aclose()
        self.assertTrue(self.driver.closed)


if __name__ == "__main__":
    unittest.main()
