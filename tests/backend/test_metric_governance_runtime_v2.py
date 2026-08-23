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
from app.adapters.model_context import execution_time, metric_selection  # noqa: E402
from app.contracts import (  # noqa: E402
    AnalysisRequest,
    Evidence,
    PeriodEvidence,
    RequestContext,
    ResolvedSlots,
    Role,
    SnapshotEvidence,
)
from app.ports.data_platform import (  # noqa: E402
    ExecutionAssetSelection,
    GovernedFieldReference,
    NoEntitledAssetsError,
    NoMetricMatchError,
    ReleaseReceiptChangedError,
    UnsupportedSemanticError,
)
from app.services.analysis.responses import _business_metrics  # noqa: E402
from app.services.analysis.result_validator import PipelineResultValidator  # noqa: E402
from app.services.context.metric_resolver import (  # noqa: E402
    MetricResolver,
    _validate_selected_data_availability,
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


def _engine(
    bundle: dict,
    *,
    max_candidate_metrics: int = QueryGovernanceEngine.MAX_CANDIDATE_METRICS,
) -> QueryGovernanceEngine:
    engine = QueryGovernanceEngine(
        object(),
        _Schema(),
        search_mode="lexical",
        max_candidate_metrics=max_candidate_metrics,
    )
    engine._loader = _Loader(_snapshot(bundle))
    return engine


async def _candidate_assets(
    engine: QueryGovernanceEngine,
    query: str,
    context: dict,
) -> list[dict]:
    """production의 candidate API를 통해 resolver 입력 projection을 복원한다."""

    return list((await engine.search_asset_candidates(query, context)).assets)


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
        _candidate_assets(
            engine,
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


def test_candidate_retrieval_does_not_require_execution_filter_values() -> None:
    """Node 1 후보 pass는 아직 선택되지 않은 Metric의 필터 값을 미리 바인딩하지 않는다."""

    engine = _engine(_runtime_bundle())

    candidates = asyncio.run(
        engine.search_asset_candidates(
            "Amount per Event",
            {"role": "analyst", "parameters": {}},
        )
    )

    assert candidates.context_release
    assert len(candidates.catalog_checksum) == 64
    assert len(candidates.canonical_checksum) == 64
    assert {
        item["id"]
        for asset in candidates.assets
        for item in asset["metrics"]
    } == {"amount_total", "event_count", "amount_per_event"}
    assert all(
        metric["required_filters"] == []
        for asset in candidates.assets
        for metric in asset["metrics"]
    )


def test_node1_candidate_terms_exclude_nonselectable_ratio_dependencies() -> None:
    """compact 후보의 ratio operand는 실행에는 남지만 Node 1의 공개·SUPPORT 선택지에는 노출하지 않는다."""

    engine = _engine(_runtime_bundle(), max_candidate_metrics=1)
    candidates = asyncio.run(
        engine.search_asset_candidates(
            "Amount per Event",
            {"role": "analyst", "parameters": {}},
        )
    )
    model = _Normalizer()
    resolver = MetricResolver(engine, model)
    context = RequestContext(
        request_id=UUID("10000000-0000-0000-0000-000000000011"),
        trace_id="compact-candidate-ratio-dependencies",
        user_id=UUID("20000000-0000-0000-0000-000000000012"),
        role=Role.ANALYST,
        as_of=date(2026, 8, 19),
    )

    asyncio.run(
        resolver.resolve(
            AnalysisRequest(
                question="Amount per Event",
                parameters={"active": True},
            ),
            context,
            list(candidates.assets),
        )
    )

    assert model.input is not None
    assert {
        identifier
        for identifier, term in model.input["business_terms"].items()
        if term["kind"] == "metric"
    } == {"amount_per_event"}
    assert not {
        identifier
        for identifier, term in model.input["business_terms"].items()
        if term["kind"] == "support_metric"
    }


def test_preferred_metric_seeds_candidates_without_question_keyword_rules() -> None:
    """멀티턴 확정 Metric은 질문 문자열 재작성 없이 active release 관계로 후보 Dataset을 찾는다."""

    engine = _engine(_runtime_bundle(), max_candidate_metrics=1)

    candidates = asyncio.run(
        engine.search_asset_candidates(
            "selected interval only",
            {
                "role": "analyst",
                "parameters": {},
                "preferred_metric_ids": ["amount_per_event"],
            },
        )
    )

    selectable_ids = {
        str(metric["id"])
        for asset in candidates.assets
        for metric in asset["metrics"]
        if metric["candidate_selectable"] is True
    }
    assert selectable_ids == {"amount_per_event"}

    with pytest.raises(NoMetricMatchError, match="outside the active semantic release"):
        asyncio.run(
            engine.search_asset_candidates(
                "selected interval only",
                {
                    "role": "analyst",
                    "parameters": {},
                    "preferred_metric_ids": ["retired_metric"],
                },
            )
        )


def test_pre_resolved_ratio_keeps_an_independent_business_operand_term() -> None:
    """ratio의 독립 BUSINESS 분자는 출력이 아니어도 Context 계보에서 누락하지 않는다."""

    engine = _engine(_runtime_bundle(), max_candidate_metrics=1)
    candidates = asyncio.run(
        engine.search_asset_candidates(
            "selected interval only",
            {
                "role": "analyst",
                "parameters": {},
                "preferred_metric_ids": ["amount_per_event"],
            },
        )
    )
    assets = [deepcopy(asset) for asset in candidates.assets]
    for asset in assets:
        for metric in asset["metrics"]:
            if metric["id"] == "amount_total":
                metric["visibility"] = "BUSINESS"

    original_get_metric_terms = engine.get_metric_terms
    amount_total_term = {
        "id": "amount_total",
        "urn": "urn:li:glossaryTerm:amount_total",
        "label": "Amount Total",
        "aliases": ["Amount Total"],
        "definition": "Governed amount numerator.",
        "unit": "credits",
        "version": "v2",
        "checksum": "a" * 64,
        "kind": "metric",
    }

    async def get_metric_terms(
        metric_ids: tuple[str, ...],
        context: dict[str, object] | None = None,
    ):
        if metric_ids == ("amount_total",):
            return {"amount_total": deepcopy(amount_total_term)}
        return await original_get_metric_terms(metric_ids, context)

    engine.get_metric_terms = get_metric_terms  # type: ignore[method-assign]
    model = _Normalizer()
    resolver = MetricResolver(engine, model)
    context = RequestContext(
        request_id=UUID("10000000-0000-0000-0000-000000000021"),
        trace_id="v2-runtime-pre-resolved-business-ratio-operand",
        user_id=UUID("20000000-0000-0000-0000-000000000022"),
        role=Role.ANALYST,
        as_of=date(2026, 8, 19),
    )

    selected_assets, _question, structured = asyncio.run(
        resolver.resolve(
            AnalysisRequest(
                question="selected interval only",
                resolved_slots=ResolvedSlots(
                    metric_id="amount_per_event",
                    metric_ids=("amount_per_event",),
                    period_start="2026-08-01",
                    period_end_exclusive="2026-08-02",
                    analysis_operation="aggregate",
                ),
            ),
            context,
            assets,
        )
    )

    assert model.input is None
    assert set(structured["metric_ids"]) == {
        "amount_per_event",
        "amount_total",
        "event_count",
    }
    assert set(structured["metric_terms"]) == {
        "amount_per_event",
        "amount_total",
    }
    assert {
        metric["id"]
        for asset in selected_assets
        for metric in asset["metrics"]
        if metric["visibility"] == "BUSINESS"
    } == {"amount_per_event", "amount_total"}


def test_pre_resolved_ratio_period_comparison_is_a_typed_unsupported_strategy() -> None:
    """미승인 ratio 기간 비교는 지표 모호성이 아니라 실행 전 semantic 차단이다."""

    engine = _engine(_runtime_bundle(), max_candidate_metrics=1)
    assets = asyncio.run(
        _candidate_assets(
            engine,
            "selected intervals only",
            {
                "role": "analyst",
                "parameters": {},
                "preferred_metric_ids": ["amount_per_event"],
            },
        )
    )
    model = _Normalizer()
    context = RequestContext(
        request_id=UUID("10000000-0000-0000-0000-000000000023"),
        trace_id="v2-runtime-pre-resolved-ratio-comparison",
        user_id=UUID("20000000-0000-0000-0000-000000000024"),
        role=Role.ANALYST,
        as_of=date(2026, 8, 19),
    )

    with pytest.raises(ContextBuildError) as raised:
        asyncio.run(
            MetricResolver(engine, model).resolve(
                AnalysisRequest(
                    question="selected intervals only",
                    resolved_slots=ResolvedSlots(
                        metric_id="amount_per_event",
                        metric_ids=("amount_per_event",),
                        period_start="2026-08-01",
                        period_end_exclusive="2026-08-02",
                        comparison_period_start="2026-07-01",
                        comparison_period_end_exclusive="2026-07-02",
                        analysis_operation="period_comparison",
                    ),
                ),
                context,
                assets,
            )
        )

    assert raised.value.code is ContextBuildErrorCode.QUERY_STRATEGY_NOT_APPROVED
    assert model.input is None


def test_compact_candidates_keep_an_explicit_support_metric_as_nonbusiness_choice() -> None:
    """SUPPORT의 고유 승인 semantic이 직접 일치하면 공개 BUSINESS로 바꾸지 않고 availability 판정에 남긴다."""

    engine = _engine(_runtime_bundle(), max_candidate_metrics=1)

    candidates = asyncio.run(
        engine.search_asset_candidates(
            "amount_total",
            {"role": "analyst", "parameters": {}},
        )
    )
    metrics = {
        str(metric["id"]): metric
        for asset in candidates.assets
        for metric in asset["metrics"]
    }

    assert metrics["amount_total"]["visibility"] == "SUPPORT"
    assert metrics["amount_total"]["candidate_selectable"] is True
    assert not any(
        metric["visibility"] == "BUSINESS"
        and metric["candidate_selectable"] is True
        for metric in metrics.values()
    )


def test_dimension_only_search_does_not_expand_to_unrelated_business_metrics() -> None:
    """Dataset recall만 있는 질문은 임의 BUSINESS 후보를 열지 않고 typed closure로 닫는다."""

    engine = _engine(_runtime_bundle())

    with pytest.raises(NoMetricMatchError, match="no governed metric has evidence"):
        asyncio.run(
            engine.search_asset_candidates(
                "cohort",
                {"role": "analyst", "parameters": {}},
            )
        )


def test_dimension_alias_inside_metric_definition_is_not_metric_evidence() -> None:
    """Dimension 별칭이 Metric 정의에도 있어도 Dimension-only 요청은 닫힌다."""

    bundle = _runtime_bundle()
    bundle["metric_terms"][0]["definition"] += " cohort별 값을 분석합니다."
    matching_rule = next(
        rule
        for rule in bundle["metric_rules"]
        if rule["id"] == bundle["metric_terms"][0]["id"]
    )
    matching_rule["governance"]["semantic"]["definition"] = bundle[
        "metric_terms"
    ][0]["definition"]
    validate_bundle(bundle)
    engine = _engine(bundle)

    with pytest.raises(NoMetricMatchError, match="no governed metric has evidence"):
        asyncio.run(
            engine.search_asset_candidates(
                "cohort",
                {"role": "analyst", "parameters": {}},
            )
        )


def test_execution_resolution_rebinds_selected_metrics_to_the_same_release() -> None:
    """후보 payload가 아니라 receipt와 선택 ID로 active release에서 실행 자산을 재구성한다."""

    engine = _engine(_runtime_bundle())
    candidates = asyncio.run(
        engine.search_asset_candidates(
            "Amount per Event",
            {"role": "analyst", "parameters": {}},
        )
    )
    selection = ExecutionAssetSelection(
        output_metric_ids=("amount_per_event",),
        execution_metric_ids=(
            "amount_per_event",
            "amount_total",
            "event_count",
        ),
        field_references=(),
        receipt_context_release=candidates.context_release,
        receipt_catalog_checksum=candidates.catalog_checksum,
        receipt_canonical_checksum=candidates.canonical_checksum,
    )

    assets = asyncio.run(
        engine.resolve_execution_assets(
            selection,
            {"role": "analyst", "parameters": {"active": True}},
        )
    )

    metrics = {
        item["id"]: item
        for asset in assets
        for item in asset["metrics"]
    }
    assert set(metrics) == {"amount_total", "event_count", "amount_per_event"}
    assert metrics["amount_total"]["required_filters"][0]["value"] is True
    assert metrics["event_count"]["required_filters"][0]["value"] is True


def test_execution_resolution_derives_ratio_dimensions_from_operands() -> None:
    """ratio 자체의 빈 물리 차원 대신 두 operand가 공유하고 release가 승인한 차원을 사용한다."""

    bundle = _runtime_bundle()
    bundle["dimensions"].append(
        {
            "id": "event_account",
            "aliases": ["event account", "account"],
            "definition": "Governed account identifier on an event.",
            "asset_fqn": "quartz.core.events",
            "column": "account_id",
        }
    )
    validate_bundle(bundle)
    engine = _engine(bundle)
    candidates = asyncio.run(
        engine.search_asset_candidates(
            "Amount per Event by account",
            {"role": "analyst", "parameters": {}},
        )
    )
    selection = ExecutionAssetSelection(
        output_metric_ids=("amount_per_event",),
        execution_metric_ids=(
            "amount_per_event",
            "amount_total",
            "event_count",
        ),
        field_references=(
            GovernedFieldReference(
                asset_fqn="quartz.core.events",
                column="account_id",
            ),
        ),
        receipt_context_release=candidates.context_release,
        receipt_catalog_checksum=candidates.catalog_checksum,
        receipt_canonical_checksum=candidates.canonical_checksum,
    )

    assets = asyncio.run(
        engine.resolve_execution_assets(
            selection,
            {"role": "analyst", "parameters": {"active": True}},
        )
    )

    assert {asset["fqn"] for asset in assets} == {"quartz.core.events"}


def test_execution_resolution_rejects_a_changed_candidate_receipt() -> None:
    """같은 Metric ID라도 candidate 이후 release identity가 달라지면 실행하지 않는다."""

    engine = _engine(_runtime_bundle())
    candidates = asyncio.run(
        engine.search_asset_candidates(
            "Amount per Event",
            {"role": "analyst", "parameters": {}},
        )
    )
    selection = ExecutionAssetSelection(
        output_metric_ids=("amount_per_event",),
        execution_metric_ids=(
            "amount_per_event",
            "amount_total",
            "event_count",
        ),
        field_references=(),
        receipt_context_release=candidates.context_release,
        receipt_catalog_checksum=candidates.catalog_checksum,
        receipt_canonical_checksum="f" * 64,
    )

    with pytest.raises(ReleaseReceiptChangedError, match="changed after candidate"):
        asyncio.run(
            engine.resolve_execution_assets(
                selection,
                {"role": "analyst", "parameters": {"active": True}},
            )
        )


def test_execution_resolution_rejects_missing_ratio_operands() -> None:
    """공개 ratio만 선택하고 숨은 operand를 누락한 실행 scope는 재구성하지 않는다."""

    engine = _engine(_runtime_bundle())
    candidates = asyncio.run(
        engine.search_asset_candidates(
            "Amount per Event",
            {"role": "analyst", "parameters": {}},
        )
    )
    selection = ExecutionAssetSelection(
        output_metric_ids=("amount_per_event",),
        execution_metric_ids=("amount_per_event",),
        field_references=(),
        receipt_context_release=candidates.context_release,
        receipt_catalog_checksum=candidates.catalog_checksum,
        receipt_canonical_checksum=candidates.canonical_checksum,
    )

    with pytest.raises(UnsupportedSemanticError, match="dependencies differ"):
        asyncio.run(
            engine.resolve_execution_assets(
                selection,
                {"role": "analyst", "parameters": {"active": True}},
            )
        )


def test_platform_admin_inherits_existing_metric_and_asset_entitlements() -> None:
    engine = _engine(_runtime_bundle())

    assets = asyncio.run(
        _candidate_assets(
            engine,
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
            _candidate_assets(
                role_restricted,
                "Amount per Event",
                {"role": "analyst", "parameters": {"active": True}},
            )
        )

    pii = _engine(_runtime_bundle(contains_pii=True))
    with pytest.raises(NoEntitledAssetsError, match="business metric"):
        asyncio.run(
            _candidate_assets(
                pii,
                "Amount per Event",
                {"role": "analyst", "parameters": {"active": True}},
            )
        )
    with pytest.raises(NoEntitledAssetsError, match="business metric"):
        asyncio.run(
            _candidate_assets(
                pii,
                "Amount per Event",
                {"role": "platform_admin", "parameters": {"active": True}},
            )
        )


class _Normalizer:
    def __init__(self) -> None:
        self.input: dict | None = None
        self.inputs: list[dict] = []

    async def normalize_question(self, payload: dict) -> dict:
        self.input = deepcopy(payload)
        self.inputs.append(deepcopy(payload))
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


class _SnapshotNormalizer(_Normalizer):
    async def normalize_question(self, payload: dict) -> dict:
        """기간 표현이 없는 질문을 최신 snapshot 단일 집계로 해석한다."""

        result = await super().normalize_question(payload)
        result["normalized_question"] = "Amount per Event at the latest governed snapshot"
        result["period_candidates"] = []
        return result


class _PeriodRecheckNormalizer(_Normalizer):
    """첫 해석에서 기간을 놓치고 bounded recheck에서만 typed 기간을 반환한다."""

    async def normalize_question(self, payload: dict) -> dict:
        result = await super().normalize_question(payload)
        if "interpretation_recheck" not in payload:
            result["period_candidates"] = []
        return result


class _MissingMetricPeriodRecheckNormalizer(_Normalizer):
    """기간-only 후속 질문에서 첫 기간 해석만 누락한 모델 응답."""

    async def normalize_question(self, payload: dict) -> dict:
        result = await super().normalize_question(payload)
        result.update(
            {
                "intent_candidates": [],
                "measurement_source_text": None,
                "measurement_source_texts": [],
                "metric_candidates": [],
                "metric_resolution": "missing",
                "selected_metric_id": None,
                "selected_metric_ids": [],
                "analysis_operation": None,
                "is_elliptical": True,
                # 이 route는 모델의 provisional 해석이다. 상위 typed ANALYSIS action이
                # 결합될 수 있으므로 기간 슬롯 recheck를 막아서는 안 된다.
                "requested_route": "PRESENTATION",
            }
        )
        if "interpretation_recheck" not in payload:
            result["period_candidates"] = []
        return result


class _UnresolvedPeriodNormalizer(_Normalizer):
    """bounded recheck 뒤에도 질문에서 기간을 확정하지 못하는 모델 응답."""

    async def normalize_question(self, payload: dict) -> dict:
        result = await super().normalize_question(payload)
        result["period_candidates"] = []
        return result


class _FuturePeriodRecheckNormalizer(_Normalizer):
    """첫 해석의 미래 구간을 bounded recheck에서 과거 구간으로 바로잡는다."""

    async def normalize_question(self, payload: dict) -> dict:
        result = await super().normalize_question(payload)
        if "interpretation_recheck" not in payload:
            result["period_candidates"] = [
                {
                    "start": "2027-08-01T00:00:00+09:00",
                    "end_exclusive": "2027-08-02T00:00:00+09:00",
                    "source_text": "selected period",
                }
            ]
        return result


class _UnresolvedFuturePeriodNormalizer(_Normalizer):
    """bounded recheck 뒤에도 데이터 기준일 이후의 기간을 반환한다."""

    async def normalize_question(self, payload: dict) -> dict:
        result = await super().normalize_question(payload)
        result["period_candidates"] = [
            {
                "start": "2027-08-01T00:00:00+09:00",
                "end_exclusive": "2027-08-02T00:00:00+09:00",
                "source_text": "selected period",
            }
        ]
        return result


class _OperationRecheckNormalizer(_Normalizer):
    """첫 해석에서 결과 형태를 놓치고 bounded recheck에서만 완성한다."""

    async def normalize_question(self, payload: dict) -> dict:
        result = await super().normalize_question(payload)
        if payload.get("interpretation_recheck") != {
            "target": "analysis_operation",
            "attempt": 1,
        }:
            result["intent_candidates"] = []
            result["analysis_operation"] = None
        return result


class _UnresolvedOperationNormalizer(_Normalizer):
    """bounded recheck 뒤에도 선택된 분석의 결과 형태를 완성하지 못한다."""

    async def normalize_question(self, payload: dict) -> dict:
        result = await super().normalize_question(payload)
        result["intent_candidates"] = []
        result["analysis_operation"] = None
        return result


def _latest_snapshot_assets(assets: list[dict[str, object]]) -> list[dict[str, object]]:
    """임의 자산의 range 계약을 도메인 비의존 최신 snapshot 계약으로 전환한다."""

    selected = deepcopy(assets)
    for asset in selected:
        metadata = dict(asset["time_metadata"])
        asset["time_metadata"] = {
            "calendar_id": metadata["calendar_id"],
            "mode": "latest_snapshot",
            "selection": "max_source_value_lt_as_of",
            "as_of_parameter": "snapshot_as_of",
            "fields": deepcopy(metadata["fields"]),
        }
        policy = dict(asset["query_policy"])
        policy["allowed_functions"] = list(
            dict.fromkeys([*policy["allowed_functions"], "max"])
        )
        asset["query_policy"] = policy
    return selected


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
        result["intent_candidates"] = []
        result["measurement_source_text"] = None
        result["measurement_source_texts"] = []
        result["metric_candidates"] = []
        result["metric_resolution"] = "missing"
        result["selected_metric_id"] = None
        result["selected_metric_ids"] = []
        result["analysis_operation"] = None
        result["is_elliptical"] = True
        return result


def test_node1_can_identify_support_metric_but_only_business_metric_is_selectable() -> None:
    engine = _engine(_runtime_bundle())
    assets = asyncio.run(
        _candidate_assets(
            engine,
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
    assert not {
        identifier
        for identifier, term in model.input["business_terms"].items()
        if term["kind"] == "support_metric"
    }
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

    # 제품 receipt는 필수 계보지만 data watermark는 manifest가 제공할 때만
    # 존재한다. 발행 시각이나 wall clock을 evidence cutoff로 꾸며내지 않는다.
    for asset in selected_assets:
        asset["product_release_id"] = "verified-product-release"

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
    assert package.product_release_id == "verified-product-release"
    assert package.evidence_cutoff is None
    assert {metric.id for metric in _business_metrics(package)} == {
        "amount_per_event"
    }
    assert metric_selection(selected_assets, package)["selected_metric_id"] == (
        "amount_per_event"
    )


def test_latest_snapshot_contract_reaches_context_without_inventing_a_period() -> None:
    """선택 자산 계약이 snapshot이면 기간을 요구하지 않고 서버 기준일을 결속한다."""

    engine = _engine(_runtime_bundle())
    assets = _latest_snapshot_assets(
        asyncio.run(
        _candidate_assets(
            engine,
                "Amount per Event",
                {"role": "analyst", "parameters": {"active": True}},
            )
        )
    )
    model = _SnapshotNormalizer()
    resolver = MetricResolver(engine, model)
    context = RequestContext(
        request_id=UUID("10000000-0000-0000-0000-000000000001"),
        trace_id="snapshot-runtime-contract",
        user_id=UUID("20000000-0000-0000-0000-000000000002"),
        role=Role.ANALYST,
        as_of=date(2026, 8, 19),
    )
    request = AnalysisRequest(
        question="Amount per Event",
        parameters={"active": True},
    )

    selected_assets, _question, structured = asyncio.run(
        resolver.resolve(request, context, assets)
    )
    package = asyncio.run(
        PipelineContextService(engine, ContextPackageBuilder()).build(
            request,
            context,
            selected_assets,
            structured,
        )
    )

    assert structured["time_mode"] == "latest_snapshot"
    assert structured["period_candidates"] == []
    assert len(model.inputs) == 1
    assert "interpretation_recheck" not in model.inputs[0]
    assert package.runtime_contracts["time_rules"]["selection"] == (
        "max_source_value_lt_as_of"
    )
    assert {
        item.name: (item.value_type, item.value)
        for item in package.parameter_bindings
    }["snapshot_as_of"] == ("date", "2026-08-19")
    assert PipelineResultValidator.execution_evidence(package)["snapshot"] == {
        "cutoff": "2026-08-19",
        "selection": "max_source_value_lt_as_of",
    }
    assert execution_time(context, package) == {
        "as_of": "2026-08-19T00:00:00+09:00",
        "timezone": "Asia/Seoul",
        "calendar_id": "iso8601",
        "time_mode": "latest_snapshot",
        "snapshot_cutoff": "2026-08-19",
        "selection": "max_source_value_lt_as_of",
    }


def test_range_metric_rechecks_a_missing_period_once_before_clarifying() -> None:
    """range Metric의 기간 누락만 한 번 재검토하고 두 번째 typed 기간을 사용한다."""

    engine = _engine(_runtime_bundle())
    assets = asyncio.run(
        _candidate_assets(
            engine,
            "Amount per Event",
            {"role": "analyst", "parameters": {"active": True}},
        )
    )
    model = _PeriodRecheckNormalizer()
    resolver = MetricResolver(engine, model)
    context = RequestContext(
        request_id=UUID("10000000-0000-0000-0000-000000000001"),
        trace_id="range-period-recheck",
        user_id=UUID("20000000-0000-0000-0000-000000000002"),
        role=Role.ANALYST,
        as_of=date(2026, 8, 19),
    )

    _selected_assets, _question, structured = asyncio.run(
        resolver.resolve(
            AnalysisRequest(
                question="Amount per Event",
                parameters={"active": True},
            ),
            context,
            assets,
        )
    )

    assert len(model.inputs) == 2
    assert "interpretation_recheck" not in model.inputs[0]
    assert model.inputs[1]["interpretation_recheck"] == {
        "target": "period_candidates",
        "attempt": 1,
    }
    assert structured["period_candidates"] == [
        {
            "start": "2026-08-01T00:00:00+09:00",
            "end_exclusive": "2026-08-02T00:00:00+09:00",
            "source_text": "2026-08-01",
        }
    ]


def test_missing_metric_followup_rechecks_only_the_period_before_clarifying() -> None:
    """기간-only 후속 질문도 기간을 1회 복구하되 Metric을 임의 선택하지 않는다."""

    engine = _engine(_runtime_bundle())
    assets = asyncio.run(
        _candidate_assets(
            engine,
            "Amount per Event 2026-08-01",
            {"role": "analyst", "parameters": {"active": True}},
        )
    )
    model = _MissingMetricPeriodRecheckNormalizer()
    resolver = MetricResolver(engine, model)
    context = RequestContext(
        request_id=UUID("10000000-0000-0000-0000-000000000001"),
        trace_id="missing-metric-period-recheck",
        user_id=UUID("20000000-0000-0000-0000-000000000002"),
        role=Role.ANALYST,
        as_of=date(2026, 8, 19),
    )

    with pytest.raises(ContextBuildError) as raised:
        asyncio.run(
            resolver.resolve(
                AnalysisRequest(
                    question="Amount per Event 2026-08-01",
                    parameters={"active": True},
                ),
                context,
                assets,
            )
        )

    assert raised.value.code is ContextBuildErrorCode.INVALID_METRIC
    assert raised.value.partial_context["period_candidates"] == [
        {
            "start": "2026-08-01T00:00:00+09:00",
            "end_exclusive": "2026-08-02T00:00:00+09:00",
            "source_text": "2026-08-01",
        }
    ]
    assert len(model.inputs) == 2
    assert model.inputs[1]["interpretation_recheck"] == {
        "target": "period_candidates",
        "attempt": 1,
    }


def test_range_metric_still_clarifies_when_the_bounded_recheck_has_no_period() -> None:
    """두 번째 해석도 기간이 없으면 기본 기간을 합성하거나 세 번째 호출을 하지 않는다."""

    engine = _engine(_runtime_bundle())
    assets = asyncio.run(
        _candidate_assets(
            engine,
            "Amount per Event",
            {"role": "analyst", "parameters": {"active": True}},
        )
    )
    model = _UnresolvedPeriodNormalizer()
    resolver = MetricResolver(engine, model)
    context = RequestContext(
        request_id=UUID("10000000-0000-0000-0000-000000000001"),
        trace_id="range-period-recheck-unresolved",
        user_id=UUID("20000000-0000-0000-0000-000000000002"),
        role=Role.ANALYST,
        as_of=date(2026, 8, 19),
    )

    with pytest.raises(ContextBuildError) as raised:
        asyncio.run(
            resolver.resolve(
                AnalysisRequest(
                    question="Amount per Event",
                    parameters={"active": True},
                ),
                context,
                assets,
            )
        )

    assert raised.value.code is ContextBuildErrorCode.PERIOD_REQUIRED
    assert len(model.inputs) == 2
    assert model.inputs[1]["interpretation_recheck"] == {
        "target": "period_candidates",
        "attempt": 1,
    }


def test_range_metric_rechecks_a_future_period_before_execution() -> None:
    """미래에서 시작하는 모델 기간을 그대로 실행하지 않고 같은 기간 슬롯만 재검토한다."""

    engine = _engine(_runtime_bundle())
    assets = asyncio.run(
        _candidate_assets(
            engine,
            "Amount per Event",
            {"role": "analyst", "parameters": {"active": True}},
        )
    )
    model = _FuturePeriodRecheckNormalizer()
    resolver = MetricResolver(engine, model)
    context = RequestContext(
        request_id=UUID("10000000-0000-0000-0000-000000000001"),
        trace_id="future-period-recheck",
        user_id=UUID("20000000-0000-0000-0000-000000000002"),
        role=Role.ANALYST,
        as_of=date(2026, 8, 19),
    )

    _selected_assets, _question, structured = asyncio.run(
        resolver.resolve(
            AnalysisRequest(
                question="Amount per Event",
                parameters={"active": True},
            ),
            context,
            assets,
        )
    )

    assert len(model.inputs) == 2
    assert model.inputs[1]["interpretation_recheck"] == {
        "target": "period_candidates",
        "attempt": 1,
    }
    assert structured["period_candidates"][0]["start"].startswith("2026-08-01")


def test_range_metric_rejects_a_future_period_after_one_recheck() -> None:
    """두 번째 해석도 미래이면 세 번째 호출이나 빈 결과 쿼리 대신 typed 범위 오류로 닫는다."""

    engine = _engine(_runtime_bundle())
    assets = asyncio.run(
        _candidate_assets(
            engine,
            "Amount per Event",
            {"role": "analyst", "parameters": {"active": True}},
        )
    )
    model = _UnresolvedFuturePeriodNormalizer()
    resolver = MetricResolver(engine, model)
    context = RequestContext(
        request_id=UUID("10000000-0000-0000-0000-000000000001"),
        trace_id="future-period-recheck-unresolved",
        user_id=UUID("20000000-0000-0000-0000-000000000002"),
        role=Role.ANALYST,
        as_of=date(2026, 8, 19),
    )

    with pytest.raises(ContextBuildError) as raised:
        asyncio.run(
            resolver.resolve(
                AnalysisRequest(
                    question="Amount per Event",
                    parameters={"active": True},
                ),
                context,
                assets,
            )
        )

    assert raised.value.code is ContextBuildErrorCode.OUT_OF_DATA_RANGE
    assert len(model.inputs) == 2


def test_release_bound_availability_rejects_period_before_run_creation() -> None:
    partial = {"metric_ids": ["room_revenue"]}
    asset = {
        "product_release_id": "phase7-release",
        "data_available_from": "2025-07-01",
        "data_available_through": "2025-08-31",
    }

    with pytest.raises(ContextBuildError) as raised:
        _validate_selected_data_availability(
            [asset],
            [
                {
                    "start": "2026-08-01",
                    "end_exclusive": "2026-09-01",
                    "source_text": "이번 달",
                }
            ],
            partial,
        )

    assert raised.value.code is ContextBuildErrorCode.OUT_OF_DATA_RANGE
    assert raised.value.suggestions == ("2025-07-01 ~ 2025-08-31",)
    assert raised.value.partial_context == {
        "metric_ids": ["room_revenue"],
        "data_availability": {
            "data_available_from": "2025-07-01",
            "data_available_through": "2025-08-31",
        },
    }


def test_selected_analysis_rechecks_a_missing_result_shape_once() -> None:
    """선택된 Metric의 결과 형태 누락만 재검토하고 두 번째 typed 연산을 사용한다."""

    engine = _engine(_runtime_bundle())
    assets = asyncio.run(
        _candidate_assets(
            engine,
            "Amount per Event",
            {"role": "analyst", "parameters": {"active": True}},
        )
    )
    model = _OperationRecheckNormalizer()
    resolver = MetricResolver(engine, model)
    context = RequestContext(
        request_id=UUID("10000000-0000-0000-0000-000000000001"),
        trace_id="analysis-operation-recheck",
        user_id=UUID("20000000-0000-0000-0000-000000000002"),
        role=Role.ANALYST,
        as_of=date(2026, 8, 19),
    )

    _selected_assets, _question, structured = asyncio.run(
        resolver.resolve(
            AnalysisRequest(
                question="Amount per Event",
                parameters={"active": True},
            ),
            context,
            assets,
        )
    )

    assert len(model.inputs) == 2
    assert "interpretation_recheck" not in model.inputs[0]
    assert model.inputs[1]["interpretation_recheck"] == {
        "target": "analysis_operation",
        "attempt": 1,
    }
    assert structured["analysis_operation"] == "aggregate"
    assert structured["intent_candidates"] == ["aggregate"]


def test_sealed_conversation_default_builds_presentation_ready_time_series_only_in_conversation() -> None:
    """같은 Node1 aggregate도 explicit Conversation capability에서만 day series로 좁힌다."""

    engine = _engine(_runtime_bundle())
    assets = asyncio.run(
        _candidate_assets(
            engine,
            "Amount per Event",
            {"role": "analyst", "parameters": {"active": True}},
        )
    )
    for asset in assets:
        asset["conversation_default_operation"] = "time_trend"
    direct_context = RequestContext(
        request_id=UUID("10000000-0000-0000-0000-000000000031"),
        trace_id="direct-aggregate-default",
        user_id=UUID("20000000-0000-0000-0000-000000000032"),
        role=Role.ANALYST,
        as_of=date(2026, 8, 19),
    )
    conversation_context = direct_context.model_copy(
        update={
            "request_id": UUID("10000000-0000-0000-0000-000000000033"),
            "trace_id": "conversation-time-trend-default",
            "conversation_id": UUID("30000000-0000-0000-0000-000000000034"),
        }
    )

    _assets, _question, direct = asyncio.run(
        MetricResolver(engine, _Normalizer()).resolve(
            AnalysisRequest(question="Amount per Event", parameters={"active": True}),
            direct_context,
            deepcopy(assets),
        )
    )
    _assets, _question, conversation = asyncio.run(
        MetricResolver(engine, _Normalizer()).resolve(
            AnalysisRequest(question="Amount per Event", parameters={"active": True}),
            conversation_context,
            deepcopy(assets),
        )
    )

    assert direct["analysis_operation"] == "aggregate"
    assert direct["intent_candidates"] == ["aggregate"]
    assert conversation["analysis_operation"] == "time_trend"
    assert conversation["intent_candidates"] == ["time_trend"]


def test_selected_analysis_rejects_an_unresolved_shape_after_one_recheck() -> None:
    """두 번째 해석도 결과 형태가 비면 기본 연산이나 세 번째 호출을 만들지 않는다."""

    engine = _engine(_runtime_bundle())
    assets = asyncio.run(
        _candidate_assets(
            engine,
            "Amount per Event",
            {"role": "analyst", "parameters": {"active": True}},
        )
    )
    model = _UnresolvedOperationNormalizer()
    resolver = MetricResolver(engine, model)
    context = RequestContext(
        request_id=UUID("10000000-0000-0000-0000-000000000001"),
        trace_id="analysis-operation-recheck-unresolved",
        user_id=UUID("20000000-0000-0000-0000-000000000002"),
        role=Role.ANALYST,
        as_of=date(2026, 8, 19),
    )

    with pytest.raises(ValueError, match="정확히 1개의 분석 의도"):
        asyncio.run(
            resolver.resolve(
                AnalysisRequest(
                    question="Amount per Event",
                    parameters={"active": True},
                ),
                context,
                assets,
            )
        )

    assert len(model.inputs) == 2
    assert model.inputs[1]["interpretation_recheck"] == {
        "target": "analysis_operation",
        "attempt": 1,
    }


def test_latest_snapshot_contract_rejects_unapproved_period_coercion() -> None:
    """질문의 기간 범위를 snapshot cutoff로 조용히 바꾸지 않는다."""

    engine = _engine(_runtime_bundle())
    assets = _latest_snapshot_assets(
        asyncio.run(
        _candidate_assets(
            engine,
                "Amount per Event",
                {"role": "analyst", "parameters": {"active": True}},
            )
        )
    )
    context = RequestContext(
        request_id=UUID("10000000-0000-0000-0000-000000000001"),
        trace_id="snapshot-period-rejected",
        user_id=UUID("20000000-0000-0000-0000-000000000002"),
        role=Role.ANALYST,
        as_of=date(2026, 8, 19),
    )

    with pytest.raises(ContextBuildError) as raised:
        asyncio.run(
            MetricResolver(engine, _Normalizer()).resolve(
                AnalysisRequest(
                    question="Amount per Event",
                    parameters={"active": True},
                ),
                context,
                assets,
            )
        )

    assert raised.value.code is ContextBuildErrorCode.QUERY_STRATEGY_NOT_APPROVED


def test_result_evidence_rejects_mixed_time_modes() -> None:
    """한 artifact가 range와 snapshot 실행을 동시에 주장하지 못하게 한다."""

    with pytest.raises(ValueError, match="동시에"):
        Evidence(
            as_of=date(2026, 8, 20),
            period=PeriodEvidence(
                start=date(2026, 8, 1),
                end_exclusive=date(2026, 8, 20),
            ),
            snapshot=SnapshotEvidence(
                cutoff=date(2026, 8, 20),
                selection="max_source_value_lt_as_of",
            ),
        )


def test_node1_preserves_multiple_explicit_business_metrics_as_one_analysis_scope() -> None:
    engine = _engine(_runtime_bundle())
    question = "Amount per Event and Account Count"
    assets = asyncio.run(
        _candidate_assets(
            engine,
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
        _candidate_assets(
            engine,
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


def test_node1_receives_typed_previous_shape_without_entering_metric_fast_path() -> None:
    """지표 없는 선행 슬롯은 현재 질문을 재해석하되 직전 결과 형태만 컨텍스트로 준다."""

    engine = _engine(_runtime_bundle())
    question = "Amount per Event"
    assets = asyncio.run(
        _candidate_assets(
            engine,
            question,
            {"role": "analyst", "parameters": {"active": True}},
        )
    )
    model = _Normalizer()
    resolver = MetricResolver(engine, model)
    context = RequestContext(
        request_id=UUID("10000000-0000-0000-0000-000000000001"),
        trace_id="v2-runtime-previous-result-shape",
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
                    dimension_ids=("prior_dimension",),
                    analysis_operation="breakdown",
                ),
            ),
            context,
            assets,
        )
    )

    assert model.input is not None
    assert model.input["previous_result_shape"] == {
        "analysis_operation": "breakdown",
        "dimension_count": 1,
        "result_limit": None,
    }
    assert structured["selected_metric_ids"] == ["amount_per_event"]


def test_cross_metric_comparison_uses_one_shared_period_without_requesting_a_second() -> None:
    engine = _engine(_runtime_bundle())
    question = "Amount per Event and Account Count"
    assets = asyncio.run(
        _candidate_assets(
            engine,
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
        _candidate_assets(
            engine,
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
    candidates = asyncio.run(
        engine.search_asset_candidates(
            "Support amount_total",
            {"role": "analyst", "parameters": {"active": True}},
        )
    )
    assets = list(candidates.assets)
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
    candidates = asyncio.run(
        engine.search_asset_candidates(
            "Support amount_total",
            {"role": "analyst", "parameters": {"active": True}},
        )
    )
    assets = list(candidates.assets)
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
        _candidate_assets(
            engine,
            "Amount per Event",
            {"role": "analyst", "parameters": {"active": True}},
        )
    )
    account_assets = asyncio.run(
        _candidate_assets(
            engine,
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
        _candidate_assets(
            engine,
            "Amount per Event",
            {"role": "analyst", "parameters": {"active": True}},
        )
    )
    account_assets = asyncio.run(
        _candidate_assets(
            engine,
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
        _candidate_assets(
            engine,
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
        _candidate_assets(
            engine,
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
    assert raised.value.partial_context["analysis_operation"] is None
    assert raised.value.partial_context["intent_candidates"] == []
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
