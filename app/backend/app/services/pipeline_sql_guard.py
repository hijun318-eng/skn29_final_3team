"""하나의 SQLGlot AST에서 read-only policy, schema·metric·join·time lineage와 named binding을 검증해 실행 SQL 또는 fail-closed GuardDecision을 만든다."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.services.pipeline_sql_schema import (
    approved_assets,
    column_violation,
    declared_assets,
    declared_metrics,
)
from app.services.pipeline_sql_scopes import projection_scope_evidence
from app.services.pipeline_sql_semantics import (
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
    """SQLGlot AST와 runtime context의 의미 대조 결과를 위반 코드·근거와 함께 보존한다.

    ``violation``이 없을 때만 references와 AST evidence를 downstream G2 증거로 사용할 수
    있으며, 문자열 검색이나 모델 설명은 이 판정을 대신하지 않는다.
    """
    violation: str | None
    detail: str
    references: tuple[dict[str, Any], ...] = ()
    ast_evidence: dict[str, Any] | None = None

    @property
    def ok(self) -> bool:
        """SemanticDecision에 누적된 정책 위반이 없는지 계산한다."""
        return self.violation is None


@dataclass(frozen=True)
class GuardDecision:
    """한 번 파싱한 AST의 정책·의미·parameter binding 결과와 실행 가능 SQL을 묶는다.

    성공 시 canonical SQL, 동일 AST에서 생성한 executable SQL, typed parameters와 evidence를
    반환한다. 어느 단계든 위반되면 executable SQL을 비워 caller가 query capability나 Trino
    실행으로 넘어가지 못하게 한다.
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
        """GuardDecision에 누적된 정책 위반이 없는지 계산한다."""
        return self.violation is None


def validate_plan(plan: object, package: Any) -> GuardDecision:
    """계획 계약과 도메인 불변식을 검사하고 위반 시 명시적 오류를 발생시킨다."""
    if not isinstance(plan, dict) or not isinstance(plan.get("sql"), str):
        return _blocked("MODEL_PLAN_INVALID", "The model plan must contain SQL text.")
    try:
        query_policy = _query_policy(package)
    except ValueError as error:
        return _blocked("CONTEXT_SCHEMA_INVALID", str(error))
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

    semantic = validate_parsed_semantics(result, package, plan)
    if not semantic.ok:
        return _blocked(str(semantic.violation), semantic.detail)
    parameters = {
        item.name: {"value_type": item.value_type, "value": item.value}
        for item in package.parameter_bindings
    }
    try:
        executable_sql = bind_sql_parameters(result.expression, parameters)
    except (SqlBindingError, TypeError, ValueError) as error:
        return _blocked("PARAMETER_CONTRACT_MISMATCH", str(error))
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
    """파싱 의미 규칙 계약과 도메인 불변식을 검사하고 위반 시 명시적 오류를 발생시킨다.

    Apply runtime semantics to the exact AST already accepted by SQL policy.
    """
    if not result.ok or result.expression is None:
        return _semantic_blocked("SQL_POLICY_INVALID", "SQL policy did not accept the AST.")
    try:
        policy = _query_policy(package)
        assets = approved_assets(package)
        physical_tables = set(result.physical_tables)
        if not physical_tables or not physical_tables.issubset(assets):
            return _semantic_blocked(
                "ASSET_SCOPE_MISMATCH",
                "Physical SQL tables must be a non-empty subset of schema_context.",
            )
        if result.limit is None or not 1 <= result.limit <= policy["max_limit"]:
            return _semantic_blocked(
                "LIMIT_OUT_OF_RANGE",
                "SQL LIMIT differs from runtime query_policy.",
            )
        catalogs = {item.split(".", 1)[0] for item in physical_tables}
        if not catalogs.issubset(set(policy["allowed_catalogs"])):
            return _semantic_blocked(
                "ASSET_SCOPE_MISMATCH",
                "SQL uses a catalog outside runtime query_policy.",
            )
        allowed_functions = {str(item).upper() for item in policy["allowed_functions"]}
        if not set(result.functions).issubset(allowed_functions):
            return _semantic_blocked(
                "FUNCTION_POLICY_MISMATCH",
                "SQL uses a function outside runtime query_policy.",
            )
        if plan is not None:
            model_assets = declared_assets(plan)
            if model_assets is not None and model_assets != physical_tables:
                return _semantic_blocked(
                    "MODEL_LINEAGE_MISMATCH",
                    "Model used_assets must exactly match SQL physical tables.",
                )
        if error := column_violation(result, assets):
            return _semantic_blocked("COLUMN_SCOPE_MISMATCH", error)

        metrics = tuple(getattr(package, "metrics", ()))
        metric_ids = {str(item.id) for item in metrics}
        if not metrics or len(metric_ids) != len(metrics):
            return _semantic_blocked(
                "METRIC_RULE_MISMATCH",
                "Context metrics must be non-empty and unique.",
            )
        if plan is not None:
            model_metrics = declared_metrics(plan)
            if model_metrics is not None and model_metrics != metric_ids:
                return _semantic_blocked(
                    "MODEL_LINEAGE_MISMATCH",
                    "Model used_metrics must exactly match metric_rules.",
                )

        output_scope = None
        for metric in metrics:
            scope = projection_scope_evidence(result, metric.result_field)
            match = match_metric(scope, metric, assets) if scope is not None else None
            if scope is None or match is None:
                return _semantic_blocked(
                    "METRIC_RULE_MISMATCH",
                    f"SQL projection does not implement metric {metric.id!r}.",
                )
            output_scope = output_scope or scope
            if scope.scope.expression is not output_scope.scope.expression:
                return _semantic_blocked(
                    "METRIC_RULE_MISMATCH",
                    "All selected metrics must be projected by one output scope.",
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
        assert output_scope is not None
        join = join_violation(package, physical_tables, output_scope, assets)
        if join.violation:
            return _semantic_blocked("JOIN_GRAPH_MISMATCH", join.violation)
        if plan is not None:
            error = _declared_lineage_violation(plan, result, join.used_join_ids)
            if error:
                return _semantic_blocked("MODEL_LINEAGE_MISMATCH", error)
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
            },
        )
    except (KeyError, TypeError, ValueError) as error:
        return _semantic_blocked("CONTEXT_SCHEMA_INVALID", str(error))


def apply_guard_decision(plan: dict[str, Any], decision: GuardDecision) -> None:
    """통과한 G2 판정의 정규 SQL·실행 SQL·lineage만 모델 계획에 반영한다.

    위반 판정이면 계획을 전혀 수정하지 않는다. 이 경계 덕분에 adapter는 모델 원문 대신
    동일 SQLGlot AST에서 검증·바인딩된 값과 query capability 발급 근거만 받는다.
    """
    if not decision.ok:
        return
    plan["sql"] = decision.canonical_sql
    plan["executable_sql"] = decision.executable_sql
    plan["references"] = [dict(item) for item in decision.references]
    plan["parameters"] = dict(decision.parameters or {})
    plan["ast_evidence"] = dict(decision.ast_evidence or {})


def _query_policy(package: Any) -> dict[str, Any]:
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
        raise ValueError("Runtime query_policy is invalid.")
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
            return "Model used_columns must be an array."
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
            return "Model used_columns do not match SQL AST lineage."
    declared_joins = plan.get("declared_joins")
    if declared_joins is not None:
        if not isinstance(declared_joins, (list, tuple)):
            return "Model used_joins must be an array."
        if (
            set(declared_joins) != set(used_join_ids)
            or len(set(declared_joins)) != len(declared_joins)
        ):
            return "Model used_joins do not match SQL AST lineage."
    return None
