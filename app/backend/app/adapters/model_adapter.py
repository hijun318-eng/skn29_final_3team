"""모델 노드 응답을 SQL plan·repair·설명 등 분석 pipeline의 typed 값으로 변환한다.

Contract adapter that maps model node responses into pipeline values.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any

from app.adapters.async_model_client import AsyncProductionModelClient
from app.adapters.model_context import (
    execution_time,
    metric_label,
    metric_selection,
    metric_unit,
    serialize_context_package,
)
from app.adapters.model_schemas import PROMPT_IDS
from app.adapters.model_transport import OpenAITransport, RoutedProductionModelClient
from src.ai.prompt_registry import get_prompt


logger = logging.getLogger("uvicorn.error")


def sql_fingerprint(sql: Any) -> str:
    """정규화한 SQL AST에서 감사와 중복 판정에 사용할 SHA-256 지문을 계산한다."""
    return hashlib.sha256(str(sql or "").encode("utf-8")).hexdigest()[:16]


class ContractModelAdapter:
    """검증된 모델 응답을 분석 pipeline의 SQL candidate·repair·설명 값으로 변환한다.

    모델이 선언한 lineage와 SQL은 신뢰하지 않고 G2/G3가 다시 검증할 candidate로만 반환한다.
    각 호출의 provider trace에 prompt ID·version·hash를 결합해 실제 실행 release를 보존한다.
    """

    def __init__(self, model: Any) -> None:
        if model is None:
            raise ValueError("a production model client is required")
        self._model = model
        self.last_trace: dict[str, Any] = {}

    @classmethod
    def from_openai(
        cls,
        endpoint: str,
        token: str | None = None,
        model: str = "",
        timeout_seconds: float = 15.0,
    ) -> ContractModelAdapter:
        """primary OpenAI route 하나를 모든 active node가 공유하는 adapter를 생성한다.

        endpoint·token·승인 model alias와 양수 timeout을 모두 요구하며, client는 schema와
        manifest capacity를 외부 호출 전에 검증한다. 누락 설정은 빈 fallback으로 대체하지 않는다.
        """
        if not endpoint or not token or not model:
            raise ValueError("OPENAI_ENDPOINT, OPENAI_API_KEY, and OPENAI_MODEL are required")
        if timeout_seconds <= 0:
            raise ValueError("MODEL_TIMEOUT_SECONDS must be positive")
        return cls(
            AsyncProductionModelClient(
                OpenAITransport(endpoint, token, model=model, provider="openai"),
                timeout_seconds=timeout_seconds,
                model_name=model,
            )
        )

    @classmethod
    def from_endpoints(
        cls,
        *,
        openai_endpoint: str,
        openai_token: str,
        openai_model: str,
        node2_endpoint: str,
        node2_token: str,
        node2_model: str,
        node2_provider: str,
        timeout_seconds: float = 60.0,
    ) -> ContractModelAdapter:
        """primary route와 Node2 전용 route를 분리한 adapter를 생성한다.

        두 route의 endpoint·token·model과 명시적 Node2 provider를 모두 요구한다. SQL 생성과
        repair만 전용 client로 보내며 primary credential로 조용히 대체하지 않는다.
        """
        if node2_provider not in {"openai", "qwen"}:
            raise ValueError(f"unsupported NODE2_MODEL_PROVIDER: {node2_provider}")
        if timeout_seconds <= 0:
            raise ValueError("MODEL_TIMEOUT_SECONDS must be positive")
        required = {
            "OPENAI_ENDPOINT": openai_endpoint,
            "OPENAI_API_KEY": openai_token,
            "OPENAI_MODEL": openai_model,
            "NODE2_MODEL_ENDPOINT": node2_endpoint,
            "NODE2_MODEL_API_TOKEN": node2_token,
            "NODE2_MODEL": node2_model,
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise ValueError(f"missing model configuration: {', '.join(missing)}")
        openai_client = AsyncProductionModelClient(
            OpenAITransport(
                openai_endpoint,
                openai_token,
                model=openai_model,
                provider="openai",
            ),
            timeout_seconds=timeout_seconds,
            model_name=openai_model,
        )
        node2_client = AsyncProductionModelClient(
            OpenAITransport(
                node2_endpoint,
                node2_token,
                model=node2_model,
                provider=node2_provider,
            ),
            timeout_seconds=timeout_seconds,
            max_attempts=3,
            model_name=node2_model,
        )
        return cls(RoutedProductionModelClient(openai_client, node2_client))

    async def normalize_question(self, payload: dict[str, Any]) -> dict[str, Any]:
        """question 값을 비교와 해시에 사용할 수 있는 표준 형태로 정규화한다."""
        return await self._generate("node1", payload)

    async def generate(self, node: str, payload: dict[str, Any]) -> dict[str, Any]:
        """노드별 governed payload를 active 모델 계약으로 변환하고 검증된 응답만 반환한다.

        Node 2는 runtime Context 여섯 계약과 lineage를 보존하며, repair와 설명 노드도 각자
        허용된 필드만 전달해 모델이 지표·SQL 권한 경계를 새로 만들지 못하게 한다.
        """
        if node == "node1":
            return await self.normalize_question(payload)
        if node == "node2":
            response = await self._generate(
                node,
                {
                    "question_id": payload["request_id"],
                    "normalized_question": payload["question"],
                    "structured_request": payload.get("structured_request") or {},
                    "context_package": serialize_context_package(payload),
                },
            )
            return self._plan(response, "sql", include_lineage=True)
        if node == "node2_repair":
            response = await self._generate(
                node,
                {
                    "trace_id": payload["trace_id"],
                    "attempt": payload["attempt"],
                    "rejected_sql": payload["rejected_sql"],
                    "normalized_question": payload["normalized_question"],
                    "structured_request": payload.get("structured_request") or {},
                    "context_package": serialize_context_package(payload),
                    "normalized_error_code": payload["violation"],
                    "violation_detail": payload["violation_detail"],
                    "repair_scope": ["sql"],
                },
            )
            return self._plan(response, "corrected_sql", include_lineage=False)
        if node == "node3":
            query = payload["query"]
            package = payload["package"]
            rows = query["rows"]
            selection = metric_selection(payload["assets"], package)
            selected_metric = selection["selected_metric_id"]
            response = await self._generate(
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
                    "metric": selected_metric,
                    "metric_label": metric_label(selected_metric, package),
                    "metric_selection": selection,
                    "period": execution_time(payload["context"], package),
                    "filters": [f"{key}={value}" for key, value in query.get("filters", {}).items()],
                    "unit": metric_unit(selected_metric, package),
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
                "model_version": self._trace_model_version(),
            }
        raise ValueError(f"unsupported node: {node}")

    async def _generate(self, node: str, payload: dict[str, Any]) -> dict[str, Any]:
        response = await self._model.generate(node, payload)
        transport_trace = dict(getattr(self._model, "last_trace", {}))
        prompt_metadata = get_prompt(PROMPT_IDS[node]).metadata()
        self.last_trace = {
            **transport_trace,
            "node": node,
            "prompt_id": prompt_metadata["prompt_id"],
            "prompt_version": prompt_metadata["version"],
            "prompt_hash": prompt_metadata["hash"],
        }
        if transport_trace.get("fallback"):
            raise TimeoutError("production model fallback is not a product result")
        return response

    async def aclose(self) -> None:
        """보유한 비동기 HTTP 연결과 transport 자원을 닫아 connection 누수를 막는다."""
        close = getattr(self._model, "aclose", None)
        if callable(close):
            await close()

    def _plan(
        self,
        response: dict[str, Any],
        sql_field: str,
        *,
        include_lineage: bool,
    ) -> dict[str, Any]:
        plan = {
            "sql": response[sql_field],
            "model_version": self._trace_model_version(),
        }
        if include_lineage:
            plan.update(
                declared_assets=list(response["used_assets"]),
                declared_columns=list(response["used_columns"]),
                declared_joins=list(response["used_joins"]),
                declared_metrics=list(response["used_metrics"]),
            )
        return plan

    def _trace_model_version(self) -> str:
        model_version = self.last_trace.get("model_version")
        if not isinstance(model_version, str) or not model_version:
            raise ValueError("production model trace is missing model_version")
        return model_version
