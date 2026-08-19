import json
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from urllib.parse import unquote

import httpx


ROOT = Path(__file__).resolve().parents[2]
DATAHUB_DIR = ROOT / "infrastructure/database/datahub"
BACKEND = ROOT / "app" / "backend"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(DATAHUB_DIR))
sys.path.insert(0, str(BACKEND))

from metadata_aspects import iter_aspects  # noqa: E402
from src.data.governance_contract import (  # noqa: E402
    catalog_hash,
    glossary_hash,
    release_manifest,
    trino_schema_hash,
)
from metadata_contract import SemanticMetadataError, validate_bundle  # noqa: E402
from metadata_graphql import _assert_release_membership  # noqa: E402
from metadata_rest import assert_contains, preflight_owner_entities  # noqa: E402
from metadata_wire import metadata_change_proposals  # noqa: E402
from publish_semantic_catalog import publish_bundle  # noqa: E402
from verify_semantic_catalog import verify  # noqa: E402
from app.adapters.datahub_metadata import parse_dataset  # noqa: E402


OWNER = "urn:li:corpGroup:quartz_stewards"
DOMAIN = "urn:li:domain:quartz"
LIFECYCLE = "urn:li:lifecycleStageType:APPROVED"


def _column(position, name, native_type, logical_type, role, *, key=False, nullable=False):
    return {
        "ordinal_position": position,
        "name": name,
        "native_type": native_type,
        "logical_type": logical_type,
        "nullable": nullable,
        "is_part_of_key": key,
        "role": role,
        "description": f"Governed {name} field.",
    }


