from __future__ import annotations

from app.contracts import RequestContext, Role
from app.ports.data_platform import DataPlatformAdapter
from app.services.context_builder import (
    ContextAsset,
    ContextBuildRequest,
    ContextPackageBuilder,
)
from app.services.context_gate import ContextGateRequest
from app.services.routing_service import RouteDecision


class FakeContextPolicyProvider:
    """Deterministic Wave 2 fixture. Replace it with the approved registry adapter."""

    def __init__(
        self,
        adapter: DataPlatformAdapter,
        *,
        active_context_releases: frozenset[str] = frozenset({"context-v1"}),
    ) -> None:
        self._adapter = adapter
        self._active_context_releases = active_context_releases
        self._builder = ContextPackageBuilder()

    def prepare(
        self,
        assets: list[dict[str, object]],
        context: RequestContext,
        decision: RouteDecision,
    ) -> ContextGateRequest:
        context_assets = tuple(self._context_asset(asset) for asset in assets)
        entitled_asset_urns = frozenset(asset.urn for asset in context_assets)
        package = self._builder.build(
            ContextBuildRequest(
                context_release="context-v1",
                policy_version="policy-v1",
                time_version="time-v1",
                entitlement_hash="fake-entitlement-v1",
                assets=context_assets,
                token_count=128,
                model_context_tokens=16_000,
            ),
            entitled_asset_urns,
        )
        valid_columns = {
            asset.urn: frozenset(asset.columns) for asset in context_assets
        }
        time_fields = {
            asset.urn: frozenset(
                column
                for column in asset.columns
                if column.endswith("_date") or column.endswith("_at")
            )
            for asset in context_assets
        }
        active_templates = (
            frozenset({decision.template_id})
            if decision.template_id is not None
            else frozenset()
        )
        return ContextGateRequest(
            package=package,
            role=context.role,
            allowed_roles=frozenset(Role),
            entitled_asset_urns=entitled_asset_urns,
            expected_entitlement_hash="fake-entitlement-v1",
            active_context_releases=self._active_context_releases,
            active_policy_versions=frozenset({"policy-v1"}),
            active_time_versions=frozenset({"time-v1"}),
            as_of=context.as_of,
            timezone=context.timezone,
            supported_timezones=frozenset({"Asia/Seoul"}),
            calendar="gregorian-kr",
            template_id=decision.template_id,
            active_template_ids=active_templates,
            normalized_question_ready=decision.template_id is None,
            valid_columns_by_urn=valid_columns,
            metric_id="reservation_count",
            active_metric_ids=frozenset({"reservation_count"}),
            time_field="check_in_date",
            valid_time_fields_by_urn=time_fields,
            dimension_history_valid=True,
            join_active=True,
        )

    def _context_asset(self, asset: dict[str, object]) -> ContextAsset:
        urn = str(asset["urn"])
        schema = self._adapter.get_asset_schema(urn)
        columns = tuple(str(column["name"]) for column in schema["columns"])
        return ContextAsset(
            urn=urn,
            fqn=str(asset["fqn"]),
            columns=columns,
        )
