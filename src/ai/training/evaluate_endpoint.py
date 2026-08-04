"""Evaluate the product SQL-only vLLM contract against G2 and synthetic Trino."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import time
from pathlib import Path
from typing import Any, Callable

from src.ai.training.benchmark_serving import request_json
from src.ai.training.dataset import load_compiled, write_jsonl
from src.ai.training.evaluate_lora import DEFAULT_MODEL, DEFAULT_REVISION, _normalize_sql, _percentile
from src.ai.training.verify_case_specs import _runtime_package

from app.services.pipeline_support import PipelineSupport


Requester = Callable[[str, str, dict[str, Any] | None, str | None, float], dict[str, Any]]


def _schema(node: str) -> dict[str, Any]:
    field = "sql" if node == "node2" else "corrected_sql"
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [field],
        "properties": {field: {"type": "string"}},
    }


def evaluate_record(
    record: dict[str, Any],
    *,
    base_url: str,
    model: str,
    requester: Requester = request_json,
    timeout: float = 60,
    trino_container: str | None = None,
    trino_user: str = "hotel_analyst",
) -> dict[str, Any]:
    started = time.perf_counter()
    response = requester(
        "POST",
        f"{base_url.rstrip('/')}/v1/chat/completions",
        {
            "model": model,
            "messages": record["messages"][:-1],
            "temperature": 0,
            "max_tokens": 512,
            "chat_template_kwargs": {"enable_thinking": False},
            "guided_json": _schema(record["node"]),
        },
        None,
        timeout,
    )
    latency_ms = (time.perf_counter() - started) * 1_000
    content = response["choices"][0]["message"]["content"]
    try:
        generated = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return {"case_id": record["case_id"], "valid_json": False, "g2": "MODEL_SCHEMA_INVALID", "trino": "NOT_RUN", "sql_exact_match": False, "latency_ms": latency_ms}
    field = "sql" if record["node"] == "node2" else "corrected_sql"
    sql = generated.get(field) if isinstance(generated, dict) else None
    if not isinstance(sql, str) or not sql.strip():
        return {"case_id": record["case_id"], "valid_json": True, "g2": "MODEL_SCHEMA_INVALID", "trino": "NOT_RUN", "sql_exact_match": False, "latency_ms": latency_ms}

    payload = json.loads(record["messages"][1]["content"])
    context = payload["context_package"]
    queried = {
        table.strip('"').lower()
        for table in re.findall(r"\b(?:from|join)\s+([a-zA-Z0-9_.\"]+)", sql, re.IGNORECASE)
    }
    join_ids = [join["id"] for join in context["joins"]]
    references = [
        {
            "urn": asset["urn"],
            "fqn": asset["trino_fqn"],
            "columns": asset["columns"],
            "join_ids": join_ids,
        }
        for asset in context["assets"]
        if asset["trino_fqn"].lower() in queried
    ]
    g2 = PipelineSupport.g2_violation(
        {"sql": sql, "parameters": {}, "references": references},
        _runtime_package(context),
    )
    trino = "NOT_RUN"
    if g2 is None and trino_container:
        completed = subprocess.run(
            ["docker", "exec", trino_container, "trino", "--user", trino_user, "--execute", sql],
            capture_output=True,
            timeout=30,
        )
        trino = "PASS" if completed.returncode == 0 else "FAIL"
    expected = json.loads(record["messages"][2]["content"])[field]
    return {
        "case_id": record["case_id"],
        "valid_json": True,
        "g2": "PASS" if g2 is None else g2,
        "trino": trino,
        "sql_exact_match": _normalize_sql(sql) == _normalize_sql(expected),
        "latency_ms": latency_ms,
        "sql": sql,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--revision", default=DEFAULT_REVISION)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--trino-container")
    parser.add_argument("--trino-user", default="hotel_analyst")
    args = parser.parse_args()

    records = load_compiled(args.data, "validation")
    if args.limit is not None:
        records = records[: args.limit]
    predictions = [
        evaluate_record(
            record,
            base_url=args.base_url,
            model=args.model,
            trino_container=args.trino_container,
            trino_user=args.trino_user,
        )
        for record in records
    ]
    write_jsonl(args.output, predictions)
    latencies = [prediction["latency_ms"] for prediction in predictions]
    summary = {
        "model": args.model,
        "revision": args.revision,
        "total": len(predictions),
        "valid_json": sum(prediction["valid_json"] for prediction in predictions),
        "g2_pass": sum(prediction["g2"] == "PASS" for prediction in predictions),
        "trino_pass": sum(prediction["trino"] == "PASS" for prediction in predictions),
        "sql_exact_match": sum(prediction["sql_exact_match"] for prediction in predictions),
        "latency_p50_ms": _percentile(latencies, 50),
        "latency_p95_ms": _percentile(latencies, 95),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["valid_json"] == summary["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