def arbitrary_bundle():
    quartz_fqn = "quartz.core.events"
    ember_fqn = "ember.core.accounts"
    quartz_urn = "urn:li:dataset:(urn:li:dataPlatform:postgres,quartz.core.events,PROD)"
    ember_urn = (
        "urn:li:dataset:(urn:li:dataPlatform:trino,"
        "ember.platform_instance.core.accounts,PROD)"
    )
    assets = [
        {
            "urn": quartz_urn,
            "fqn": quartz_fqn,
            "description": "Generic event facts.",
            "schema_version": "schema-r7",
            "seed_version": "seed-r2",
            "synthetic": False,
            "approval_status": "APPROVED",
            "owner_urn": OWNER,
            "domain_urn": DOMAIN,
            "approved_lifecycle_urn": LIFECYCLE,
            "platform_urn": "urn:li:dataPlatform:postgres",
            "schema_name": "core.events",
            "schema_metadata_version": 7,
            "dataset_key": {
                "platform": "urn:li:dataPlatform:postgres",
                "name": "quartz.core.events",
                "origin": "PROD",
            },
            "table_type": "BASE TABLE",
            "entitlements": {"roles": ["analyst"], "domains": [DOMAIN]},
            "grain": {"kind": "event", "keys": ["event_id"]},
            "columns": [
                _column(1, "event_id", "bigint", "number", "identifier", key=True),
                _column(2, "account_id", "varchar", "string", "dimension"),
                _column(3, "event_at", "timestamp(3)", "time", "time"),
                _column(4, "amount", "decimal(18,2)", "number", "measure"),
                _column(5, "active", "boolean", "boolean", "attribute"),
            ],
        },
        {
            "urn": ember_urn,
            "fqn": ember_fqn,
            "description": "Generic account dimensions.",
            "schema_version": "schema-r4",
            "seed_version": "seed-r2",
            "synthetic": False,
            "approval_status": "APPROVED",
            "owner_urn": OWNER,
            "domain_urn": DOMAIN,
            "approved_lifecycle_urn": LIFECYCLE,
            "platform_urn": "urn:li:dataPlatform:trino",
            "schema_name": "core.accounts",
            "schema_metadata_version": 4,
            "dataset_key": {
                "platform": "urn:li:dataPlatform:trino",
                "name": "ember.platform_instance.core.accounts",
                "origin": "PROD",
            },
            "table_type": "VIEW",
            "entitlements": {"roles": ["analyst"], "domains": [DOMAIN]},
            "grain": {"kind": "row", "keys": ["account_id"]},
            "columns": [
                _column(1, "account_id", "varchar", "string", "identifier", key=True),
                _column(2, "segment", "varchar", "string", "dimension"),
                _column(3, "valid_from", "timestamp(3)", "time", "time"),
                _column(4, "valid_to", "timestamp(3)", "time", "time", nullable=True),
            ],
        },
    ]
    field = lambda asset, column: {"asset_fqn": asset, "column": column}
    metrics = [
        {
            "id": "amount_total",
            "source": {"kind": "column", "field": field(quartz_fqn, "amount")},
            "aggregation": "sum",
            "result_field": "amount_total",
            "unit": "currency",
            "time_field": field(quartz_fqn, "event_at"),
            "reduction": "sum",
            "dimensions": [field(quartz_fqn, "account_id")],
            "required_filters": [
                {"field": field(quartz_fqn, "active"), "operator": "eq", "parameter": "active"}
            ],
        },
        {
            "id": "account_count",
            "source": {"kind": "column", "field": field(ember_fqn, "account_id")},
            "aggregation": "count_distinct",
            "result_field": "account_count",
            "unit": "count",
            "time_field": field(ember_fqn, "valid_from"),
            "reduction": "sum",
            "dimensions": [field(ember_fqn, "segment")],
            "required_filters": [],
        },
    ]
    terms = [
        {
            "id": metric["id"],
            "urn": f"urn:li:glossaryTerm:{metric['id']}",
            "name": metric["id"],
            "definition": f"Governed definition for {metric['id']}.",
            "aliases": [metric["id"], f"{metric['id']}_alias"],
            "unit": metric["unit"],
            "version": "glossary-r3",
            "approval_status": "APPROVED",
            "owner_urn": OWNER,
            "domain_urn": DOMAIN,
            "approved_lifecycle_urn": LIFECYCLE,
        }
        for metric in metrics
    ]
    return {
        "catalog_version": "catalog-r9",
        "policy_version": "policy-r5",
        "governance_entities": {
            "owners": [{"urn": OWNER, "name": "Quartz Stewards", "description": "Stewards."}],
            "domains": [{"urn": DOMAIN, "name": "Quartz", "description": "Generic domain."}],
            "approved_lifecycles": [
                {"urn": LIFECYCLE, "name": "APPROVED", "description": "Approved metadata."}
            ],
        },
        "schema_context": {"version": "context-r9", "assets": assets},
        "metric_rules": metrics,
        "metric_terms": terms,
        "dimensions": [
            {
                "id": "segment",
                "aliases": ["segment", "cohort"],
                "definition": "Governed account segment.",
                "asset_fqn": ember_fqn,
                "column": "segment",
            }
        ],
        "join_graph": {
            "edges": [
                {
                    "id": "event_account",
                    "left": quartz_fqn,
                    "right": ember_fqn,
                    "kind": "left",
                    "cardinality": "many_to_one",
                    "equality_conditions": [
                        {"left_column": "account_id", "right_column": "account_id"}
                    ],
                    "temporal_conditions": [
                        {
                            "event_field": field(quartz_fqn, "event_at"),
                            "validity_asset_fqn": ember_fqn,
                            "valid_from_column": "valid_from",
                            "valid_to_column": "valid_to",
                            "end_exclusive": True,
                        }
                    ],
                    "preaggregation": {
                        "required": True,
                        "grain": [field(quartz_fqn, "account_id")],
                        "keys": [field(quartz_fqn, "account_id")],
                    },
                }
            ]
        },
        "time_rules": {
            "timezone": "UTC",
            "calendar_id": "iso8601",
            "interval": "[start,end)",
            "start_parameter": "start_at",
            "end_parameter": "end_at",
            "fields": [
                {
                    "field": field(quartz_fqn, "event_at"),
                    "native_type": "timestamp(3)",
                    "bucket": "day",
                    "timezone_mode": "preserve",
                },
                {
                    "field": field(ember_fqn, "valid_from"),
                    "native_type": "timestamp(3)",
                    "bucket": "none",
                    "timezone_mode": "preserve",
                },
            ],
        },
        "parameter_contract": {
            "style": "named",
            "parameters": [
                {"name": "start_at", "type": "timestamp", "scope": "time"},
                {"name": "end_at", "type": "timestamp", "scope": "time"},
                {"name": "active", "type": "boolean", "scope": "filter"},
                {"name": "row_limit", "type": "number", "scope": "limit"},
            ],
        },
        "query_policy": {
            "dialect": "trino",
            "statement_type": "select",
            "read_only": True,
            "require_limit": True,
            "max_limit": 500,
            "allowed_functions": ["sum", "count"],
            "allowed_catalogs": ["ember", "quartz"],
        },
    }


