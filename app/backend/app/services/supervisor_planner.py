"""외부 Supervisor 계획을 서버 검증 가능한 단일 Agent 요청으로 변환한다."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Literal, Protocol

from pydantic import ConfigDict, Field, model_validator

from app.contract_core import ContractModel
from app.conversation_contracts import MLPredictionAction
from app.ports.agent import AgentKind, AgentRequest, MLPredictionInvocation
from app.services.agent_supervisor import AgentDispatchError
from app.services.ml_prediction_service import MLRuntimeCapability


SUPERVISOR_ROUTE_PLAN_VERSION = "SupervisorRoutePlan.v1"


class SupervisorPlanRoute(str, Enum):
    """현재 한 command에서 실행 가능한 Agent 또는 안전한 미실행 판정이다."""

    ANALYSIS_WORKFLOW = AgentKind.ANALYSIS_WORKFLOW.value
    INTERNAL_GUIDELINE = AgentKind.INTERNAL_GUIDELINE.value
    ML_PREDICTION = AgentKind.ML_PREDICTION.value
    UNAVAILABLE = "UNAVAILABLE"


class SupervisorMLPropertyScope(ContractModel):
    """Supervisor가 선택할 수 있는 검증된 ML property 날짜 범위다."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    property_id: str = Field(min_length=1, max_length=64)
    min_as_of: date
    max_as_of: date


class SupervisorCapabilityCatalog(ContractModel):
    """현재 요청에서 모델에 공개하는 최소 capability 목록이다."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    available_agents: tuple[AgentKind, ...] = Field(min_length=1, max_length=3)
    unavailable_agents: tuple[AgentKind, ...] = Field(default=(), max_length=2)
    ml_properties: tuple[SupervisorMLPropertyScope, ...] = Field(
        default=(),
        max_length=50,
    )
    ml_min_horizon_days: int | None = Field(default=None, ge=1, le=366)
    ml_max_horizon_days: int | None = Field(default=None, ge=1, le=366)

    @model_validator(mode="after")
    def validate_catalog(self) -> "SupervisorCapabilityCatalog":
        """중복 Agent와 불완전 ML 범위가 모델 입력으로 넘어가지 않게 한다."""

        if (
            len(self.available_agents) != len(set(self.available_agents))
            or len(self.unavailable_agents) != len(set(self.unavailable_agents))
            or set(self.available_agents) & set(self.unavailable_agents)
        ):
            raise ValueError("Supervisor capability Agent 목록이 올바르지 않습니다.")
        ml_available = AgentKind.ML_PREDICTION in self.available_agents
        ml_scope_complete = bool(
            self.ml_properties
            and self.ml_min_horizon_days is not None
            and self.ml_max_horizon_days is not None
        )
        if ml_available != ml_scope_complete:
            raise ValueError("Supervisor ML capability 범위가 완전하지 않습니다.")
        if (
            self.ml_min_horizon_days is not None
            and self.ml_max_horizon_days is not None
            and self.ml_min_horizon_days > self.ml_max_horizon_days
        ):
            raise ValueError("Supervisor ML horizon 범위가 올바르지 않습니다.")
        return self

    @classmethod
    def from_runtime(
        cls,
        *,
        rag_enabled: bool,
        ml_enabled: bool,
        ml_capability: MLRuntimeCapability | None,
    ) -> "SupervisorCapabilityCatalog":
        """feature flag와 이미 검증된 ML receipt만 capability 입력으로 축약한다."""

        available = [AgentKind.ANALYSIS_WORKFLOW]
        unavailable: list[AgentKind] = []
        if rag_enabled:
            available.append(AgentKind.INTERNAL_GUIDELINE)
        else:
            unavailable.append(AgentKind.INTERNAL_GUIDELINE)
        properties: tuple[SupervisorMLPropertyScope, ...] = ()
        min_horizon: int | None = None
        max_horizon: int | None = None
        if ml_enabled and ml_capability is not None:
            available.append(AgentKind.ML_PREDICTION)
            properties = tuple(
                SupervisorMLPropertyScope(
                    property_id=item.property_id,
                    min_as_of=item.min_as_of,
                    max_as_of=item.max_as_of,
                )
                for item in ml_capability.properties
            )
            min_horizon = ml_capability.min_horizon_days
            max_horizon = ml_capability.max_horizon_days
        else:
            unavailable.append(AgentKind.ML_PREDICTION)
        return cls(
            available_agents=tuple(available),
            unavailable_agents=tuple(unavailable),
            ml_properties=properties,
            ml_min_horizon_days=min_horizon,
            ml_max_horizon_days=max_horizon,
        )


class SupervisorRoutePlan(ContractModel):
    """Terra가 반환하고 서버가 다시 검증하는 최소 단일 route 계획이다."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["SupervisorRoutePlan.v1"] = (
        SUPERVISOR_ROUTE_PLAN_VERSION
    )
    route: SupervisorPlanRoute
    objective: str = Field(min_length=1, max_length=240)
    ml_prediction: MLPredictionAction | None = None

    @model_validator(mode="after")
    def validate_route_payload(self) -> "SupervisorRoutePlan":
        """ML route에만 구조화 예측 입력을 허용한다."""

        has_ml_input = self.ml_prediction is not None
        if (self.route is SupervisorPlanRoute.ML_PREDICTION) != has_ml_input:
            raise ValueError("Supervisor ML route와 prediction 입력이 일치하지 않습니다.")
        return self


@dataclass(frozen=True)
class SupervisorPlanResult:
    """검증된 계획과 외부 응답을 원문 없이 봉인한 증거 참조다."""

    plan: SupervisorRoutePlan
    evidence_ref: str
    model: str
    response_id: str


class SupervisorPlanner(Protocol):
    """자연어를 실행하지 않고 typed Agent 계획만 반환하는 외부 경계다."""

    async def plan(
        self,
        request: AgentRequest,
        catalog: SupervisorCapabilityCatalog,
        *,
        previous_route: str | None,
    ) -> SupervisorPlanResult:
        """현재 capability와 직전 route를 기준으로 한 계획을 반환한다."""

        ...


def materialize_supervisor_plan(
    request: AgentRequest,
    result: SupervisorPlanResult,
    catalog: SupervisorCapabilityCatalog,
) -> AgentRequest:
    """모델 계획을 허용 Agent·ML 범위와 대조해 immutable 실행 요청으로 만든다."""

    plan = result.plan
    if plan.route is SupervisorPlanRoute.UNAVAILABLE:
        raise AgentDispatchError(
            "AGENT_ROUTE_NOT_RESOLVED",
            "현재 연결된 Agent만으로 요청을 안전하게 실행할 수 없습니다.",
            evidence_refs=(result.evidence_ref,),
        )
    selected_agent = AgentKind(plan.route.value)
    if selected_agent not in catalog.available_agents:
        raise AgentDispatchError(
            "AGENT_MODEL_PLAN_OUTSIDE_CAPABILITY",
            "Supervisor 계획이 현재 승인된 Agent 범위를 벗어났습니다.",
            evidence_refs=(result.evidence_ref,),
        )
    invocation = (
        MLPredictionInvocation(
            **plan.ml_prediction.model_dump(mode="python")
        )
        if plan.ml_prediction is not None
        else None
    )
    payload = request.model_dump(mode="python")
    payload.update(
        target_agent=selected_agent,
        invocation=invocation,
        supervisor_plan_ref=result.evidence_ref,
    )
    return AgentRequest.model_validate(payload)
