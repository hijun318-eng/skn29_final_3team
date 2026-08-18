"""evaluate 엔드포인트 학습·평가 데이터의 생성, 실행, 검증 절차와 CLI 진입점을 제공한다.

Evaluate structured SQL model outputs with server-owned runtime bindings.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Callable

from src.ai.schema import schema_definition
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
    _execute,
    _result_hash,
    load_binding_manifest,
    validate_output,
)


Requester = Callable[[str, str, dict[str, Any] | None, str | None, float], dict[str, Any]]


def _schema(node: str) -> dict[str, Any]:
    """Return the same strict response schema used by offline validation."""
    return schema_definition(f"{node}_response")


def _run_trino(
    executable_sql: str,
    container: str,
    user: str,
    password: str,
) -> tuple[str, str | None, str | None]:
    """AST-bound SQL과 password를 각각 stdin과 child 환경으로 분리해 실행한다."""
    try:
        completed = _execute(
            executable_sql,
            container=container,
            user=user,
            password=password,
            timeout=30,
        )
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        digest = hashlib.sha256(str(error).encode()).hexdigest()
        return "FAIL", None, digest
    if completed.returncode:
        diagnostic = completed.stderr or completed.stdout
        return "FAIL", None, hashlib.sha256(diagnostic.encode()).hexdigest()
    return "PASS", _result_hash(completed.stdout), None


def _validation_result(
    node: str,
    request: dict[str, Any],
    output: Any,
    bindings: Mapping[str, object] | None,
) -> tuple[str, dict[str, Any] | None]:
    if not isinstance(output, dict):
        return "MODEL_SCHEMA_INVALID", None
    try:
        return "PASS", validate_output(node, request, output, bindings)
    except PlanContractError as error:
        return error.code, None


def _base_evidence(record: dict[str, Any], response: dict[str, Any], latency_ms: float) -> tuple[dict[str, Any], Any]:
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
    return evidence, content


def _invalid_json(evidence: dict[str, Any]) -> dict[str, Any]:
    return {
        **evidence,
        "valid_json": False,
        "g2": "MODEL_SCHEMA_INVALID",
        "expected_g2": "NOT_RUN",
        "trino": "NOT_RUN",
        "result_match": "NOT_RUN",
        "sql_exact_match": False,
    }


def evaluate_record(
    record: dict[str, Any],
    *,
    base_url: str,
    model: str,
    bindings: Mapping[str, object] | None = None,
    requester: Requester = request_json,
    timeout: float = 60,
    trino_container: str | None = None,
    trino_user: str | None = None,
    trino_password: str | None = None,
) -> dict[str, Any]:
    """한 compiled case를 모델에 보내 G2 검증과 실제 Trino 결과 일치 evidence를 만든다.

    server binding은 모델 입력에서 분리하고 AST 검증 뒤에만 주입하며, JSON·G2·Trino 단계 중
    하나라도 실패하면 이후 단계를 실행하지 않고 안정된 상태 code로 남긴다.
    """
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
    evidence, content = _base_evidence(
        record, response, (time.perf_counter() - started) * 1_000
    )
    try:
        generated = json.loads(content)
        request = json.loads(record["messages"][1]["content"])
        expected = json.loads(record["messages"][2]["content"])
    except (json.JSONDecodeError, TypeError, KeyError):
        return _invalid_json(evidence)

    node = record["node"]
    field = "sql" if node == "node2" else "corrected_sql"
    g2, generated_plan = _validation_result(node, request, generated, bindings)
    expected_g2, expected_plan = _validation_result(node, request, expected, bindings)
    generated_sql = generated.get(field) if isinstance(generated, dict) else None
    expected_sql = expected.get(field) if isinstance(expected, dict) else None
    exact_match = (
        isinstance(generated_sql, str)
        and isinstance(expected_sql, str)
        and _normalize_sql(generated_sql) == _normalize_sql(expected_sql)
    )

    trino = "NOT_RUN"
    generated_hash = expected_hash = diagnostic_hash = None
    result_match: bool | str = "NOT_RUN"
    if g2 == expected_g2 == "PASS" and trino_container is not None:
        if not trino_user or not trino_password:
            trino = "CONFIGURATION_INVALID"
        else:
            assert generated_plan is not None and expected_plan is not None
            trino, generated_hash, diagnostic_hash = _run_trino(
                generated_plan["executable_sql"], trino_container, trino_user,
                trino_password,
            )
            if trino == "PASS":
                expected_status, expected_hash, expected_diagnostic = _run_trino(
                    expected_plan["executable_sql"], trino_container, trino_user,
                    trino_password,
                )
                result_match = expected_status == "PASS" and generated_hash == expected_hash
                diagnostic_hash = diagnostic_hash or expected_diagnostic
    return {
        **evidence,
        "valid_json": True,
        "g2": g2,
        "expected_g2": expected_g2,
        "trino": trino,
        "result_match": result_match,
        "generated_result_sha256": generated_hash,
        "expected_result_sha256": expected_hash,
        "trino_diagnostic_sha256": diagnostic_hash,
        "sql_exact_match": exact_match,
        "sql": generated_sql if isinstance(generated_sql, str) else None,
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
    """validation case를 순서대로 endpoint·G2·인증 Trino에 검증하고 첫 실패에서 evidence를 확정한다."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--revision", default=DEFAULT_REVISION)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--bindings", type=Path, required=True)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--trino-container", required=True)
    parser.add_argument(
        "--trino-user", default=os.getenv("TRINO_RUNTIME_USER", "")
    )
    args = parser.parse_args()

    records = load_compiled(args.data, "validation")
    if args.manifest:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        records = _select_manifest_records(records, manifest)
    if args.limit is not None:
        records = records[: args.limit]
    if not records:
        raise ValueError("evaluation selection is empty")
    binding_manifest = load_binding_manifest(args.bindings)
    trino_password = os.getenv("TRINO_RUNTIME_PASSWORD", "")
    predictions = []
    for index, record in enumerate(records, 1):
        prediction = evaluate_record(
            record,
            base_url=args.base_url,
            model=args.model,
            bindings=binding_manifest.get(record["case_id"]),
            trino_container=args.trino_container,
            trino_user=args.trino_user,
            trino_password=trino_password,
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
        "expected_g2_pass": sum(item["expected_g2"] == "PASS" for item in predictions),
        "trino_pass": sum(prediction["trino"] == "PASS" for prediction in predictions),
        "result_match": sum(prediction["result_match"] is True for prediction in predictions),
        "sql_exact_match": sum(prediction["sql_exact_match"] for prediction in predictions),
        "latency_p50_ms": _percentile(latencies, 50),
        "latency_p95_ms": _percentile(latencies, 95),
        "observed": observed_metrics(
            accuracy=sum(item["sql_exact_match"] for item in predictions) / len(predictions),
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