def arbitrary_ratio_bundle():
    """같은 계산 범위의 두 column metric과 derived ratio를 가진 일반 publication fixture를 만든다."""

    bundle = arbitrary_bundle()
    fqn = "quartz.core.events"
    field = lambda column: {"asset_fqn": fqn, "column": column}
    amount = bundle["metric_rules"][0]
    count = {
        "id": "event_count",
        "source": {"kind": "column", "field": field("event_id")},
        "aggregation": "count",
        "result_field": "event_count",
        "unit": "count",
        "time_field": field("event_at"),
        "reduction": "sum",
        "dimensions": deepcopy(amount["dimensions"]),
        "required_filters": deepcopy(amount["required_filters"]),
    }
    ratio = {
        "id": "amount_per_event",
        "source": {
            "kind": "ratio",
            "numerator_metric_id": "amount_total",
            "denominator_metric_id": "event_count",
            "zero_policy": "null_on_zero_denominator",
        },
        "aggregation": "ratio",
        "result_field": "amount_per_event",
        "unit": "currency_per_event",
        "time_field": None,
        "reduction": "ratio",
        "dimensions": [],
        "required_filters": [],
    }
    bundle["metric_rules"].extend((count, ratio))
    bundle["metric_terms"].extend(
        (
            {
                "id": "event_count",
                "urn": "urn:li:glossaryTerm:event_count",
                "name": "Event Count",
                "definition": "Approved count of governed events.",
                "aliases": ["Event Count", "event volume"],
                "unit": "count",
                "version": "glossary-r3",
                "approval_status": "APPROVED",
                "owner_urn": OWNER,
                "domain_urn": DOMAIN,
                "approved_lifecycle_urn": LIFECYCLE,
            },
            {
                "id": "amount_per_event",
                "urn": "urn:li:glossaryTerm:amount_per_event",
                "name": "Amount per Event",
                "definition": "Approved amount divided by governed event count.",
                "aliases": ["Amount per Event", "average event amount"],
                "unit": "currency_per_event",
                "version": "glossary-r3",
                "approval_status": "APPROVED",
                "owner_urn": OWNER,
                "domain_urn": DOMAIN,
                "approved_lifecycle_urn": LIFECYCLE,
            },
        )
    )
    return bundle


def _aspect_index(bundle):
    result = {}
    for _entity_type, urn, name, value in iter_aspects(bundle):
        result.setdefault(urn, {})[name] = value
    return result


def test_glossary_key_uses_canonical_urn_identifier():
    """업무 metric id와 DataHub entity key를 혼동하지 않는다."""

    bundle = arbitrary_bundle()
    term = bundle["metric_terms"][0]
    key = _aspect_index(bundle)[term["urn"]]["glossaryTermKey"]

    assert key["name"] == term["urn"].removeprefix("urn:li:glossaryTerm:")


def _native(entity, definition):
    entity.update(
        {
            "status": {
                "removed": False,
                "lifecycleStage": {"urn": LIFECYCLE, "name": "APPROVED"},
            },
            "ownership": {
                "owners": [
                    {
                        "type": "TECHNICAL_OWNER",
                        "associatedUrn": definition["urn"],
                        "ownershipType": {
                            "urn": "urn:li:ownershipType:__system__technical_owner"
                        },
                        "owner": {"urn": definition["owner_urn"]},
                    }
                ]
            },
            "domain": {"domain": {"urn": definition["domain_urn"]}},
        }
    )
    return entity


def _graphql_dataset(asset, bundle, aspects):
    properties = aspects[asset["urn"]]["datasetProperties"]
    dataset_terms = aspects[asset["urn"]]["glossaryTerms"]["terms"]
    entity = {
        "urn": asset["urn"],
        "name": asset["fqn"],
        "properties": {
            "name": properties["name"],
            "qualifiedName": properties["qualifiedName"],
            "description": properties["description"],
            "customProperties": [
                {"key": key, "value": value}
                for key, value in properties["customProperties"].items()
            ],
        },
        "schemaMetadata": {
            "version": asset["schema_metadata_version"],
            "name": asset["schema_name"],
            "hash": aspects[asset["urn"]]["schemaMetadata"]["hash"],
            "fields": [
                {
                    "fieldPath": column["name"],
                    "nativeDataType": column["native_type"],
                    "nullable": column["nullable"],
                    "isPartOfKey": column["is_part_of_key"],
                    "description": column["description"],
                    # DataHub v1.7 GraphQL은 editable field term을 여기 투영하지 않는다.
                    "glossaryTerms": None,
                }
                for column in asset["columns"]
            ],
        },
        "glossaryTerms": {
            "terms": [
                {"term": {"urn": item["urn"]}}
                for item in dataset_terms
            ]
        },
    }
    return _native(entity, asset)


