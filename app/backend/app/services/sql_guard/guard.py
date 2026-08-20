"""SQLGlot AST 기반의 SQL 보안 정책 및 거버넌스 가드(SQL Guard) 진입점 모듈.

[핵심 목적]
LLM(Node 2)이 생성한 원시 SQL 텍스트를 단일 SQLGlot AST로 파싱한 후,
1. 구문 및 보안 정책 검증 (SELECT 전용, LIMIT 강제, 단일 쿼리문, 금지 함수/카탈로그 차단)
2. 스키마/지표/조인/시간 조건 의미론적 검증 (Semantics Validation)
3. 파라미터 바인딩 (Named Parameter Binding)
을 일괄 수행하여, 안전성이 100% 입증된 정규 SQL(`canonical_sql`)과 실행 SQL(`executable_sql`) 또는
안전한 차단 결정(`GuardDecision`)을 산출합니다.

[Fail-Closed 원칙]
어느 한 단계라도 정책이나 스키마/지표 불변식을 위반하면 `executable_sql`을 비우고 오류 코드를 반환하여,
Trino 쿼리 엔진이나 백엔드 실행기로 진입하지 못하도록 즉각 차단합니다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.services.sql_guard.schema import (
    approved_assets,
    column_violation,
    declared_assets,
    declared_metrics,
)
from app.services.analysis.logical_plan import (
    AnalysisOperation,
    AnalysisPlanError,
    validate_analysis_plan_payload,
)
from app.services.sql_guard.scopes import projection_scope_evidence
from app.services.sql_guard.operation_semantics import operation_violation
from app.services.sql_guard.semantics import (
    join_violation,
    match_metric,
    references,
    required_filter_violation,
    time_rule_violation,
)
from src.ai.sql_binding import SqlBindingError, bind_sql_parameters
from src.ai.sql_policy import SqlValidationResult, validate_sql


@dataclass(frozen=True)
class SemanticDecision:
    """SQLGlot AST와 런타임 컨텍스트 간의 의미론적 대조 결과를 담는 데이터 클래스.

    Attributes:
        violation: 위반 발생 시 에러 코드 문자열 (성공 시 None)
        detail: 상세 위반 내용 설명
        references: 검증된 테이블/컬럼/조인/지표 리니지 참조 튜플
        ast_evidence: AST 정적 분석 메타데이터 증거 딕셔너리
    """

    violation: str | None
    detail: str
    references: tuple[dict[str, Any], ...] = ()
    ast_evidence: dict[str, Any] | None = None

    @property
    def ok(self) -> bool:
        """위반 사항 없이 성공했는지 여부를 반환합니다."""
        return self.violation is None


@dataclass(frozen=True)
class GuardDecision:
    """SQL 가드의 최종 검증 결과와 실행 가능 SQL을 캡슐화한 불변 데이터 클래스.

    Attributes:
        violation: 위반 발생 시 에러 코드 (성공 시 None)
        detail: 상세 오류 메시지
        canonical_sql: 표준화된 정규 SQL 텍스트
        executable_sql: 파라미터가 바인딩된 실제 실행 가능 SQL (위반 시 None)
        references: 검증된 데이터 리니지 증거 목록
        parameters: 바인딩된 파라미터 사전
        ast_evidence: AST 검증 증거 메타데이터
    """

    violation: str | None
    detail: str
    canonical_sql: str | None = None
    executable_sql: str | None = None
    references: tuple[dict[str, Any], ...] = ()
    parameters: dict[str, dict[str, Any]] | None = None
    ast_evidence: dict[str, Any] | None = None

    @property
    def ok(self) -> bool:
        """가드 검증을 완전히 통과했는지 여부를 반환합니다."""
        return self.violation is None


def validate_plan(plan: object, package: Any) -> GuardDecision:
    """생성된 모델 계획(Plan)의 SQL 텍스트를 AST 수준에서 엄격히 검증하고 GuardDecision을 생성합니다.

    [검증 4단계]
    1. 기본 구문 및 정적 정책 검증 (validate_sql): SELECT 단일문, LIMIT 범위, 읽기 전용 검사
    2. 세맨틱 의미론 검증 (validate_parsed_semantics): 카탈로그, 함수, 컬럼, 지표 수식, 조인, 필수 필터, 시간 조건 검사
    3. 파라미터 바인딩 (bind_sql_parameters): 런타임 값으로 typed named parameter 치환
    4. GuardDecision 반환 (성공 시 실행 가능 SQL 포함, 실패 시 차단 코드 반환)

    Args:
        plan: LLM이 생성한 SQL 계획 딕셔너리 (sql 키 포함)
        package: ContextPackage 인스턴스 (runtime_contracts, parameter_bindings 등 포함)

    Returns:
        최종 GuardDecision 객체
    """
    if not isinstance(plan, dict) or not isinstance(plan.get("sql"), str):
        return _blocked("MODEL_PLAN_INVALID", "모델 계획은 반드시 SQL 텍스트를 포함해야 합니다.")
    try:
        query_policy = _query_policy(package)
    except ValueError as error:
        return _blocked("CONTEXT_SCHEMA_INVALID", str(error))

    # 1. SQL 정적 정책 검증
    result = validate_sql(
        plan["sql"],
        require_limit=query_policy["require_limit"],
        max_limit=query_policy["max_limit"],
    )
    if not result.ok or result.expression is None or result.canonical_sql is None:
        codes = [item.code for item in result.violations]
        unsafe = {
            "READ_ONLY_QUERY_REQUIRED",
            "FORBIDDEN_STATEMENT",
            "SINGLE_STATEMENT_REQUIRED",
        }
        return _blocked(
            "UNSAFE_SQL" if unsafe.intersection(codes) else codes[0],
            "; ".join(codes),
        )

    # 2. 세맨틱 의미론 검증
    semantic = validate_parsed_semantics(result, package, plan)
    if not semantic.ok:
        return _blocked(str(semantic.violation), semantic.detail)

    # 3. 파라미터 바인딩
    parameters = {
        item.name: {"value_type": item.value_type, "value": item.value}
        for item in package.parameter_bindings
    }
    try:
        executable_sql = bind_sql_parameters(result.expression, parameters)
    except (SqlBindingError, TypeError, ValueError) as error:
        return _blocked("PARAMETER_CONTRACT_MISMATCH", str(error))

    # 4. 성공 결과 반환
    return GuardDecision(
        violation=None,
        detail="",
        canonical_sql=result.canonical_sql,
        executable_sql=executable_sql,
        references=semantic.references,
        parameters=parameters,
        ast_evidence=semantic.ast_evidence,
    )


def validate_parsed_semantics(
    result: SqlValidationResult,
    package: Any,
    plan: dict[str, Any] | None = None,
) -> SemanticDecision:
    """SQL 정책을 통과한 SQLGlot AST를 대상으로 세부 런타임 거버넌스 규칙들을 종합 검증합니다."""
    if not result.ok or result.expression is None:
        return _semantic_blocked("SQL_POLICY_INVALID", "SQL 정책 검증에 실패한 AST입니다.")
    try:
        policy = _query_policy(package)
        logical_plan = None
        if plan is not None and "analysis_plan" in plan:
            try:
                logical_plan = validate_analysis_plan_payload(
                    plan["analysis_plan"], package
                )
            except AnalysisPlanError as error:
                return _semantic_blocked("ANALYSIS_PLAN_MISMATCH", error.code.value)
        assets = approved_assets(package)
        physical_tables = set(result.physical_tables)

        # 1. 물리 테이블 카탈로그 및 스키마 검증
        if not physical_tables or not physical_tables.issubset(assets):
            return _semantic_blocked(
                "ASSET_SCOPE_MISMATCH",
                "물리 SQL 테이블은 승인된 schema_context의 비어있지 않은 부분집합이어야 합니다.",
            )
        if result.limit is None or not 1 <= result.limit <= policy["max_limit"]:
            return _semantic_blocked(
                "LIMIT_OUT_OF_RANGE",
                "SQL LIMIT 절이 런타임 query_policy 허용 범위를 벗어납니다.",
            )
        catalogs = {item.split(".", 1)[0] for item in physical_tables}
        if not catalogs.issubset(set(policy["allowed_catalogs"])):
            return _semantic_blocked(
                "ASSET_SCOPE_MISMATCH",
                "SQL이 런타임 query_policy 허용 범위 밖의 카탈로그를 사용했습니다.",
            )

        # 2. 사용 함수 화이트리스트 검증
        allowed_functions = {str(item).upper() for item in policy["allowed_functions"]} | {"CAST", "TRY_CAST"}
        if not set(result.functions).issubset(allowed_functions):
            return _semantic_blocked(
                "FUNCTION_POLICY_MISMATCH",
                "SQL이 런타임 query_policy 허용 범위 밖의 함수를 사용했습니다.",
            )

        # 3. 모델 선언 리니지 일치 검증
        if plan is not None:
            model_assets = declared_assets(plan)
            if model_assets is not None and model_assets != physical_tables:
                return _semantic_blocked(
                    "MODEL_LINEAGE_MISMATCH",
                    "모델이 선언한 used_assets가 실제 SQL 물리 테이블과 일치하지 않습니다.",
                )

        # 4. 컬럼 스코프 검증
        if error := column_violation(result, assets):
            return _semantic_blocked("COLUMN_SCOPE_MISMATCH", error)

        # 5. 지표(Metric) 일치 및 필수 필터 / 시간 조건 검증
        metrics = tuple(getattr(package, "metrics", ()))
        metric_ids = {str(item.id) for item in metrics}
        if not metrics or len(metric_ids) != len(metrics):
            return _semantic_blocked(
                "METRIC_RULE_MISMATCH",
                "컨텍스트 지표 목록은 비어있지 않고 고유해야 합니다.",
            )
        if plan is not None:
            model_metrics = declared_metrics(plan)
            if model_metrics is not None and model_metrics != metric_ids:
                return _semantic_blocked(
                    "MODEL_LINEAGE_MISMATCH",
                    "모델이 선언한 used_metrics가 런타임 metric_rules와 일치하지 않습니다.",
                )

        metrics_by_id = {str(item.id): item for item in metrics}
        time_rules = (
            getattr(package, "runtime_contracts", None) or {}
        ).get("time_rules") or {}
        comparison_window = time_rules.get("comparison_window")
        bound_names = {item.name for item in getattr(package, "parameter_bindings", ())}
        is_comparison = bool(comparison_window) and str(
            comparison_window.get("start_parameter")
        ) in bound_names
        if logical_plan is not None and (
            logical_plan.operation is AnalysisOperation.PERIOD_COMPARISON
        ) != is_comparison:
            return _semantic_blocked(
                "ANALYSIS_PLAN_MISMATCH",
                "AnalysisPlan 연산과 실제 기간 parameter binding이 일치하지 않습니다.",
            )

        if is_comparison and any(
            str(item.aggregation).casefold() == "ratio" for item in metrics
        ):
            return _semantic_blocked(
                "METRIC_RULE_MISMATCH",
                "Ratio metric과 기간 비교의 동시 사용은 아직 거버넌스되지 않았습니다.",
            )
        if is_comparison and any(
            str(item.aggregation).casefold() == "exists" for item in metrics
        ):
            return _semantic_blocked(
                "METRIC_RULE_MISMATCH",
                "Exists metric과 기간 비교의 동시 사용은 아직 거버넌스되지 않았습니다.",
            )

        output_scope = None
        for metric in metrics:
            if is_comparison:
                scope = projection_scope_evidence(result, metric.result_field)
                match = (
                    match_metric(scope, metric, assets, metrics_by_id, filtered=True)
                    if scope is not None
                    else None
                )
                comparison_alias = f"{metric.result_field}__comparison"
                comparison_scope = projection_scope_evidence(result, comparison_alias)
                comparison_match = (
                    match_metric(
                        comparison_scope,
                        metric,
                        assets,
                        metrics_by_id,
                        filtered=True,
                        expected_alias=comparison_alias,
                    )
                    if comparison_scope is not None
                    else None
                )
                if scope is None or match is None or comparison_scope is None or comparison_match is None:
                    return _semantic_blocked(
                        "METRIC_RULE_MISMATCH",
                        f"SQL 프로젝션이 비교 지표 {metric.id!r} 을(를) 구현하지 않았습니다.",
                    )
                for candidate_scope in (scope, comparison_scope):
                    output_scope = output_scope or candidate_scope
                    if candidate_scope.scope.expression is not output_scope.scope.expression:
                        return _semantic_blocked(
                            "METRIC_RULE_MISMATCH",
                            "모든 선택된 지표는 단일 출력 스코프에서 프로젝션되어야 합니다.",
                        )
                primary_comparisons = set(match.where_comparisons)
                comparison_comparisons = set(comparison_match.where_comparisons)
                if error := required_filter_violation(
                    package,
                    primary_comparisons,
                    assets,
                    str(metric.id),
                ):
                    return _semantic_blocked("REQUIRED_FILTER_MISSING", error)
                if error := time_rule_violation(
                    package, primary_comparisons, assets, metric, window="primary"
                ):
                    return _semantic_blocked("TIME_RULE_MISMATCH", error)
                if error := time_rule_violation(
                    package, comparison_comparisons, assets, metric, window="comparison"
                ):
                    return _semantic_blocked("TIME_RULE_MISMATCH", error)
                continue

            scope = projection_scope_evidence(result, metric.result_field)
            match = match_metric(scope, metric, assets, metrics_by_id) if scope is not None else None
            if scope is None or match is None:
                return _semantic_blocked(
                    "METRIC_RULE_MISMATCH",
                    f"SQL 프로젝션이 지표 {metric.id!r} 을(를) 올바르게 구현하지 않았습니다.",
                )
            output_scope = output_scope or scope
            if scope.scope.expression is not output_scope.scope.expression:
                return _semantic_blocked(
                    "METRIC_RULE_MISMATCH",
                    "모든 선택된 지표는 단일 출력 스코프에서 프로젝션되어야 합니다.",
                )
            comparisons = set(match.where_comparisons)
            if error := required_filter_violation(
                package,
                comparisons,
                assets,
                str(metric.id),
            ):
                return _semantic_blocked("REQUIRED_FILTER_MISSING", error)
            if error := time_rule_violation(package, comparisons, assets, metric):
                return _semantic_blocked("TIME_RULE_MISMATCH", error)

        # 6. 논리 연산의 출력 grain·정렬·순위 LIMIT 검증
        assert output_scope is not None
        if logical_plan is not None:
            if error := operation_violation(
                logical_plan,
                result,
                package,
                output_scope,
            ):
                return _semantic_blocked("ANALYSIS_OPERATION_MISMATCH", error)

        # 7. 조인 위상(Join Graph Topology) 검증
        join = join_violation(package, physical_tables, output_scope, assets)
        if join.violation:
            return _semantic_blocked(join.code, join.violation)

        if plan is not None:
            error = _declared_lineage_violation(plan, result, join.used_join_ids)
            if error:
                return _semantic_blocked("MODEL_LINEAGE_MISMATCH", error)

        # 8. 검증 완료 SemanticDecision 반환
        return SemanticDecision(
            violation=None,
            detail="",
            references=references(result, package, assets, join.used_join_ids),
            ast_evidence={
                "physical_tables": list(result.physical_tables),
                "projection_aliases": list(result.projection_aliases),
                "functions": list(result.functions),
                "join_count": len(result.joins),
                "limit": result.limit,
                "analysis_plan_checksum": (
                    logical_plan.checksum if logical_plan is not None else None
                ),
                "analysis_operation": (
                    logical_plan.operation.value if logical_plan is not None else None
                ),
                "fanout_plans": [
                    {
                        "join_id": item.join_id,
                        "plan": item.plan.value,
                        "reason": item.reason.value,
                    }
                    for item in join.fanout_decisions
                ],
            },
        )
    except (KeyError, TypeError, ValueError) as error:
        return _semantic_blocked("CONTEXT_SCHEMA_INVALID", str(error))


def apply_guard_decision(plan: dict[str, Any], decision: GuardDecision) -> None:
    """가드 검증을 통과한 canonical_sql, executable_sql 및 증거 데이터를 계획(Plan) 딕셔너리에 반영합니다."""
    if not decision.ok:
        return
    plan["sql"] = decision.canonical_sql
    plan["executable_sql"] = decision.executable_sql
    plan["references"] = [dict(item) for item in decision.references]
    plan["parameters"] = dict(decision.parameters or {})
    plan["ast_evidence"] = dict(decision.ast_evidence or {})


def _query_policy(package: Any) -> dict[str, Any]:
    """package로부터 runtime query_policy 딕셔너리를 추출하고 유효성을 검증합니다."""
    contracts = getattr(package, "runtime_contracts", None)
    policy = contracts.get("query_policy") if isinstance(contracts, dict) else None
    fields = {
        "dialect",
        "statement_type",
        "read_only",
        "require_limit",
        "max_limit",
        "allowed_functions",
        "allowed_catalogs",
    }
    if (
        not isinstance(policy, dict)
        or set(policy) != fields
        or policy.get("dialect") != "trino"
        or policy.get("statement_type") != "select"
        or policy.get("read_only") is not True
        or policy.get("require_limit") is not True
        or not isinstance(policy.get("max_limit"), int)
        or isinstance(policy.get("max_limit"), bool)
        or policy["max_limit"] < 1
        or not isinstance(policy.get("allowed_functions"), list)
        or not isinstance(policy.get("allowed_catalogs"), list)
    ):
        raise ValueError("런타임 query_policy 가 유효하지 않습니다.")
    return policy


def _blocked(code: str, detail: str) -> GuardDecision:
    return GuardDecision(violation=code, detail=detail)


def _semantic_blocked(code: str, detail: str) -> SemanticDecision:
    return SemanticDecision(violation=code, detail=detail)


def _declared_lineage_violation(
    plan: dict[str, Any],
    result: SqlValidationResult,
    used_join_ids: frozenset[str],
) -> str | None:
    declared_columns = plan.get("declared_columns")
    if declared_columns is not None:
        if not isinstance(declared_columns, (list, tuple)):
            return "모델의 used_columns는 배열이어야 합니다."
        values = {
            (str(item.get("asset_fqn")), str(item.get("column")))
            for item in declared_columns
            if isinstance(item, dict) and set(item) == {"asset_fqn", "column"}
        }
        actual = {
            (item.source_table, item.name)
            for item in result.columns
            if item.source_table is not None
        }
        if len(values) != len(declared_columns) or values != actual:
            return "모델의 used_columns가 실제 SQL AST 리니지와 일치하지 않습니다."
    declared_joins = plan.get("declared_joins")
    if declared_joins is not None:
        if not isinstance(declared_joins, (list, tuple)):
            return "모델의 used_joins는 배열이어야 합니다."
        if (
            set(declared_joins) != set(used_join_ids)
            or len(set(declared_joins)) != len(declared_joins)
        ):
            return "모델의 used_joins가 실제 SQL AST 리니지와 일치하지 않습니다."
    return None
