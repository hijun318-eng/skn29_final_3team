"""Evaluate the product SQL-only vLLM contract against G2 and synthetic Trino."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import time
from pathlib import Path
from typing import Any, Callable

from src.ai.training.benchmark_serving import request_json
from src.ai.training.dataset import load_compiled, write_jsonl
from src.ai.training.evaluate_lora import (
    DEFAULT_MODEL,
    DEFAULT_REVISION,
    _normalize_sql,
    _percentile,
    observed_metrics,
)
from src.ai.training.verify_case_specs import (
    PlanContractError,
    _context_plan,
    _declared_parameters,
    _result_hash,
)

from app.adapters.i2_data_platform import I2DataPlatformAdapter
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


def _run_trino(
    sql: str,
    parameters: dict[str, Any],
    container: str,
    user: str,
) -> tuple[str, str | None, str | None]:
    sql = I2DataPlatformAdapter._bind_parameters(sql, parameters)
    completed = subprocess.run(
        [
            "docker",
            "exec",
            container,
            "trino",
            "--server",
            "http://localhost:8080",
            "--user",
            user,
            "--output-format",
            "JSON",
            "--execute",
            sql,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    if completed.returncode:
        lines = [line for line in (completed.stderr or completed.stdout).splitlines() if line.strip()]
        return "FAIL", None, "\n".join(lines[-4:])
    return "PASS", _result_hash(completed.stdout), None


def _references(sql: str, context: dict[str, Any]) -> list[dict[str, Any]]:
    queried = {
        table.strip('"').lower()
        for table in re.findall(r"\b(?:from|join)\s+([a-zA-Z0-9_.\"]+)", sql, re.IGNORECASE)
    }
    join_ids = [join["id"] for join in context["joins"]]
    metric_ids = [metric["id"] for metric in context["metrics"]]
    return [
        {
            "urn": asset["urn"],
            "fqn": asset["trino_fqn"],
            "columns": asset["columns"],
            "join_ids": join_ids,
            "metric_ids": metric_ids,
        }
        for asset in context["assets"]
        if asset["trino_fqn"].lower() in queried
    ]


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
    choice = response["choices"][0]
    content = choice["message"]["content"]
    evidence = {
        "case_id": record["case_id"],
        "domain": record["domain"],
        "node": record["node"],
        "evaluation_slice": record.get("evaluation_slice"),
        "latency_ms": latency_ms,
        "finish_reason": choice.get("finish_reason"),
        "completion_tokens": response.get("usage", {}).get("completion_tokens"),
        "content_sha256": hashlib.sha256(str(content).encode()).hexdigest(),
    }
    try:
        generated = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return {**evidence, "valid_json": False, "g2": "MODEL_SCHEMA_INVALID", "expected_g2": "NOT_RUN", "trino": "NOT_RUN", "result_match": "NOT_RUN", "sql_exact_match": False}
    field = "sql" if record["node"] == "node2" else "corrected_sql"
    sql = generated.get(field) if isinstance(generated, dict) else None
    if not isinstance(sql, str) or not sql.strip():
        return {**evidence, "valid_json": True, "g2": "MODEL_SCHEMA_INVALID", "expected_g2": "NOT_RUN", "trino": "NOT_RUN", "result_match": "NOT_RUN", "sql_exact_match": False}

    payload = json.loads(record["messages"][1]["content"])
    context = payload["context_package"]
    try:
        generated_plan, package = _context_plan(sql, context, _references(sql, context))
        g2 = PipelineSupport.g2_violation(generated_plan, package)
    except (PlanContractError, KeyError, ValueError) as error:
        generated_plan = None
        g2 = error.code if isinstance(error, PlanContractError) else "PARAMETERS_INVALID"
    expected_payload = json.loads(record["messages"][2]["content"])
    expected = expected_payload[field]
    try:
        expected_plan, expected_package = _context_plan(
            expected,
            context,
            _references(expected, context),
            _declared_parameters(expected_payload),
        )
        expected_g2 = PipelineSupport.g2_violation(expected_plan, expected_package)
    except (PlanContractError, KeyError, ValueError) as error:
        expected_plan = None
        expected_g2 = error.code if isinstance(error, PlanContractError) else "PARAMETERS_INVALID"
    trino = "NOT_RUN"
    generated_hash = None
    expected_hash = None
    trino_error = None
    result_match: bool | str = "NOT_RUN"
    if g2 is None and expected_g2 is None and trino_container:
        trino, generated_hash, trino_error = _run_trino(
            generated_plan["sql"], generated_plan["parameters"], trino_container, trino_user
        )
        if trino == "PASS":
            expected_status, expected_hash, _ = _run_trino(
                expected_plan["sql"], expected_plan["parameters"], trino_container, trino_user
            )
            result_match = expected_status == "PASS" and generated_hash == expected_hash
    return {
        **evidence,
        "valid_json": True,
        "g2": "PASS" if g2 is None else g2,
        "expected_g2": "PASS" if expected_g2 is None else expected_g2,
        "trino": trino,
        "result_match": result_match,
        "generated_result_sha256": generated_hash,
        "expected_result_sha256": expected_hash,
        "trino_error": trino_error,
        "sql_exact_match": _normalize_sql(sql) == _normalize_sql(expected),
        "sql": sql,
    }


def _select_manifest_records(records: list[dict[str, Any]], manifest: dict[str, Any]) -> list[dict[str, Any]]:
    by_id = {record["case_id"]: record for record in records}
    selected = []
    for case in manifest["cases"]:
        record = by_id.get(case["case_id"])
        if record is None:
            raise ValueError(f"manifest case is absent from dataset: {case['case_id']}")
        selected.append({**record, "evaluation_slice": case["evaluation_slice"]})
    return selected


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--revision", default=DEFAULT_REVISION)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--trino-container")
    parser.add_argument("--trino-user", default="hotel_analyst")
    args = parser.parse_args()

    records = load_compiled(args.data, "validation")
    if args.manifest:
        records = _select_manifest_records(records, json.loads(args.manifest.read_text(encoding="utf-8")))
    if args.limit is not None:
        records = records[: args.limit]
    predictions = []
    for index, record in enumerate(records, 1):
        prediction = evaluate_record(
            record,
            base_url=args.base_url,
            model=args.model,
            trino_container=args.trino_container,
            trino_user=args.trino_user,
        )
        predictions.append(prediction)
        print(
            f"[{index}/{len(records)}] {record['case_id']} "
            f"json={prediction['valid_json']} g2={prediction['g2']} "
            f"trino={prediction['trino']} result_match={prediction['result_match']}",
            flush=True,
        )
        if not (
            prediction["valid_json"]
            and prediction["g2"] == "PASS"
            and prediction["trino"] == "PASS"
            and prediction["result_match"] is True
        ):
            break
    write_jsonl(args.output, predictions)
    latencies = [prediction["latency_ms"] for prediction in predictions]
    summary = {
        "model": args.model,
        "revision": args.revision,
        "total": len(predictions),
        "requested": len(records),
        "stopped_early": len(predictions) < len(records),
        "valid_json": sum(prediction["valid_json"] for prediction in predictions),
        "g2_pass": sum(prediction["g2"] == "PASS" for prediction in predictions),
        "expected_g2_pass": sum(prediction.get("expected_g2") == "PASS" for prediction in predictions),
        "trino_pass": sum(prediction["trino"] == "PASS" for prediction in predictions),
        "result_match": sum(prediction["result_match"] is True for prediction in predictions),
        "sql_exact_match": sum(prediction["sql_exact_match"] for prediction in predictions),
        "latency_p50_ms": _percentile(latencies, 50),
        "latency_p95_ms": _percentile(latencies, 95),
        "observed": observed_metrics(
            accuracy=sum(prediction["sql_exact_match"] for prediction in predictions) / len(predictions),
            p50_ms=_percentile(latencies, 50),
            p95_ms=_percentile(latencies, 95),
            peak_vram_bytes=None,
            cost_usd=None,
        ),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    required = ("valid_json", "g2_pass", "expected_g2_pass", "trino_pass", "result_match")
    return 0 if all(summary[name] == summary["total"] for name in required) else 1


if __name__ == "__main__":
    raise SystemExit(main())
