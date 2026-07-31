from dataclasses import dataclass

from sqlalchemy import create_engine, text

from app.contracts import AnalysisRequest, ErrorCode, RouteType


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
    def __init__(self, code: ErrorCode, message: str) -> None:
        self.code, self.message = code, message


class RoutingService:
    def __init__(self, templates: tuple[ApprovedTemplate, ...] = ()) -> None:
        self._templates = {item.template_id: item for item in templates}

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
        return cls(templates)

    def decide(self, payload: AnalysisRequest) -> RouteDecision:
        if payload.template_id is None:
            return RouteDecision(RouteType.GENERAL, None, True, True)
        template = self._templates.get(payload.template_id)
        if template is None:
            raise RoutingError(
                ErrorCode.ACCESS_DENIED,
                "승인되지 않은 Template입니다.",
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
