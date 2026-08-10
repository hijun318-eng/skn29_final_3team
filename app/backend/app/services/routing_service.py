import json
import os
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import create_engine, text

from app.contracts import AnalysisRequest, ErrorCode, Role, RouteType


ACCESS_POLICY_VERSION = "ACCESS-POLICY-v1.0.0"


@dataclass(frozen=True)
class ApprovedTemplate:
    template_id: str
    parameter_names: frozenset[str]
    allowed_roles: frozenset[Role]
    sql_text: str
    source_fqns: frozenset[str]
    requires_g1: bool = True
    requires_g2: bool = True


@dataclass(frozen=True)
class RouteDecision:
    route_type: RouteType
    template_id: str | None
    requires_g1: bool
    requires_g2: bool
    sql_text: str | None = None
    source_fqns: frozenset[str] = frozenset()


class RoutingError(ValueError):
    def __init__(self, code: ErrorCode, message: str) -> None:
        self.code, self.message = code, message


class RoutingService:
    def __init__(self, templates: tuple[ApprovedTemplate, ...] = ()) -> None:
        self._templates = {item.template_id: item for item in templates}

    @classmethod
    def for_versioned_trino_demo(cls) -> "RoutingService":
        return cls(
            (
                ApprovedTemplate(
                    template_id="weekly-room-operations",
                    parameter_names=frozenset({"period_start", "period_end_exclusive"}),
                    allowed_roles=frozenset({Role.HOTEL_ANALYST}),
                    sql_text=(
                        "SELECT business_date, SUM(room_revenue) AS room_revenue "
                        "FROM serving.analytics.hotel_daily_metrics "
                        "WHERE business_date >= DATE ':period_start' "
                        "AND business_date < DATE ':period_end_exclusive' "
                        "AND data_period_status = 'YTD_SYNTHETIC' "
                        "AND is_forecast = false "
                        "GROUP BY business_date ORDER BY business_date LIMIT 1000"
                    ),
                    source_fqns=frozenset(
                        {"serving.analytics.hotel_daily_metrics"}
                    ),
                ),
            )
        )

    @classmethod
    def from_database(cls, database_url: str) -> "RoutingService":
        role_policy = _template_role_policy()
        engine = create_engine(database_url, pool_pre_ping=True)
        try:
            with engine.connect() as connection:
                rows = connection.execute(
                    text(
                        """
                        SELECT template_id, parameter_names_json, sql_text,
                               source_fqns_json, requires_g1, requires_g2
                        FROM context.analysis_templates
                        WHERE status = 'APPROVED'
                          AND sql_text IS NOT NULL
                          AND source_fqns_json IS NOT NULL
                        """
                    )
                ).mappings()
                templates = tuple(
                    ApprovedTemplate(
                        template_id=row["template_id"],
                        parameter_names=frozenset(row["parameter_names_json"]),
                        allowed_roles=role_policy.get(
                            row["template_id"],
                            frozenset(),
                        ),
                        sql_text=row["sql_text"],
                        source_fqns=frozenset(row["source_fqns_json"]),
                        requires_g1=row["requires_g1"],
                        requires_g2=row["requires_g2"],
                    )
                    for row in rows
                )
        finally:
            engine.dispose()
        return cls(templates)

    def decide(
        self,
        payload: AnalysisRequest,
        role: Role = Role.HOTEL_ANALYST,
    ) -> RouteDecision:
        if payload.template_id is None:
            return RouteDecision(RouteType.GENERAL, None, True, True)
        template = self._templates.get(payload.template_id)
        if template is None:
            raise RoutingError(
                ErrorCode.ACCESS_DENIED,
                "승인되지 않은 Template입니다.",
            )
        if role not in template.allowed_roles:
            raise RoutingError(
                ErrorCode.ACCESS_DENIED,
                "Template 실행 권한이 없습니다.",
            )
        if set(payload.parameters) != template.parameter_names:
            raise RoutingError(
                ErrorCode.CONTEXT_INCOMPLETE,
                "Template parameter가 일치하지 않습니다.",
            )
        return RouteDecision(
            RouteType.TEMPLATE,
            template.template_id,
            template.requires_g1,
            template.requires_g2,
            template.sql_text,
            template.source_fqns,
        )


def _template_role_policy() -> dict[str, frozenset[Role]]:
    configured = os.getenv("ACCESS_POLICY_PATH")
    service = Path(__file__).resolve()
    candidates = [Path(configured)] if configured else []
    candidates.append(service.parents[2] / "config" / "access-policy.yaml")
    if len(service.parents) > 4:
        candidates.append(service.parents[4] / "config" / "access-policy.yaml")
    path = next((candidate for candidate in candidates if candidate.is_file()), None)
    if path is None:
        raise RuntimeError("config/access-policy.yaml is required")
    policy = json.loads(path.read_text(encoding="utf-8"))
    if policy.get("policy_version") != ACCESS_POLICY_VERSION:
        raise RuntimeError("unsupported access policy version")
    templates = policy.get("analysis_templates")
    if not isinstance(templates, dict) or not templates:
        raise RuntimeError("analysis template role policy is missing")
    return {
        template_id: frozenset(Role(value) for value in template["allowed_roles"])
        for template_id, template in templates.items()
    }
