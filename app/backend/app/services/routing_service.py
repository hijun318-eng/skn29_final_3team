import json
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import create_engine, text

from app.contracts import AnalysisRequest, ErrorCode, Role, RouteType


@dataclass(frozen=True)
class ApprovedTemplate:
    template_id: str
    parameter_names: frozenset[str]
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
    def __init__(
        self,
        code: ErrorCode,
        message: str,
        status_code: int | None = None,
    ) -> None:
        self.code, self.message, self.status_code = code, message, status_code


class RoutingService:
    def __init__(
        self,
        templates: tuple[ApprovedTemplate, ...] = (),
        template_roles: dict[str, frozenset[str]] | None = None,
    ) -> None:
        self._templates = {item.template_id: item for item in templates}
        self._template_roles = template_roles or {
            "weekly-room-operations": frozenset({Role.HOTEL_ANALYST.value})
        }

    @staticmethod
    def _template_policy() -> dict[str, frozenset[str]]:
        current = Path(__file__).resolve()
        candidates = (
            current.parents[4] / "config" / "access-policy.yaml",
            current.parents[2] / "config" / "access-policy.yaml",
        )
        policy_path = next((path for path in candidates if path.is_file()), None)
        if policy_path is None:
            raise RuntimeError("access policy file is missing")
        policy = json.loads(policy_path.read_text(encoding="utf-8"))
        if policy.get("policy_version") != "ACCESS-POLICY-v1.0.0":
            raise RuntimeError("unsupported access policy version")
        return {
            template_id: frozenset(config["allowed_roles"])
            for template_id, config in policy["analysis_templates"].items()
        }

    @classmethod
    def from_database(cls, database_url: str) -> "RoutingService":
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
                        sql_text=row["sql_text"],
                        source_fqns=frozenset(row["source_fqns_json"]),
                        requires_g1=row["requires_g1"],
                        requires_g2=row["requires_g2"],
                    )
                    for row in rows
                )
        finally:
            engine.dispose()
        return cls(templates, cls._template_policy())

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
                403,
            )
        if role.value not in self._template_roles.get(template.template_id, frozenset()):
            raise RoutingError(
                ErrorCode.ACCESS_DENIED,
                "해당 역할은 이 Template을 실행할 수 없습니다.",
                403,
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
