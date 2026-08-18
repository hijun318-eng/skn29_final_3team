from __future__ import annotations

import copy
import json
import os
import sys
import unittest
from pathlib import Path
from urllib.parse import unquote

import httpx


ROOT = Path(__file__).resolve().parents[2]
PUBLISHER = ROOT / "infrastructure" / "database" / "datahub"
sys.path.insert(0, str(PUBLISHER))
from metadata_aspects import iter_aspects  # noqa: E402
from metadata_contract import validate_bundle  # noqa: E402

from app.adapters.datahub_catalog import DataHubCatalogClient  # noqa: E402
from app.adapters.governed_data_platform import (  # noqa: E402
    GovernedDataPlatformAdapter,
)
from app.adapters.trino_async import TrinoAsyncClient  # noqa: E402
from app.ports.data_platform import (  # noqa: E402
    MetadataUnavailableError,
    NoEntitledAssetsError,
)
from app.query_capability import issue_query_capability  # noqa: E402


LIFECYCLE_URN = "urn:li:lifecycleStageType:approved"


def _bundle() -> dict:
    assets = []
    metrics = []
    terms = []
    time_fields = []
    for name, alias, domain in (
        ("helium", "Helium yield", "helium_operations"),
        ("argon", "Argon output", "argon_operations"),
    ):
        fqn = f"orbit.lake.{name}_fact"
        urn = f"urn:li:dataset:(urn:li:dataPlatform:trino,{fqn},PROD)"
        domain_urn = f"urn:li:domain:{domain}"
        assets.append(
            {
                "urn": urn,
                "fqn": fqn,
                "description": f"Governed {name} observations.",
                "schema_version": "schema-arbitrary-4",
                "seed_version": "data-arbitrary-9",
                "synthetic": False,
                "approval_status": "APPROVED",
                "entitlements": {"roles": ["hotel_analyst"], "domains": []},
                "grain": {"kind": "event", "keys": ["event_id"]},
                "columns": [
                    {
                        "name": "event_id",
                        "native_type": "varchar",
                        "logical_type": "string",
                        "ordinal_position": 1,
                        "nullable": False,
                        "is_part_of_key": True,
                        "role": "identifier",
                        "description": "Governed event identifier.",
                    },
                    {
                        "name": "observed_on",
                        "native_type": "date",
                        "logical_type": "date",
                        "ordinal_position": 2,
                        "nullable": False,
                        "is_part_of_key": False,
                        "role": "time",
                        "description": "Observation date.",
                    },
                    {
                        "name": "measure_value",
                        "native_type": "double",
                        "logical_type": "number",
                        "ordinal_position": 3,
                        "nullable": False,
                        "is_part_of_key": False,
                        "role": "measure",
                        "description": f"Measured {name} value.",
                    },
                ],
                "owner_urn": f"urn:li:corpGroup:{domain}",
                "domain_urn": domain_urn,
                "approved_lifecycle_urn": LIFECYCLE_URN,
                "platform_urn": "urn:li:dataPlatform:trino",
                "schema_name": fqn,
                "schema_metadata_version": 1,
                "dataset_key": {
                    "platform": "urn:li:dataPlatform:trino",
                    "name": fqn,
                    "origin": "PROD",
                },
                "table_type": "BASE TABLE",
            }
        )
        metrics.append(
            {
                "id": f"{name}_yield",
                "source": {
                    "kind": "column",
                    "field": {"asset_fqn": fqn, "column": "measure_value"},
                },
                "aggregation": "sum",
                "result_field": f"{name}_total",
                "unit": "arbitrary_units",
                "time_field": {"asset_fqn": fqn, "column": "observed_on"},
                "reduction": "sum",
                "dimensions": [],
                "required_filters": [],
            }
        )
        terms.append(
            {
                "id": f"{name}_yield",
                "urn": f"urn:li:glossaryTerm:{name}_yield",
                "name": alias,
                "definition": f"Approved aggregate for {name} observations.",
                "aliases": [alias, f"{name.title()} aggregate"],
                "unit": "arbitrary_units",
                "version": "glossary-arbitrary-3",
                "approval_status": "APPROVED",
                "owner_urn": f"urn:li:corpGroup:{domain}",
                "domain_urn": domain_urn,
                "approved_lifecycle_urn": LIFECYCLE_URN,
            }
        )
        time_fields.append(
            {
                "field": {"asset_fqn": fqn, "column": "observed_on"},
                "native_type": "date",
                "bucket": "day",
                "timezone_mode": "context",
            }
        )
    return {
        "catalog_version": "catalog-arbitrary-11",
        "policy_version": "policy-arbitrary-7",
        "governance_entities": {
            "owners": [
                {
                    "urn": "urn:li:corpGroup:helium_operations",
                    "name": "Helium operators",
                    "description": "Owners of helium governance.",
                },
                {
                    "urn": "urn:li:corpGroup:argon_operations",
                    "name": "Argon operators",
                    "description": "Owners of argon governance.",
                },
            ],
            "domains": [
                {
                    "urn": "urn:li:domain:helium_operations",
                    "name": "Helium domain",
                    "description": "Governance domain for helium.",
                },
                {
                    "urn": "urn:li:domain:argon_operations",
                    "name": "Argon domain",
                    "description": "Governance domain for argon.",
                },
            ],
            "approved_lifecycles": [
                {
                    "urn": LIFECYCLE_URN,
                    "name": "APPROVED",
                    "description": "Approved for governed runtime use.",
                }
            ],
        },
        "schema_context": {"version": "schema-context-4", "assets": assets},
        "metric_rules": metrics,
        "metric_terms": terms,
        "dimensions": [],
        "join_graph": {"edges": []},
        "time_rules": {
            "timezone": "Asia/Seoul",
            "calendar_id": "calendar-arbitrary-lunisolar",
            "interval": "[start,end)",
            "start_parameter": "range_open",
            "end_parameter": "range_close",
            "fields": time_fields,
        },
        "parameter_contract": {
            "style": "named",
            "parameters": [
                {"name": "range_open", "type": "date", "scope": "time"},
                {"name": "range_close", "type": "date", "scope": "time"},
            ],
        },
        "query_policy": {
            "dialect": "trino",
            "statement_type": "select",
            "read_only": True,
            "require_limit": True,
            "max_limit": 100,
            "allowed_functions": ["SUM"],
            "allowed_catalogs": ["orbit"],
        },
    }


