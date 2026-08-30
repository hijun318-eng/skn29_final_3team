"""승인 Semantic Request snapshot의 불변성·재실행 fail-closed 경계를 검증한다."""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
from datetime import date
from pathlib import Path
from sys import path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID

import pytest
from pydantic import ValidationError

BACKEND = Path(__file__).resolve().parents[2] / "app" / "backend"
path.insert(0, str(BACKEND))

from app.authorization import permission_snapshot_id
from app.analysis_contracts import ReplayAnalysisRequest
from app.api import router as analysis_api
from app.context import ContextValidationError
from app.contracts import RequestContext, Role, RouteType
from app.services.analysis.semantic_request import (
    APPROVED_SEMANTIC_REQUEST_VERSION,
    SemanticParameterBinding,
    SemanticReplayAnalysisRequest,
    create_approved_semantic_request_snapshot,
    parse_approved_semantic_request_snapshot,
)
from app.services.analysis.pipeline_support import PipelineSupport
from app.services.analysis.stages.plan_stage import AnalysisPlanStage
from app.services.analysis.sql_generation_mode import SqlGenerationMode
from app.services.execution_control import IsolatedExecutionCache
from app.services.report.execution import AnalysisDefinitionReplay
from app.services.analysis.stages.context_stage import AnalysisContextStage
from app.services.context.package_types import (
    ContextDimensionMemberReceipt,
    ContextParameterBinding,
)
from app.services.conversation.analysis_request import build_replay_analysis_request
from app.services.routing_service import RouteDecision
from src.data.metric_governance import RUNTIME_GOVERNANCE_VERSION_V2
from src.report.domain import BlockFailureCode


def _canonical_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def _analysis_plan(*, operator: str = "eq") -> dict[str, object]:
    identity: dict[str, object] = {
        "version": "ANSWERVICE-ANALYSIS-PLAN-v4",
        "operation": "aggregate",
        "output_metric_ids": ["room_revenue"],
        "dependency_metric_ids": ["room_revenue"],
        "dimension_fields": [],
        "filter_fields": [
            {
                "asset_fqn": "pms.serving.room_revenue_daily",
                "column": "property_code",
                "operator": operator,
                "parameter": "property_filter",
            }
        ],
        "time_mode": "range",
        "time_fields": [
            {
                "asset_fqn": "pms.serving.room_revenue_daily",
                "column": "business_date",
            }
        ],
        "time_bucket": "none",
        "period_parameters": [
            {"start_parameter": "period_start", "end_parameter": "period_end"}
        ],
        "snapshot_parameter": None,
        "result_limit": None,
        "query_strategy": "RAW_APPROVED_DETAIL",
        "joins": [],
        "context_package_hash": "a" * 64,
    }
    return {**identity, "checksum": _canonical_hash(identity)}


def _snapshot(
    *,
    product_release: str = "product-v1",
    semantic_release: str = "semantic-v1",
    operator: str = "eq",
):
    return create_approved_semantic_request_snapshot(
        source_request_id=UUID("10000000-0000-0000-0000-000000000001"),
        query_execution_id=UUID("20000000-0000-0000-0000-000000000002"),
        artifact_id=UUID("30000000-0000-0000-0000-000000000003"),
        execution_as_of=date(2026, 8, 30),
        analysis_plan=_analysis_plan(operator=operator),
        parameter_bindings=(
            ContextParameterBinding("period_start", "date", "2026-07-01"),
            ContextParameterBinding("period_end", "date", "2026-08-01"),
            ContextParameterBinding("property_filter", "string", "SEOUL"),
        ),
        dimension_member_receipts=(
            ContextDimensionMemberReceipt(
                dimension_id="property",
                member_id="seoul",
                term_urn="urn:li:glossaryTerm:property.seoul",
                canonical_value="SEOUL",
                version="member-v1",
                semantic_sha256="d" * 64,
                asset_fqn="pms.serving.room_revenue_daily",
                column="property_code",
            ),
        ),
        release_receipt={
            "product_release_id": product_release,
            "permission_snapshot_id": "permission-at-approval",
            "semantic_release_id": semantic_release,
            "context_release": semantic_release,
            "policy_version": "policy-v1",
            "catalog_checksum": "1" * 64,
            "canonical_checksum": "2" * 64,
            "runtime_projection_checksum": "3" * 64,
        },
    )