def _graphql_term(term, aspects):
    info = aspects[term["urn"]]["glossaryTermInfo"]
    entity = {
        "urn": term["urn"],
        "exists": True,
        "glossaryTermInfo": {
            "name": info["name"],
            "description": info["definition"],
            "termSource": info["termSource"],
            "sourceRef": info["sourceRef"],
            "customProperties": [
                {"key": key, "value": value}
                for key, value in info["customProperties"].items()
            ],
        },
    }
    entity = _native(entity, term)
    # Pinned DataHub v1.7의 실제 GraphQL wire는 term status를 null로 반환한다.
    entity["status"] = None
    return entity


class SemanticPublicationContractTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.bundle = arbitrary_bundle()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.bundle_path = Path(self.temp_dir.name) / "arbitrary-semantic-bundle.json"
        self.bundle_path.write_text(json.dumps(self.bundle), encoding="utf-8")

    def test_contract_and_canonical_fingerprint_algorithms(self):
        validate_bundle(self.bundle)
        manifest = release_manifest(self.bundle)
        self.assertEqual(2, manifest["dataset_count"])
        self.assertEqual(9, manifest["column_count"])
        self.assertEqual(2, manifest["metric_term_count"])
        by_urn = {item["urn"]: item for item in manifest["datasets"]}
        first_asset = self.bundle["schema_context"]["assets"][0]
        self.assertEqual(
            trino_schema_hash(first_asset),
            by_urn[first_asset["urn"]]["trino_schema_sha256"],
        )
        reversed_terms = deepcopy(self.bundle)
        reversed_terms["metric_terms"].reverse()
        self.assertEqual(glossary_hash(self.bundle), glossary_hash(reversed_terms))
        changed = deepcopy(self.bundle)
        changed["schema_context"]["assets"][0]["columns"][3]["native_type"] = "double"
        self.assertNotEqual(catalog_hash(self.bundle), catalog_hash(changed))

    def test_ratio_contract_is_hashed_and_associated_without_fake_column_binding(self):
        bundle = arbitrary_ratio_bundle()
        validate_bundle(bundle)
        aspects = _aspect_index(bundle)
        ratio_urn = "urn:li:glossaryTerm:amount_per_event"
        asset = bundle["schema_context"]["assets"][0]

        dataset_terms = {
            item["urn"] for item in aspects[asset["urn"]]["glossaryTerms"]["terms"]
        }
        editable = aspects[asset["urn"]]["editableSchemaMetadata"]
        field_terms = {
            item["fieldPath"]: {
                term["urn"]
                for term in item.get("glossaryTerms", {}).get("terms", ())
            }
            for item in editable["editableSchemaFieldInfo"]
        }
        self.assertIn(ratio_urn, dataset_terms)
        self.assertTrue(all(ratio_urn not in values for values in field_terms.values()))
        self.assertEqual(4, release_manifest(bundle)["metric_term_count"])

        changed = deepcopy(bundle)
        changed["metric_rules"][-1]["result_field"] = "amount_per_event_changed"
        self.assertNotEqual(catalog_hash(bundle), catalog_hash(changed))

    def test_ratio_contract_rejects_missing_or_misaligned_operands(self):
        bundle = arbitrary_ratio_bundle()
        missing = deepcopy(bundle)
        missing["metric_rules"][-1]["source"]["denominator_metric_id"] = "missing"
        misaligned = deepcopy(bundle)
        misaligned["metric_rules"][2]["dimensions"] = []
        nested = deepcopy(bundle)
        nested["metric_rules"][-1]["source"]["denominator_metric_id"] = "amount_per_event"
        for invalid in (missing, misaligned, nested):
            with self.subTest(invalid=invalid["metric_rules"][-1]["source"]):
                with self.assertRaises(SemanticMetadataError):
                    validate_bundle(invalid)

    def test_contract_rejects_values_formula_and_incomplete_native_governance(self):
        cases = []
        runtime_value = deepcopy(self.bundle)
        runtime_value["parameter_contract"]["parameters"][0]["value"] = "forbidden"
        cases.append(runtime_value)
        formula = deepcopy(self.bundle)
        formula["metric_rules"][0]["source"] = {"kind": "formula", "field": None}
        cases.append(formula)
        bad_owner = deepcopy(self.bundle)
        bad_owner["schema_context"]["assets"][0]["owner_urn"] = "urn:li:corpGroup:missing"
        cases.append(bad_owner)
        unused_owner = deepcopy(self.bundle)
        unused_owner["governance_entities"]["owners"].append(
            {"urn": "urn:li:corpGroup:unused", "name": "Unused", "description": "Unused."}
        )
        cases.append(unused_owner)
        invalid_entitlement_domain = deepcopy(self.bundle)
        invalid_entitlement_domain["schema_context"]["assets"][0]["entitlements"][
            "domains"
        ] = ["quartz"]
        cases.append(invalid_entitlement_domain)
        invalid_metric_id = deepcopy(self.bundle)
        invalid_metric_id["metric_rules"][0]["id"] = "amount-total"
        invalid_metric_id["metric_terms"][0]["id"] = "amount-total"
        cases.append(invalid_metric_id)
        invalid_result_field = deepcopy(self.bundle)
        invalid_result_field["metric_rules"][0]["result_field"] = "amount-total"
        cases.append(invalid_result_field)
        invalid_dimension_id = deepcopy(self.bundle)
        invalid_dimension_id["dimensions"][0]["id"] = "account-segment"
        cases.append(invalid_dimension_id)
        excessive_metrics = deepcopy(self.bundle)
        prototype_metric = excessive_metrics["metric_rules"][0]
        prototype_term = excessive_metrics["metric_terms"][0]
        excessive_metrics["metric_rules"] = [
            {**deepcopy(prototype_metric), "id": f"metric_{index}"}
            for index in range(65)
        ]
        excessive_metrics["metric_terms"] = [
            {**deepcopy(prototype_term), "id": f"metric_{index}"}
            for index in range(65)
        ]
        cases.append(excessive_metrics)
        for case in cases:
            with self.subTest(case=cases.index(case)):
                with self.assertRaises(SemanticMetadataError):
                    validate_bundle(case)

    def test_publisher_graphql_shape_is_accepted_by_runtime_parser(self):
        validate_bundle(self.bundle)
        aspects = _aspect_index(self.bundle)
        for asset in self.bundle["schema_context"]["assets"]:
            parsed = parse_dataset(_graphql_dataset(asset, self.bundle, aspects))
            self.assertEqual(asset["urn"], parsed.urn)
            self.assertEqual(frozenset(asset["entitlements"]["domains"]), parsed.allowed_domains)

        ratio_bundle = arbitrary_ratio_bundle()
        ratio_aspects = _aspect_index(ratio_bundle)
        ratio_asset = ratio_bundle["schema_context"]["assets"][0]
        parsed = parse_dataset(
            _graphql_dataset(ratio_asset, ratio_bundle, ratio_aspects)
        )
        self.assertIn(
            "urn:li:glossaryTerm:amount_per_event", parsed.dataset_terms
        )

    async def test_mcp_wire_contract_uses_one_injected_audit_stamp(self):
        requests = []

        def handler(request):
            if request.method == "GET":
                return httpx.Response(
                    200,
                    json={
                        "urn": OWNER,
                        "aspects": {
                            "corpGroupInfo": {"value": {
                                "displayName": "Quartz Stewards",
                                "description": "Stewards.",
                            }},
                            "status": {"value": {"removed": False}},
                        },
                    },
                )
            body = json.loads(request.content)
            proposal = body["proposal"]
            requests.append((request.url.path, proposal))
            return httpx.Response(200)

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport, trust_env=False) as http:
            result = await publish_bundle(
                "http://localhost:18081",
                self.bundle,
                actor_urn="urn:li:corpuser:publisher",
                http=http,
                clock=lambda: 1_808_000_000_123,
            )
        self.assertEqual("PUBLISHED", result["status"])
        self.assertTrue(requests)
        self.assertTrue(all(path == "/aspects" for path, _ in requests))
        self.assertFalse(any("/openapi/" in path for path, _ in requests))
        schema = next(
            json.loads(body["aspect"]["value"])
            for _path, body in requests
            if body["entityType"] == "dataset"
            and body["aspectName"] == "schemaMetadata"
        )
        self.assertIn("com.linkedin.schema.OtherSchema", schema["platformSchema"])
        self.assertIn(
            "com.linkedin.schema.NumberType",
            schema["fields"][0]["type"]["type"],
        )
        wire = json.dumps(
            [
                json.loads(body["aspect"]["value"])
                for _path, body in requests
            ],
            sort_keys=True,
        )
        self.assertIn("urn:li:corpuser:publisher", wire)
        self.assertIn("1808000000123", wire)
        self.assertNotIn("corpuser:unknown", wire)
        with self.assertRaisesRegex(ValueError, "explicit actor"):
            metadata_change_proposals("dataset", "urn:li:dataset:x", {"status": {"removed": False}}, {"actor": "urn:li:corpuser:unknown", "time": 0})

    async def test_owner_preflight_rejects_description_drift(self):
        class DriftedOwnerClient:
            async def get_entity(self, _urn, _aspects):
                return {"aspects": {
                    "corpGroupInfo": {"value": {
                        "displayName": "Quartz Stewards",
                        "description": "Drifted description.",
                    }},
                    "status": {"value": {"removed": False}},
                }}

        with self.assertRaisesRegex(ValueError, "owner precondition"):
            await preflight_owner_entities(DriftedOwnerClient(), self.bundle)

    async def test_owner_preflight_accepts_ui_created_group_without_status_aspect(self):
        class UiCreatedOwnerClient:
            async def get_entity(self, _urn, _aspects):
                return {"aspects": {
                    "corpGroupInfo": {"value": {
                        "displayName": "Quartz Stewards",
                        "description": "Stewards.",
                    }},
                }}

        await preflight_owner_entities(UiCreatedOwnerClient(), self.bundle)

    def test_rest_subset_comparison_allows_server_fields_inside_ordered_lists(self):
        """Rest.li가 list item에 생성 필드를 보강해도 계약 필드와 순서는 유지한다."""

        assert_contains(
            [{"fieldPath": "amount", "serverAudit": {"version": 1}}],
            [{"fieldPath": "amount"}],
            "editable fields",
        )
        with self.assertRaisesRegex(ValueError, "value mismatch"):
            assert_contains(
                [{"fieldPath": "other"}],
                [{"fieldPath": "amount"}],
                "editable fields",
            )

    async def test_mocked_verifier_contract_requires_rest_and_graphql_shapes(self):
        aspects = _aspect_index(self.bundle)
        assets = {item["urn"]: item for item in self.bundle["schema_context"]["assets"]}
        terms = {item["urn"]: item for item in self.bundle["metric_terms"]}
        graphql_calls = []

        def handler(request):
            if request.method == "GET":
                urn = unquote(request.url.path.rsplit("/", 1)[1])
                if urn == OWNER:
                    values = {
                        "corpGroupInfo": {
                            "displayName": "Quartz Stewards",
                            "description": "Stewards.",
                        },
                        "status": {"removed": False},
                    }
                else:
                    values = aspects[urn]
                return httpx.Response(
                    200,
                    json={"urn": urn, "aspects": {k: {"value": v} for k, v in values.items()}},
                )
            body = json.loads(request.content)
            if "searchAcrossEntities" in body["query"]:
                entity_type = body["variables"]["input"]["types"][0]
                urns = assets if entity_type == "DATASET" else terms
                rows = [
                    {"entity": {"urn": urn, "type": entity_type}}
                    for urn in urns
                ]
                return httpx.Response(200, json={"data": {"searchAcrossEntities": {
                    "start": 0, "count": len(rows), "total": len(rows),
                    "searchResults": rows,
                }}})
            urn = body["variables"]["urn"]
            graphql_calls.append(urn)
            if urn in assets:
                entity = _graphql_dataset(assets[urn], self.bundle, aspects)
                return httpx.Response(200, json={"data": {"dataset": entity}})
            entity = _graphql_term(terms[urn], aspects)
            return httpx.Response(200, json={"data": {"glossaryTerm": entity}})

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler), trust_env=False
        ) as http:
            result = await verify(
                "http://localhost:18081", self.bundle_path, http=http
            )
        self.assertEqual("VERIFIED", result["status"])
        self.assertEqual(set(assets) | set(terms), set(graphql_calls))

    def test_verifier_rejects_partial_or_extra_release_membership(self):
        with self.assertRaisesRegex(ValueError, "release membership"):
            _assert_release_membership({"urn:one": {}}, {"urn:one", "urn:two"}, "dataset")
        with self.assertRaisesRegex(ValueError, "release membership"):
            _assert_release_membership({"urn:one": {}, "urn:extra": {}}, {"urn:one"}, "dataset")
if __name__ == "__main__":
    unittest.main()
