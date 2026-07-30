from dataclasses import dataclass

from app.contracts import AnalysisRequest, ErrorCode, RouteType


@dataclass(frozen=True)
class ApprovedTemplate:
    template_id: str
    parameter_names: frozenset[str]
    requires_g1: bool = True
    requires_g2: bool = True


@dataclass(frozen=True)
class RouteDecision:
    route_type: RouteType
    template_id: str | None
    requires_g1: bool
    requires_g2: bool


class RoutingError(ValueError):
    def __init__(self, code: ErrorCode, message: str) -> None:
        self.code, self.message = code, message


class RoutingService:
    def __init__(self, templates: tuple[ApprovedTemplate, ...] = ()) -> None:
        self._templates = {item.template_id: item for item in templates}

    def decide(self, payload: AnalysisRequest) -> RouteDecision:
        if payload.template_id is None:
            return RouteDecision(RouteType.GENERAL, None, True, True)
        template = self._templates.get(payload.template_id)
        if template is None:
            raise RoutingError(ErrorCode.ACCESS_DENIED, "승인되지 않은 Template입니다.")
        if set(payload.parameters) != template.parameter_names:
            raise RoutingError(ErrorCode.CONTEXT_INCOMPLETE, "Template parameter가 일치하지 않습니다.")
        return RouteDecision(RouteType.TEMPLATE, template.template_id, template.requires_g1, template.requires_g2)