def _bundle_with_dimension_bridge() -> dict:
    bundle = _bundle()
    fact_fqn = "orbit.lake.helium_fact"
    dimension_fqn = "orbit.reference.neon_dimension"
    domain_urn = "urn:li:domain:helium_operations"
    bundle["schema_context"]["assets"].append(
        {
            "urn": (
                "urn:li:dataset:(urn:li:dataPlatform:trino,"
                f"{dimension_fqn},PROD)"
            ),
            "fqn": dimension_fqn,
            "description": "Governed neon classification labels.",
            "schema_version": "schema-arbitrary-4",
            "seed_version": "data-arbitrary-9",
            "synthetic": False,
            "approval_status": "APPROVED",
            "entitlements": {"roles": ["hotel_analyst"], "domains": []},
            "grain": {"kind": "row", "keys": ["event_id"]},
            "columns": [
                {
                    "name": "event_id",
                    "native_type": "varchar",
                    "logical_type": "string",
                    "ordinal_position": 1,
                    "nullable": False,
                    "is_part_of_key": True,
                    "role": "identifier",
                    "description": "Governed event identifier.",
                },
                {
                    "name": "neon_label",
                    "native_type": "varchar",
                    "logical_type": "string",
                    "ordinal_position": 2,
                    "nullable": False,
                    "is_part_of_key": False,
                    "role": "dimension",
                    "description": "Governed neon classification label.",
                },
            ],
            "owner_urn": "urn:li:corpGroup:helium_operations",
            "domain_urn": domain_urn,
            "approved_lifecycle_urn": LIFECYCLE_URN,
            "platform_urn": "urn:li:dataPlatform:trino",
            "schema_name": dimension_fqn,
            "schema_metadata_version": 1,
            "dataset_key": {
                "platform": "urn:li:dataPlatform:trino",
                "name": dimension_fqn,
                "origin": "PROD",
            },
            "table_type": "BASE TABLE",
        }
    )
    bundle["dimensions"].append(
        {
            "id": "neon_category",
            "aliases": ["Neon category", "neon"],
            "definition": "Approved neon classification for governed observations.",
            "asset_fqn": dimension_fqn,
            "column": "neon_label",
        }
    )
    bundle["join_graph"]["edges"].append(
        {
            "id": "helium_neon_by_event",
            "left": fact_fqn,
            "right": dimension_fqn,
            "kind": "left",
            "cardinality": "many_to_one",
            "equality_conditions": [
                {"left_column": "event_id", "right_column": "event_id"}
            ],
            "temporal_conditions": [],
            "preaggregation": {
                "required": False,
                "grain": [{"asset_fqn": fact_fqn, "column": "event_id"}],
                "keys": [{"asset_fqn": fact_fqn, "column": "event_id"}],
            },
        }
    )
    validate_bundle(bundle)
    return bundle


