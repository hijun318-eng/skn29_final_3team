"""active model release의 노드 schema를 OpenAI strict JSON과 Qwen guided JSON payload로 조립한다.

Provider payload schemas built from governed runtime context.
"""

from __future__ import annotations

from functools import lru_cache
from types import MappingProxyType
from typing import Any

from src.ai.model_contracts import canonical_messages, model_release_manifest
from src.ai.schema import schema_definition
from src.modelops.runtime_config import load_model_runtime_manifest


_RELEASE_NODES = MappingProxyType(
    {
        name: MappingProxyType(dict(contract))
        for name, contract in model_release_manifest()["nodes"].items()
    }
)
PROMPT_IDS = MappingProxyType(
    {name: str(contract["prompt_id"]) for name, contract in _RELEASE_NODES.items()}
)


def request_definition(node: str) -> str:
    """모델 노드 요청이 따라야 할 JSON Schema definition을 반환한다."""
    try:
        return str(_RELEASE_NODES[node]["request_definition"])
    except KeyError as error:
        raise ValueError(f"unsupported model node: {node}") from error


def response_definition(node: str) -> str:
    """지정한 모델 노드 응답의 JSON Schema definition을 조회한다."""
    try:
        return str(_RELEASE_NODES[node]["response_definition"])
    except KeyError as error:
        raise ValueError(f"unsupported model node: {node}") from error


@lru_cache(maxsize=None)
def response_schema(node: str) -> dict[str, Any]:
    """노드 응답 definition을 독립 검증 가능한 JSON Schema로 조립한다."""
    return schema_definition(response_definition(node))


def serving_schema(node: str) -> dict[str, Any]:
    """서빙 엔드포인트가 반환해야 할 노드별 응답 스키마를 구성한다."""
    return response_schema(node)


def node2_training_input(payload: dict[str, Any]) -> dict[str, Any]:
    """Node 2 입력을 여섯 거버넌스 계약과 해결된 의도·지표·차원으로 정규화한다.

    요청의 선택값이 ``metric_rules``에 없는 경우 학습·서빙 입력이 서로 갈라지지 않도록
    ``ValueError``로 거부하며, 일반 생성과 한 번의 repair 입력을 각각 같은 형태로 만든다.
    """
    contracts = payload["context_package"]
    contract_names = {
        "schema_context",
        "metric_rules",
        "join_graph",
        "time_rules",
        "parameter_contract",
        "query_policy",
    }
    if not isinstance(contracts, dict) or set(contracts) != contract_names:
        raise ValueError("Node 2 requires all six governed context contracts")
    common = {name: contracts[name] for name in sorted(contract_names)}
    structured = payload.get("structured_request") or {}
    intents = list(structured.get("intent_candidates", ()))
    if len(intents) != 1 or not isinstance(intents[0], str):
        raise ValueError("Node 2 requires one resolved intent")
    metric_ids = list(structured.get("metric_ids", ()))
    if not metric_ids:
        metric_ids = [item["id"] for item in contracts["metric_rules"]]
    approved_metric_ids = {item["id"] for item in contracts["metric_rules"]}
    if set(metric_ids) != approved_metric_ids or len(metric_ids) != len(set(metric_ids)):
        raise ValueError("Node 2 metric resolution differs from metric_rules")
    dimensions = structured.get("dimension_fields", ())
    if not isinstance(dimensions, (list, tuple)):
        raise ValueError("Node 2 resolved dimensions must be structured fields")
    approved_dimensions = {
        (item["asset_fqn"], item["column"])
        for metric in contracts["metric_rules"]
        for item in metric["dimensions"]
    }
    filtered_dimensions = [
        dict(item)
        for item in dimensions
        if isinstance(item, dict)
        and (item.get("asset_fqn"), item.get("column")) in approved_dimensions
    ]
    seen_dims = set()
    unique_dims = []
    for item in filtered_dimensions:
        key = (item["asset_fqn"], item["column"])
        if key not in seen_dims:
            seen_dims.add(key)
            unique_dims.append(item)
    resolved_dimensions = unique_dims or [
        dict(item)
        for metric in contracts["metric_rules"]
        for item in metric["dimensions"]
    ]
    resolved_request = {
        "intent": intents[0],
        "metric_ids": list(metric_ids),
        "dimensions": resolved_dimensions,
        "filters": [
            dict(item)
            for metric in contracts["metric_rules"]
            for item in metric["required_filters"]
        ],
    }
    if "rejected_sql" in payload:
        return {
            "trace_id": payload["trace_id"],
            "attempt": payload["attempt"],
            "rejected_sql": payload["rejected_sql"],
            "normalized_question": payload["normalized_question"],
            "resolved_request": resolved_request,
            "normalized_error_code": payload["normalized_error_code"],
            "repair_scope": list(payload["repair_scope"]),
            **common,
        }
    return {
        "question_id": payload["question_id"],
        "normalized_question": payload["normalized_question"],
        "resolved_request": resolved_request,
        **common,
    }