def test_snapshot_round_trip_preserves_only_typed_semantic_contract() -> None:
    snapshot = _snapshot()

    restored = parse_approved_semantic_request_snapshot(
        snapshot.model_dump(mode="json")
    )

    assert restored.schema_version == APPROVED_SEMANTIC_REQUEST_VERSION
    assert restored.parameters == {
        "period_start": "2026-07-01",
        "period_end": "2026-08-01",
        "property_filter": "SEOUL",
    }
    assert restored.structured_request()["metric_ids"] == ["room_revenue"]
    assert restored.structured_request()["filter_fields"] == [
        {
            "asset_fqn": "pms.serving.room_revenue_daily",
            "column": "property_code",
            "operator": "eq",
            "value_text": "SEOUL",
        }
    ]
    assert "question" not in restored.model_dump(mode="json")


@pytest.mark.parametrize("operator", ["eq", "neq"])
def test_filtered_snapshot_restores_typed_member_without_internal_parameter(
    operator: str,
) -> None:
    snapshot = _snapshot(operator=operator)

    structured = snapshot.structured_request()

    assert structured["filter_fields"] == [
        {
            "asset_fqn": "pms.serving.room_revenue_daily",
            "column": "property_code",
            "operator": operator,
            "value_text": "SEOUL",
        }
    ]
    assert structured["dimension_member_receipts"] == [
        {
            "dimension_id": "property",
            "member_id": "seoul",
            "term_urn": "urn:li:glossaryTerm:property.seoul",
            "canonical_value": "SEOUL",
            "version": "member-v1",
            "semantic_sha256": "d" * 64,
            "asset_fqn": "pms.serving.room_revenue_daily",
            "column": "property_code",
        }
    ]


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_numeric_parameter_rejects_non_finite_values(value: float) -> None:
    with pytest.raises(ValidationError):
        SemanticParameterBinding(name="unsafe_value", value_type="number", value=value)


@pytest.mark.parametrize("value_type", ["string", "date", "timestamp"])
def test_text_parameter_rejects_empty_values(value_type: str) -> None:
    with pytest.raises(ValidationError):
        SemanticParameterBinding(name="empty_value", value_type=value_type, value="")


def test_snapshot_rejects_hash_and_analysis_plan_tampering() -> None:
    snapshot = _snapshot()
    bad_hash = snapshot.model_dump(mode="json")
    bad_hash["snapshot_hash"] = "0" * 64
    with pytest.raises(ValidationError):
        parse_approved_semantic_request_snapshot(bad_hash)

    bad_plan = snapshot.model_dump(mode="json")
    bad_plan["analysis_plan"]["operation"] = "time_trend"
    with pytest.raises(ValidationError):
        parse_approved_semantic_request_snapshot(bad_plan)


@pytest.mark.parametrize(
    "mutation",
    ["empty_bucket", "malformed_time_field", "aggregate_dimension", "latest_with_period"],
)
def test_snapshot_rejects_structurally_impossible_sealed_plan(mutation: str) -> None:
    payload = _snapshot().model_dump(mode="json")
    plan = payload["analysis_plan"]
    if mutation == "empty_bucket":
        plan["time_bucket"] = ""
    elif mutation == "malformed_time_field":
        plan["time_fields"][0]["unexpected"] = "not-sealed"
    elif mutation == "aggregate_dimension":
        plan["dimension_fields"] = [
            {
                "asset_fqn": "pms.serving.room_revenue_daily",
                "column": "property_code",
            }
        ]
    else:
        plan["time_mode"] = "latest_snapshot"
    plan["checksum"] = _canonical_hash(
        {key: value for key, value in plan.items() if key != "checksum"}
    )
    payload["snapshot_hash"] = _canonical_hash(
        {key: value for key, value in payload.items() if key != "snapshot_hash"}
    )

    with pytest.raises(ValidationError):
        parse_approved_semantic_request_snapshot(payload)