def _graphql_entities(bundle: dict) -> tuple[dict[str, dict], dict[str, dict]]:
    aspects = {
        (entity_type, urn, aspect): value
        for entity_type, urn, aspect, value in iter_aspects(bundle)
    }
    datasets = {}
    for asset in bundle["schema_context"]["assets"]:
        urn = asset["urn"]
        properties = copy.deepcopy(aspects[("dataset", urn, "datasetProperties")])
        properties["customProperties"] = [
            {"key": key, "value": value}
            for key, value in properties["customProperties"].items()
        ]
        editable = aspects[("dataset", urn, "editableSchemaMetadata")]
        by_name = {
            item["fieldPath"]: item
            for item in editable["editableSchemaFieldInfo"]
        }
        schema_aspect = aspects[("dataset", urn, "schemaMetadata")]
        fields = []
        for column in asset["columns"]:
            editable_field = by_name[column["name"]]
            associations = editable_field.get("glossaryTerms", {}).get("terms", [])
            fields.append(
                {
                    "fieldPath": column["name"],
                    "nativeDataType": column["native_type"],
                    "nullable": column["nullable"],
                    "isPartOfKey": column["is_part_of_key"],
                    "description": column["description"],
                    "glossaryTerms": {
                        "terms": [{"term": {"urn": item["urn"]}} for item in associations]
                    },
                }
            )
        term_urns = aspects[("dataset", urn, "glossaryTerms")]["terms"]
        datasets[urn] = {
            "urn": urn,
            "name": asset["fqn"],
            "status": {"removed": False, "lifecycleStage": {"urn": LIFECYCLE_URN, "name": "APPROVED"}},
            "ownership": {
                "owners": [{
                    "type": "TECHNICAL_OWNER",
                    "associatedUrn": urn,
                    "ownershipType": {
                        "urn": "urn:li:ownershipType:__system__technical_owner"
                    },
                    "owner": {"urn": asset["owner_urn"]},
                }]
            },
            "domain": {"domain": {"urn": asset["domain_urn"]}},
            "properties": properties,
            "glossaryTerms": {
                "terms": [{"term": {"urn": item["urn"]}} for item in term_urns]
            },
            "schemaMetadata": {
                "version": 1,
                "name": asset["fqn"],
                "hash": schema_aspect["hash"],
                "fields": fields,
            },
        }
    terms = {}
    for term in bundle["metric_terms"]:
        urn = term["urn"]
        info = copy.deepcopy(aspects[("glossaryTerm", urn, "glossaryTermInfo")])
        info["description"] = info.pop("definition")
        info["customProperties"] = [
            {"key": key, "value": value}
            for key, value in info["customProperties"].items()
        ]
        terms[urn] = {
            "urn": urn,
            "exists": True,
            "status": None,
            "ownership": {
                "owners": [{
                    "type": "TECHNICAL_OWNER",
                    "associatedUrn": urn,
                    "ownershipType": {
                        "urn": "urn:li:ownershipType:__system__technical_owner"
                    },
                    "owner": {"urn": term["owner_urn"]},
                }]
            },
            "domain": {"domain": {"urn": term["domain_urn"]}},
            "glossaryTermInfo": info,
        }
    return datasets, terms