def canonical_model_input(node: str, payload: dict[str, Any]) -> dict[str, Any]:
    """모델 입력 payload를 학습·서빙이 공유하는 표준 필드 순서로 정규화한다."""
    if node in {"node2", "node2_repair"} and "context_package" in payload:
        return node2_training_input(payload)
    return payload


_UNSUPPORTED_OPENAI_STRICT_KEYWORDS = frozenset({
    "minItems",
    "maxItems",
    "uniqueItems",
    "minLength",
    "maxLength",
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "multipleOf",
    "pattern",
    "if",
    "then",
    "else",
    "default",
    "$id",
    "$schema",
})


def to_openai_strict_schema(raw_schema: dict[str, Any]) -> dict[str, Any]:
    """표준 JSON Schema(Draft 2020-12)를 OpenAI Structured Outputs strict 규격으로 동적 변환한다.

    1. $defs 중 실제로 참조되는 정의만 트리쉐이킹(Tree-shaking)하여 보존
    2. OpenAI strict 모드 미지원 키워드(minItems, uniqueItems, pattern, minLength, minimum 등) 제거
    3. const -> enum 변환
    4. 모든 type: object에 additionalProperties: false 보장
    5. properties의 모든 키를 required에 포함하며, 기존 optional 필드는 nullable로 승격
    """
    defs = raw_schema.get("$defs", {})

    def collect_refs(s: Any) -> set[str]:
        refs: set[str] = set()
        if isinstance(s, dict):
            if "$ref" in s and isinstance(s["$ref"], str):
                ref = s["$ref"].rsplit("/", 1)[-1]
                refs.add(ref)
            for v in s.values():
                refs.update(collect_refs(v))
        elif isinstance(s, list):
            for item in s:
                refs.update(collect_refs(item))
        return refs

    used_defs: set[str] = set()
    frontier = collect_refs({k: v for k, v in raw_schema.items() if k != "$defs"})
    while frontier:
        nxt = frontier.pop()
        if nxt in defs and nxt not in used_defs:
            used_defs.add(nxt)
            frontier.update(collect_refs(defs[nxt]))

    def sanitize(node: Any) -> Any:
        if not isinstance(node, dict):
            if isinstance(node, list):
                return [sanitize(x) for x in node]
            return node

        result: dict[str, Any] = {}
        if "const" in node:
            result["enum"] = [node["const"]]

        for k, v in node.items():
            if k in _UNSUPPORTED_OPENAI_STRICT_KEYWORDS or k == "const" or k == "$defs":
                continue
            if k == "properties" and isinstance(v, dict):
                result["properties"] = {pk: sanitize(pv) for pk, pv in v.items()}
            elif k == "items":
                result["items"] = sanitize(v)
            elif k in {"anyOf", "oneOf", "allOf"} and isinstance(v, list):
                result[k] = [sanitize(item) for item in v]
            else:
                result[k] = sanitize(v)

        if result.get("type") == "object" or "properties" in result:
            result["type"] = "object"
            result["additionalProperties"] = False
            props = result.get("properties")
            if isinstance(props, dict):
                req = list(result.get("required", []))
                for pk, pval in props.items():
                    if pk not in req:
                        req.append(pk)
                        if isinstance(pval, dict):
                            if "type" in pval and isinstance(pval["type"], str) and pval["type"] != "null":
                                pval["type"] = [pval["type"], "null"]
                            elif "type" in pval and isinstance(pval["type"], list) and "null" not in pval["type"]:
                                pval["type"] = list(pval["type"]) + ["null"]
                            elif "$ref" in pval:
                                ref_val = pval.pop("$ref")
                                pval["anyOf"] = [{"$ref": ref_val}, {"type": "null"}]
                            elif "anyOf" in pval and isinstance(pval["anyOf"], list):
                                if not any(isinstance(x, dict) and x.get("type") == "null" for x in pval["anyOf"]):
                                    pval["anyOf"] = list(pval["anyOf"]) + [{"type": "null"}]
                            elif "enum" in pval and isinstance(pval["enum"], list):
                                if None not in pval["enum"]:
                                    pval["enum"] = list(pval["enum"]) + [None]
                result["required"] = req

        return result

    cleaned_root = sanitize({k: v for k, v in raw_schema.items() if k != "$defs"})
    if not isinstance(cleaned_root, dict):
        raise ValueError("Sanitized root schema must be a dict")
    if used_defs:
        cleaned_root["$defs"] = {name: sanitize(defs[name]) for name in sorted(used_defs)}
    return cleaned_root


