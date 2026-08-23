from __future__ import annotations

import copy
import json
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import unquote

import httpx


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "app" / "backend"
PUBLISHER = ROOT / "infrastructure" / "database" / "datahub"
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(PUBLISHER))
from metadata_aspects import iter_aspects  # noqa: E402
from metadata_contract import validate_bundle  # noqa: E402
from src.data.governance_contract import datahub_schema_sha1  # noqa: E402

from app.adapters.catalog_snapshot import (  # noqa: E402
    DEFAULT_CATALOG_RELEASE_TTL_SECONDS,
)
from app.adapters.datahub_catalog import DataHubCatalogClient  # noqa: E402
from app.adapters.governed_data_platform import (  # noqa: E402
    GovernedDataPlatformAdapter,
)
from app.adapters.query_governance import QueryGovernanceEngine  # noqa: E402
from app.adapters.runtime_catalog_projection import (  # noqa: E402
    LEGACY_SHADOW,
    NATIVE_PRIORITY,
    RuntimeCatalogProjection,
    RuntimeCatalogProjectionError,
    build_source_selection_manifest,
)
from app.adapters.runtime_catalog_repository import (  # noqa: E402
    ActiveRuntimeCatalogProjection,
)
from app.adapters.trino_async import TrinoAsyncClient  # noqa: E402
from app.adapters.trino_schema import TrinoSchemaInspector  # noqa: E402
from app.ports.data_platform import (  # noqa: E402
    ExecutionAssetSelection,
    MetadataUnavailableError,
    NoEntitledAssetsError,
    NoMetricMatchError,
    ReleaseReceiptChangedError,
    UnsupportedSemanticError,
)
from app.query_capability import issue_query_capability  # noqa: E402
from app.services.context.contract import GovernedJoin  # noqa: E402
from app.adapters.legacy_semantic_release import (  # noqa: E402
    compile_legacy_semantic_release,
)


LIFECYCLE_URN = "urn:li:lifecycleStageType:approved"


class MutableProjectionRepository:
    """Test-only active pointer whose receipt can change between two calls."""

    def __init__(self, active: ActiveRuntimeCatalogProjection) -> None:
        self.active = active
        self.releases = {active.product_release_id: active}

    async def load_active(self) -> ActiveRuntimeCatalogProjection:
        self.releases[self.active.product_release_id] = self.active
        return self.active

    async def load_product_release(
        self,
        product_release_id: str,
    ) -> ActiveRuntimeCatalogProjection:
        if product_release_id not in self.releases:
            raise RuntimeError("product release is unavailable")
        return self.releases[product_release_id]


