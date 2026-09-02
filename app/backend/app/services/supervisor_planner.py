"""외부 Supervisor 계획을 서버 검증 가능한 단일 Agent 요청으로 변환한다."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal, Protocol

from pydantic import ConfigDict, Field, model_validator

from app.contract_core import ContractModel
from app.conversation_contracts import MLPredictionAction
from app.ports.agent import AgentKind, AgentRequest, MLPredictionInvocation
from app.services.agent_supervisor import AgentDispatchError
from app.services.ml_prediction_service import MLRuntimeCapability


SUPERVISOR_EXECUTION_PLAN_VERSION = "SupervisorExecutionPlan.v2"


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


class SupervisorTaskPlan(ContractModel):
    """Terra가 한 Agent에 배정한 원문 범위 내의 실행 task다."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    agent: AgentKind
    objective: str = Field(min_length=1, max_length=240)
    analysis_route: Literal["ANALYSIS", "PRESENTATION"] | None = None
    presentation_type: Literal[
        "SUMMARY",
        "TABLE",
        "BAR",
        "LINE",
        "PIE",
        "HORIZONTAL_BAR",
        "DONUT",
    ] | None = None
    ml_prediction: MLPredictionAction | None = None

    @model_validator(mode="after")
    def validate_task_payload(self) -> "SupervisorTaskPlan":
        """ML task에만 구조화 예측 입력을 허용한다."""

        has_ml_input = self.ml_prediction is not None
        if (self.agent is AgentKind.ML_PREDICTION) != has_ml_input:
            raise ValueError("Supervisor ML task와 prediction 입력이 일치하지 않습니다.")
        if (
            self.presentation_type is not None
            and self.agent is not AgentKind.ANALYSIS_WORKFLOW
        ):
            raise ValueError("분석 Agent만 출력 표현 타입을 지정할 수 있습니다.")
        if (self.agent is AgentKind.ANALYSIS_WORKFLOW) != (
            self.analysis_route is not None
        ):
            raise ValueError("분석 Agent task에는 분석 라우트가 필요합니다.")
        return self


class SupervisorExecutionPlan(ContractModel):
    """한 command를 최대 세 개의 고유 Agent task로 분해한 strict 계획이다."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["SupervisorExecutionPlan.v2"] = (
        SUPERVISOR_EXECUTION_PLAN_VERSION
    )
    status: Literal["EXECUTABLE", "UNAVAILABLE"]
    tasks: tuple[SupervisorTaskPlan, ...] = Field(default=(), max_length=3)
    unavailable_reason: str | None = Field(default=None, min_length=1, max_length=240)

    @model_validator(mode="after")
    def validate_execution_plan(self) -> "SupervisorExecutionPlan":
        """실행 가능 계획과 안전한 미실행 계획을 완전히 분리한다."""

        if self.status == "UNAVAILABLE":
            if self.tasks or self.unavailable_reason is None:
                raise ValueError("미실행 계획은 task 없이 사유를 제공해야 합니다.")
            return self
        if not self.tasks or self.unavailable_reason is not None:
            raise ValueError("실행 계획은 task만 제공해야 합니다.")
        agents = tuple(task.agent for task in self.tasks)
        if len(agents) != len(set(agents)):
            raise ValueError("Supervisor 실행 계획에 중복 Agent가 있습니다.")
        return self


@dataclass(frozen=True)
class SupervisorPlanResult:
    """검증된 계획과 외부 응답을 원문 없이 봉인한 증거 참조다."""

    plan: SupervisorExecutionPlan
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


@dataclass(frozen=True)
class MaterializedSupervisorPlan:
    """같은 외부 계획 영수증에 결속된 하나 이상의 immutable Agent 요청이다."""

    requests: tuple[AgentRequest, ...]
    evidence_ref: str

    def __post_init__(self) -> None:
        if not self.requests or len(self.requests) > 3:
            raise ValueError("Supervisor 실행 요청 수가 올바르지 않습니다.")
        if any(
            request.supervisor_plan_ref != self.evidence_ref
            for request in self.requests
        ):
            raise ValueError("Supervisor 실행 요청과 계획 영수증이 일치하지 않습니다.")

    @property
    def is_composite(self) -> bool:
        """둘 이상의 Agent가 필요한 계획인지 반환한다."""

        return len(self.requests) > 1


def materialize_supervisor_plan(
    request: AgentRequest,
    result: SupervisorPlanResult,
    catalog: SupervisorCapabilityCatalog,
) -> MaterializedSupervisorPlan:
    """모델 task를 허용 Agent·ML 범위와 대조해 immutable 요청들로 만든다."""

    plan = result.plan
    if plan.status == "UNAVAILABLE":
        raise AgentDispatchError(
            "AGENT_ROUTE_NOT_RESOLVED",
            "현재 연결된 Agent만으로 요청을 안전하게 실행할 수 없습니다.",
            evidence_refs=(result.evidence_ref,),
        )
    requests: list[AgentRequest] = []
    for task in plan.tasks:
        if task.agent not in catalog.available_agents:
            raise AgentDispatchError(
                "AGENT_MODEL_PLAN_OUTSIDE_CAPABILITY",
                "Supervisor 계획이 현재 승인된 Agent 범위를 벗어났습니다.",
                evidence_refs=(result.evidence_ref,),
            )
        invocation = (
            MLPredictionInvocation(
                **task.ml_prediction.model_dump(mode="python")
            )
            if task.ml_prediction is not None
            else None
        )
        payload = request.model_dump(mode="python")
        payload.update(
            target_agent=task.agent,
            invocation=invocation,
            task_objective=task.objective,
            task_analysis_route=task.analysis_route,
            task_presentation_type=task.presentation_type,
            supervisor_plan_ref=result.evidence_ref,
        )
        requests.append(AgentRequest.model_validate(payload))
    return MaterializedSupervisorPlan(
        requests=tuple(requests),
        evidence_ref=result.evidence_ref,
    )