adapt_schema_for_openai_strict = to_openai_strict_schema


@lru_cache(maxsize=None)
def openai_serving_schema(node: str) -> dict[str, Any]:
    """OpenAI Structured Outputs Strict 모드 규격으로 변환된 노드별 응답 스키마를 반환한다."""
    return to_openai_strict_schema(serving_schema(node))


@lru_cache(maxsize=None)
def guided_serving_schema(node: str) -> dict[str, Any]:
    """vLLM/sLLM Guided Decoding을 위한 원본 Draft 2020-12 JSON Schema를 반환한다."""
    return serving_schema(node)


def openai_payload(model: str, node: str, payload: dict[str, Any]) -> dict[str, Any]:
    """표준 메시지·strict JSON Schema·승인된 출력 한도를 OpenAI 요청으로 묶는다.

    출력 한도는 provider 코드에 다시 적지 않고 versioned runtime manifest의 model alias에서
    조회한다. 등록되지 않은 alias나 provider 불일치는 외부 호출 전에 ``ValueError``로 닫힌다.
    """
    output_limit = load_model_runtime_manifest().capacity_for(
        model,
        provider="openai",
    ).runtime_max_output_tokens
    return {
        "model": model,
        "messages": canonical_messages(PROMPT_IDS[node], payload),
        "max_completion_tokens": output_limit,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": f"answervice_{node}_response",
                "strict": True,
                "schema": openai_serving_schema(node),
            },
        },
    }


def qwen_payload(model: str, node: str, payload: dict[str, Any]) -> dict[str, Any]:
    """표준 메시지·guided JSON Schema·승인된 출력 한도를 Qwen 요청으로 묶는다.

    vLLM OpenAI-compatible API가 사용하는 ``max_tokens`` 값은 active serving alias에 결합된
    runtime manifest에서 가져와 context budget 계산과 실제 생성 요청이 같은 한도를 사용한다.
    """
    output_limit = load_model_runtime_manifest().capacity_for(
        model,
        provider="qwen",
    ).runtime_max_output_tokens
    return {
        "model": model,
        "messages": canonical_messages(PROMPT_IDS[node], payload),
        "temperature": 0,
        "max_tokens": output_limit,
        "chat_template_kwargs": {"enable_thinking": False},
        "guided_json": guided_serving_schema(node),
    }
