"""adapter에서 조회한 schema·glossary와 구조화 기간을 공유 release·policy로 검증해 bounded RuntimeContextPackage를 만들며 로컬 metadata 기본값은 허용하지 않는다."""

from __future__ import annotations

import hashlib
from datetime import date, datetime
from typing import Any

from app.contracts import AnalysisRequest, RequestContext
from app.ports.data_platform import DataPlatformAdapter
from app.services.context_builder import (
    ContextAsset,
    ContextBuildError,
    ContextBuildErrorCode,
    ContextBuildRequest,
    ContextMetric,
    ContextMetricTerm,
    ContextPackage,
    ContextPackageBuilder,
    ContextParameterBinding,
    ContextRequiredFilter,
)
from app.services.pipeline_context_contract import (
    RuntimeContextPackage,
    enrich_context_package,
)
from app.services.pipeline_runtime_contracts import (
    build_runtime_contracts,
    filter_parameter_bindings,
    schema_columns,
    time_parameter_names,
)
from src.modelops.runtime import estimate_token_count


def _period_suggestions(candidates: object) -> tuple[str, ...]:
    if not isinstance(candidates, (list, tuple)):
        return ()
    return tuple(
        str(candidate["source_text"])
        for candidate in candidates
        if isinstance(candidate, dict)
        and isinstance(candidate.get("source_text"), str)
    )


def _required_filter(item: dict[str, Any]) -> ContextRequiredFilter:
    return ContextRequiredFilter(
        field=str(item["field"]),
        operator=str(item["operator"]),
        value=item["value"],
        value_type=str(item.get("value_type") or ""),
    )


def _metric(item: dict[str, Any]) -> ContextMetric:
    return ContextMetric(
        id=str(item["id"]),
        asset_fqn=str(item["asset_fqn"]),
        field=str(item["field"]),
        aggregation=str(item["aggregation"]),
        time_field=str(item["time_field"]),
        required_filters=tuple(
            _required_filter(value) for value in item.get("required_filters", ())
        ),
        result_field=str(item.get("result_field") or item["id"]),
        unit=str(item.get("unit") or ""),
        reduction=str(item.get("reduction") or ""),
    )