def test_replay_revalidates_hash_after_nested_plan_mutation() -> None:
    snapshot = _snapshot()
    request = SemanticReplayAnalysisRequest(approved_semantic_snapshot=snapshot)
    snapshot.analysis_plan["filter_fields"][0]["parameter"] = "mutated_parameter"

    with pytest.raises(ValidationError, match="checksum|hash"):
        _ = request.parameters


def test_snapshot_rejects_dimension_receipt_extension_and_duplicate_identity() -> None:
    snapshot = _snapshot()
    extended = snapshot.model_dump(mode="json")
    extended["dimension_member_receipts"][0]["raw_user_payload"] = "not-allowed"
    with pytest.raises(ValidationError):
        parse_approved_semantic_request_snapshot(extended)

    duplicate = snapshot.model_dump(mode="json")
    duplicate["dimension_member_receipts"].append(
        dict(duplicate["dimension_member_receipts"][0])
    )
    duplicate["snapshot_hash"] = _canonical_hash(
        {key: value for key, value in duplicate.items() if key != "snapshot_hash"}
    )
    with pytest.raises(ValidationError, match="중복"):
        parse_approved_semantic_request_snapshot(duplicate)


@pytest.mark.parametrize("mutation", ["missing", "extra"])
def test_snapshot_requires_exact_plan_parameter_binding_set(mutation: str) -> None:
    snapshot = _snapshot()
    payload = snapshot.model_dump(mode="json")
    if mutation == "missing":
        payload["parameter_bindings"] = payload["parameter_bindings"][1:]
    else:
        payload["parameter_bindings"].append(
            {"name": "unapproved_secret", "value_type": "string", "value": "x"}
        )
    payload["snapshot_hash"] = _canonical_hash(
        {key: value for key, value in payload.items() if key != "snapshot_hash"}
    )

    with pytest.raises(ValidationError, match="정확히 일치"):
        parse_approved_semantic_request_snapshot(payload)


def test_replay_request_rejects_legacy_and_parameter_override() -> None:
    snapshot = _snapshot()
    definition = {
        "approved_semantic_snapshot": snapshot.model_dump(mode="json")
    }
    request = build_replay_analysis_request(definition, snapshot.parameters)
    assert isinstance(request, SemanticReplayAnalysisRequest)
    assert request.question == "승인된 Semantic Request 재실행"

    with pytest.raises(ValueError, match="변경할 수 없습니다"):
        build_replay_analysis_request(definition, {"period_start": "2020-01-01"})
    with pytest.raises(ValueError, match="snapshot"):
        build_replay_analysis_request({"semantic_request": {}}, {})


class _Adapter:
    def __init__(self) -> None:
        self.search_count = 0

    async def search_asset_candidates(self, *_args: object, **_kwargs: object) -> None:
        self.search_count += 1
        raise AssertionError("snapshot replay는 lexical catalog 검색을 호출하면 안 됩니다.")


class _GovernanceAdapter(_Adapter):
    def __init__(self) -> None:
        super().__init__()
        self.selection = None
        self.resolve_context: dict[str, object] | None = None

    async def resolve_execution_assets(
        self,
        selection: object,
        context: dict[str, object],
    ) -> list[dict[str, object]]:
        self.selection = selection
        self.resolve_context = context
        return [
            {
                "urn": "urn:li:dataset:approved-room-revenue",
                "fqn": "pms.serving.room_revenue_daily",
                "join_ids": [],
                "metrics": [
                    {
                        "id": "room_revenue",
                        "governance_version": RUNTIME_GOVERNANCE_VERSION_V2,
                        "allowed_join_ids": [],
                        "join_required": False,
                        "visibility": "BUSINESS",
                    }
                ],
            }
        ]