class RuntimeTransport:
    def __init__(self, bundle: dict) -> None:
        validate_bundle(bundle)
        self.bundle = bundle
        self.datasets, self.terms = _graphql_entities(bundle)
        governance = bundle["governance_entities"]
        self.owners = {item["urn"]: copy.deepcopy(item) for item in governance["owners"]}
        self.domains = {item["urn"]: copy.deepcopy(item) for item in governance["domains"]}
        self.lifecycle_stages = copy.deepcopy(governance["approved_lifecycles"])
        self.search_starts: dict[str, list[int]] = {"DATASET": [], "GLOSSARY_TERM": []}
        self.semantic_disabled = False
        self.schema_drift = False
        self.trino_statements: list[str] = []

    def datahub(self, request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            if request.url.path.startswith("/entitiesV2/"):
                urn = unquote(request.url.path.rsplit("/", 1)[1])
                return httpx.Response(200, json={
                    "urn": urn,
                    "aspects": {"status": {"value": {
                        "removed": False,
                        "lifecycleStage": LIFECYCLE_URN,
                    }}},
                })
            return httpx.Response(200, json={"models": {}})
        body = json.loads(request.content)
        query = body["query"]
        variables = body["variables"]
        if "semanticSearchAcrossEntities" in query:
            if self.semantic_disabled:
                return httpx.Response(
                    200,
                    json={
                        "data": None,
                        "errors": [{"message": "Semantic search is disabled in this environment"}],
                    },
                )
            first = next(iter(self.datasets))
            return httpx.Response(
                200,
                json={
                    "data": {
                        "semanticSearchAcrossEntities": {
                            "start": 0,
                            "count": 1,
                            "total": 1,
                            "searchResults": [{
                                "entity": {"urn": first, "type": "DATASET"},
                                "matchedFields": [],
                            }],
                        }
                    }
                },
            )
        if "searchAcrossEntities" in query:
            request_input = variables["input"]
            entity_type = request_input["types"][0]
            self.search_starts[entity_type].append(request_input["start"])
            values = list(self.datasets if entity_type == "DATASET" else self.terms)
            start = request_input["start"]
            page = values[start : start + request_input["count"]]
            return httpx.Response(
                200,
                json={"data": {"searchAcrossEntities": {
                    "start": start,
                    "count": len(page),
                    "total": len(values),
                    "searchResults": [
                        {"entity": {"urn": urn, "type": entity_type}, "matchedFields": []}
                        for urn in page
                    ],
                }}},
            )
        if "GovernedDataset" in query:
            return httpx.Response(200, json={"data": {"dataset": self.datasets[variables["urn"]]}})
        if "GovernedGlossaryTerm" in query:
            return httpx.Response(200, json={"data": {"glossaryTerm": self.terms[variables["urn"]]}})
        if "GovernanceOwner" in query:
            owner = self.owners[variables["urn"]]
            return httpx.Response(200, json={"data": {"corpGroup": {
                "urn": owner["urn"],
                "name": owner["urn"].rsplit(":", 1)[-1],
                "properties": {
                    "displayName": owner["name"],
                    "description": owner["description"],
                },
            }}})
        if "GovernanceDomain" in query:
            domain = self.domains[variables["urn"]]
            return httpx.Response(200, json={"data": {"domain": {
                "urn": domain["urn"],
                "id": domain["urn"].rsplit(":", 1)[-1],
                "properties": {
                    "name": domain["name"],
                    "description": domain["description"],
                },
            }}})
        if "GovernanceLifecycleStages" in query:
            return httpx.Response(
                200,
                json={"data": {"listLifecycleStages": self.lifecycle_stages}},
            )
        raise AssertionError("unexpected DataHub GraphQL operation")

    def trino(self, request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path == "/v1/info":
            return httpx.Response(200, json={"starting": False})
        statement = request.content.decode("utf-8")
        self.trino_statements.append(statement)
        asset = self._asset_for_statement(statement)
        if '"information_schema"."tables"' in statement:
            return httpx.Response(200, json={
                "id": "table-query",
                "stats": {"state": "FINISHED"},
                "columns": [{"name": "table_type"}],
                "data": [[asset["table_type"]]],
            })
        if '"information_schema"."columns"' in statement:
            rows = [
                [
                    column["ordinal_position"],
                    column["name"],
                    column["native_type"],
                    "YES" if column["nullable"] else "NO",
                ]
                for column in asset["columns"]
            ]
            if self.schema_drift:
                rows[-1][2] = "bigint"
            return httpx.Response(200, json={
                "id": "schema-query",
                "stats": {"state": "FINISHED"},
                "columns": [{"name": name} for name in (
                    "ordinal_position", "column_name", "data_type", "is_nullable"
                )],
                "data": rows,
            })
        return httpx.Response(200, json={
            "id": "analysis-query",
            "stats": {"state": "FINISHED"},
            "columns": [{"name": "helium_total"}],
            "data": [[23.5]],
        })

    def _asset_for_statement(self, statement: str) -> dict:
        for asset in self.bundle["schema_context"]["assets"]:
            catalog, schema, table = asset["fqn"].split(".")
            if (
                f'FROM "{catalog}"."information_schema"' in statement
                and f'"table_schema" = \'{schema}\'' in statement
                and f'"table_name" = \'{table}\'' in statement
            ):
                return asset
        if "information_schema" in statement:
            raise AssertionError("Trino inspection did not identify a governed asset")
        return self.bundle["schema_context"]["assets"][0]


class GovernedDataPlatformRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.transport = RuntimeTransport(_bundle())
        self.datahub_http = httpx.AsyncClient(transport=httpx.MockTransport(self.transport.datahub))
        self.trino_http = httpx.AsyncClient(transport=httpx.MockTransport(self.transport.trino))
        catalog = DataHubCatalogClient(
            "http://datahub.test",
            client=self.datahub_http,
            page_size=1,
            max_entities=20,
        )
        trino = TrinoAsyncClient(
            "https://trino.test", "runtime", "test-password", client=self.trino_http
        )
        self.adapter = GovernedDataPlatformAdapter(
            "https://trino.test",
            "runtime",
            datahub_client=catalog,
            trino_client=trino,
            search_mode="hybrid",
        )

    async def asyncTearDown(self) -> None:
        await self.adapter.aclose()
        await self.datahub_http.aclose()
        await self.trino_http.aclose()

    async def test_publisher_aspect_mock_contract_and_prebound_sql_passthrough(self) -> None:
        assets = await self.adapter.search_assets(
            "helium",
            {"role": "hotel_analyst", "parameters": {}},
        )
        term = await self.adapter.get_metric_terms(("helium_yield",))
        schema = await self.adapter.get_asset_schema(assets[0]["urn"])
        executable_sql = (
            'SELECT SUM("measure_value") AS "helium_total" '
            'FROM "orbit"."lake"."helium_fact" LIMIT 10'
        )
        gate_token = issue_query_capability("1" * 64, executable_sql)
        submitted = await self.adapter.execute_query(executable_sql, {}, gate_token)
        terminal = await self.adapter.get_query_status(submitted["query_id"])
        repeated = await self.adapter.get_query_status(submitted["query_id"])

        self.assertEqual(["orbit.lake.helium_fact"], [item["fqn"] for item in assets])
        self.assertEqual("calendar-arbitrary-lunisolar", assets[0]["time_metadata"]["calendar_id"])
        self.assertEqual("Helium yield", term["helium_yield"]["label"])
        self.assertEqual(["event_id", "observed_on", "measure_value"], [item["name"] for item in schema["columns"]])
        self.assertEqual("SUCCEEDED", terminal["status"])
        self.assertEqual(terminal, repeated)
        self.assertEqual([{"helium_total": 23.5}], terminal["rows"])
        self.assertIn(executable_sql, self.transport.trino_statements)
        self.assertEqual([0, 1], self.transport.search_starts["DATASET"])
        self.assertEqual([0, 1], self.transport.search_starts["GLOSSARY_TERM"])

    async def test_semantic_capability_failure_is_typed_and_closed(self) -> None:
        self.transport.semantic_disabled = True
        with self.assertRaises(MetadataUnavailableError):
            await self.adapter.search_assets(
                "helium",
                {"role": "hotel_analyst", "parameters": {}},
            )

    async def test_explicit_lexical_mode_does_not_call_disabled_semantic_search(self) -> None:
        self.transport.semantic_disabled = True
        catalog = DataHubCatalogClient(
            "http://datahub.test",
            client=self.datahub_http,
            page_size=1,
            max_entities=20,
        )
        trino = TrinoAsyncClient(
            "https://trino.test", "runtime", "test-password", client=self.trino_http
        )
        adapter = GovernedDataPlatformAdapter(
            "https://trino.test",
            "runtime",
            datahub_client=catalog,
            trino_client=trino,
            search_mode="lexical",
        )
        assets = await adapter.search_assets(
            "helium",
            {"role": "hotel_analyst", "parameters": {}},
        )
        self.assertEqual(["orbit.lake.helium_fact"], [item["fqn"] for item in assets])

    async def test_entitlement_is_only_the_published_role_domain_policy(self) -> None:
        with self.assertRaises(NoEntitledAssetsError):
            await self.adapter.search_assets(
                "helium",
                {"role": "unpublished_role", "parameters": {}},
            )

    async def test_incomplete_governance_and_trino_drift_are_typed_failures(self) -> None:
        first = next(iter(self.transport.datasets.values()))
        first["properties"]["customProperties"] = [
            item
            for item in first["properties"]["customProperties"]
            if item["key"] != "answervice.query_policy"
        ]
        with self.assertRaises(MetadataUnavailableError):
            await self.adapter.search_assets(
                "helium", {"role": "hotel_analyst", "parameters": {}}
            )
        self.transport = RuntimeTransport(_bundle())
        self.transport.schema_drift = True
        await self.datahub_http.aclose()
        await self.trino_http.aclose()
        self.datahub_http = httpx.AsyncClient(transport=httpx.MockTransport(self.transport.datahub))
        self.trino_http = httpx.AsyncClient(transport=httpx.MockTransport(self.transport.trino))
        catalog = DataHubCatalogClient("http://datahub.test", client=self.datahub_http, page_size=1, max_entities=20)
        trino = TrinoAsyncClient(
            "https://trino.test", "runtime", "test-password", client=self.trino_http
        )
        self.adapter = GovernedDataPlatformAdapter("https://trino.test", "runtime", datahub_client=catalog, trino_client=trino)
        with self.assertRaises(MetadataUnavailableError):
            await self.adapter.search_assets(
                "helium", {"role": "hotel_analyst", "parameters": {}}
            )

    async def test_execution_rejects_rebinding_after_phase_three(self) -> None:
        with self.assertRaisesRegex(ValueError, "must be bound"):
            sql = "SELECT :value"
            await self.adapter.execute_query(
                sql,
                {"value": 1},
                issue_query_capability("1" * 64, sql),
            )

    async def test_execution_capability_is_bound_to_exact_sql(self) -> None:
        approved_sql = "SELECT 1"
        token = issue_query_capability("2" * 64, approved_sql)
        for sql, candidate in (
            ("SELECT 2", token),
            (approved_sql, "random-token"),
            (approved_sql + " ", token),
        ):
            with self.subTest(sql=sql, candidate=candidate):
                with self.assertRaisesRegex(ValueError, "does not match"):
                    await self.adapter.execute_query(sql, {}, candidate)

    async def test_asset_schema_requires_complete_active_release_membership(self) -> None:
        removed_urn = next(
            urn for urn in self.transport.datasets if "argon_fact" in urn
        )
        self.transport.datasets.pop(removed_urn)
        remaining_urn = next(iter(self.transport.datasets))
        with self.assertRaises(MetadataUnavailableError):
            await self.adapter.get_asset_schema(remaining_urn)

    async def test_live_content_hash_rejects_coordinated_policy_tampering(self) -> None:
        for dataset in self.transport.datasets.values():
            for item in dataset["properties"]["customProperties"]:
                if item["key"] == "answervice.query_policy":
                    value = json.loads(item["value"])
                    value["max_limit"] -= 1
                    item["value"] = json.dumps(
                        value,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
        with self.assertRaises(MetadataUnavailableError):
            await self.adapter.search_assets(
                "helium", {"role": "hotel_analyst", "parameters": {}}
            )

    async def test_native_governance_detail_drift_fails_closed(self) -> None:
        for kind in ("owners", "domains", "approved_lifecycles"):
            with self.subTest(kind=kind):
                transport = RuntimeTransport(_bundle())
                values = getattr(
                    transport,
                    "lifecycle_stages" if kind == "approved_lifecycles" else kind,
                )
                target = values[0] if isinstance(values, list) else next(iter(values.values()))
                target["description"] += " drift"
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
                        page_size=1,
                        max_entities=20,
                    ),
                    trino_client=TrinoAsyncClient(
                        "https://trino.test", "runtime", "test-password", client=trino_http
                    ),
                )
                try:
                    with self.assertRaises(MetadataUnavailableError):
                        await adapter.search_assets(
                            "helium", {"role": "hotel_analyst", "parameters": {}}
                        )
                finally:
                    await adapter.aclose()
                    await datahub_http.aclose()
                    await trino_http.aclose()

    async def test_empty_metric_dimension_is_allowed_only_on_governed_join_path(self) -> None:
        transport = RuntimeTransport(_bundle_with_dimension_bridge())
        datahub_http = httpx.AsyncClient(transport=httpx.MockTransport(transport.datahub))
        trino_http = httpx.AsyncClient(transport=httpx.MockTransport(transport.trino))
        adapter = GovernedDataPlatformAdapter(
            "https://trino.test",
            "runtime",
            datahub_client=DataHubCatalogClient(
                "http://datahub.test", client=datahub_http, page_size=1, max_entities=20
            ),
            trino_client=TrinoAsyncClient(
                "https://trino.test", "runtime", "test-password", client=trino_http
            ),
        )
        try:
            assets = await adapter.search_assets(
                "neon", {"role": "hotel_analyst", "parameters": {}}
            )
        finally:
            await adapter.aclose()
            await datahub_http.aclose()
            await trino_http.aclose()

        by_fqn = {item["fqn"]: item for item in assets}
        self.assertEqual(
            {"orbit.lake.helium_fact", "orbit.reference.neon_dimension"},
            set(by_fqn),
        )
        self.assertEqual([], by_fqn["orbit.reference.neon_dimension"]["metrics"])
        self.assertEqual(
            ["helium_neon_by_event"],
            by_fqn["orbit.reference.neon_dimension"]["join_ids"],
        )


@unittest.skipUnless(
    os.getenv("TEST_REAL_DATA_PLATFORM") == "1",
    "opt-in live DataHub/Trino fail-closed smoke",
)
class LiveGovernanceSmokeTest(unittest.IsolatedAsyncioTestCase):
    def _adapter(self, *, search_mode: str = "lexical") -> GovernedDataPlatformAdapter:
        return GovernedDataPlatformAdapter(
            os.getenv("TRINO_URL", "https://127.0.0.1:18443"),
            os.getenv("TRINO_RUNTIME_USER", ""),
            os.getenv("DATAHUB_GMS_URL", "https://127.0.0.1:18081"),
            os.getenv("DATAHUB_API_TOKEN"),
            trino_password=os.getenv("TRINO_RUNTIME_PASSWORD", ""),
            trino_ca_file=os.getenv("TRINO_TLS_CA_FILE", ""),
            datahub_ca_file=os.getenv("DATAHUB_TLS_CA_FILE", ""),
            expected_context_release=os.getenv("ANALYTICS_CONTEXT_RELEASE") or None,
            search_mode=search_mode,
        )

    async def test_current_disabled_semantic_capability_is_not_bypassed(self) -> None:
        adapter = self._adapter(search_mode="hybrid")
        try:
            with self.assertRaises(MetadataUnavailableError):
                await adapter.search_assets(
                    os.getenv("LIVE_GOVERNANCE_SMOKE_QUERY", "runtime governance"),
                    {"role": "hotel_analyst", "parameters": {}},
                )
        finally:
            await adapter.aclose()

    async def test_current_incomplete_catalog_is_not_accepted(self) -> None:
        adapter = self._adapter()
        try:
            with self.assertRaises(MetadataUnavailableError):
                await adapter.get_active_context_release()
        finally:
            await adapter.aclose()