class PipelineContextService:
    """PipelineContextService는 파이프라인 컨텍스트 서비스에서 build 흐름과 선행 도메인 검증 순서를 조정한다."""
    def __init__(
        self,
        adapter: DataPlatformAdapter,
        context_builder: ContextPackageBuilder,
    ) -> None:
        self._adapter = adapter
        self._context_builder = context_builder

    async def build(
        self,
        payload: AnalysisRequest,
        context: RequestContext,
        assets: list[dict[str, object]],
        structured_request: dict[str, object] | None = None,
    ) -> RuntimeContextPackage:
        """선택 asset의 runtime schema와 DataHub metric term을 조회해 실행 context를 만든다.

        구조화 기간을 half-open binding으로 바꾸고 모든 asset의 release·policy·제품 증거가
        일치하는지 검증한다. 누락·모호성·schema drift는 ``ContextBuildError``로 닫으며,
        성공 시 SQL guard가 사용할 schema·metric·join·time·parameter 계약까지 포함한다.
        """
        schemas: dict[str, dict[str, Any]] = {}
        for asset in assets:
            urn = str(asset["urn"])
            if urn not in schemas:
                schemas[urn] = await self._adapter.get_asset_schema(urn)
        validated_schemas = {
            urn: schema_columns(schema) for urn, schema in schemas.items()
        }
        items = tuple(
            ContextAsset(
                urn=str(asset["urn"]),
                fqn=str(asset["fqn"]),
                columns=tuple(
                    str(column["name"])
                    for column in validated_schemas[str(asset["urn"])]
                ),
                join_ids=tuple(map(str, asset.get("join_ids", ()))),
                metrics=tuple(
                    _metric(metric)
                    for metric in asset.get("metrics", ())
                    if isinstance(metric, dict)
                ),
                metric_registry_required=True,
                required_filters=tuple(
                    _required_filter(item)
                    for item in asset.get("required_filters", ())
                    if isinstance(item, dict)
                ),
                column_types=tuple(
                    (str(column["name"]), str(column["native_type"]))
                    for column in validated_schemas[str(asset["urn"])]
                ),
            )
            for asset in assets
        )
        start_parameter, end_parameter = time_parameter_names(assets)
        period_values = {
            name: payload.parameters[name]
            for name in (start_parameter, end_parameter)
            if name in payload.parameters
        }
        if not period_values and structured_request is not None:
            candidates = structured_request.get("period_candidates")
            if not isinstance(candidates, list) or len(candidates) != 1:
                raise ContextBuildError(
                    ContextBuildErrorCode.PERIOD_REQUIRED,
                    "The analysis period must resolve to one range.",
                    _period_suggestions(candidates),
                )
            candidate = candidates[0]
            if not isinstance(candidate, dict):
                raise ContextBuildError(
                    ContextBuildErrorCode.INVALID_METADATA,
                    "Node1 period candidate must be an object.",
                )
            try:
                period_values = {
                    start_parameter: datetime.fromisoformat(
                        str(candidate["start"])
                    ).date().isoformat(),
                    end_parameter: datetime.fromisoformat(
                        str(candidate["end_exclusive"])
                    ).date().isoformat(),
                }
            except (KeyError, ValueError) as error:
                raise ContextBuildError(
                    ContextBuildErrorCode.INVALID_METADATA,
                    "Node1 period candidate is not an ISO date-time range.",
                ) from error
        if period_values and set(period_values) != {start_parameter, end_parameter}:
            raise ContextBuildError(
                ContextBuildErrorCode.INVALID_METADATA,
                "Analysis period requires both range boundaries.",
            )
        if (
            period_values
            and period_values[start_parameter] >= period_values[end_parameter]
        ):
            raise ContextBuildError(
                ContextBuildErrorCode.INVALID_METADATA,
                "Analysis period must be a non-empty half-open range.",
            )
        period_bindings = tuple(
            ContextParameterBinding(name, "date", period_values[name])
            for name in (start_parameter, end_parameter)
            if name in period_values
        )
        governed_filters = filter_parameter_bindings(assets)
        parameter_bindings = (
            *period_bindings,
            *governed_filters,
        )
        releases = {str(asset.get("context_release") or "") for asset in assets}
        policies = {str(asset.get("policy_version") or "") for asset in assets}
        product_releases = {
            str(asset["product_release_id"])
            for asset in assets
            if asset.get("product_release_id")
        }
        evidence_cutoffs = {
            str(asset["evidence_cutoff"])
            for asset in assets
            if asset.get("evidence_cutoff")
        }
        if (
            len(releases) != 1
            or not next(iter(releases), "")
            or len(policies) != 1
            or not next(iter(policies), "")
            or len(product_releases) > 1
            or len(evidence_cutoffs) > 1
            or bool(product_releases) != bool(evidence_cutoffs)
        ):
            raise ContextBuildError(
                ContextBuildErrorCode.INVALID_METADATA,
                "Runtime assets must share one release and policy version.",
            )
        try:
            evidence_cutoff = (
                date.fromisoformat(next(iter(evidence_cutoffs)))
                if evidence_cutoffs
                else None
            )
        except ValueError as error:
            raise ContextBuildError(
                ContextBuildErrorCode.INVALID_METADATA,
                "Runtime evidence cutoff is invalid.",
            ) from error
        metric_ids = tuple(dict.fromkeys(metric.id for asset in items for metric in asset.metrics))
        if not metric_ids:
            raise ContextBuildError(
                ContextBuildErrorCode.INVALID_METRIC,
                "Context must contain at least one resolved metric.",
            )
        term_payloads = (
            structured_request.get("metric_terms")
            if isinstance(structured_request, dict)
            else None
        )
        single_term = (
            structured_request.get("metric_term")
            if isinstance(structured_request, dict)
            else None
        )
        if isinstance(single_term, dict) and len(metric_ids) == 1:
            term_payloads = {metric_ids[0]: single_term}
        if not isinstance(term_payloads, dict):
            term_payloads = await self._adapter.get_metric_terms(metric_ids)
        if set(term_payloads) != set(metric_ids) or any(
            not isinstance(term_payloads.get(metric_id), dict)
            for metric_id in metric_ids
        ):
            raise ContextBuildError(
                ContextBuildErrorCode.INVALID_METRIC,
                "DataHub Glossary Terms are incomplete for the resolved metrics.",
            )
        request = ContextBuildRequest(
            context_release=next(iter(releases)),
            policy_version=next(iter(policies)),
            time_version=context.as_of.isoformat(),
            entitlement_hash=hashlib.sha256(
                f"{context.user_id}:{context.role.value}".encode()
            ).hexdigest(),
            assets=items,
            token_count=max(1, estimate_token_count(payload.question)),
            model_context_tokens=24_000,
            product_release_id=(next(iter(product_releases)) if product_releases else None),
            evidence_cutoff=evidence_cutoff,
            parameter_bindings=parameter_bindings,
            metric_terms=tuple(
                ContextMetricTerm(
                    id=str(term_payloads[metric_id]["id"]),
                    urn=str(term_payloads[metric_id]["urn"]),
                    label=str(term_payloads[metric_id]["label"]),
                    aliases=tuple(map(str, term_payloads[metric_id]["aliases"])),
                    definition=str(term_payloads[metric_id]["definition"]),
                    unit=str(term_payloads[metric_id]["unit"]),
                    version=str(term_payloads[metric_id]["version"]),
                    checksum=str(term_payloads[metric_id]["checksum"]),
                )
                for metric_id in metric_ids
            ),
        )
        package = self._context_builder.build(
            request,
            frozenset(item.urn for item in items),
        )
        runtime_contracts, joins = build_runtime_contracts(
            package,
            assets,
            schemas,
            context,
        )
        return enrich_context_package(package, runtime_contracts, joins)
