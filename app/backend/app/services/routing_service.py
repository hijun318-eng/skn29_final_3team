"""일반 요청은 동적 분석으로 보내고 template 요청은 동일한 승인 DB 행의 SQL·source·role·parameter 계약이 모두 맞을 때만 실행 route를 반환한다."""

from dataclasses import dataclass
from typing import Any

from sqlalchemy import text

from app.authorization import role_is_entitled
from app.contracts import AnalysisRequest, ErrorCode, Role, RouteType
from app.database import session_scope


@dataclass(frozen=True)
class ApprovedTemplate:
    """동일한 APPROVED DB 행에서 읽은 template SQL·parameter·source·role 권한 snapshot이다.

    SQL text와 허용 역할을 별도 파일이나 기본값에서 보강하지 않으며, 호출 주체와 parameter가
    이 snapshot에 정확히 부합할 때만 template route가 사용할 수 있다.
    """
    template_id: str
    parameter_names: frozenset[str]
    allowed_roles: frozenset[Role]
    sql_text: str
    source_fqns: frozenset[str]
    requires_g1: bool = True
    requires_g2: bool = True


@dataclass(frozen=True)
class RouteDecision:
    """요청을 동적 분석 또는 승인 template로 보낸 결과와 필수 gate를 표현한다.

    일반 질문은 질문 문구나 keyword mapping 없이 dynamic route가 되고, template route만
    승인 SQL·source FQN을 포함한다. ``requires_g1``/``requires_g2``는 이후 stage가 생략할 수
    없는 검증 계약이다.
    """
    route_type: RouteType
    template_id: str | None
    requires_g1: bool
    requires_g2: bool
    sql_text: str | None = None
    source_fqns: frozenset[str] = frozenset()


class RoutingError(ValueError):
    """template route의 승인·역할·parameter 계약이 충족되지 않았음을 전달한다.

    ``code``와 공개 ``message``만 API 계층에 제공하며, DB 행이 없거나 malformed한 경우도
    같은 fail-closed 경계로 처리해 정적 SQL 또는 기본 역할로 우회하지 못하게 한다.
    """
    def __init__(self, code: ErrorCode, message: str) -> None:
        self.code, self.message = code, message


class RoutingService:
    """일반 질문은 동적 분석으로 보내고 template 요청만 승인 DB 행의 역할·SQL·source 계약으로 제한한다."""
    def __init__(
        self,
        database_url: str | None = None,
    ) -> None:
        self._database_url = database_url

    @classmethod
    def from_database(cls, database_url: str) -> "RoutingService":
        """승인 template과 역할 정책을 같은 App DB transaction에서 읽는 router를 구성한다."""
        return cls(database_url=database_url)

    async def _template(self, template_id: str) -> ApprovedTemplate | None:
        # 승인 SQL과 역할 정책은 같은 DB 행에서만 읽어야 배포 시점이 어긋난 정적 파일이나
        # 프로세스 주입값이 권한 우회 원본이 되지 않는다. DB가 없으면 보정하지 않고 거부한다.
        if self._database_url is None:
            return None
        async with session_scope(self._database_url) as session:
            result = await session.execute(
                text(
                    """
                    SELECT template_id, parameter_names_json, sql_text,
                           source_fqns_json, allowed_roles_json,
                           requires_g1, requires_g2
                    FROM context.analysis_templates
                    WHERE template_id = :template_id
                      AND status = 'APPROVED'
                      AND sql_text IS NOT NULL
                      AND source_fqns_json IS NOT NULL
                      AND allowed_roles_json IS NOT NULL
                    """
                ),
                {"template_id": template_id},
            )
            row = result.mappings().one_or_none()
        if row is None:
            return None
        # Template 권한을 별도 파일에서 결합하면 DB 승인 상태와 policy 배포가 원자적으로
        # 움직이지 않아 권한 공백이 생긴다. 동일 row의 typed JSONB만 신뢰하고 malformed
        # metadata는 기본 role로 보정하지 않은 채 접근 거부로 닫는다.
        return ApprovedTemplate(
            template_id=row["template_id"],
            parameter_names=_string_set(
                row["parameter_names_json"], "parameter_names_json"
            ),
            allowed_roles=_allowed_roles(row["allowed_roles_json"]),
            sql_text=row["sql_text"],
            source_fqns=_string_set(
                row["source_fqns_json"], "source_fqns_json", required=True
            ),
            requires_g1=row["requires_g1"],
            requires_g2=row["requires_g2"],
        )

    async def decide(
        self,
        payload: AnalysisRequest,
        role: Role = Role.ANALYST,
    ) -> RouteDecision:
        """요청의 template 선택과 인증된 역할을 DB 승인 계약에 대조해 route를 결정한다.

        일반 요청은 동적 route를 반환한다. template 요청은 동일 승인 행의 SQL·source·role·
        parameter를 원자적으로 확인하며, 누락·권한 불일치·malformed metadata는 ``RoutingError``로 거부한다.
        """
        if payload.template_id is None:
            return RouteDecision(RouteType.GENERAL, None, True, True)
        template = await self._template(payload.template_id)
        if template is None:
            raise RoutingError(
                ErrorCode.ACCESS_DENIED,
                "승인되지 않은 Template입니다.",
            )
        if not role_is_entitled(role, template.allowed_roles):
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


def _string_set(
    value: Any,
    field: str,
    *,
    required: bool = False,
) -> frozenset[str]:
    if (
        not isinstance(value, list)
        or any(not isinstance(item, str) or not item.strip() for item in value)
        or len(value) != len(set(value))
        or (required and not value)
    ):
        raise RoutingError(
            ErrorCode.ACCESS_DENIED,
            f"Template {field} 계약이 올바르지 않습니다.",
        )
    return frozenset(value)


def _allowed_roles(value: Any) -> frozenset[Role]:
    raw_roles = _string_set(value, "allowed_roles_json", required=True)
    try:
        return frozenset(Role(item) for item in raw_roles)
    except ValueError as error:
        raise RoutingError(
            ErrorCode.ACCESS_DENIED,
            "Template allowed_roles_json 계약이 올바르지 않습니다.",
        ) from error
