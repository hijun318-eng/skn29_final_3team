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

from app.adapters.i2_data_platform import I2DataPlatformAdapter  # noqa: E402
from app.services.context_builder import (  # noqa: E402
    ContextAsset,
    ContextMetric,
    ContextParameterBinding,
    ContextPackage,
    ContextRequiredFilter,
)
from app.services.pipeline_support import PipelineSupport  # noqa: E402


class PlanContractError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _context_parameter_bindings(context: dict[str, Any]) -> tuple[ContextParameterBinding, ...]:
    execution = context["execution_time"]
    bindings = [
        ContextParameterBinding(name, "date", execution[name][:10])
        for name in ("period_start", "period_end_exclusive")
        if name in execution
    ]
    filters = sorted(
        context["metrics"][0].get("required_filters", ()),
        key=lambda item: item["field"],
    )
    bindings.extend(
        ContextParameterBinding(
            f"required_filter_{index}",
            item["value_type"],
            item["value"],
        )
        for index, item in enumerate(filters, start=1)
    )
    return tuple(bindings)


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
    metrics = tuple(
        ContextMetric(
            id=metric["id"],
            asset_fqn=next(
                asset["trino_fqn"]
                for asset in context["assets"]
                if any(
                    metric[field].startswith(f"{asset['trino_fqn']}.")
                    for field in ("field", "time_field")
                )
            ),
            field=metric["field"],
            aggregation=metric["aggregation"],
            time_field=metric["time_field"],
            required_filters=tuple(
                ContextRequiredFilter(
                    field=item["field"],
                    operator=item["operator"],
                    value=item["value"],
                    value_type=item["value_type"],
                )
                for item in metric.get("required_filters", ())
            ),
        )
        for metric in context["metrics"]
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
        metrics=metrics,
        parameter_bindings=_context_parameter_bindings(context),
    )


def _references(output: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "urn": item["urn"],
            "fqn": item["trino_fqn"],
            "columns": item["columns"],
            "join_ids": item["join_ids"],
            "metric_ids": item.get("metric_ids", []),
        }
        for item in output["references"]
    ]


def _declared_parameters(output: dict[str, Any]) -> dict[str, dict[str, Any]]:
    declared = output.get("parameters")
    if not isinstance(declared, list):
        raise PlanContractError("PARAMETERS_INVALID")
    parameters = {}
    for item in declared:
        if not isinstance(item, dict) or set(item) != {"name", "value_type", "value"}:
            raise PlanContractError("PARAMETERS_INVALID")
        name = item["name"]
        if not isinstance(name, str) or not name or name in parameters:
            raise PlanContractError("PARAMETERS_INVALID")
        parameters[name] = {"value_type": item["value_type"], "value": item["value"]}
    return parameters


def _context_plan(
    sql: str,
    context: dict[str, Any],
    references: list[dict[str, Any]],
    declared: dict[str, dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], ContextPackage]:
    package = _runtime_package(context)
    parameters = {
        item.name: {"value_type": item.value_type, "value": item.value}
        for item in package.parameter_bindings
    }
    if declared is not None and declared != parameters:
        raise PlanContractError("PARAMETERS_INVALID")
    return {
        "sql": sql,
        "references": references,
        "parameters": parameters,
        "model_version": "MODEL-v1.0.0",
    }, package


def _rejected_plan(case: dict[str, Any], parameters: dict[str, Any]) -> dict[str, Any]:
    code = case["input"]["normalized_error_code"]
    output = case["expected_output"]
    references = _references(output)
    rejected_parameters: object = parameters
    if code == "REFERENCE_MISSING":
        references = []
    elif code == "REFERENCE_OUTSIDE_CONTEXT":
        references = [{"urn": "outside", "fqn": "outside.schema.table", "columns": ["value"]}]
    elif code == "PARAMETERS_INVALID":
        rejected_parameters = []
    return {"sql": case["input"]["rejected_sql"], "references": references, "parameters": rejected_parameters}


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
    statements = []
    for case in cases:
        plan = validate_g2(case)
        bound = I2DataPlatformAdapter._bind_parameters(plan["sql"], plan["parameters"])
        statements.extend((bound + ";", f"SELECT '{case['case_id']}' AS __case_marker LIMIT 1;"))
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


def validate_g2(case: dict[str, Any]) -> dict[str, Any]:
    output = case["expected_output"]
    sql_field = "sql" if case["node"] == "node2" else "corrected_sql"
    plan, package = _context_plan(
        output[sql_field],
        case["input"]["context_package"],
        _references(output),
        _declared_parameters(output),
    )
    violation = PipelineSupport.g2_violation(plan, package)
    if violation is not None:
        raise ValueError(f"{case['case_id']}: corrected SQL failed G2: {violation}")
    if case["node"] == "node2_repair":
        expected = case["input"]["normalized_error_code"]
        actual = PipelineSupport.g2_violation(_rejected_plan(case, plan["parameters"]), package)
        if actual != expected:
            raise ValueError(f"{case['case_id']}: rejected SQL expected {expected}, got {actual}")
    return plan


def verify_case(case: dict[str, Any], *, container: str, user: str) -> None:
    plan = validate_g2(case)
    sql = I2DataPlatformAdapter._bind_parameters(plan["sql"], plan["parameters"])

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
        sql,
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