async def _room_revenue_snapshot_resolves_without_time_field_as_dimension() -> None:
    snapshot = _snapshot()
    payload = SemanticReplayAnalysisRequest(approved_semantic_snapshot=snapshot)
    adapter = _GovernanceAdapter()
    support = PipelineSupport(adapter, object())
    context = RequestContext(
        user_id=UUID("40000000-0000-0000-0000-000000000004"),
        role=Role.ANALYST,
        as_of=snapshot.execution_as_of,
        permission_snapshot_id=permission_snapshot_id(
            UUID("40000000-0000-0000-0000-000000000004"), Role.ANALYST
        ),
        product_release_id=snapshot.release_receipt.product_release_id,
        semantic_release_id=snapshot.release_receipt.semantic_release_id,
    )

    assets = await support.resolve_snapshot_execution_assets(
        payload,
        context,
        snapshot,
    )

    assert assets[0]["fqn"] == "pms.serving.room_revenue_daily"
    assert adapter.search_count == 0
    assert adapter.selection is not None
    assert {
        (item.asset_fqn, item.column)
        for item in adapter.selection.field_references
    } == {("pms.serving.room_revenue_daily", "property_code")}
    assert adapter.resolve_context is not None
    assert adapter.resolve_context["permission_snapshot_id"] == context.permission_snapshot_id


def test_room_revenue_snapshot_resolves_without_time_field_as_dimension() -> None:
    asyncio.run(_room_revenue_snapshot_resolves_without_time_field_as_dimension())


class _Support:
    def __init__(self, events: list[str], expected_permission: str) -> None:
        self.events = events
        self.expected_permission = expected_permission
        self.resolve_count = 0

    async def resolve_snapshot_execution_assets(
        self,
        _payload: object,
        context: RequestContext,
        _snapshot: object,
    ) -> list[dict[str, object]]:
        assert context.permission_snapshot_id == self.expected_permission
        self.events.append("resolve-current-entitlement")
        self.resolve_count += 1
        return [
            {
                "urn": "urn:li:dataset:approved-room-revenue",
                "schema_version": "schema-v1",
                "seed_version": "seed-v1",
            }
        ]

    async def build_context(
        self,
        _payload: object,
        _context: RequestContext,
        _assets: list[dict[str, object]],
        _structured_request: dict[str, object],
    ) -> object:
        self.events.append("build-current-context")
        fqn = "pms.serving.room_revenue_daily"
        return SimpleNamespace(
            package_hash="4" * 64,
            policy_version="policy-current",
            entitlement_hash="5" * 64,
            parameter_bindings=(
                ContextParameterBinding("period_start", "date", "2026-07-01"),
                ContextParameterBinding("period_end", "date", "2026-08-01"),
                ContextParameterBinding("property_filter", "string", "SEOUL"),
                ContextParameterBinding(
                    "current_policy_filter", "string", "current-only"
                ),
            ),
            assets=(
                SimpleNamespace(
                    urn="urn:li:dataset:approved-room-revenue",
                    fqn=fqn,
                    columns=("business_date", "room_revenue", "property_code"),
                    join_ids=(),
                ),
            ),
            metrics=(SimpleNamespace(id="room_revenue", asset_fqn=fqn),),
        )


class _Responses:
    def error(self, *args: object, **kwargs: object) -> dict[str, object]:
        return {"kind": "error", "args": args, "kwargs": kwargs}

    def model_error(self, *args: object, **kwargs: object) -> dict[str, object]:
        return {"kind": "model_error", "args": args, "kwargs": kwargs}


class _PlanSupport:
    def __init__(self, plan: dict[str, object]) -> None:
        self.plan = plan

    def analysis_plan(self, *_args: object, **_kwargs: object) -> object:
        return SimpleNamespace(as_dict=lambda: self.plan)


async def _parameter_name_drift_is_blocked_by_plan_identity() -> None:
    snapshot = _snapshot()
    drifted_plan = copy.deepcopy(snapshot.analysis_plan)
    drifted_plan["filter_fields"][0]["parameter"] = "renamed_property_filter"
    drift_identity = {
        key: value for key, value in drifted_plan.items() if key != "checksum"
    }
    drifted_plan["checksum"] = _canonical_hash(drift_identity)
    context = RequestContext(
        user_id=UUID("40000000-0000-0000-0000-000000000004"),
        role=Role.ANALYST,
        as_of=snapshot.execution_as_of,
        product_release_id=snapshot.release_receipt.product_release_id,
        semantic_release_id=snapshot.release_receipt.semantic_release_id,
    )
    state = SimpleNamespace(
        package=object(),
        context=context,
        decision=RouteDecision(RouteType.GENERAL, None, True, True),
        structured_request=snapshot.structured_request(),
        approved_analysis_plan=dict(snapshot.analysis_plan),
        machine=object(),
        trace=[],
    )
    responses = _Responses()
    stage = AnalysisPlanStage(
        object(),
        _PlanSupport(drifted_plan),
        responses,
        IsolatedExecutionCache(),
        SqlGenerationMode.HYBRID,
    )

    response = await stage.run(state)

    assert response is not None
    assert response["kind"] == "error"
    assert str(response["args"][5].value) == "SCHEMA_VERSION_MISMATCH"
    assert response["kwargs"]["detail"] == "APPROVED_SEMANTIC_PLAN_MISMATCH"


