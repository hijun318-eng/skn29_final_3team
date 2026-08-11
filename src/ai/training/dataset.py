"""Build and validate versioned SQL SFT JSONL data without third-party packages."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from src.ai.prompt_registry import get_prompt
from src.ai.schema import ContractError, validate_payload


class DatasetError(ValueError):
    """Raised when a training case is unsafe, malformed, or leaks across splits."""


SPLITS = {"train", "validation", "gold", "acceptance"}
NODES = {"node2", "node2_repair"}
DOMAINS = {"pms", "crm", "pms_crm", "pos", "facility", "banquet"}
REVIEW_STATUSES = {"AUTO_PASSED", "APPROVED"}
SPEC_FIELDS = {
    "case_id",
    "split",
    "node",
    "domain",
    "scenario_group",
    "synthetic",
    "schema_version",
    "seed_version",
    "review_status",
    "trino_status",
    "result_sha256",
    "input",
    "expected_output",
}
COMPILED_FIELDS = SPEC_FIELDS - {"input", "expected_output"} | {"messages"}
NODE2_INPUT_FIELDS = {"normalized_question", "context_package"}
REPAIR_INPUT_FIELDS = {
    "normalized_question",
    "trace_id",
    "attempt",
    "rejected_sql",
    "context_package",
    "normalized_error_code",
    "repair_scope",
}
OUTPUT_FIELDS = {
    "node2": {"sql", "references", "parameters"},
    "node2_repair": {"corrected_sql", "references", "parameters"},
}
MESSAGE_ROLES = ("system", "user", "assistant")
PII_PATTERNS = (
    re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE),
    re.compile(r"(?<!\d)01[016789][ -]?\d{3,4}[ -]?\d{4}(?!\d)"),
)
BANNED_SQL = re.compile(
    r"\b(INSERT|UPDATE|DELETE|MERGE|DROP|ALTER|CREATE|TRUNCATE|GRANT|REVOKE|CALL|EXECUTE)\b",
    re.IGNORECASE,
)


def load_specs(path: Path) -> list[dict[str, Any]]:
    records = _read_jsonl(path)
    _validate_records(records, compiled=False)
    return records


def load_compiled(path: Path, split: str | None = None) -> list[dict[str, Any]]:
    records = _read_jsonl(path)
    _validate_records(records, compiled=True)
    if split is None:
        return records
    if split not in SPLITS:
        raise DatasetError(f"unknown split: {split}")
    return [record for record in records if record["split"] == split]


def build_records(specs: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    records = []
    for spec in specs:
        prompt_id = "node2.sql" if spec["node"] == "node2" else "node2.repair"
        records.append(
            {
                **{key: spec[key] for key in SPEC_FIELDS - {"input", "expected_output"}},
                "messages": [
                    {"role": "system", "content": get_prompt(prompt_id).text},
                    {"role": "user", "content": _stable_json(spec["input"])},
                    {"role": "assistant", "content": _stable_json(spec["expected_output"])},
                ],
            }
        )
    _validate_records(records, compiled=True)
    return records


def write_jsonl(path: Path, records: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as output:
        for record in records:
            output.write(_stable_json(record) + "\n")


def summarize(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    records = list(records)
    return {
        "total": len(records),
        "splits": dict(sorted(Counter(record["split"] for record in records).items())),
        "nodes": dict(sorted(Counter(record["node"] for record in records).items())),
        "domains": dict(sorted(Counter(record["domain"] for record in records).items())),
    }


def validate_model_output(node: str, output: Any) -> None:
    if not isinstance(output, dict) or set(output) != OUTPUT_FIELDS[node]:
        raise DatasetError(f"{node} output fields must be {sorted(OUTPUT_FIELDS[node])}")
    sql_field = "sql" if node == "node2" else "corrected_sql"
    _validate_sql(output[sql_field])
    if not isinstance(output["references"], list) or not output["references"]:
        raise DatasetError("references must be a non-empty list")
    if not isinstance(output["parameters"], list):
        raise DatasetError("parameters must be a list")
    for parameter in output["parameters"]:
        if not isinstance(parameter, dict) or set(parameter) != {"name", "value"}:
            raise DatasetError("each parameter must contain only name and value")
        if not isinstance(parameter["name"], str) or not parameter["name"]:
            raise DatasetError("parameter name must be a non-empty string")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    records = []
    with path.open(encoding="utf-8") as source:
        for line_number, line in enumerate(source, 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as error:
                raise DatasetError(f"{path}:{line_number}: invalid JSON") from error
            if not isinstance(record, dict):
                raise DatasetError(f"{path}:{line_number}: record must be an object")
            records.append(record)
    if not records:
        raise DatasetError(f"{path}: no records")
    return records


def _validate_records(records: list[dict[str, Any]], *, compiled: bool) -> None:
    seen_ids: set[str] = set()
    group_splits: dict[str, str] = {}
    group_join_graphs: dict[str, str] = {}
    for index, record in enumerate(records, 1):
        try:
            _validate_record(record, compiled=compiled)
        except (DatasetError, ContractError) as error:
            raise DatasetError(f"record {index}: {error}") from error

        case_id = record["case_id"]
        if case_id in seen_ids:
            raise DatasetError(f"duplicate case_id: {case_id}")
        seen_ids.add(case_id)
        previous = group_splits.setdefault(record["scenario_group"], record["split"])
        if previous != record["split"]:
            raise DatasetError(
                f"scenario_group {record['scenario_group']!r} leaks across {previous} and {record['split']}"
            )
        join_graph = _join_graph_signature(record, compiled=compiled)
        previous_graph = group_join_graphs.setdefault(record["scenario_group"], join_graph)
        if previous_graph != join_graph:
            raise DatasetError(
                f"scenario_group {record['scenario_group']!r} changes join graph"
            )


def _validate_record(record: dict[str, Any], *, compiled: bool) -> None:
    expected_fields = COMPILED_FIELDS if compiled else SPEC_FIELDS
    if set(record) != expected_fields:
        raise DatasetError(f"fields must be exactly {sorted(expected_fields)}")
    for field in ("case_id", "scenario_group", "schema_version", "seed_version"):
        if not isinstance(record[field], str) or not record[field].strip():
            raise DatasetError(f"{field} must be a non-empty string")
    if record["split"] not in SPLITS:
        raise DatasetError(f"split must be one of {sorted(SPLITS)}")
    if record["node"] not in NODES:
        raise DatasetError(f"node must be one of {sorted(NODES)}")
    if record["domain"] not in DOMAINS:
        raise DatasetError(f"domain must be one of {sorted(DOMAINS)}")
    if record["synthetic"] is not True:
        raise DatasetError("synthetic must be true")
    if record["review_status"] not in REVIEW_STATUSES:
        raise DatasetError(f"review_status must be one of {sorted(REVIEW_STATUSES)}")
    if record["split"] in {"gold", "acceptance"} and record["review_status"] != "APPROVED":
        raise DatasetError("gold and acceptance records require APPROVED review_status")
    if record["trino_status"] not in {"NOT_RUN", "PASS"}:
        raise DatasetError("trino_status must be NOT_RUN or PASS")
    result_hash = record["result_sha256"]
    if record["trino_status"] == "PASS":
        if not isinstance(result_hash, str) or re.fullmatch(r"[0-9a-f]{64}", result_hash) is None:
            raise DatasetError("PASS records require a lowercase SHA-256 result hash")
    elif result_hash is not None:
        raise DatasetError("NOT_RUN records must have a null result_sha256")

    if compiled:
        _validate_messages(record["node"], record["messages"])
    else:
        _validate_input(record["node"], record["input"])
        validate_model_output(record["node"], record["expected_output"])
        _validate_references(record["input"]["context_package"], record["expected_output"])
        _reject_pii({"input": record["input"], "expected_output": record["expected_output"]})


def _validate_input(node: str, value: Any) -> None:
    fields = NODE2_INPUT_FIELDS if node == "node2" else REPAIR_INPUT_FIELDS
    if not isinstance(value, dict) or set(value) != fields:
        raise DatasetError(f"{node} input fields must be {sorted(fields)}")
    if not isinstance(value["normalized_question"], str) or not value["normalized_question"].strip():
        raise DatasetError("normalized_question must be a non-empty string")
    validate_payload("context_package", value["context_package"])
    if node == "node2_repair":
        if value["attempt"] != 1:
            raise DatasetError("node2_repair attempt must be 1")
        for field in ("trace_id", "rejected_sql", "normalized_error_code"):
            if not isinstance(value[field], str) or not value[field].strip():
                raise DatasetError(f"{field} must be a non-empty string")
        if not isinstance(value["repair_scope"], list):
            raise DatasetError("repair_scope must be a list")


def _validate_messages(node: str, messages: Any) -> None:
    if not isinstance(messages, list) or len(messages) != 3:
        raise DatasetError("messages must contain system, user, and assistant")
    for expected_role, message in zip(MESSAGE_ROLES, messages):
        if not isinstance(message, dict) or set(message) != {"role", "content"}:
            raise DatasetError("each message must contain only role and content")
        if message["role"] != expected_role:
            raise DatasetError(f"message role must be {expected_role}")
        if not isinstance(message["content"], str) or not message["content"].strip():
            raise DatasetError("message content must be a non-empty string")
    try:
        input_value = json.loads(messages[1]["content"])
        output_value = json.loads(messages[2]["content"])
    except json.JSONDecodeError as error:
        raise DatasetError("user and assistant content must be JSON") from error
    _validate_input(node, input_value)
    validate_model_output(node, output_value)
    _validate_references(input_value["context_package"], output_value)
    _reject_pii(messages)


def _join_graph_signature(record: dict[str, Any], *, compiled: bool) -> str:
    if compiled:
        input_value = json.loads(record["messages"][1]["content"])
        joins = input_value["context_package"]["joins"]
    else:
        joins = record["input"]["context_package"]["joins"]
    return _stable_json(
        sorted(
            joins,
            key=lambda join: _stable_json(join),
        )
    )


def _validate_references(context: dict[str, Any], output: dict[str, Any]) -> None:
    assets = {asset["urn"]: asset for asset in context["assets"]}
    allowed_joins = {join["id"] for join in context["joins"]}
    allowed_metrics = {metric["id"] for metric in context["metrics"]}
    for reference in output["references"]:
        fields = {"urn", "trino_fqn", "columns", "join_ids", "metric_ids"}
        if not isinstance(reference, dict) or set(reference) != fields:
            raise DatasetError(f"reference fields must be {sorted(fields)}")
        asset = assets.get(reference["urn"])
        if asset is None or reference["trino_fqn"] != asset["trino_fqn"]:
            raise DatasetError("reference must point to a Context Package asset")
        if not set(reference["columns"]).issubset(asset["columns"]):
            raise DatasetError("reference columns must be allowed by the Context Package")
        if not set(reference["join_ids"]).issubset(allowed_joins):
            raise DatasetError("reference join_ids must be allowed by the Context Package")
        if not set(reference["metric_ids"]).issubset(allowed_metrics):
            raise DatasetError("reference metric_ids must be allowed by the Context Package")


def _validate_sql(value: Any) -> None:
    if not isinstance(value, str) or not value.strip():
        raise DatasetError("SQL must be a non-empty string")
    sql = value.strip()
    without_trailing = sql[:-1].rstrip() if sql.endswith(";") else sql
    if ";" in without_trailing:
        raise DatasetError("SQL must contain exactly one statement")
    if not re.match(r"^(SELECT|WITH)\b", without_trailing, re.IGNORECASE):
        raise DatasetError("SQL must start with SELECT or WITH")
    if BANNED_SQL.search(without_trailing):
        raise DatasetError("SQL contains a write or administrative keyword")
    if "--" in without_trailing or "/*" in without_trailing:
        raise DatasetError("SQL comments are not allowed in training data")
    if re.search(r"\bSELECT\s+\*", without_trailing, re.IGNORECASE):
        raise DatasetError("SELECT * is not allowed")


def _reject_pii(value: Any) -> None:
    text = _stable_json(value)
    if any(pattern.search(text) for pattern in PII_PATTERNS):
        raise DatasetError("possible email address or Korean mobile number detected")


def _stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build", help="validate case specs and compile chat JSONL")
    build.add_argument("source", type=Path)
    build.add_argument("output", type=Path)
    validate = subparsers.add_parser("validate", help="validate compiled chat JSONL")
    validate.add_argument("dataset", type=Path)
    args = parser.parse_args()

    if args.command == "build":
        records = build_records(load_specs(args.source))
        write_jsonl(args.output, records)
    else:
        records = load_compiled(args.dataset)
    print(json.dumps(summarize(records), ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
