"""동적 metric/context 해석과 G2 SQL·G3 결과 검증을 stage에 일관되게 노출하고, 하드코딩 SQL이나 metadata fallback을 만들지 않는 facade다."""

from __future__ import annotations

from datetime import date
from typing import Any

from app.contracts import AnalysisRequest, PeriodEvidence, RequestContext, SourceReference
from app.ports.data_platform import DataPlatformAdapter
from app.services.context_builder import ContextPackage, ContextPackageBuilder
from app.services.pipeline_context_service import PipelineContextService
from app.services.pipeline_metric_resolver import MetricResolver
from app.services.pipeline_result_validator import PipelineResultValidator
from app.services.pipeline_sql_guard import apply_guard_decision, validate_plan


class PipelineSupport:
    """동적 context 구성, SQL governance, 결과 검증을 stage에 제공하는 얇은 facade다.

    adapter에서 발견한 metadata와 runtime package를 하위 서비스의 유일한 권위로 전달하고,
    G2 위반 detail만 요청 인스턴스에 보관한다. 계획·결과를 자체 생성하거나 기본 SQL로 보정하지 않는다.
    """
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
        """분석 요청·권한 context·해석된 asset을 동적 runtime package로 변환한다.

        schema와 glossary 조회, 기간 binding, release·policy 일치 및 크기 상한은 하위
        ``PipelineContextService``가 검증한다. 실패는 기본 metadata로 보정하지 않고
        ``ContextBuildError``로 그대로 전파한다.
        """
        return await self._context.build(payload, context, assets, structured_request)

    async def select_metric(
        self,
        payload: AnalysisRequest,
        context: RequestContext,
        assets: list[dict[str, object]],
    ) -> tuple[list[dict[str, object]], str, dict[str, object]]:
        """지표 후보를 거버넌스 제약과 입력 증거로 판정해 하나의 결과로 좁힌다."""
        return await self._resolver.resolve(payload, context, assets)

    def g2_violation(
        self,
        plan: dict[str, object],
        package: ContextPackage,
    ) -> str | None:
        """모델 계획을 SQLGlot·runtime 계약으로 검증하고 첫 G2 위반 code를 반환한다.

        실패 detail은 같은 facade의 repair hint용으로 보존한다. 통과한 경우에만 정규 SQL,
        바인딩된 실행 SQL, lineage 증거를 계획에 반영하고 ``None``을 반환한다.
        """
        decision = validate_plan(plan, package)
        if decision.violation:
            self._guard_details[decision.violation] = decision.detail
            return decision.violation
        apply_guard_decision(plan, decision)
        return None

    def g2_repair_hint(self, violation: str, package: ContextPackage) -> str:
        """직전 G2 위반과 runtime 계약 경계를 모델 재작성 지시문으로 제한한다.

        runtime 계약이 없으면 ``ValueError``로 중단하며, 특정 정답 SQL 대신 승인된 schema·
        metric·join·time·parameter·policy만 사용하도록 위반 detail을 반환한다.
        """
        contracts = getattr(package, "runtime_contracts", None)
        if not isinstance(contracts, dict):
            raise ValueError("Runtime Context contracts are required for repair")
        detail = self._guard_details.get(violation, "The candidate violated G2.")
        return (
            f"constraint={violation}; detail={detail}; rebuild the invalid AST subtree "
            "only from schema_context, metric_rules, join_graph, time_rules, "
            "parameter_contract, and query_policy"
        )

    @staticmethod
    def model_plan_violation(plan: object) -> str | None:
        """모델 계획 envelope의 필수 타입과 선택적 lineage 선언 형태를 검사한다.

        SQL 내용의 안전성은 G2가 담당하므로 여기서는 schema 오류에 ``MODEL_SCHEMA_INVALID``를
        반환하고, 선언이 구조적으로 완전할 때만 ``None``을 반환한다.
        """
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
        """실행 결과를 승인 AST와 context 증거에 대조해 G3 위반 code 또는 ``None``을 반환한다.

        검증 책임은 ``PipelineResultValidator``에 단일화해 facade와 직접 호출 경로가 같은 fail-closed 규칙을 쓴다.
        """
        return self._results.g3_violation(query, plan, package)

    def normalize_empty_aggregate(
        self,
        query: dict[str, object],
        package: ContextPackage,
    ) -> dict[str, object]:
        """empty aggregate 값을 비교와 해시에 사용할 수 있는 표준 형태로 정규화한다."""
        return self._results.normalize_empty_aggregate(query, package)

    def period(
        self,
        _as_of: date,
        package: ContextPackage | None = None,
    ) -> PeriodEvidence:
        """runtime package binding에서 기간 근거를 만들고 호출자의 기준일 추론은 사용하지 않는다.

        package가 없으면 ``ValueError``로 실패해 고정 날짜나 로컬 기본 기간으로 보정하지 않는다.
        """
        if package is None:
            raise ValueError("Runtime Context is required for period evidence")
        return self._results.period(package)

    def gate_token(self, package: ContextPackage, sql: str) -> str:
        """G2를 통과한 context hash와 SQL 조합의 실행 capability를 반환한다.

        실제 발급을 결과 검증기에 위임해 모든 파이프라인 경로가 동일한 token 알고리즘을 사용한다.
        """
        return self._results.gate_token(package, sql)

    def artifact_id(self, request_id: str, query_id: str, context_hash: str):
        """요청·query·context 조합을 결과 검증기의 결정론적 artifact UUID로 변환한다.

        같은 실행 재처리는 같은 ID를 얻고 어느 증거 식별자라도 바뀌면 별도 artifact가 된다.
        """
        return self._results.artifact_id(request_id, query_id, context_hash)

    def sources(
        self,
        assets: list[dict[str, object]],
    ) -> tuple[SourceReference, ...]:
        """동적으로 발견된 asset 목록을 release 정보가 보존된 typed lineage로 변환한다.

        malformed asset은 결과 검증기의 생성 오류를 그대로 전파해 불완전한 source 근거를 만들지 않는다.
        """
        return self._results.sources(assets)

    def execution_evidence(self, package: ContextPackage) -> dict[str, dict[str, object]]:
        """context의 governed time/filter binding을 실행 저장용 근거 payload로 반환한다.

        필수 binding 누락은 ``ValueError``로 전파하며 질문 문자열이나 adapter 결과로 대체하지 않는다.
        """
        return self._results.execution_evidence(package)

    _result_value_type = staticmethod(PipelineResultValidator.result_value_type)
    _result_metadata = PipelineResultValidator.result_metadata