def test_parameter_name_drift_is_blocked_by_plan_identity() -> None:
    asyncio.run(_parameter_name_drift_is_blocked_by_plan_identity())


class _ActivePlatform:
    def __init__(self, product_release: str, semantic_release: str) -> None:
        self.product_release = product_release
        self.semantic_release = semantic_release

    async def get_active_context_release(self) -> str:
        return self.semantic_release

    async def get_catalog_readiness(self) -> tuple[dict[str, str], str]:
        return {"runtime_catalog": "ready"}, self.product_release


class _ReportDefinitionRepository:
    def __init__(self, snapshot: object) -> None:
        self.definition = {
            "definition_id": UUID("50000000-0000-0000-0000-000000000005"),
            "version": 1,
            "approved_semantic_snapshot": snapshot.model_dump(mode="json"),
        }

    async def get_definition_for_report(
        self,
        _definition_id: str,
        _version: int,
    ) -> dict[str, object]:
        return self.definition


class _UnusedGate:
    async def acquire(self, _wait_seconds: float = 0) -> bool:
        raise AssertionError("inactive release는 execution gate 전에 차단해야 합니다.")

    def release(self) -> None:
        raise AssertionError("획득하지 않은 gate를 반환하면 안 됩니다.")


async def _report_replay_blocks_inactive_release(mismatch: str) -> None:
    snapshot = _snapshot()
    active_product = (
        "product-v2"
        if mismatch == "product"
        else snapshot.release_receipt.product_release_id
    )
    active_semantic = (
        "semantic-v2"
        if mismatch == "semantic"
        else snapshot.release_receipt.semantic_release_id
    )
    controller = SimpleNamespace(
        data_platform=_ActivePlatform(active_product, active_semantic)
    )
    replay = AnalysisDefinitionReplay(
        "postgresql://unused",
        controller,
        _UnusedGate(),
    )
    repository = _ReportDefinitionRepository(snapshot)
    owner_id = UUID("40000000-0000-0000-0000-000000000004")

    with (
        patch(
            "app.services.report.execution.PostgresAnalysisRepository",
            return_value=repository,
        ),
        patch(
            "app.services.report.execution.require_active_subject_with_capability",
            return_value=SimpleNamespace(role=Role.ANALYST),
        ),
    ):
        outcome = await replay.execute(
            owner_id=owner_id,
            definition_id=str(repository.definition["definition_id"]),
            definition_version=1,
            as_of=SimpleNamespace(),
            idempotency_key=f"inactive-{mismatch}",
            product_release_id=snapshot.release_receipt.product_release_id,
            permission_snapshot_id=permission_snapshot_id(owner_id, Role.ANALYST),
            semantic_release_id=snapshot.release_receipt.semantic_release_id,
        )

    assert outcome.failure_code is BlockFailureCode.REPLAY_UNAVAILABLE


@pytest.mark.parametrize("mismatch", ["product", "semantic"])
def test_report_replay_blocks_inactive_release(mismatch: str) -> None:
    asyncio.run(_report_replay_blocks_inactive_release(mismatch))


class _ApiDefinitionRepository:
    def __init__(self, snapshot: object) -> None:
        self.definition = {
            "definition_id": UUID("50000000-0000-0000-0000-000000000005"),
            "version": 1,
            "approved_semantic_snapshot": snapshot.model_dump(mode="json"),
        }

    async def get_definition(
        self,
        _definition_id: UUID,
        *,
        replay: bool = False,
    ) -> dict[str, object]:
        assert replay is True
        return self.definition


