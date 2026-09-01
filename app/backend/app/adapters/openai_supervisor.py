"""OpenAI Responses API의 strict output으로 Terra Supervisor 계획을 생성한다."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
from typing import Any

import httpx
from pydantic import ValidationError

from app.adapters.async_model_client import (
    ModelAuthenticationError,
    ModelRateLimitError,
    ModelRequestRejectedError,
)
from app.adapters.model_schemas import to_openai_strict_schema
from app.adapters.model_transport import _request_json, _validated_https_url
from app.ports.agent import AgentKind, AgentRequest, canonical_agent_request_fingerprint
from app.services.agent_supervisor import AgentDispatchError
from app.services.supervisor_planner import (
    SupervisorCapabilityCatalog,
    SupervisorExecutionPlan,
    SupervisorPlanResult,
)


SUPERVISOR_MODEL = "gpt-5.6-terra"
SUPERVISOR_RESPONSE_SCHEMA_NAME = "answervice_supervisor_execution_plan_v2"
_REASONING_EFFORTS = frozenset({"none", "low", "medium", "high", "xhigh", "max"})
_AGENT_DESCRIPTIONS = {
    AgentKind.ANALYSIS_WORKFLOW: (
        "승인된 정형 데이터 지표를 조회·집계·비교하고 기존 분석 결과의 표·차트 표현을 변경한다."
    ),
    AgentKind.INTERNAL_GUIDELINE: (
        "승인된 내부 문서·지침·월간 보고서에서 근거를 검색해 문서 기반 설명을 만든다."
    ),
    AgentKind.ML_PREDICTION: (
        "검증된 HGBR runtime으로 지원 property의 미래 객실 수요를 예측한다."
    ),
}
_INSTRUCTIONS = """당신은 Answervice의 실행 계획 Supervisor입니다.
답변이나 데이터 분석을 직접 수행하지 말고 제공된 JSON Schema의 계획 하나만 반환하세요.
한 command를 실제로 필요한 고유 Agent task 1~3개로만 분해하세요. 같은 Agent를 반복하지 마세요.
ANALYSIS_WORKFLOW는 승인된 정형 지표 분석과 이전 분석의 표·차트 변경에 사용합니다.
INTERNAL_GUIDELINE은 내부 문서 근거가 필요한 질문에 사용합니다.
ML_PREDICTION은 제공된 ML scope 안의 미래 객실 수요 예측에만 사용하고 구조화 입력을 채웁니다.
각 objective는 사용자 문장에서 해당 Agent가 처리할 범위만 간결하게 다시 쓰되,
기간·지표·대상·명시한 문서 종류는 생략하거나 일반화하지 마세요.
직전 route와 previous_analysis·previous_ml은 생략된 후속 요청의 문맥을 판정할 때만 사용하세요.
previous_analysis는 서버가 확정한 이전 분석 지표·기간이며 새 사실로 간주하지 마세요.
previous_analysis를 사용한 task의 objective에는 metric_ids와 정확한 시작일·종료일을 포함하세요.
previous_ml은 서버가 확정한 직전 성공 예측의 입력 범위이며 예측 결과가 아닙니다.
직전 route가 ML_PREDICTION이고 사용자가 같은 예측의 그래프·표·모델·한계 설명을 요구하면,
previous_ml의 property_id·as_of·horizon_days를 그대로 사용한 ML_PREDICTION task를 계획하세요.
사용자가 새 예측 조건을 명시한 경우에만 previous_ml 대신 새 조건을 사용하세요.
필수 입력이 없거나 필요한 Agent가 unavailable이면 다른 Agent로 대체하지 말고
status=UNAVAILABLE, tasks=[]와 사유를 반환하세요. 실행 가능하면 status=EXECUTABLE로 반환하세요."""


def _response_text(response: dict[str, Any]) -> str:
    """Responses API output에서 유일한 assistant output_text만 추출한다."""

    if response.get("status") != "completed" or response.get("error") not in (None, {}):
        raise ValueError("supervisor response did not complete")
    output = response.get("output")
    if not isinstance(output, list):
        raise ValueError("supervisor response output must be an array")
    texts: list[str] = []
    for item in output:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if (
                isinstance(part, dict)
                and part.get("type") == "output_text"
                and isinstance(part.get("text"), str)
                and part["text"].strip()
            ):
                texts.append(part["text"].strip())
    if len(texts) != 1:
        raise ValueError("supervisor response must contain one output_text")
    return texts[0]


class OpenAISupervisorPlanner:
    """Terra가 만든 계획을 strict schema와 서버 capability로 검증한다."""

    def __init__(
        self,
        endpoint: str,
        token: str,
        *,
        model: str = SUPERVISOR_MODEL,
        reasoning_effort: str = "medium",
        timeout_seconds: float = 15.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._endpoint = _validated_https_url(
            endpoint,
            label="supervisor model endpoint",
        ).rstrip("/")
        if not isinstance(token, str) or not token.strip():
            raise ValueError("supervisor model token is required")
        if model != SUPERVISOR_MODEL:
            raise ValueError(f"supervisor model must be {SUPERVISOR_MODEL}")
        if reasoning_effort not in _REASONING_EFFORTS:
            raise ValueError("supervisor reasoning effort is invalid")
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(float(timeout_seconds))
            or not 0 < float(timeout_seconds) <= 15
        ):
            raise ValueError("supervisor timeout must be between 0 and 15 seconds")
        if client is not None and not isinstance(
            getattr(client, "_transport", None),
            httpx.MockTransport,
        ):
            raise ValueError("Only httpx.MockTransport may be injected")
        self._token = token.strip()
        self._model = model
        self._reasoning_effort = reasoning_effort
        self._timeout_seconds = float(timeout_seconds)
        self._client = client

    async def plan(
        self,
        request: AgentRequest,
        catalog: SupervisorCapabilityCatalog,
        *,
        previous_route: str | None,
    ) -> SupervisorPlanResult:
        """원문 질문과 최소 capability metadata만 전송하고 계획을 봉인한다."""

        if not isinstance(request, AgentRequest) or not isinstance(
            catalog,
            SupervisorCapabilityCatalog,
        ):
            raise TypeError("Supervisor planner 입력 계약이 올바르지 않습니다.")
        model_input = {
            "question": request.command.user_message,
            "request_as_of": request.context.as_of.isoformat(),
            "timezone": request.context.timezone,
            "previous_route": previous_route,
            "previous_analysis": (
                request.previous_analysis.model_dump(mode="json")
                if request.previous_analysis is not None
                else None
            ),
            "previous_ml": (
                request.previous_ml.model_dump(mode="json")
                if request.previous_ml is not None
                else None
            ),
            "available_capabilities": [
                {
                    "agent": agent.value,
                    "description": _AGENT_DESCRIPTIONS[agent],
                }
                for agent in catalog.available_agents
            ],
            "unavailable_agents": [
                agent.value for agent in catalog.unavailable_agents
            ],
            "ml_scope": {
                "properties": [
                    item.model_dump(mode="json")
                    for item in catalog.ml_properties
                ],
                "min_horizon_days": catalog.ml_min_horizon_days,
                "max_horizon_days": catalog.ml_max_horizon_days,
            },
        }
        payload = {
            "model": self._model,
            "instructions": _INSTRUCTIONS,
            "input": json.dumps(
                model_input,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ),
            "reasoning": {
                "effort": self._reasoning_effort,
                "context": "current_turn",
            },
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": SUPERVISOR_RESPONSE_SCHEMA_NAME,
                    "strict": True,
                    "schema": to_openai_strict_schema(
                        SupervisorExecutionPlan.model_json_schema()
                    ),
                }
            },
            "max_output_tokens": 600,
            "store": False,
            "truncation": "disabled",
            "safety_identifier": hashlib.sha256(
                f"answervice-supervisor:{request.context.user_id}".encode("utf-8")
            ).hexdigest(),
        }
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(trust_env=False)
        try:
            response = await _request_json(
                client,
                "POST",
                f"{self._endpoint}/v1/responses",
                payload,
                self._token,
                self._timeout_seconds,
            )
            response_id = response.get("id")
            response_model = response.get("model")
            if (
                not isinstance(response_id, str)
                or not response_id.strip()
                or not isinstance(response_model, str)
                or not response_model.strip()
            ):
                raise ValueError("supervisor response identity is invalid")
            plan = SupervisorExecutionPlan.model_validate_json(
                _response_text(response)
            )
        except asyncio.CancelledError:
            raise
        except ModelAuthenticationError as error:
            raise AgentDispatchError(
                "AGENT_SUPERVISOR_AUTHENTICATION_FAILED",
                "Supervisor 모델 인증을 확인하지 못했습니다.",
            ) from error
        except ModelRateLimitError as error:
            raise AgentDispatchError(
                "AGENT_SUPERVISOR_RATE_LIMITED",
                "Supervisor 모델 호출 한도에 도달했습니다.",
            ) from error
        except ModelRequestRejectedError as error:
            raise AgentDispatchError(
                "AGENT_SUPERVISOR_REQUEST_REJECTED",
                "Supervisor 모델이 계획 요청을 거부했습니다.",
            ) from error
        except TimeoutError as error:
            raise AgentDispatchError(
                "AGENT_SUPERVISOR_TIMEOUT",
                "Supervisor 모델 계획 시간이 초과되었습니다.",
            ) from error
        except (OSError, ValueError, ValidationError, json.JSONDecodeError) as error:
            raise AgentDispatchError(
                "AGENT_SUPERVISOR_CONTRACT_INVALID",
                "Supervisor 모델 계획을 검증하지 못했습니다.",
            ) from error
        finally:
            if owns_client:
                await client.aclose()

        canonical = {
            "schema_version": "OpenAISupervisorPlanReceipt.v1",
            "request_fingerprint": canonical_agent_request_fingerprint(request),
            "catalog": catalog.model_dump(mode="json"),
            "previous_route": previous_route,
            "requested_model": self._model,
            "response_model": response_model,
            "response_id": response_id,
            "plan": plan.model_dump(mode="json"),
        }
        digest = hashlib.sha256(
            json.dumps(
                canonical,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()
        return SupervisorPlanResult(
            plan=plan,
            evidence_ref=f"model-supervisor:sha256:{digest}",
            model=response_model,
            response_id=response_id,
        )


def openai_supervisor_planner_from_env() -> OpenAISupervisorPlanner:
    """Supervisor가 활성화된 프로세스의 명시 설정을 검증해 planner를 만든다."""

    endpoint = os.getenv("SUPERVISOR_OPENAI_ENDPOINT", "").strip()
    token = os.getenv("SUPERVISOR_OPENAI_API_KEY", "").strip()
    model = os.getenv("SUPERVISOR_OPENAI_MODEL", SUPERVISOR_MODEL).strip()
    effort = os.getenv("SUPERVISOR_REASONING_EFFORT", "medium").strip().lower()
    raw_timeout = os.getenv("SUPERVISOR_TIMEOUT_SECONDS", "15").strip()
    try:
        timeout = float(raw_timeout)
        return OpenAISupervisorPlanner(
            endpoint,
            token,
            model=model,
            reasoning_effort=effort,
            timeout_seconds=timeout,
        )
    except (TypeError, ValueError) as error:
        raise AgentDispatchError(
            "AGENT_SUPERVISOR_CONFIGURATION_INVALID",
            "Supervisor 모델 설정이 올바르지 않습니다.",
        ) from error
