"""provider 공통 canonical 메시지와 active prompt/schema model release의 checksum 결합을 검증한다.

Canonical provider messages and the single active model contract release.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from functools import lru_cache
from hashlib import sha256
from pathlib import Path
from types import MappingProxyType
from typing import Any

from .prompt_registry import get_prompt
from .schema import (
    ContractError,
    schema_bundle,
    schema_definition,
    schema_sha256,
    schema_version,
)

_RELEASE_MANIFEST_PATH = (
    Path(__file__).with_name("contracts") / "model_release.v1.json"
)


def canonical_json(payload: Any) -> str:
    """입력 객체를 키 순서와 구분자가 고정된 표준 JSON으로 직렬화한다.

    Return the provider-independent representation of model input.
    """
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def canonical_json_sha256(payload: Any) -> str:
    """입력 객체의 표준 JSON 표현에서 재현 가능한 SHA-256 해시를 계산한다."""
    return sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def canonical_messages(prompt_id: str, payload: Any) -> list[dict[str, str]]:
    """messages 값을 비교와 해시에 사용할 수 있는 표준 형태로 정규화한다.

    Build byte-equivalent chat messages for every provider adapter.
    """
    return [
        {"role": "system", "content": get_prompt(prompt_id).text},
        {"role": "user", "content": canonical_json(payload)},
    ]


@lru_cache(maxsize=1)
def model_release_manifest() -> Mapping[str, Any]:
    """운영 모델 어댑터가 사용할 단일 ACTIVE release manifest를 검증해 읽는다.

    schema version·checksum, 노드 집합, prompt version·hash와 request/response definition이
    현재 코드 계약과 정확히 일치하지 않으면 ``ContractError``로 닫고 불변 mapping을 반환한다.
    """
    payload = json.loads(_RELEASE_MANIFEST_PATH.read_text(encoding="utf-8"))
    if set(payload) != {
        "manifest_version",
        "state",
        "schema_contract",
        "schema_version",
        "schema_sha256",
        "compatible_runtime",
        "nodes",
    }:
        raise ContractError("model release manifest fields are invalid")
    if (
        payload["manifest_version"] != "MODEL-RELEASE-v1.38.0"
        or payload["state"] != "ACTIVE"
        or payload["schema_contract"] != "v1"
        or payload["schema_version"] != schema_version()
        or payload["schema_sha256"] != schema_sha256()
        or set(payload["nodes"]) != _schema_model_nodes()
    ):
        raise ContractError("active model release metadata is invalid")
    compatible_runtime = payload["compatible_runtime"]
    if (
        not isinstance(compatible_runtime, dict)
        or set(compatible_runtime)
        != {
            "analysis_plan_version",
            "typed_sql_compiler_version",
            "canonical_semantic_release_version",
            "runtime_governance_version",
        }
        or any(
            not isinstance(value, str) or not value
            for value in compatible_runtime.values()
        )
    ):
        raise ContractError("active model runtime compatibility is invalid")

    for node in sorted(_schema_model_nodes()):
        entry = payload["nodes"][node]
        if set(entry) != {
            "prompt_id",
            "prompt_version",
            "prompt_sha256",
            "request_definition",
            "response_definition",
        }:
            raise ContractError(f"active {node} release fields are invalid")
        prompt_id = entry["prompt_id"]
        request_definition = f"{node}_request"
        response_definition = f"{node}_response"
        try:
            prompt = get_prompt(prompt_id)
        except KeyError as error:
            raise ContractError(f"active {node} prompt is not registered") from error
        expected_entry = {
            "prompt_id": prompt_id,
            "prompt_version": prompt.version,
            "prompt_sha256": prompt.metadata()["hash"],
            "request_definition": request_definition,
            "response_definition": response_definition,
        }
        if entry != expected_entry:
            raise ContractError(f"active {node} release hash is stale")
        if prompt.node != node:
            raise ContractError(f"active {node} prompt belongs to another node")
        schema_definition(request_definition)
        schema_definition(response_definition)
    return _freeze(payload)


@lru_cache(maxsize=1)
def model_release_checksum() -> str:
    """검증된 active model manifest 전체의 canonical SHA-256을 반환한다."""

    manifest = model_release_manifest()
    return canonical_json_sha256(_thaw(manifest))


def model_node_contract(node: str) -> Mapping[str, str]:
    """ACTIVE release에서 한 노드의 prompt·schema 식별자를 불변 mapping으로 조회한다.

    release에 없는 노드나 mapping이 아닌 entry는 지원되지 않는 계약으로 거부한다.
    """
    nodes = model_release_manifest()["nodes"]
    if not isinstance(nodes, Mapping):
        raise ContractError("active model release nodes are invalid")
    try:
        entry = nodes[node]
    except KeyError as error:
        raise ContractError(f"unsupported active model node: {node}") from error
    if not isinstance(entry, Mapping):
        raise ContractError(f"active {node} release entry is invalid")
    return entry


def _schema_model_nodes() -> set[str]:
    definitions = schema_bundle()["$defs"]
    request_nodes = {
        name.removesuffix("_request")
        for name in definitions
        if name.endswith("_request")
    }
    return {
        node for node in request_nodes if f"{node}_response" in definitions
    }


def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value
