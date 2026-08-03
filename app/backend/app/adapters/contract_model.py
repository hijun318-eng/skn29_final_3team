from __future__ import annotations

import json
from datetime import datetime, time
from functools import lru_cache, partial
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from src.ai import schema as ai_schema
from src.ai.fake_model import FakeModelAdapter as R3FakeModelAdapter
from src.ai.prompt_registry import get_prompt
from src.ai.training.benchmark_serving import request_json
from src.modelops.runtime import ProductionModelClient


_PROMPT_IDS = {
    "node2": "node2.sql",
    "node2_repair": "node2.repair",
    "node3": "node3.explain",
}


@lru_cache(maxsize=None)
def _response_schema(node: str) -> dict[str, Any]:
    path = Path(ai_schema.__file__).with_name("contracts") / "node_io.v0.1.json"
    with path.open(encoding="utf-8") as schema_file:
        bundle = json.load(schema_file)
    return {"$defs": bundle["$defs"], **bundle["$defs"][f"{node}_response"]}


def openai_transport(
    endpoint: str,
    token: str | None,
    node: str,
    payload: dict[str, Any],
    timeout: float,
) -> dict[str, Any]:
    response = request_json(
        "POST",
        f"{endpoint.rstrip('/')}/v1/chat/completions",
        {
            "model": "Qwen/Qwen3-4B",
            "messages": [
                {"role": "system", "content": get_prompt(_PROMPT_IDS[node]).text},
                {
                    "role": "user",
                    "content": json.dumps(
                        payload,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                },
            ],
            "temperature": 0,
            "max_tokens": 1_500,
            "chat_template_kwargs": {"enable_thinking": False},
            "guided_json": _response_schema(node),
        },
        token,
        timeout,
    )
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("chat completion response has no choices")
    message = choices[0].get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str):
        raise ValueError("chat completion response has no text content")
    result = json.loads(content)
    if not isinstance(result, dict):
        raise ValueError("model content must be a JSON object")
    return result


class ContractModelAdapter:
    """R3 동결 schema와 R4 내부 plan 형식을 연결한다."""

    def __init__(self, model=None) -> None:
        self._model = model or R3FakeModelAdapter()

    @classmethod
    def from_openai(
        cls,
        endpoint: str,
        token: str | None = None,
        timeout_seconds: float = 15.0,
    ) -> ContractModelAdapter:
        if not endpoint:
            raise ValueError("MODEL_ENDPOINT is required in openai mode")
        return cls(
            ProductionModelClient(
                partial(openai_transport, endpoint, token),
                timeout_seconds=timeout_seconds,
            )
        )

    def generate(self, node: str, payload: dict[str, Any]) -> dict[str, Any]:
        if node == "node2":
            response = self._generate(
                node,
                {
                    "question_id": payload["request_id"],
                    "normalized_question": payload["question"],
                    "context_package": self._context_package(payload),
                },
            )
            return self._plan(response, "sql")
        if node == "node2_repair":
            response = self._generate(
                node,
                {
                    "trace_id": payload["trace_id"],
                    "attempt": 1,
                    "rejected_sql": payload["rejected_sql"],
                    "context_package": self._context_package(payload),
                    "normalized_error_code": payload["violation"],
                    "repair_scope": ["sql"],
                },
            )
            return self._plan(response, "corrected_sql")
        if node == "node3":
            query = payload["query"]
            context = payload["context"]
            rows = query["rows"]
            response = self._generate(
                node,
                {
                    "g3_result": "pass",
                    "shaped_result": {
                        "columns": [
                            {"name": name, "type": "scalar"}
                            for name in (rows[0] if rows else ())
                        ],
                        "rows": rows,
                    },
                    "metric": "recognized_room_revenue_krw",
                    "period": self._execution_time(context),
                    "filters": [
                        f"{key}={value}"
                        for key, value in query.get("filters", {}).items()
                    ],
                    "unit": "KRW",
                    "sampling": bool(query.get("sampling", {}).get("applied")),
                    "masking": bool(query.get("masking", {}).get("applied")),
                    "partial": query.get("status") == "PARTIAL",
                    "source_ids": [item["urn"] for item in payload["assets"]],
                    "result_reference": {
                        "kind": "query_execution_id",
                        "value": str(query["query_id"]),
                    },
                },
            )
            return {
                "summary": response["explanation"],
                "model_version": response["model"]["model_version"],
            }
        raise ValueError(f"unsupported node: {node}")

    def _generate(self, node: str, payload: dict[str, Any]) -> dict[str, Any]:
        response = self._model.generate(node, payload)
        if getattr(self._model, "last_trace", {}).get("fallback"):
            raise TimeoutError("production model fallback is not a product result")
        return response

    @staticmethod
    def _plan(response: dict[str, Any], sql_field: str) -> dict[str, Any]:
        return {
            "sql": response[sql_field],
            "references": [
                {
                    "urn": item["urn"],
                    "fqn": item["trino_fqn"],
                    "columns": item["columns"],
                }
                for item in response["references"]
            ],
            "parameters": {
                item["name"]: item["value"]
                for item in response["parameters"]
            },
            "model_version": response["model"]["model_version"],
        }

    @classmethod
    def _context_package(cls, payload: dict[str, Any]) -> dict[str, Any]:
        package = payload["package"]
        context = payload["context"]
        assets = [
            {
                "urn": item.urn,
                "trino_fqn": item.fqn,
                "columns": list(item.columns),
            }
            for item in package.assets
        ]
        return {
            "context_version": package.context_release,
            "policy_version": package.policy_version,
            "execution_time": cls._execution_time(context),
            "assets": assets,
            "metrics": [
                {
                    "id": "recognized_room_revenue_krw",
                    "field": "pms.public.pms_stays.room_revenue",
                    "aggregation": "sum",
                    "time_field": "pms.public.pms_stays.actual_checkout_at",
                }
            ],
            "joins": [
                {
                    "id": "pms_stay_to_crm_membership_grade_event_time_v1",
                    "left": "pms.public.pms_stays",
                    "right": "crm.dbo.crm_member_grade_history",
                    "cardinality": "many_to_zero_or_one",
                    "status": "approved",
                }
            ],
        }

    @staticmethod
    def _execution_time(context) -> dict[str, str]:
        timezone = ZoneInfo(context.timezone)
        as_of = datetime.combine(context.as_of, time.min, timezone)
        period_start = as_of.replace(day=1)
        return {
            "as_of": as_of.isoformat(),
            "timezone": context.timezone,
            "calendar_id": "gregorian-kr",
            "period_start": period_start.isoformat(),
            "period_end_exclusive": as_of.isoformat(),
        }
