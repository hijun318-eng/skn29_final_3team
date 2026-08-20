"""파이프라인 단계(Stages)별 공통 서비스 연동 파사드(PipelineSupport) 모듈.

[핵심 목적]
개별 파이프라인 단계(ContextStage, PlanStage, QueryStage, ResultStage)에서 필요로 하는:
- MetricResolver & PipelineContextService를 통한 컨텍스트 빌드
- validate_plan & apply_guard_decision을 통한 G2 SQL 가드 검증 및 복구 힌트 생성
- PipelineResultValidator를 통한 G3 결과 검증, 쿼리 capability 토큰 및 아티팩트 ID 발급
을 단일 파사드 인터페이스로 캡슐화하여 제공합니다.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from app.contracts import AnalysisRequest, PeriodEvidence, RequestContext, SourceReference
from app.ports.data_platform import DataPlatformAdapter
from app.services.context.builder import ContextPackage, ContextPackageBuilder
from app.services.context.service import PipelineContextService
from app.services.context.metric_resolver import MetricResolver
from app.services.analysis.result_validator import PipelineResultValidator
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
        assets: list[dict[str, object]],
    ) -> tuple[list[dict[str, object]], str, dict[str, object]]:
        """질문과 자산 메타데이터를 대조하여 단일 지표 및 구조화 요청 객체를 확정합니다."""
        return await self._resolver.resolve(payload, context, assets)

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

    def g2_repair_hint(self, violation: str, package: ContextPackage) -> str:
        """G2 위반 발생 시 모델 재작성을 유도하기 위한 구체적인 수리 힌트를 생성합니다."""
        contracts = getattr(package, "runtime_contracts", None)
        if not isinstance(contracts, dict):
            raise ValueError("수리 힌트 생성을 위해 Runtime Context 계약이 필요합니다.")
        detail = self._guard_details.get(violation, "후보 계획이 G2 규칙을 위반했습니다.")
        return (
            f"constraint={violation}; detail={detail}; rebuild the invalid AST subtree "
            "only from schema_context, metric_rules, join_graph, time_rules, "
            "parameter_contract, and query_policy"
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
