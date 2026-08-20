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
from app.contracts import AnalysisRequest, RequestContext, Role  # noqa: E402
from app.ports.data_platform import NoEntitledAssetsError  # noqa: E402
from app.services.context.metric_resolver import MetricResolver  # noqa: E402
from app.services.context.metric_execution_scope import select_assets_for_metrics  # noqa: E402
from app.services.context.builder import ContextBuildError, ContextPackageBuilder  # noqa: E402
from app.services.context.service import PipelineContextService  # noqa: E402
from metadata_aspects import iter_aspects  # noqa: E402
from metadata_contract import validate_bundle  # noqa: E402
from test_datahub_metadata_publication import (  # noqa: E402
    _graphql_dataset,
    _graphql_term,
)
from test_metric_governance_v2 import _v2_bundle  # noqa: E402
from src.data.metric_governance import RUNTIME_GOVERNANCE_VERSION_V1  # noqa: E402


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
            "intent_candidates": ["general"],
            "metric_candidates": ["amount_per_event"],
            "selected_metric_id": "amount_per_event",
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


def test_node1_receives_only_business_metric_while_context_keeps_operands() -> None:
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
    assert "amount_total" not in model.input["business_terms"]
    assert "event_count" not in model.input["business_terms"]
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
    assert metric_selection(selected_assets, package)["selected_metric_id"] == (
        "amount_per_event"
    )


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
