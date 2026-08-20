"""런타임 메타데이터 조회 및 RuntimeContextPackage 빌드 서비스 모듈.

[핵심 목적]
DataPlatformAdapter(DataHub/Trino)를 통해:
1. 런타임 스키마 및 비즈니스 용어사전 조회
2. 차원 필터 값 실데이터 검증 및 주입 (Filter Value Resolution)
3. 반개방 구간(Half-Open Range) 시간 파라미터 바인딩 생성 및 데이터 기준일(Cutoff) 초과 검사
4. ContextPackage 생성 후 런타임 계약(`runtime_contracts`)과 조인 그래프를 결합한 최종 `RuntimeContextPackage` 반환
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime
from typing import Any

from app.contracts import AnalysisRequest, RequestContext
from app.ports.data_platform import DataPlatformAdapter
from app.services.context.builder import (
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
from app.services.context.contract import (
    RuntimeContextPackage,
    enrich_context_package,
)
from app.services.context.filter_value_resolver import (
    FilterValueUnresolvedError,
    ResolvedFilterValue,
    resolve_filter_value,
)
from app.services.context.runtime_contracts import (
    build_runtime_contracts,
    comparison_time_parameter_names,
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


def _inject_turn_filters(
    assets: list[dict[str, object]],
    turn_filters: list[ResolvedFilterValue],
) -> list[dict[str, object]]:
    """실제 Trino DB 조회를 통해 검증된 turn 필터를 대상 테이블의 지표 required_filters에 병합합니다."""
    if not turn_filters:
        return assets
    updated: list[dict[str, object]] = []
    for asset in assets:
        asset_copy = dict(asset)
        metrics = asset_copy.get("metrics")
        if isinstance(metrics, (list, tuple)):
            new_metrics = []
            for metric in metrics:
                if not isinstance(metric, dict):
                    new_metrics.append(metric)
                    continue
                metric_copy = dict(metric)
                # ratio는 물리 필드가 없는 계산 계약이며 required_filters가 항상 비어 있어야
                # 한다. 같은 asset의 분자·분모 column metric에 적용된 WHERE 조건이 두
                # operand의 범위를 함께 제한하므로 ratio 자체에 필터를 복제하지 않는다.
                if str(metric_copy.get("aggregation") or "").casefold() == "ratio":
                    new_metrics.append(metric_copy)
                    continue
                required = list(metric_copy.get("required_filters") or ())
                for index, turn_filter in enumerate(turn_filters):
                    if turn_filter.asset_fqn != str(asset_copy.get("fqn", "")):
                        continue
                    required.append(
                        {
                            "field": turn_filter.column,
                            "operator": turn_filter.operator,
                            "value": turn_filter.value,
                            "value_type": "string",
                            "parameter": f"user_filter_{index}",
                        }
                    )
                metric_copy["required_filters"] = required
                new_metrics.append(metric_copy)
            asset_copy["metrics"] = new_metrics
        updated.append(asset_copy)
    return updated


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
        numerator_metric_id=str(item.get("numerator_metric_id") or ""),
        denominator_metric_id=str(item.get("denominator_metric_id") or ""),
        zero_policy=str(item.get("zero_policy") or ""),
        visibility=str(item.get("visibility") or "BUSINESS"),
        governance_version=str(item.get("governance_version") or ""),
        allowed_roles=tuple(map(str, item.get("allowed_roles", ()))),
        contains_pii=item.get("contains_pii") is True,
        allowed_join_ids=tuple(map(str, item.get("allowed_join_ids", ()))),
        join_required=item.get("join_required") is True,
        query_strategies=tuple(map(str, item.get("query_strategies", ()))),
    )


class PipelineContextService:
    """파이프라인 컨텍스트 구축 서비스 클래스."""

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
        """선택된 자산 메타데이터로부터 실행 컨텍스트 스냅샷인 RuntimeContextPackage를 생성합니다."""
        # 1. 대상 자산들의 스키마를 DataPlatformAdapter로부터 병렬/순차 조회
        schemas: dict[str, dict[str, Any]] = {}
        for asset in assets:
            urn = str(asset["urn"])
            if urn not in schemas:
                schemas[urn] = await self._adapter.get_asset_schema(urn)
        validated_schemas = {
            urn: schema_columns(schema) for urn, schema in schemas.items()
        }

        # 2. 필터 값 실데이터 확인 및 주입 (Filter Value Resolution)
        filter_fields = (
            structured_request.get("filter_fields")
            if isinstance(structured_request, dict)
            else None
        )
        if isinstance(filter_fields, list) and filter_fields:
            fqn_to_urn = {str(asset["fqn"]): str(asset["urn"]) for asset in assets}
            resolved_turn_filters: list[ResolvedFilterValue] = []
            for item in filter_fields:
                if not isinstance(item, dict):
                    continue
                asset_fqn = str(item.get("asset_fqn", ""))
                column = str(item.get("column", ""))
                operator = str(item.get("operator", ""))
                value_text = str(item.get("value_text", ""))
                urn = fqn_to_urn.get(asset_fqn)
                if (
                    urn is None
                    or operator not in {"eq", "neq"}
                    or not value_text
                    or column not in {c["name"] for c in validated_schemas[urn]}
                ):
                    raise ContextBuildError(
                        ContextBuildErrorCode.INVALID_METADATA,
                        "요청한 필터가 승인된 asset·column 범위를 벗어났습니다.",
                    )
                try:
                    resolved_turn_filters.append(
                        await resolve_filter_value(
                            self._adapter, asset_fqn, column, operator, value_text
                        )
                    )
                except FilterValueUnresolvedError as error:
                    raise ContextBuildError(
                        ContextBuildErrorCode.FILTER_VALUE_NOT_FOUND,
                        str(error),
                    ) from error
            assets = _inject_turn_filters(assets, resolved_turn_filters)

        # 3. ContextAsset 객체 튜플 조립
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

        # 4. 시간 파라미터 및 비교 윈도우 계산
        start_parameter, end_parameter = time_parameter_names(assets)
        comparison_names = comparison_time_parameter_names(assets)
        relationship = (
            structured_request.get("period_relationship")
            if isinstance(structured_request, dict)
            else None
        )
        is_comparison_request = relationship == "comparison"
        if is_comparison_request and comparison_names is None:
            raise ContextBuildError(
                ContextBuildErrorCode.INVALID_METADATA,
                "선택된 자산들이 거버넌스 비교 윈도우를 지원하지 않습니다.",
            )
        comparison_start, comparison_end = comparison_names or ("", "")
        window_names = (start_parameter, end_parameter, comparison_start, comparison_end)
        period_values = {
            name: payload.parameters[name]
            for name in window_names
            if name and name in payload.parameters
        }
        if not period_values and structured_request is not None:
            candidates = structured_request.get("period_candidates")
            expected_count = 2 if is_comparison_request else 1
            if not isinstance(candidates, list) or len(candidates) != expected_count:
                raise ContextBuildError(
                    ContextBuildErrorCode.PERIOD_REQUIRED,
                    "기간 비교 분석은 정확히 2개의 기간 범위를 요구합니다."
                    if is_comparison_request
                    else "분석 기간은 정확히 1개의 기간 범위로 해석되어야 합니다.",
                    _period_suggestions(candidates),
                )
            windows = [(start_parameter, end_parameter, candidates[0])]
            if is_comparison_request:
                windows.append((comparison_start, comparison_end, candidates[1]))
            period_values = {}
            for window_start, window_end, candidate in windows:
                if not isinstance(candidate, dict):
                    raise ContextBuildError(
                        ContextBuildErrorCode.INVALID_METADATA,
                        "Node1 기간 후보 항목은 객체여야 합니다.",
                    )
                try:
                    period_values[window_start] = datetime.fromisoformat(
                        str(candidate["start"])
                    ).date().isoformat()
                    period_values[window_end] = datetime.fromisoformat(
                        str(candidate["end_exclusive"])
                    ).date().isoformat()
                except (KeyError, ValueError) as error:
                    raise ContextBuildError(
                        ContextBuildErrorCode.INVALID_METADATA,
                        "Node1 기간 후보가 올바른 ISO 날짜-시간 형식이 아닙니다.",
                    ) from error
        expected_names = {start_parameter, end_parameter}
        if is_comparison_request:
            expected_names |= {comparison_start, comparison_end}
        if period_values and set(period_values) != expected_names:
            raise ContextBuildError(
                ContextBuildErrorCode.INVALID_METADATA,
                "분석 기간은 시작과 종료 경계값을 모두 포함해야 합니다.",
            )
        window_pairs = [(start_parameter, end_parameter)]
        if is_comparison_request:
            window_pairs.append((comparison_start, comparison_end))
        for window_start, window_end in window_pairs:
            if not period_values:
                continue
            start_date = date.fromisoformat(period_values[window_start])
            end_date = date.fromisoformat(period_values[window_end])
            if start_date >= context.as_of:
                raise ContextBuildError(
                    ContextBuildErrorCode.OUT_OF_DATA_RANGE,
                    "요청 기간은 오늘 이전의 완료된 영업일을 포함해야 합니다.",
                )
            if end_date > context.as_of:
                period_values[window_end] = context.as_of.isoformat()
                end_date = context.as_of
            if start_date >= end_date:
                raise ContextBuildError(
                    ContextBuildErrorCode.INVALID_METADATA,
                    "분석 기간은 비어있지 않은 반개구간 [start, end) 이어야 합니다.",
                )
        period_bindings = tuple(
            ContextParameterBinding(name, "date", period_values[name])
            for name in window_names
            if name and name in period_values
        )
        governed_filters = filter_parameter_bindings(assets)
        parameter_bindings = (
            *period_bindings,
            *governed_filters,
        )

        # 5. 릴리즈, 정책 버전 및 Cutoff 일자 무결성 검증
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
                "런타임 자산들은 동일한 release 및 policy 버전을 공유해야 합니다.",
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
                "런타임 증거 기준일(evidence cutoff)이 유효하지 않습니다.",
            ) from error
        if evidence_cutoff is not None and period_values:
            for window_start, _window_end in window_pairs:
                if window_start not in period_values:
                    continue
                if date.fromisoformat(period_values[window_start]) > evidence_cutoff:
                    raise ContextBuildError(
                        ContextBuildErrorCode.OUT_OF_DATA_RANGE,
                        f"요청한 기간은 데이터 기준일({evidence_cutoff.isoformat()}) 이후라 아직 데이터가 없습니다.",
                    )

        # 6. 용어사전(Glossary Term) 조회 및 ContextPackage 생성
        metric_ids = tuple(
            dict.fromkeys(metric.id for asset in items for metric in asset.metrics)
        )
        business_metric_ids = tuple(
            dict.fromkeys(
                metric.id
                for asset in items
                for metric in asset.metrics
                if metric.visibility == "BUSINESS"
            )
        )
        if not metric_ids:
            raise ContextBuildError(
                ContextBuildErrorCode.INVALID_METRIC,
                "컨텍스트에는 최소 1개 이상의 해결된 지표가 포함되어야 합니다.",
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
        if isinstance(single_term, dict) and len(business_metric_ids) == 1:
            term_payloads = {business_metric_ids[0]: single_term}
        if not isinstance(term_payloads, dict):
            term_payloads = await self._adapter.get_metric_terms(business_metric_ids)
        if set(term_payloads) != set(business_metric_ids) or any(
            not isinstance(term_payloads.get(metric_id), dict)
            for metric_id in business_metric_ids
        ):
            raise ContextBuildError(
                ContextBuildErrorCode.INVALID_METRIC,
                "해결된 지표에 대한 DataHub Glossary Term 정의가 불완전합니다.",
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
                for metric_id in business_metric_ids
            ),
        )
        package = self._context_builder.build(
            request,
            frozenset(item.urn for item in items),
        )

        # 7. 런타임 계약 및 조인 그래프 결합 후 최종 반환
        runtime_contracts, joins = build_runtime_contracts(
            package,
            assets,
            schemas,
            context,
        )
        return enrich_context_package(package, runtime_contracts, joins)