async def _api_replay_blocks_inactive_release(mismatch: str) -> None:
    snapshot = _snapshot()
    repository = _ApiDefinitionRepository(snapshot)
    active_product = (
        "product-v2"
        if mismatch == "product"
        else snapshot.release_receipt.product_release_id
    )
    active_semantic = (
        "semantic-v2"
        if mismatch == "semantic"
        else snapshot.release_receipt.semantic_release_id
    )
    context = RequestContext(
        user_id=UUID("40000000-0000-0000-0000-000000000004"),
        role=Role.ANALYST,
        as_of=snapshot.execution_as_of,
    )

    async def active_receipt() -> tuple[str, str]:
        return active_product, active_semantic

    with (
        patch.object(analysis_api, "_analysis_repository", return_value=repository),
        patch.object(
            analysis_api,
            "_active_product_release_receipt",
            new=active_receipt,
        ),
        pytest.raises(ContextValidationError) as caught,
    ):
        await analysis_api.replay_analysis_definition(
            repository.definition["definition_id"],
            ReplayAnalysisRequest(idempotency_key=f"inactive-{mismatch}"),
            context,
        )

    assert caught.value.status_code == 409
    assert caught.value.code.value == "SCHEMA_VERSION_MISMATCH"


@pytest.mark.parametrize("mismatch", ["product", "semantic"])
def test_api_replay_blocks_inactive_release(mismatch: str) -> None:
    asyncio.run(_api_replay_blocks_inactive_release(mismatch))


def _state(
    snapshot: object,
    context: RequestContext,
    admission_sink: object,
) -> SimpleNamespace:
    return SimpleNamespace(
        payload=SemanticReplayAnalysisRequest(approved_semantic_snapshot=snapshot),
        context=context,
        decision=RouteDecision(RouteType.GENERAL, None, True, True),
        machine=object(),
        trace=[],
        budget=None,
        run_admission_sink=admission_sink,
        context_receipt_sink=None,
        approved_semantic_snapshot=None,
        approved_analysis_plan=None,
        semantic_candidate_receipt=None,
        record=lambda *_args, **_kwargs: None,
        cancelled=lambda _stage: None,
    )


async def _snapshot_replay_admits_then_rechecks_current_entitlement() -> None:
    snapshot = _snapshot()
    user_id = UUID("40000000-0000-0000-0000-000000000004")
    expected_permission = permission_snapshot_id(user_id, Role.ANALYST)
    events: list[str] = []

    async def admit(context: RequestContext) -> None:
        assert context.permission_snapshot_id == expected_permission
        assert context.permission_snapshot_id != "caller-supplied-stale-permission"
        events.append("durable-admission")

    context = RequestContext(
        user_id=user_id,
        role=Role.ANALYST,
        as_of=snapshot.execution_as_of,
        permission_snapshot_id="caller-supplied-stale-permission",
        product_release_id=snapshot.release_receipt.product_release_id,
        semantic_release_id=snapshot.release_receipt.semantic_release_id,
    )
    adapter = _Adapter()
    support = _Support(events, expected_permission)
    state = _state(snapshot, context, admit)
    stage = AnalysisContextStage(adapter, object(), support, _Responses())

    response = await stage.run(state)

    assert response is None
    assert events == [
        "durable-admission",
        "resolve-current-entitlement",
        "build-current-context",
    ]
    assert support.resolve_count == 1
    assert adapter.search_count == 0
    assert state.context.permission_snapshot_id == expected_permission


def test_snapshot_replay_admits_then_rechecks_current_entitlement() -> None:
    asyncio.run(_snapshot_replay_admits_then_rechecks_current_entitlement())


