#!/usr/bin/env python3
"""격리된 Node2 vLLM endpoint에 보류 검증 record 한 건을 보내 SQL exact match를 확인한다."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import time
from pathlib import Path
from typing import Any

import httpx


def _load_record(path: Path, index: int) -> dict[str, Any]:
    with path.open(encoding="utf-8") as source:
        for current, line in enumerate(source):
            if current == index:
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise ValueError("validation record must be an object")
                return value
    raise ValueError(f"validation index is out of range: {index}")


def _assistant_json(record: dict[str, Any]) -> dict[str, Any]:
    messages = record.get("messages")
    if not isinstance(messages, list):
        raise ValueError("validation record has no messages")
    assistant = [message for message in messages if message.get("role") == "assistant"]
    if len(assistant) != 1 or not isinstance(assistant[0].get("content"), str):
        raise ValueError("validation record must have one assistant answer")
    value = json.loads(assistant[0]["content"])
    if not isinstance(value, dict):
        raise ValueError("assistant answer must be a JSON object")
    return value


def _request_payload(record: dict[str, Any], model: str) -> dict[str, Any]:
    messages = [
        message for message in record["messages"] if message.get("role") != "assistant"
    ]
    return {
        "model": model,
        "messages": messages,
        "temperature": 0,
        "max_tokens": 1024,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "node2_sql_only_response",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {"sql": {"type": "string"}},
                    "required": ["sql"],
                    "additionalProperties": False,
                },
            },
        },
    }


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


async def _post_json(
    base_url: str,
    payload: dict[str, Any],
    timeout: float,
) -> tuple[int, dict[str, Any]]:
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(
            f"{base_url.rstrip('/')}/v1/chat/completions",
            json=payload,
        )
    value = response.json()
    if not isinstance(value, dict):
        raise ValueError("vLLM response must be a JSON object")
    return response.status_code, value


def main() -> int:
    """보류 record를 한 번 추론해 HTTP·schema·SQL 일치 결과만 영수증으로 남긴다."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--index", type=int, default=0)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--model", required=True)
    parser.add_argument("--timeout", type=float, default=240.0)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    try:
        record = _load_record(args.dataset, args.index)
        expected = _assistant_json(record)
        payload = _request_payload(record, args.model)
        started = time.perf_counter()
        http_status, response_json = asyncio.run(
            _post_json(args.base_url, payload, args.timeout)
        )
        elapsed = time.perf_counter() - started
        content = response_json["choices"][0]["message"]["content"]
        actual = json.loads(content)
        valid_schema = (
            isinstance(actual, dict)
            and set(actual) == {"sql"}
            and isinstance(actual["sql"], str)
            and bool(actual["sql"])
        )
        sql_exact_match = valid_schema and actual["sql"] == expected.get("sql")
        passed = http_status == 200 and valid_schema and sql_exact_match
        result = {
            "status": "PASS_SMOKE" if passed else "FAIL_SMOKE",
            "case_id": record.get("case_id"),
            "http_status": http_status,
            "elapsed_seconds": round(elapsed, 3),
            "response_format": "json_schema",
            "valid_schema": valid_schema,
            "sql_exact_match": sql_exact_match,
            "finish_reason": response_json.get("choices", [{}])[0].get(
                "finish_reason"
            ),
            "usage": response_json.get("usage"),
            "actual_sql_sha256": (
                _sha256_text(actual["sql"]) if valid_schema else None
            ),
            "expected_sql_sha256": _sha256_text(str(expected.get("sql", ""))),
            "production_switch_allowed": False,
        }
        if valid_schema and not sql_exact_match:
            result["sql_mismatch"] = {
                "actual": actual["sql"],
                "expected": expected.get("sql"),
            }
        exit_code = 0 if passed else 1
    except Exception as error:
        result = {
            "status": "FAIL_SMOKE",
            "error": f"{type(error).__name__}: {error}",
            "production_switch_allowed": False,
        }
        exit_code = 1

    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
