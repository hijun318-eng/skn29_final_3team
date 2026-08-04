"""Validate generated SQL with runtime G2 and execute it through local Trino."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from src.ai.training.dataset import load_specs, summarize, write_jsonl


BACKEND = Path(__file__).resolve().parents[3] / "app" / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.services.context_builder import ContextAsset, ContextPackage  # noqa: E402
from app.services.pipeline_support import PipelineSupport  # noqa: E402


def _runtime_package(context: dict[str, Any]) -> ContextPackage:
    join_ids = tuple(join["id"] for join in context["joins"])
    assets = tuple(
        ContextAsset(
            asset["urn"],
            asset["trino_fqn"],
            tuple(asset["columns"]),
            join_ids,
        )
        for asset in context["assets"]
    )
    return ContextPackage(
        context_release=context["context_version"],
        policy_version=context["policy_version"],
        time_version=context["execution_time"]["as_of"],
        entitlement_hash="training-verification",
        assets=assets,
        dataset_count=len(assets),
        column_count=sum(len(asset.columns) for asset in assets),
        token_count=1,
        token_limit=6_000,
        package_hash="training-verification",
        approved_join_ids=join_ids,
    )


def _references(output: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "urn": item["urn"],
            "fqn": item["trino_fqn"],
            "columns": item["columns"],
            "join_ids": item["join_ids"],
        }
        for item in output["references"]
    ]


def _rejected_plan(case: dict[str, Any]) -> dict[str, Any]:
    code = case["input"]["normalized_error_code"]
    output = case["expected_output"]
    references = _references(output)
    parameters: object = {}
    if code == "REFERENCE_MISSING":
        references = []
    elif code == "REFERENCE_OUTSIDE_CONTEXT":
        references = [{"urn": "outside", "fqn": "outside.schema.table", "columns": ["value"]}]
    elif code == "PARAMETERS_INVALID":
        parameters = []
    return {"sql": case["input"]["rejected_sql"], "references": references, "parameters": parameters}


def _result_hash(stdout: str) -> str:
    rows = [json.loads(line) for line in stdout.splitlines() if line.strip()]
    return _rows_hash(rows)


def _rows_hash(rows: list[dict[str, Any]]) -> str:
    canonical = json.dumps(
        sorted(rows, key=lambda row: json.dumps(row, ensure_ascii=False, sort_keys=True)),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def verify_batch(cases: list[dict[str, Any]], *, container: str, user: str) -> None:
    for case in cases:
        validate_g2(case)
    statements = []
    for case in cases:
        output = case["expected_output"]
        sql_field = "sql" if case["node"] == "node2" else "corrected_sql"
        statements.extend((output[sql_field] + ";", f"SELECT '{case['case_id']}' AS __case_marker LIMIT 1;"))
    command = [
        "docker",
        "exec",
        "-i",
        container,
        "trino",
        "--server",
        "http://localhost:8080",
        "--user",
        user,
        "--output-format",
        "JSON",
    ]
    result = subprocess.run(
        command,
        input="\n".join(statements) + "\n",
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode:
        detail = "\n".join((result.stderr or result.stdout).strip().splitlines()[-12:])
        raise ValueError(f"batch {cases[0]['case_id']}..{cases[-1]['case_id']} failed:\n{detail}")
    rows: list[dict[str, Any]] = []
    verified = 0
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        marker = row.get("__case_marker")
        if marker is None:
            rows.append(row)
            continue
        case = cases[verified]
        if marker != case["case_id"]:
            raise ValueError(f"expected marker {case['case_id']}, got {marker}")
        case["trino_status"] = "PASS"
        case["result_sha256"] = _rows_hash(rows)
        rows = []
        verified += 1
    if verified != len(cases) or rows:
        raise ValueError(f"batch result boundary mismatch: {verified}/{len(cases)}")


def validate_g2(case: dict[str, Any]) -> None:
    output = case["expected_output"]
    sql_field = "sql" if case["node"] == "node2" else "corrected_sql"
    package = _runtime_package(case["input"]["context_package"])
    plan = {"sql": output[sql_field], "references": _references(output), "parameters": {}}
    violation = PipelineSupport.g2_violation(plan, package)
    if violation is not None:
        raise ValueError(f"{case['case_id']}: corrected SQL failed G2: {violation}")
    if case["node"] == "node2_repair":
        expected = case["input"]["normalized_error_code"]
        actual = PipelineSupport.g2_violation(_rejected_plan(case), package)
        if actual != expected:
            raise ValueError(f"{case['case_id']}: rejected SQL expected {expected}, got {actual}")


def verify_case(case: dict[str, Any], *, container: str, user: str) -> None:
    validate_g2(case)
    output = case["expected_output"]
    sql_field = "sql" if case["node"] == "node2" else "corrected_sql"

    command = [
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
        output[sql_field],
    ]
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8")
    if result.returncode:
        detail = (result.stderr or result.stdout).strip().splitlines()[-1]
        raise ValueError(f"{case['case_id']}: Trino failed: {detail}")
    case["trino_status"] = "PASS"
    case["result_sha256"] = _result_hash(result.stdout)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--container", default="hotel-synthetic-db-trino-1")
    parser.add_argument("--user", default="hotel_synthetic_setup")
    parser.add_argument("--batch-size", type=int, default=0)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    cases = load_specs(args.output if args.resume and args.output.exists() else args.source)
    if args.batch_size:
        pending = [case for case in cases if case["trino_status"] != "PASS"]
        completed = len(cases) - len(pending)
        for start in range(0, len(pending), args.batch_size):
            batch = pending[start : start + args.batch_size]
            verify_batch(batch, container=args.container, user=args.user)
            write_jsonl(args.output, cases)
            print(f"[{completed + start + len(batch)}/{len(cases)}] batch PASS", flush=True)
    else:
        for index, case in enumerate(cases, 1):
            verify_case(case, container=args.container, user=args.user)
            print(f"[{index}/{len(cases)}] {case['case_id']} PASS", flush=True)
    write_jsonl(args.output, cases)
    load_specs(args.output)
    print(json.dumps(summarize(cases), ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
