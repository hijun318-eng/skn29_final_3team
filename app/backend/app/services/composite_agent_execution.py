"""복합 Agent 결과를 하나의 Conversation terminal에 원자적으로 결합한다."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from copy import deepcopy
from dataclasses import dataclass
import re
from typing import Any

from app.ports.agent import AgentKind


TerminalWriter = Callable[[Any], Awaitable[None]]


@dataclass(frozen=True)
class CompositeExecutionAugmentation:
    """이미 검증·실행된 보조 Agent 결과와 영속 writer를 대표 Agent에 전달한다."""

    primary_agent: AgentKind
    agents: tuple[AgentKind, ...]
    plan_ref: str
    evidence_refs: tuple[str, ...]
    rag_response: dict[str, Any] | None = None
    ml_prediction: dict[str, Any] | None = None
    terminal_writer: TerminalWriter | None = None

    def __post_init__(self) -> None:
        if not 2 <= len(self.agents) <= 3 or len(self.agents) != len(set(self.agents)):
            raise ValueError("복합 Agent 목록이 올바르지 않습니다.")
        if self.primary_agent not in self.agents:
            raise ValueError("복합 실행의 대표 Agent가 계획에 없습니다.")
        if re.fullmatch(r"model-supervisor:sha256:[0-9a-f]{64}", self.plan_ref) is None:
            raise ValueError("복합 실행 계획 영수증이 올바르지 않습니다.")
        if (
            not self.evidence_refs
            or self.plan_ref not in self.evidence_refs
            or len(self.evidence_refs) != len(set(self.evidence_refs))
            or any(not isinstance(item, str) or not item for item in self.evidence_refs)
        ):
            raise ValueError("복합 실행 capability 근거가 올바르지 않습니다.")
        has_ml = AgentKind.ML_PREDICTION in self.agents
        if has_ml != (self.ml_prediction is not None):
            raise ValueError("복합 ML 결과가 Agent 계획과 일치하지 않습니다.")
        needs_prepared_rag = (
            AgentKind.INTERNAL_GUIDELINE in self.agents
            and self.primary_agent is not AgentKind.INTERNAL_GUIDELINE
        )
        if needs_prepared_rag != (self.rag_response is not None):
            raise ValueError("복합 RAG 결과가 대표 Agent와 일치하지 않습니다.")

    def resolved_slots(self) -> dict[str, Any]:
        """원문 없이 plan·capability lineage와 보조 결과만 저장 계약으로 반환한다."""

        payload: dict[str, Any] = {
            "supervisor_composition": {
                "schema_version": "SupervisorCompositionReceipt.v1",
                "plan_ref": self.plan_ref,
                "primary_agent": self.primary_agent.value,
                "agents": [agent.value for agent in self.agents],
                "evidence_refs": list(self.evidence_refs),
            }
        }
        if self.rag_response is not None:
            payload["rag"] = deepcopy(self.rag_response)
        if self.ml_prediction is not None:
            payload["ml_prediction"] = deepcopy(self.ml_prediction)
        return payload

    def public_fields(self) -> dict[str, Any]:
        """기존 단일 Agent 응답과 함께 노출할 typed 조합 결과를 만든다."""

        slots = self.resolved_slots()
        return {
            "type": "COMPOSITE",
            "composition": slots["supervisor_composition"],
            "rag_response": slots.get("rag"),
            "ml_prediction": slots.get("ml_prediction"),
        }

    def chain_terminal_writer(
        self,
        primary_writer: TerminalWriter | None,
    ) -> TerminalWriter | None:
        """대표 Agent와 추가 영속 작업을 동일 transaction의 단일 writer로 합친다."""

        if self.terminal_writer is None:
            return primary_writer

        async def _write(session: Any) -> None:
            if primary_writer is not None:
                await primary_writer(session)
            await self.terminal_writer(session)

        return _write
