"""파이프라인 단계(Stages)별 공통 서비스 연동 파사드(PipelineSupport) 모듈.

[핵심 목적]
개별 파이프라인 단계(ContextStage, PlanStage, QueryStage, ResultStage)에서 필요로 하는:
- MetricResolver & PipelineContextService를 통한 컨텍스트 빌드
- validate_plan & apply_guard_decision을 통한 G2 SQL 가드 검증 및 복구 힌트 생성
- PipelineResultValidator를 통한 G3 결과 검증, 쿼리 capability 토큰 및 아티팩트 ID 발급
을 단일 파사드 인터페이스로 캡슐화하여 제공합니다.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any

from app.contracts import AnalysisRequest, PeriodEvidence, RequestContext, SourceReference
from app.ports.data_platform import (
    AssetCandidateSet,
    DataPlatformAdapter,
    ExecutionAssetSelection,
    GovernedFieldReference,
    UnsupportedSemanticError,
)
from app.services.context.builder import (
    ContextPackage,
    ContextPackageBuilder,
)
from app.services.context.metric_execution_scope import select_assets_for_metrics
from app.services.context.service import PipelineContextService
from app.services.context.metric_resolver import MetricResolver
from app.services.analysis.result_validator import PipelineResultValidator
from app.services.analysis.logical_plan import AnalysisPlan, build_analysis_plan
from app.services.analysis.semantic_request import ApprovedSemanticRequestSnapshot
from app.services.analysis.typed_sql_compiler import compile_typed_sql
from app.services.sql_guard.guard import apply_guard_decision, validate_plan


class PipelineSupport:
    """파이프라인 실행 단계들에 도메인 로직 및 거버넌스 가드를 제공하는 파사드 클래스."""

    MAX_RESULT_ROWS = PipelineResultValidator.MAX_RESULT_ROWS
    MAX_RESULT_COLUMNS = PipelineResultValidator.MAX_RESULT_COLUMNS
    MAX_RESULT_CELLS = PipelineResultValidator.MAX_RESULT_CELLS

    def __init__(
        self,
        adapter: DataPlatformAdapter,
        context_builder: ContextPackageBuilder,
        model: object | None = None,
    ) -> None:
        self._adapter = adapter
        self._resolver = MetricResolver(adapter, model)
        self._context = PipelineContextService(adapter, context_builder)
        self._results = PipelineResultValidator()
        self._guard_details: dict[str, str] = {}

    async def build_context(
        self,
        payload: AnalysisRequest,
        context: RequestContext,
        assets: list[dict[str, object]],
        structured_request: dict[str, object] | None = None,
    ) -> ContextPackage:
        """분석 요청과 권한 자산 목록으로부터 불변 ContextPackage를 빌드합니다."""
        return await self._context.build(payload, context, assets, structured_request)

    async def select_metric(
        self,
        payload: AnalysisRequest,
        context: RequestContext,
        candidates: AssetCandidateSet,
        *,
        budget: Any = None,
    ) -> tuple[list[dict[str, object]], str, dict[str, object]]:
        """질문과 자산 메타데이터를 대조하여 단일 지표 및 구조화 요청 객체를 확정합니다."""
        if (
            candidates.product_release_id is None
            or candidates.runtime_projection_checksum is None
        ):
            from app.ports.data_platform import MetadataUnavailableError

            raise MetadataUnavailableError(
                "Node1 grounding requires an active RuntimeCatalogProjection receipt"
            )
        return await self._resolver.resolve(
            payload,
            context,
            list(candidates.assets),
            candidate_set=candidates,
            budget=budget,
        )

    async def resolve_execution_assets(
        self,
        payload: AnalysisRequest,
        context: RequestContext,
        candidates: AssetCandidateSet,
        structured_request: dict[str, object],
    ) -> list[dict[str, object]]:
        """Node 1 선택을 후보 payload가 아닌 동일 active release 전체에서 다시 해결한다."""

        raw_execution_ids = structured_request.get("metric_ids")
        raw_output_ids = structured_request.get("selected_metric_ids")
        if (
            not isinstance(raw_execution_ids, list)
            or not isinstance(raw_output_ids, list)
            or any(not isinstance(item, str) for item in raw_execution_ids)
            or any(not isinstance(item, str) for item in raw_output_ids)
        ):
            raise UnsupportedSemanticError(
                "실행 자산 재해결에 필요한 Metric 선택이 불완전합니다.",
            )
        field_references: set[GovernedFieldReference] = set()
        for key in ("dimension_fields", "filter_fields"):
            raw_fields = structured_request.get(key) or []
            if not isinstance(raw_fields, list):
                raise UnsupportedSemanticError(
                    "실행 자산 재해결에 필요한 필드 선택이 유효하지 않습니다.",
                )
            for item in raw_fields:
                if (
                    not isinstance(item, dict)
                    or not isinstance(item.get("asset_fqn"), str)
                    or not isinstance(item.get("column"), str)
                ):
                    raise UnsupportedSemanticError(
                        "실행 필드 참조는 asset과 column을 포함해야 합니다.",
                    )
                try:
                    field_references.add(
                        GovernedFieldReference(
                            asset_fqn=item["asset_fqn"],
                            column=item["column"],
                        )
                    )
                except ValueError as error:
                    raise UnsupportedSemanticError(
                        "실행 필드 참조가 active release 형식과 맞지 않습니다.",
                    ) from error
        try:
            selection = ExecutionAssetSelection(
                output_metric_ids=tuple(raw_output_ids),
                execution_metric_ids=tuple(raw_execution_ids),
                field_references=tuple(sorted(field_references)),
                receipt_context_release=candidates.context_release,
                receipt_catalog_checksum=candidates.catalog_checksum,
                receipt_canonical_checksum=candidates.canonical_checksum,
                receipt_product_release_id=candidates.product_release_id,
                receipt_runtime_projection_checksum=(
                    candidates.runtime_projection_checksum
                ),
            )
        except ValueError as error:
            raise UnsupportedSemanticError(
                "실행 자산 선택과 candidate release receipt가 유효하지 않습니다.",
            ) from error
        resolved = await self._adapter.resolve_execution_assets(
            selection,
            {
                **context.model_dump(mode="json"),
                "parameters": payload.parameters,
            },
        )
        return select_assets_for_metrics(
            resolved,
            set(selection.execution_metric_ids),
            None,
        )

    async def resolve_snapshot_execution_assets(
        self,
        payload: object,
        context: RequestContext,
        snapshot: ApprovedSemanticRequestSnapshot,
    ) -> list[dict[str, object]]:
        """원문 검색 없이 승인 plan의 ID·필드를 같은 release와 현재 권한에 재결속한다."""

        plan = snapshot.analysis_plan
        field_references: set[GovernedFieldReference] = set()
        # 신규 실행과 같은 QueryGovernance selection 계약을 유지한다. time field는
        # business dimension이 아니며, 선택 Metric의 governed time 계약과 아래
        # current Context에서 AnalysisPlan을 재빌드할 때 별도로 검증된다.
        for key in ("dimension_fields", "filter_fields"):
            for item in plan[key]:
                field_references.add(
                    GovernedFieldReference(
                        asset_fqn=str(item["asset_fqn"]),
                        column=str(item["column"]),
                    )
                )
        receipt = snapshot.release_receipt
        try:
            selection = ExecutionAssetSelection(
                output_metric_ids=tuple(plan["output_metric_ids"]),
                execution_metric_ids=tuple(plan["dependency_metric_ids"]),
                field_references=tuple(sorted(field_references)),
                receipt_context_release=receipt.context_release,
                receipt_catalog_checksum=receipt.catalog_checksum,
                receipt_canonical_checksum=receipt.canonical_checksum,
                receipt_product_release_id=receipt.product_release_id,
                receipt_runtime_projection_checksum=(
                    receipt.runtime_projection_checksum
                ),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise UnsupportedSemanticError(
                "승인 Semantic Request의 실행 자산 계약이 유효하지 않습니다."
            ) from error
        resolved = await self._adapter.resolve_execution_assets(
            selection,
            {
                **context.model_dump(mode="json"),
                "parameters": dict(getattr(payload, "parameters", {})),
            },
        )
        return select_assets_for_metrics(
            resolved,
            set(selection.execution_metric_ids),
            None,
        )

    def g2_violation(
        self,
        plan: dict[str, object],
        package: ContextPackage,
    ) -> str | None:
        """모델이 생성한 SQL 계획을 AST 가드로 검증하고 위반 코드를 반환합니다 (통과 시 None)."""
        decision = validate_plan(plan, package)
        if decision.violation:
            self._guard_details[decision.violation] = decision.detail
            return decision.violation
        apply_guard_decision(plan, decision)
        return None

    @staticmethod
    def analysis_plan(
        structured_request: dict[str, object],
        package: ContextPackage,
    ) -> AnalysisPlan:
        """검증된 구조화 슬롯과 Runtime Context를 버전형 논리 분석 계획으로 컴파일합니다."""

        return build_analysis_plan(structured_request, package)

    @staticmethod
    def typed_sql_plan(
        analysis_plan: AnalysisPlan,
        package: ContextPackage,
    ) -> dict[str, object] | None:
        """지원되는 단일 Serving View 계획을 결정론적 SQL 후보로 컴파일합니다."""

        return compile_typed_sql(analysis_plan, package)

    def g2_repair_hint(self, violation: str, package: ContextPackage) -> str:
        """G2 위반 발생 시 모델 재작성을 유도하기 위한 구체적인 수리 힌트를 생성합니다."""
        contracts = getattr(package, "runtime_contracts", None)
        if not isinstance(contracts, dict):
            raise ValueError("수리 힌트 생성을 위해 Runtime Context 계약이 필요합니다.")
        detail = self._guard_details.get(violation, "후보 계획이 G2 규칙을 위반했습니다.")
        approved_contract = self._g2_repair_contract_summary(contracts)
        return (
            f"constraint={violation}; detail={detail}; rebuild the invalid AST subtree "
            "only from schema_context, metric_rules, join_graph, time_rules, "
            "parameter_contract, and query_policy; use these exact governed names: "
            f"{approved_contract}"
        )

    @staticmethod
    def _g2_repair_contract_summary(contracts: dict[str, Any]) -> str:
        """모델 수리에 필요한 승인 이름만 Runtime Context에서 결정론적으로 추출합니다."""

        schema_context = contracts.get("schema_context")
        assets = schema_context.get("assets") if isinstance(schema_context, dict) else None
        approved_assets = sorted(
            {
                str(item["fqn"])
                for item in assets or ()
                if isinstance(item, dict) and str(item.get("fqn") or "")
            }
        )

        metric_rules = contracts.get("metric_rules")
        expected_result_fields = sorted(
            {
                str(item["result_field"])
                for item in metric_rules or ()
                if isinstance(item, dict) and str(item.get("result_field") or "")
            }
        )

        parameter_contract = contracts.get("parameter_contract")
        parameters = (
            parameter_contract.get("parameters")
            if isinstance(parameter_contract, dict)
            else None
        )
        allowed_parameters = sorted(
            {
                f":{item['name']}"
                for item in parameters or ()
                if isinstance(item, dict) and str(item.get("name") or "")
            }
        )

        time_rules = contracts.get("time_rules")
        time_fields = time_rules.get("fields") if isinstance(time_rules, dict) else None
        approved_time_fields = sorted(
            {
                f"{field['asset_fqn']}.{field['column']}"
                for item in time_fields or ()
                if isinstance(item, dict)
                and isinstance((field := item.get("field")), dict)
                and str(field.get("asset_fqn") or "")
                and str(field.get("column") or "")
            }
        )

        return json.dumps(
            {
                "allowed_parameters": allowed_parameters,
                "approved_assets": approved_assets,
                "approved_time_fields": approved_time_fields,
                "expected_result_fields": expected_result_fields,
            },
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )

    @staticmethod
    def model_plan_violation(plan: object) -> str | None:
        """모델 응답 봉투(Plan Envelope)의 필수 스키마 구조를 정적 검증합니다."""
        if not isinstance(plan, dict):
            return "MODEL_SCHEMA_INVALID"
        if not isinstance(plan.get("sql"), str) or not plan["sql"].strip():
            return "MODEL_SCHEMA_INVALID"
        if not isinstance(plan.get("model_version"), str):
            return "MODEL_SCHEMA_INVALID"
        declarations = (
            "declared_assets",
            "declared_columns",
            "declared_joins",
            "declared_metrics",
        )
        present = [name in plan for name in declarations]
        if any(present) and (
            not all(present)
            or any(not isinstance(plan[name], list) for name in declarations)
        ):
            return "MODEL_SCHEMA_INVALID"
        if "references" in plan and not isinstance(plan["references"], list):
            return "MODEL_SCHEMA_INVALID"
        if "parameters" in plan and not isinstance(plan["parameters"], dict):
            return "MODEL_SCHEMA_INVALID"
        return None

    def g3_violation(
        self,
        query: dict[str, object],
        plan: dict[str, object],
        package: ContextPackage,
    ) -> str | None:
        """실행 결과의 G3 거버넌스 위반 여부를 검증합니다."""
        return self._results.g3_violation(query, plan, package)

    def normalize_empty_aggregate(
        self,
        query: dict[str, object],
        package: ContextPackage,
    ) -> dict[str, object]:
        """빈 집계 결과를 정규화합니다."""
        return self._results.normalize_empty_aggregate(query, package)

    def period(
        self,
        _as_of: date,
        package: ContextPackage | None = None,
    ) -> PeriodEvidence:
        """ContextPackage로부터 PeriodEvidence 객체를 반환합니다."""
        if package is None:
            raise ValueError("기간 증거 데이터 생성을 위해 Runtime Context가 필요합니다.")
        return self._results.period(package)

    def gate_token(self, package: ContextPackage, sql: str) -> str:
        """쿼리 실행 capability 토큰을 발급합니다."""
        return self._results.gate_token(package, sql)

    def artifact_id(self, request_id: str, query_id: str, context_hash: str):
        """결정론적 아티팩트 UUID를 발급합니다."""
        return self._results.artifact_id(request_id, query_id, context_hash)

    def sources(
        self,
        assets: list[dict[str, object]],
    ) -> tuple[SourceReference, ...]:
        """자산 목록으로부터 SourceReference 튜플을 생성합니다."""
        return self._results.sources(assets)

    def execution_evidence(self, package: ContextPackage) -> dict[str, dict[str, object]]:
        """실행 파라미터 증거를 반환합니다."""
        return self._results.execution_evidence(package)

    _result_value_type = staticmethod(PipelineResultValidator.result_value_type)
    _result_metadata = PipelineResultValidator.result_metadata