def _v2_metric_governance(
    *,
    name: str,
    definition: str,
    aliases: list[str],
    grain_kind: str = "event",
    grain_keys: list[str] | None = None,
    dimensions: list[str] | None = None,
) -> dict:
    """운영 runtime과 같은 v2 fail-closed 계약을 합성 fixture에 부여한다."""

    return {
        "visibility": "BUSINESS",
        "semantic": {
            "name": name,
            "definition": definition,
            "aliases": aliases,
        },
        "grain": {
            "kind": grain_kind,
            "keys": grain_keys or ["event_id"],
            "dimensions": dimensions or [],
        },
        "time": {
            "field": "observed_on",
            "semantics": "event_time",
            "timezone": "Asia/Seoul",
            "interval": "[start,end)",
        },
        "join": {"required": False, "allowed_edge_ids": []},
        "permission": {
            "roles": ["analyst"],
            "contains_pii": False,
            "synthetic": False,
        },
        "query_strategies": ["RAW_APPROVED_DETAIL"],
    }


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
        definition = f"Approved aggregate for {name} observations."
        aliases = [alias, f"{name.title()} aggregate"]
        assets.append(
            {
                "urn": urn,
                "fqn": fqn,
                "description": f"Governed {name} observations.",
                "schema_version": "schema-arbitrary-4",
                "seed_version": "data-arbitrary-9",
                "synthetic": False,
                "approval_status": "APPROVED",
                "entitlements": {"roles": ["analyst"], "domains": []},
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
        assets[-1]["datahub_schema_hash"] = datahub_schema_sha1(assets[-1])
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
                "governance": _v2_metric_governance(
                    name=alias,
                    definition=definition,
                    aliases=aliases,
                ),
            }
        )
        terms.append(
            {
                "id": f"{name}_yield",
                "urn": f"urn:li:glossaryTerm:{name}_yield",
                "name": alias,
                "definition": definition,
                "aliases": aliases,
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


def _bundle_with_ratio() -> dict:
    """한 asset의 승인 column operands에서 derived ratio를 발행한 runtime fixture를 만든다."""

    bundle = _bundle()
    fqn = "orbit.lake.helium_fact"
    domain = "urn:li:domain:helium_operations"
    owner = "urn:li:corpGroup:helium_operations"
    count = {
        "id": "helium_observation_count",
        "source": {
            "kind": "column",
            "field": {"asset_fqn": fqn, "column": "event_id"},
        },
        "aggregation": "count",
        "result_field": "helium_observation_count",
        "unit": "count",
        "time_field": {"asset_fqn": fqn, "column": "observed_on"},
        "reduction": "sum",
        "dimensions": [],
        "required_filters": [],
        "governance": _v2_metric_governance(
            name="Helium observation count",
            definition="Approved count of governed helium observations.",
            aliases=["Helium observation count", "Helium volume"],
        ),
    }
    ratio = {
        "id": "helium_rate",
        "source": {
            "kind": "ratio",
            "numerator_metric_id": "helium_yield",
            "denominator_metric_id": "helium_observation_count",
            "zero_policy": "null_on_zero_denominator",
        },
        "aggregation": "ratio",
        "result_field": "helium_rate",
        "unit": "arbitrary_units_per_observation",
        "time_field": None,
        "reduction": "ratio",
        "dimensions": [],
        "required_filters": [],
        "governance": _v2_metric_governance(
            name="Helium rate",
            definition="Approved helium yield per governed observation.",
            aliases=["Helium rate", "Helium average yield"],
        ),
    }
    bundle["metric_rules"].extend((count, ratio))
    bundle["metric_terms"].extend(
        (
            {
                "id": count["id"],
                "urn": "urn:li:glossaryTerm:helium_observation_count",
                "name": "Helium observation count",
                "definition": "Approved count of governed helium observations.",
                "aliases": ["Helium observation count", "Helium volume"],
                "unit": count["unit"],
                "version": "glossary-arbitrary-3",
                "approval_status": "APPROVED",
                "owner_urn": owner,
                "domain_urn": domain,
                "approved_lifecycle_urn": LIFECYCLE_URN,
            },
            {
                "id": ratio["id"],
                "urn": "urn:li:glossaryTerm:helium_rate",
                "name": "Helium rate",
                "definition": "Approved helium yield per governed observation.",
                "aliases": ["Helium rate", "Helium average yield"],
                "unit": ratio["unit"],
                "version": "glossary-arbitrary-3",
                "approval_status": "APPROVED",
                "owner_urn": owner,
                "domain_urn": domain,
                "approved_lifecycle_urn": LIFECYCLE_URN,
            },
        )
    )
    return bundle


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
            "entitlements": {"roles": ["analyst"], "domains": []},
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
    dimension_asset = bundle["schema_context"]["assets"][-1]
    dimension_asset["datahub_schema_hash"] = datahub_schema_sha1(dimension_asset)
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


def _bundle_with_metric_join() -> dict:
    """두 공개 Metric이 같은 승인 edge만 공유하는 일반 multi-asset release를 만든다."""

    bundle = _bundle()
    edge_id = "helium_argon_by_event"
    bundle["join_graph"]["edges"].append(
        {
            "id": edge_id,
            "left": "orbit.lake.helium_fact",
            "right": "orbit.lake.argon_fact",
            "kind": "inner",
            "cardinality": "one_to_one",
            "equality_conditions": [
                {"left_column": "event_id", "right_column": "event_id"}
            ],
            "temporal_conditions": [],
            "preaggregation": {
                "required": False,
                "grain": [
                    {
                        "asset_fqn": "orbit.lake.helium_fact",
                        "column": "event_id",
                    }
                ],
                "keys": [
                    {
                        "asset_fqn": "orbit.lake.helium_fact",
                        "column": "event_id",
                    }
                ],
            },
        }
    )
    for metric in bundle["metric_rules"]:
        metric["governance"]["join"] = {
            "required": True,
            "allowed_edge_ids": [edge_id],
        }
    validate_bundle(bundle)
    return bundle


def _bundle_with_unentitled_metric_join() -> dict:
    """검색 가능 node와 권한 밖 node가 한 edge로 이어진 negative release를 만든다."""

    bundle = _bundle_with_metric_join()
    for asset in bundle["schema_context"]["assets"]:
        if asset["fqn"] == "orbit.lake.argon_fact":
            asset["entitlements"] = {"roles": ["report_admin"], "domains": []}
    for metric in bundle["metric_rules"]:
        if metric["id"] == "argon_yield":
            metric["governance"]["permission"]["roles"] = ["report_admin"]
    validate_bundle(bundle)
    return bundle


def _bundle_with_ambiguous_metric_join() -> dict:
    """같은 두 자산 사이의 관계 의미를 고를 근거가 없는 병렬 edge release를 만든다."""

    bundle = _bundle_with_metric_join()
    parallel = copy.deepcopy(bundle["join_graph"]["edges"][0])
    parallel["id"] = "helium_argon_by_alternate_event"
    bundle["join_graph"]["edges"].append(parallel)
    for metric in bundle["metric_rules"]:
        metric["governance"]["join"]["allowed_edge_ids"] = sorted(
            ("helium_argon_by_event", "helium_argon_by_alternate_event")
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
                # Connector-owned schema read-back is independent from the
                # semantic publisher aspects assembled above.
                "hash": asset["datahub_schema_hash"],
                "fields": fields,
            },
            "editableSchemaMetadata": {
                "editableSchemaFieldInfo": copy.deepcopy(
                    editable["editableSchemaFieldInfo"]
                )
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
        self.scroll_cursors: dict[str, list[str | None]] = {
            "DATASET": [],
            "GLOSSARY_TERM": [],
        }
        self.candidate_queries: list[str] = []
        # 후보 검색 전용 주입점. 열거(scroll) 경로와 분리해 실패·결과를 따로 검증한다.
        self.candidate_search_status: int | None = None
        self.candidate_hits: list[tuple[str, str]] | None = None
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
        if "scrollAcrossEntities" in query:
            request_input = variables["input"]
            entity_type = request_input["types"][0]
            cursor = request_input.get("scrollId")
            self.scroll_cursors[entity_type].append(cursor)
            values = list(self.datasets if entity_type == "DATASET" else self.terms)
            start = int(cursor) if cursor is not None else 0
            page = values[start : start + request_input["count"]]
            next_start = start + len(page)
            return httpx.Response(
                200,
                json={"data": {"scrollAcrossEntities": {
                    "count": len(page),
                    "nextScrollId": (
                        str(next_start) if next_start < len(values) else None
                    ),
                    "searchResults": [
                        {"entity": {"urn": urn, "type": entity_type}, "matchedFields": []}
                        for urn in page
                    ],
                }}},
            )
        if "searchAcrossEntities" in query:
            request_input = variables["input"]
            entity_type = request_input["types"][0]
            self.search_starts[entity_type].append(request_input["start"])
            self.candidate_queries.append(request_input["query"])
            if self.candidate_search_status is not None:
                return httpx.Response(self.candidate_search_status, json={})
            if self.candidate_hits is not None:
                hits = [
                    {"entity": {"urn": urn, "type": hit_type}, "matchedFields": []}
                    for urn, hit_type in self.candidate_hits
                    if hit_type in request_input["types"]
                ]
                return httpx.Response(
                    200,
                    json={"data": {"searchAcrossEntities": {
                        "start": 0,
                        "count": len(hits),
                        "total": len(hits),
                        "searchResults": hits,
                    }}},
                )
            values = [
                (urn, "DATASET")
                for urn in self.datasets
                if "DATASET" in request_input["types"]
            ]
            values.extend(
                (urn, "GLOSSARY_TERM")
                for urn in self.terms
                if "GLOSSARY_TERM" in request_input["types"]
            )
            start = request_input["start"]
            page = values[start : start + request_input["count"]]
            return httpx.Response(
                200,
                json={"data": {"searchAcrossEntities": {
                    "start": start,
                    "count": len(page),
                    "total": len(values),
                    "searchResults": [
                        {"entity": {"urn": urn, "type": hit_type}, "matchedFields": []}
                        for urn, hit_type in page
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


async def _candidate_assets(
    adapter: GovernedDataPlatformAdapter,
    query: str,
    context: dict[str, Any],
) -> list[dict[str, Any]]:
    """production candidate API로 해석 단계의 asset projection을 반환한다."""

    return list((await adapter.search_asset_candidates(query, context)).assets)


class GovernedDataPlatformRuntimeTests(unittest.IsolatedAsyncioTestCase):
    def test_catalog_snapshot_default_and_environment_override_are_explicit(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            default_engine = QueryGovernanceEngine(
                object(), object(), search_mode="lexical"
            )
        with patch.dict(
            os.environ,
            {"DATAHUB_CATALOG_TTL_SECONDS": "43200"},
            clear=True,
        ):
            override_engine = QueryGovernanceEngine(
                object(), object(), search_mode="lexical"
            )

        self.assertEqual(
            DEFAULT_CATALOG_RELEASE_TTL_SECONDS,
            default_engine._loader._ttl_seconds,
        )
        self.assertEqual(43_200.0, override_engine._loader._ttl_seconds)

    def test_ranked_connected_candidates_keep_a_bounded_complete_component(self) -> None:
        """검색 hit가 상한보다 많아도 상위 연결 component 전체를 버리지 않는다."""

        datasets = tuple(
            SimpleNamespace(
                fqn=f"orbit.analytics.candidate_{index}",
                metrics=({"dimensions": []},),
                policy_version="policy-v1",
                query_policy={"dialect": "trino", "read_only": True},
                time_metadata={"calendar_id": "calendar-v1"},
                entitled=lambda _context: True,
            )
            for index in range(5)
        )
        edges = tuple(
            GovernedJoin(
                id=f"candidate_{index}_to_{index + 1}",
                left=datasets[index].fqn,
                right=datasets[index + 1].fqn,
                kind="inner",
                cardinality="many_to_one",
                equality_conditions=(("left_id", "right_id"),),
                temporal_conditions=(),
                preaggregation_required=False,
                preaggregation_grain=("left_id",),
                preaggregation_keys=("left_id",),
            )
            for index in range(4)
        )
        engine = QueryGovernanceEngine(
            object(),
            object(),
            max_request_assets=3,
            search_mode="lexical",
        )

        selected, selected_graph = engine._select_connected(
            datasets,
            datasets,
            {"role": "analyst"},
            edges,
        )

        self.assertEqual(
            [
                "orbit.analytics.candidate_0",
                "orbit.analytics.candidate_1",
                "orbit.analytics.candidate_2",
            ],
            [item.fqn for item in selected],
        )
        self.assertEqual(edges, selected_graph)

    def test_candidate_dependency_component_is_never_partially_admitted(self) -> None:
        """의존 자산까지 넣을 공간이 없으면 seed 일부만 후보 context에 남기지 않는다."""

        fqns = tuple(f"orbit.analytics.asset_{index}" for index in range(4))
        datasets = (
            SimpleNamespace(
                fqn=fqns[0],
                metrics=({"dimensions": []},),
                policy_version="policy-v1",
                query_policy={"dialect": "trino"},
                time_metadata={"calendar_id": "calendar-v1"},
                entitled=lambda _context: True,
            ),
            SimpleNamespace(
                fqn=fqns[1],
                metrics=({"dimensions": []},),
                policy_version="policy-v1",
                query_policy={"dialect": "trino"},
                time_metadata={"calendar_id": "calendar-v1"},
                entitled=lambda _context: True,
            ),
            SimpleNamespace(
                fqn=fqns[2],
                metrics=({"dimensions": [{"asset_fqn": fqns[3]}]},),
                policy_version="policy-v1",
                query_policy={"dialect": "trino"},
                time_metadata={"calendar_id": "calendar-v1"},
                entitled=lambda _context: True,
            ),
            SimpleNamespace(
                fqn=fqns[3],
                metrics=(),
                policy_version="policy-v1",
                query_policy={"dialect": "trino"},
                time_metadata={"calendar_id": "calendar-v1"},
                entitled=lambda _context: True,
            ),
        )
        edges = tuple(
            GovernedJoin(
                id=f"asset_{index}_to_{index + 1}",
                left=fqns[index],
                right=fqns[index + 1],
                kind="inner",
                cardinality="many_to_one",
                equality_conditions=(("left_id", "right_id"),),
                temporal_conditions=(),
                preaggregation_required=False,
                preaggregation_grain=("left_id",),
                preaggregation_keys=("left_id",),
            )
            for index in range(3)
        )
        engine = QueryGovernanceEngine(
            object(),
            object(),
            max_request_assets=3,
            search_mode="lexical",
        )

        selected, _ = engine._select_connected(
            datasets[:3],
            datasets,
            {"role": "analyst"},
            edges,
        )

        self.assertEqual(fqns[:2], tuple(item.fqn for item in selected))

    def test_interpretation_scope_unions_independent_policies_only_with_one_calendar(self) -> None:
        """후보 recall은 독립 실행 policy를 허용하되 현재 Node 1이 해석할 수 없는 혼합 calendar는 넣지 않는다."""

        datasets = tuple(
            SimpleNamespace(
                fqn=f"orbit.analytics.scope_{index}",
                metrics=({"dimensions": []},),
                policy_version=f"policy-v{index + 1}",
                query_policy={"strategy": f"strategy-{index + 1}"},
                time_metadata={
                    "calendar_id": (
                        "calendar-shared" if index < 2 else "calendar-distinct"
                    )
                },
                entitled=lambda _context: True,
            )
            for index in range(3)
        )
        engine = QueryGovernanceEngine(
            object(),
            object(),
            max_request_assets=3,
            search_mode="lexical",
        )

        selected, selected_graph = engine._select_interpretation_scope(
            datasets,
            datasets,
            {"role": "analyst"},
            (),
        )

        self.assertEqual(
            tuple(item.fqn for item in datasets[:2]),
            tuple(item.fqn for item in selected),
        )
        self.assertEqual((), selected_graph)

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

    async def test_runtime_catalog_projection_round_trips_exact_snapshot_and_receipts(self) -> None:
        snapshot = await self.adapter._governance._loader.load()
        release = compile_legacy_semantic_release(snapshot)
        datasets = tuple(
            snapshot.datasets_by_fqn[item.fqn] for item in release.assets
        )
        fingerprints = await self.adapter._governance._schema.fingerprints(datasets)
        terms = {item["id"]: item for item in release.as_bundle()["metric_terms"]}
        native_records = {
            metric_id: {
                "urn": (
                    "urn:li:metric:(urn:li:dataPlatform:datahub,"
                    f"answervice.business_metrics,{metric_id})"
                ),
                "metricInfo": {
                    "name": term["name"],
                    "description": term["definition"],
                    "expression": {
                        "dialects": [
                            {
                                "dialect": "ANSI_SQL",
                                "expression": f'SUM("{metric_id}")',
                            }
                        ]
                    },
                },
                "aiContext": {"synonyms": term["aliases"]},
                "status": {"removed": False},
            }
            for metric_id, term in terms.items()
        }
        source_selection = build_source_selection_manifest(
            release,
            authority_mode=NATIVE_PRIORITY,
            native_records=native_records,
            native_projection_sha256="1" * 64,
            native_membership_sha256="2" * 64,
        )
        projection = RuntimeCatalogProjection.compile(
            snapshot,
            release,
            source_selection=source_selection,
            trino_fingerprints=fingerprints,
        )
        restored = RuntimeCatalogProjection.from_document(
            projection.as_document(),
            expected_projection_sha256=projection.projection_sha256,
        )

        self.assertEqual(release.canonical_checksum, restored.release.canonical_checksum)
        self.assertEqual(set(snapshot.datasets_by_urn), set(restored.snapshot.datasets_by_urn))
        self.assertEqual(set(snapshot.terms_by_urn), set(restored.snapshot.terms_by_urn))
        self.assertEqual(NATIVE_PRIORITY, restored.source_selection["authority_mode"])

        tampered = projection.as_document()
        tampered["snapshot"]["datasets"][0]["description"] = "tampered"
        with self.assertRaises(RuntimeCatalogProjectionError):
            RuntimeCatalogProjection.from_document(tampered)

    async def test_runtime_projection_path_avoids_full_scroll_and_preserves_pinned_release(self) -> None:
        snapshot = await self.adapter._governance._loader.load()
        release = compile_legacy_semantic_release(snapshot)
        datasets = tuple(
            snapshot.datasets_by_fqn[item.fqn] for item in release.assets
        )
        fingerprints = await self.adapter._governance._schema.fingerprints(datasets)
        projection = RuntimeCatalogProjection.compile(
            snapshot,
            release,
            source_selection=build_source_selection_manifest(
                release, authority_mode=LEGACY_SHADOW
            ),
            trino_fingerprints=fingerprints,
        )
        repository = MutableProjectionRepository(
            ActiveRuntimeCatalogProjection(
                projection=projection,
                product_release_id="phase4-product-a",
                generation=1,
            )
        )
        for values in self.transport.scroll_cursors.values():
            values.clear()
        governance = QueryGovernanceEngine(
            self.adapter._datahub,
            self.adapter._governance._schema,
            expected_context_release=release.catalog_version,
            search_mode="lexical",
            projection_repository=repository,
        )
        try:
            candidates = await governance.search_asset_candidates(
                "Helium yield",
                {"role": "analyst", "parameters": {}},
            )
            self.assertEqual("phase4-product-a", candidates.product_release_id)
            self.assertEqual(
                projection.projection_sha256,
                candidates.runtime_projection_checksum,
            )
            self.assertEqual([], self.transport.scroll_cursors["DATASET"])
            self.assertEqual([], self.transport.scroll_cursors["GLOSSARY_TERM"])
            stages, receipt = await governance.catalog_readiness()
            self.assertEqual("phase4-product-a", receipt)
            self.assertTrue(all(value == "ready" for value in stages.values()))
            verified_statement_count = len(self.transport.trino_statements)
            self.assertEqual(
                release.catalog_version,
                await governance.active_context_release(),
            )
            cached_stages, cached_receipt = await governance.catalog_readiness()
            self.assertEqual(stages, cached_stages)
            self.assertEqual(receipt, cached_receipt)
            self.assertEqual(
                verified_statement_count,
                len(self.transport.trino_statements),
            )

            selection = ExecutionAssetSelection(
                output_metric_ids=("helium_yield",),
                execution_metric_ids=("helium_yield",),
                field_references=(),
                receipt_context_release=candidates.context_release,
                receipt_catalog_checksum=candidates.catalog_checksum,
                receipt_canonical_checksum=candidates.canonical_checksum,
                receipt_product_release_id=candidates.product_release_id,
                receipt_runtime_projection_checksum=(
                    candidates.runtime_projection_checksum
                ),
            )
            assets = await governance.resolve_execution_assets(
                selection,
                {
                    "role": "analyst",
                    "parameters": {},
                    "product_release_id": "caller-spoofed-release",
                },
            )
            self.assertTrue(assets)
            self.assertEqual(
                {"phase4-product-a"},
                {asset.get("product_release_id") for asset in assets},
            )
            self.assertTrue(
                all("evidence_cutoff" not in asset for asset in assets)
            )

            repository.active = ActiveRuntimeCatalogProjection(
                projection=projection,
                product_release_id="phase4-product-b",
                generation=2,
            )
            rebound_assets = await governance.resolve_execution_assets(
                selection,
                {"role": "analyst", "parameters": {}},
            )
            self.assertEqual(
                {"phase4-product-a"},
                {asset.get("product_release_id") for asset in rebound_assets},
            )
            self.assertEqual([], self.transport.scroll_cursors["DATASET"])
            self.assertEqual([], self.transport.scroll_cursors["GLOSSARY_TERM"])
        finally:
            await governance.aclose()

    async def test_publisher_aspect_mock_contract_and_prebound_sql_passthrough(self) -> None:
        assets = await _candidate_assets(
            self.adapter,
            "helium",
            {"role": "analyst", "parameters": {}},
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
        # 전체 열거는 offset이 아니라 scroll cursor로만 진행한다.
        self.assertEqual([None, "1"], self.transport.scroll_cursors["DATASET"])
        self.assertEqual([None, "1"], self.transport.scroll_cursors["GLOSSARY_TERM"])
        self.assertEqual([], self.transport.search_starts["DATASET"])

    async def test_semantic_capability_failure_is_typed_and_closed(self) -> None:
        self.transport.semantic_disabled = True
        with self.assertRaises(MetadataUnavailableError):
            await self.adapter.search_asset_candidates(
                "helium",
                {"role": "analyst", "parameters": {}},
            )

    async def test_ratio_term_is_discovered_and_projected_without_physical_field(self) -> None:
        transport = RuntimeTransport(_bundle_with_ratio())
        datahub_http = httpx.AsyncClient(transport=httpx.MockTransport(transport.datahub))
        trino_http = httpx.AsyncClient(transport=httpx.MockTransport(transport.trino))
        catalog = DataHubCatalogClient(
            "http://datahub.test", client=datahub_http, page_size=2, max_entities=20
        )
        trino = TrinoAsyncClient(
            "https://trino.test", "runtime", "test-password", client=trino_http
        )
        adapter = GovernedDataPlatformAdapter(
            "https://trino.test",
            "runtime",
            datahub_client=catalog,
            trino_client=trino,
            search_mode="lexical",
        )
        self.addAsyncCleanup(datahub_http.aclose)
        self.addAsyncCleanup(trino_http.aclose)
        self.addAsyncCleanup(adapter.aclose)

        assets = await _candidate_assets(
            adapter,
            "Helium average yield",
            {"role": "analyst", "parameters": {}},
        )
        terms = await adapter.get_metric_terms(("helium_rate",))
        metrics = {
            metric["id"]: metric
            for asset in assets
            for metric in asset["metrics"]
        }

        self.assertEqual("ratio", metrics["helium_rate"]["aggregation"])
        self.assertEqual("", metrics["helium_rate"]["asset_fqn"])
        self.assertEqual("helium_yield", metrics["helium_rate"]["numerator_metric_id"])
        self.assertEqual("ratio", terms["helium_rate"]["kind"])

    async def test_candidate_projection_limits_choices_but_keeps_ratio_dependencies(self) -> None:
        """Metric 후보 상한은 Node 1 선택지만 줄이고 ratio operand 실행 계약은 제거하지 않는다."""

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
            max_candidate_metrics=1,
            search_mode="lexical",
        )
        self.addAsyncCleanup(datahub_http.aclose)
        self.addAsyncCleanup(trino_http.aclose)
        self.addAsyncCleanup(adapter.aclose)

        candidates = await adapter.search_asset_candidates(
            "Helium average yield",
            {"role": "analyst", "parameters": {}},
        )
        metrics = {
            str(metric["id"]): metric
            for asset in candidates.assets
            for metric in asset["metrics"]
        }

        self.assertEqual(
            {"helium_rate", "helium_yield", "helium_observation_count"},
            set(metrics),
        )
        self.assertTrue(metrics["helium_rate"]["candidate_selectable"])
        self.assertEqual(1, metrics["helium_rate"]["candidate_rank"])
        self.assertFalse(metrics["helium_yield"]["candidate_selectable"])
        self.assertIsNone(metrics["helium_yield"]["candidate_rank"])
        self.assertFalse(
            metrics["helium_observation_count"]["candidate_selectable"]
        )
        self.assertIsNone(metrics["helium_observation_count"]["candidate_rank"])
        self.assertEqual([], transport.trino_statements)

    async def test_candidate_projection_omits_unrelated_same_asset_metrics(self) -> None:
        """직접 Glossary 증거가 강한 column Metric은 같은 Dataset의 무관한 지표를 끌고 오지 않는다."""

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
            max_candidate_metrics=1,
            search_mode="lexical",
        )
        self.addAsyncCleanup(datahub_http.aclose)
        self.addAsyncCleanup(trino_http.aclose)
        self.addAsyncCleanup(adapter.aclose)

        candidates = await adapter.search_asset_candidates(
            "Helium observation count",
            {"role": "analyst", "parameters": {}},
        )
        metric_ids = {
            str(metric["id"])
            for asset in candidates.assets
            for metric in asset["metrics"]
        }

        self.assertEqual({"helium_observation_count"}, metric_ids)
        self.assertEqual([], transport.trino_statements)

    async def test_candidates_keep_disconnected_metrics_until_execution_resolution(self) -> None:
        """같은 시간 계약의 복수 후보는 JOIN 부재로 숨기지 않고 선택 후 semantic Gate에서 차단한다."""

        context = {"role": "analyst", "parameters": {}}
        candidates = await self.adapter.search_asset_candidates(
            "Helium yield and Argon output",
            context,
        )
        selectable_ids = {
            str(metric["id"])
            for asset in candidates.assets
            for metric in asset["metrics"]
            if metric.get("candidate_selectable") is True
        }

        self.assertEqual({"helium_yield", "argon_yield"}, selectable_ids)
        self.assertEqual(
            {1, 2},
            {
                int(metric["candidate_rank"])
                for asset in candidates.assets
                for metric in asset["metrics"]
                if metric.get("candidate_selectable") is True
            },
        )
        self.assertEqual([], self.transport.trino_statements)
        selection = ExecutionAssetSelection(
            output_metric_ids=("helium_yield", "argon_yield"),
            execution_metric_ids=("helium_yield", "argon_yield"),
            field_references=(),
            receipt_context_release=candidates.context_release,
            receipt_catalog_checksum=candidates.catalog_checksum,
            receipt_canonical_checksum=candidates.canonical_checksum,
        )

        with self.assertRaisesRegex(
            UnsupportedSemanticError,
            "no unique commonly approved join path",
        ):
            await self.adapter.resolve_execution_assets(selection, context)
        self.assertEqual([], self.transport.trino_statements)

    async def test_execution_resolution_uses_only_the_common_approved_join_path(self) -> None:
        """복수 Metric 선택은 active graph의 공통 whitelist edge만 실행 context에 남긴다."""

        transport = RuntimeTransport(_bundle_with_metric_join())
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
        self.addAsyncCleanup(datahub_http.aclose)
        self.addAsyncCleanup(trino_http.aclose)
        self.addAsyncCleanup(adapter.aclose)
        context = {"role": "analyst", "parameters": {}}
        candidates = await adapter.search_asset_candidates(
            "Helium yield and Argon output",
            context,
        )
        selection = ExecutionAssetSelection(
            output_metric_ids=("helium_yield", "argon_yield"),
            execution_metric_ids=("helium_yield", "argon_yield"),
            field_references=(),
            receipt_context_release=candidates.context_release,
            receipt_catalog_checksum=candidates.catalog_checksum,
            receipt_canonical_checksum=candidates.canonical_checksum,
        )
        self.assertEqual([], transport.trino_statements)

        assets = await adapter.resolve_execution_assets(selection, context)

        self.assertTrue(transport.trino_statements)
        self.assertTrue(
            all(
                "information_schema" in statement
                for statement in transport.trino_statements
            )
        )
        self.assertEqual(
            {"orbit.lake.helium_fact", "orbit.lake.argon_fact"},
            {item["fqn"] for item in assets},
        )
        for asset in assets:
            self.assertEqual(["helium_argon_by_event"], asset["join_ids"])
            self.assertEqual(
                ["helium_argon_by_event"],
                [edge["id"] for edge in asset["join_graph"]["edges"]],
            )

    async def test_execution_resolution_rejects_an_unentitled_join_node(self) -> None:
        """후보에 없던 Metric을 주입해도 권한 밖 중간·대상 node로 실행 범위를 넓히지 못한다."""

        transport = RuntimeTransport(_bundle_with_unentitled_metric_join())
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
        self.addAsyncCleanup(datahub_http.aclose)
        self.addAsyncCleanup(trino_http.aclose)
        self.addAsyncCleanup(adapter.aclose)
        context = {"role": "analyst", "parameters": {}}
        candidates = await adapter.search_asset_candidates(
            "Helium yield",
            context,
        )
        selection = ExecutionAssetSelection(
            output_metric_ids=("helium_yield", "argon_yield"),
            execution_metric_ids=("helium_yield", "argon_yield"),
            field_references=(),
            receipt_context_release=candidates.context_release,
            receipt_catalog_checksum=candidates.catalog_checksum,
            receipt_canonical_checksum=candidates.canonical_checksum,
        )

        with self.assertRaisesRegex(
            NoEntitledAssetsError,
            "outside the request entitlement",
        ):
            await adapter.resolve_execution_assets(selection, context)

    async def test_execution_resolution_rejects_ambiguous_parallel_join_edges(self) -> None:
        """동일 endpoint의 승인 edge가 둘이면 질문별 추측 없이 관계 계약 보강을 요구한다."""

        transport = RuntimeTransport(_bundle_with_ambiguous_metric_join())
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
        self.addAsyncCleanup(datahub_http.aclose)
        self.addAsyncCleanup(trino_http.aclose)
        self.addAsyncCleanup(adapter.aclose)
        context = {"role": "analyst", "parameters": {}}
        candidates = await adapter.search_asset_candidates(
            "Helium yield and Argon output",
            context,
        )
        selection = ExecutionAssetSelection(
            output_metric_ids=("helium_yield", "argon_yield"),
            execution_metric_ids=("helium_yield", "argon_yield"),
            field_references=(),
            receipt_context_release=candidates.context_release,
            receipt_catalog_checksum=candidates.catalog_checksum,
            receipt_canonical_checksum=candidates.canonical_checksum,
        )

        with self.assertRaisesRegex(
            UnsupportedSemanticError,
            "no unique commonly approved join path",
        ):
            await adapter.resolve_execution_assets(selection, context)
        self.assertEqual([], transport.trino_statements)

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
        assets = await _candidate_assets(
            adapter,
            "helium",
            {"role": "analyst", "parameters": {}},
        )
        self.assertEqual(["orbit.lake.helium_fact"], [item["fqn"] for item in assets])

    async def test_lexical_no_match_is_distinct_from_entitlement_denial(self) -> None:
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

        with self.assertRaises(NoMetricMatchError):
            await adapter.search_asset_candidates(
                "2042-06",
                {"role": "analyst", "parameters": {}},
            )

    async def test_entitlement_is_only_the_published_role_domain_policy(self) -> None:
        with self.assertRaises(NoEntitledAssetsError):
            await self.adapter.search_asset_candidates(
                "helium",
                {"role": "unpublished_role", "parameters": {}},
            )

    async def test_catalog_readiness_requires_manifest_membership_and_all_trino_schemas(self) -> None:
        stages, receipt = await self.adapter.get_catalog_readiness()

        self.assertEqual(
            {
                "semantic_release": "ready",
                "catalog_manifest": "ready",
                "trino_schema": "ready",
            },
            stages,
        )
        self.assertRegex(
            receipt or "",
            r"^ANSWERVICE-PRODUCT-RELEASE-v1:[0-9a-f]{64}$",
        )

    async def test_catalog_readiness_rejects_manifest_governed_count_mismatch(self) -> None:
        removed_urn = next(
            urn for urn in self.transport.datasets if "argon_fact" in urn
        )
        self.transport.datasets.pop(removed_urn)

        stages, receipt = await self.adapter.get_catalog_readiness()

        # 불완전한 membership은 canonical release 자체도 만들 수 없으므로 가장
        # 이른 semantic gate에서 fail-closed한다.
        self.assertEqual("not_ready", stages["semantic_release"])
        self.assertEqual("not_ready", stages["catalog_manifest"])
        self.assertEqual("not_ready", stages["trino_schema"])
        self.assertIsNone(receipt)

    async def test_catalog_readiness_rejects_trino_schema_drift_after_valid_manifest(self) -> None:
        self.transport.schema_drift = True

        stages, receipt = await self.adapter.get_catalog_readiness()

        self.assertEqual("ready", stages["semantic_release"])
        self.assertEqual("ready", stages["catalog_manifest"])
        self.assertEqual("not_ready", stages["trino_schema"])
        self.assertIsNone(receipt)

    async def test_incomplete_governance_and_trino_drift_are_typed_failures(self) -> None:
        first = next(iter(self.transport.datasets.values()))
        first["properties"]["customProperties"] = [
            item
            for item in first["properties"]["customProperties"]
            if item["key"] != "answervice.query_policy"
        ]
        with self.assertRaises(MetadataUnavailableError):
            await self.adapter.search_asset_candidates(
                "helium", {"role": "analyst", "parameters": {}}
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
            await self.adapter.get_asset_schema(next(iter(self.transport.datasets)))

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
            await self.adapter.search_asset_candidates(
                "helium", {"role": "analyst", "parameters": {}}
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
                        await adapter.search_asset_candidates(
                            "helium", {"role": "analyst", "parameters": {}}
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
            search_mode="lexical",
            datahub_client=DataHubCatalogClient(
                "http://datahub.test", client=datahub_http, page_size=1, max_entities=20
            ),
            trino_client=TrinoAsyncClient(
                "https://trino.test", "runtime", "test-password", client=trino_http
            ),
        )
        try:
            assets = await _candidate_assets(
                adapter,
                "helium neon",
                {"role": "analyst", "parameters": {}},
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

    async def test_join_expansion_cannot_reach_an_unentitled_asset(self) -> None:
        """seed는 권한이 있어도 join으로 끌려온 metric asset이 비권한이면 fail-closed여야 한다."""

        bundle = _bundle_with_dimension_bridge()
        for asset in bundle["schema_context"]["assets"]:
            if asset["fqn"] == "orbit.lake.helium_fact":
                asset["entitlements"] = {"roles": ["report_admin"], "domains": []}
        for metric in bundle["metric_rules"]:
            source = metric["source"]
            if (
                source["kind"] == "column"
                and source["field"]["asset_fqn"] == "orbit.lake.helium_fact"
            ):
                metric["governance"]["permission"]["roles"] = ["report_admin"]
        transport = RuntimeTransport(bundle)
        datahub_http = httpx.AsyncClient(transport=httpx.MockTransport(transport.datahub))
        trino_http = httpx.AsyncClient(transport=httpx.MockTransport(transport.trino))
        adapter = GovernedDataPlatformAdapter(
            "https://trino.test",
            "runtime",
            search_mode="lexical",
            datahub_client=DataHubCatalogClient(
                "http://datahub.test", client=datahub_http, page_size=1, max_entities=20
            ),
            trino_client=TrinoAsyncClient(
                "https://trino.test", "runtime", "test-password", client=trino_http
            ),
        )
        self.addAsyncCleanup(datahub_http.aclose)
        self.addAsyncCleanup(trino_http.aclose)
        self.addAsyncCleanup(adapter.aclose)

        # "neon"은 권한 있는 dimension만 seed로 만들지만, 이 asset은 metric이 없어
        # 인접한 helium_fact가 join 경로로 끌려온다. 그 asset은 이 role에 권한이 없다.
        with self.assertRaises(NoEntitledAssetsError):
            await adapter.search_asset_candidates(
                "neon", {"role": "analyst", "parameters": {}}
            )


@unittest.skipUnless(
    os.getenv("TEST_REAL_DATA_PLATFORM") == "1",
    "opt-in live canonical DataHub/Trino smoke",
)
class LiveGovernanceSmokeTest(unittest.IsolatedAsyncioTestCase):
    def _adapter(self, *, search_mode: str = "lexical") -> GovernedDataPlatformAdapter:
        return GovernedDataPlatformAdapter(
            os.getenv("TRINO_URL", "https://127.0.0.1:18443"),
            os.getenv("TRINO_RUNTIME_USER", ""),
            trino_password=os.getenv("TRINO_RUNTIME_PASSWORD", ""),
            trino_ca_file=os.getenv("TRINO_TLS_CA_FILE", ""),
            expected_context_release=os.getenv("ANALYTICS_CONTEXT_RELEASE") or None,
            search_mode=search_mode,
        )

    async def test_current_disabled_semantic_capability_is_not_bypassed(self) -> None:
        adapter = self._adapter(search_mode="hybrid")
        try:
            with self.assertRaises(MetadataUnavailableError):
                await adapter.search_asset_candidates(
                    os.getenv("LIVE_GOVERNANCE_SMOKE_QUERY", "runtime governance"),
                    {"role": "analyst", "parameters": {}},
                )
        finally:
            await adapter.aclose()

    async def test_active_catalog_release_is_ready(self) -> None:
        adapter = self._adapter()
        try:
            stages, receipt = await adapter.get_catalog_readiness()
            self.assertEqual(
                stages,
                {
                    "semantic_release": "ready",
                    "catalog_manifest": "ready",
                    "trino_schema": "ready",
                },
            )
            self.assertTrue(receipt)
            self.assertTrue(await adapter.get_active_context_release())
        finally:
            await adapter.aclose()

    async def test_live_compact_candidates_use_glossary_without_schema_gate(self) -> None:
        """live Glossary label 후보 검색은 선택 전 Trino schema I/O 없이 bounded Metric만 노출한다."""

        adapter = self._adapter()
        try:
            governance = adapter._governance
            snapshot = await governance._loader.load()
            release = governance._active_release(snapshot)
            datasets = governance._datasets_for_release(snapshot, release)
            terms = governance._required_terms(snapshot, datasets)
            entitled_fqns = {
                item.fqn for item in datasets if item.entitled({"role": "analyst"})
            }
            eligible = next(
                (
                    metric
                    for metric in release.metrics
                    if metric.visibility == "BUSINESS"
                    and metric.source_kind == "column"
                    and set(metric.source_assets).issubset(entitled_fqns)
                    and (
                        not metric.allowed_roles
                        or "analyst" in metric.allowed_roles
                    )
                ),
                None,
            )
            self.assertIsNotNone(eligible)

            class RejectSchemaInspection:
                """candidate pass에서 schema 검사가 호출되면 즉시 실패시키는 live sentinel이다."""

                async def verify(self, _datasets) -> None:
                    raise AssertionError(
                        "candidate search must not inspect Trino schema"
                    )

            governance._schema = RejectSchemaInspection()
            candidates = await adapter.search_asset_candidates(
                terms[eligible.id].label,
                {"role": "analyst", "parameters": {}},
            )
            selectable_ids = {
                str(metric["id"])
                for asset in candidates.assets
                for metric in asset["metrics"]
                if metric.get("candidate_selectable") is True
            }

            self.assertIn(eligible.id, selectable_ids)
            self.assertLessEqual(
                len(selectable_ids),
                QueryGovernanceEngine.MAX_CANDIDATE_METRICS,
            )
        finally:
            await adapter.aclose()