class _ClampingSupport(_Support):
    async def build_context(
        self,
        payload: object,
        context: RequestContext,
        assets: list[dict[str, object]],
        structured_request: dict[str, object],
    ) -> object:
        package = await super().build_context(
            payload,
            context,
            assets,
            structured_request,
        )
        return SimpleNamespace(
            **{
                **package.__dict__,
                "parameter_bindings": (
                    ContextParameterBinding(
                        "period_start", "date", "2026-07-01"
                    ),
                    ContextParameterBinding(
                        "period_end", "date", "2026-07-31"
                    ),
                    ContextParameterBinding(
                        "property_filter", "string", "SEOUL"
                    ),
                    ContextParameterBinding(
                        "current_policy_filter", "string", "current-only"
                    ),
                ),
            }
        )


async def _snapshot_replay_blocks_current_binding_value_drift() -> None:
    snapshot = _snapshot()
    user_id = UUID("40000000-0000-0000-0000-000000000004")
    expected_permission = permission_snapshot_id(user_id, Role.ANALYST)
    events: list[str] = []

    async def admit(_context: RequestContext) -> None:
        events.append("durable-admission")

    context = RequestContext(
        user_id=user_id,
        role=Role.ANALYST,
        as_of=snapshot.execution_as_of,
        product_release_id=snapshot.release_receipt.product_release_id,
        semantic_release_id=snapshot.release_receipt.semantic_release_id,
    )
    state = _state(snapshot, context, admit)
    stage = AnalysisContextStage(
        _Adapter(),
        object(),
        _ClampingSupport(events, expected_permission),
        _Responses(),
    )

    response = await stage.run(state)

    assert response is not None
    assert response["kind"] == "error"
    assert str(response["args"][5].value) == "SCHEMA_VERSION_MISMATCH"
    assert response["kwargs"]["detail"] == "APPROVED_SEMANTIC_BINDING_MISMATCH"


def test_snapshot_replay_blocks_current_binding_value_drift() -> None:
    asyncio.run(_snapshot_replay_blocks_current_binding_value_drift())


@pytest.mark.parametrize("mismatch", ["product", "semantic"])
def test_snapshot_replay_blocks_each_current_release_mismatch(mismatch: str) -> None:
    asyncio.run(_snapshot_replay_blocks_each_current_release_mismatch(mismatch))


async def _snapshot_replay_blocks_each_current_release_mismatch(
    mismatch: str,
) -> None:
    snapshot = _snapshot()
    events: list[str] = []

    async def admit(_context: RequestContext) -> None:
        events.append("durable-admission")

    context = RequestContext(
        user_id=UUID("40000000-0000-0000-0000-000000000004"),
        role=Role.ANALYST,
        as_of=snapshot.execution_as_of,
        product_release_id=(
            "different-product"
            if mismatch == "product"
            else snapshot.release_receipt.product_release_id
        ),
        semantic_release_id=(
            "different-semantic"
            if mismatch == "semantic"
            else snapshot.release_receipt.semantic_release_id
        ),
    )
    adapter = _Adapter()
    support = _Support(events, "not-used")
    state = _state(snapshot, context, admit)
    stage = AnalysisContextStage(adapter, object(), support, _Responses())

    response = await stage.run(state)

    assert response is not None
    assert response["kind"] == "error"
    assert events == []
    assert support.resolve_count == 0
    assert adapter.search_count == 0


def test_migration_creates_immutable_snapshot_and_blocks_legacy_replay_binding() -> None:
    migration = (
        Path("app/backend/migrations/versions/20260831_60_approved_semantic_request.py")
        .read_text(encoding="utf-8")
    )

    assert "approved_semantic_request_snapshots" in migration
    assert "reject_immutable_mutation" in migration
    assert "semantic_snapshot_id" in migration
    assert "ON DELETE RESTRICT" in migration
    assert "jsonb_typeof(snapshot_json) = 'object'" in migration
    assert "jsonb_typeof(snapshot_json->'analysis_plan') IS NOT NULL" in migration
    assert "snapshot_json->>'timezone' = 'Asia/Seoul'" in migration
    assert "snapshot_json->>'snapshot_id' IS NOT NULL" in migration
    assert "snapshot_json#>>'{lineage,artifact_id}' IS NOT NULL" in migration
    assert "snapshot_json#>>'{release_receipt,context_release}' IS NOT NULL" in migration
    assert "snapshot_json#>>'{release_receipt,catalog_checksum}' IS NOT NULL" in migration
