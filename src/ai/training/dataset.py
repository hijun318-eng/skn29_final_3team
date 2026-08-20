"""데이터셋 학습·평가 데이터의 생성, 실행, 검증 절차와 CLI 진입점을 제공한다.

Build and validate versioned SQL SFT JSONL data against governed contracts.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from sqlglot import exp

from src.ai.prompt_registry import get_prompt
from src.ai.schema import ContractError, schema_version as current_schema_version, validate_payload
from src.ai.sql_policy import (
    SqlValidationResult,
    canonicalize_table_fqn,
    validate_sql,
)


class DatasetError(ValueError):
    """학습 case schema·SQL 안전성·review 증거 또는 split 누출 검사가 실패했음을 알린다."""


SPLITS = {"train", "validation", "gold", "acceptance"}
NODES = {"node2", "node2_repair"}
REVIEW_STATUSES = {"AUTO_PASSED", "APPROVED"}
SPEC_FIELDS = set(
    "case_id split node domain scenario_group synthetic schema_version seed_version "
    "review_status trino_status result_sha256 input expected_output".split()
)
COMPILED_FIELDS = SPEC_FIELDS - {"input", "expected_output"} | {"messages"}
MESSAGE_ROLES = ("system", "user", "assistant")
PII_PATTERNS = (
    re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE),
    re.compile(r"(?<!\d)01[016789][ -]?\d{3,4}[ -]?\d{4}(?!\d)"),
)


def load_specs(path: Path) -> list[dict[str, Any]]:
    """full-spec JSONL을 읽고 compile 전 필드·review·SQL·split 불변식을 모두 검증한다."""
    records = _read_jsonl(path)
    _validate_records(records, compiled=False)
    return records


def load_compiled(path: Path, split: str | None = None) -> list[dict[str, Any]]:
    """compiled chat JSONL을 재검증하고 요청한 허용 split의 record만 반환한다."""
    records = _read_jsonl(path)
    _validate_records(records, compiled=True)
    if split is None:
        return records
    if split not in SPLITS:
        raise DatasetError(f"unknown split: {split}")
    return [record for record in records if record["split"] == split]


def build_records(specs: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """검증된 spec을 versioned system prompt와 canonical user/assistant JSON 메시지로 compile한다."""
    records = []
    for spec in specs:
        if spec["node"] == "node2" and set(spec["expected_output"]) != {"sql"}:
            raise DatasetError("Node2 training requires the SQL-only output shape")
        prompt_id = (
            "node2.sql_only" if spec["node"] == "node2" else "node2.repair"
        )
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
    """jsonl 산출물을 결정론적 형식으로 기록하고 완료 상태를 반환한다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as output:
        for record in records:
            output.write(_stable_json(record) + "\n")


def summarize(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """검증된 학습 record의 총수와 split·node·domain별 건수를 안정된 key 순서로 반환한다.

    iterable을 한 번 소비해 집계할 뿐 record나 message payload는 변경하지 않는다.
    """
    records = list(records)
    return {
        "total": len(records),
        "splits": dict(sorted(Counter(record["split"] for record in records).items())),
        "nodes": dict(sorted(Counter(record["node"] for record in records).items())),
        "domains": dict(sorted(Counter(record["domain"] for record in records).items())),
    }


def validate_model_output(
    node: str, output: Any, input_value: dict[str, Any] | None = None
) -> SqlValidationResult:
    """검증된 Node 계약과 SQL AST를 사용해 학습 출력을 불신 입력으로 검사한다."""
    if node not in NODES:
        raise DatasetError(f"node must be one of {sorted(NODES)}")
    try:
        validate_payload(f"{node}_response", output)
    except ContractError as error:
        raise DatasetError(str(error)) from error
    sql_field = "sql" if node == "node2" else "corrected_sql"
    if input_value is not None:
        _validate_input(node, input_value)
    max_limit = input_value["query_policy"]["max_limit"] if input_value else 1_000
    result = _validate_sql(output[sql_field], max_limit=max_limit)
    if input_value is not None:
        _validate_sql_contract(node, input_value, output, result)
    return result


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
    for field in ("case_id", "domain", "scenario_group", "schema_version", "seed_version"):
        if not isinstance(record[field], str) or not record[field].strip():
            raise DatasetError(f"{field} must be a non-empty string")
    if record["split"] not in SPLITS:
        raise DatasetError(f"split must be one of {sorted(SPLITS)}")
    if record["node"] not in NODES:
        raise DatasetError(f"node must be one of {sorted(NODES)}")
    if record["schema_version"] != current_schema_version():
        raise DatasetError("schema_version must match the active Node contract")
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
        validate_model_output(
            record["node"], record["expected_output"], record["input"]
        )
        _reject_pii({"input": record["input"], "expected_output": record["expected_output"]})


def _validate_input(node: str, value: Any) -> None:
    validate_payload(f"{node}_request", value)

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
    prompt_id = "node2.sql_only" if node == "node2" else "node2.repair"
    if messages[0]["content"] != get_prompt(prompt_id).text:
        raise DatasetError("system prompt must match the versioned training prompt")
    if node == "node2" and (
        not isinstance(output_value, dict) or set(output_value) != {"sql"}
    ):
        raise DatasetError("Node2 training requires the SQL-only output shape")
    validate_model_output(node, output_value, input_value)
    _reject_pii(messages)


def _join_graph_signature(record: dict[str, Any], *, compiled: bool) -> str:
    if compiled:
        input_value = json.loads(record["messages"][1]["content"])
    else:
        input_value = record["input"]
    return _stable_json(sorted(input_value["join_graph"]["edges"], key=_stable_json))

def _validate_sql_contract(
    node: str, request: dict[str, Any], output: dict[str, Any], result: SqlValidationResult
) -> None:
    policy = request["query_policy"]
    assets = {
        _canonical_fqn(asset["fqn"]): {
            column["name"].casefold() for column in asset["columns"]
        }
        for asset in request["schema_context"]["assets"]
    }
    physical_tables = set(result.physical_tables)
    if not physical_tables or not physical_tables.issubset(assets):
        raise DatasetError("SQL physical tables must be approved schema_context assets")
    catalogs = {table.split(".", 1)[0].casefold() for table in physical_tables}
    if not catalogs.issubset({item.casefold() for item in policy["allowed_catalogs"]}):
        raise DatasetError("SQL catalog is outside query_policy")
    if not {item.casefold() for item in result.functions}.issubset(
        {item.casefold() for item in policy["allowed_functions"]}
    ):
        raise DatasetError("SQL function is outside query_policy")

    parameters = {
        item["name"]: item for item in request["parameter_contract"]["parameters"]
    }
    if set(result.placeholders) != set(parameters):
        raise DatasetError("SQL placeholders must exactly match parameter_contract")
    _validate_parameter_contexts(result, parameters)
    physical_columns = _physical_columns(result, assets)

    requested_metrics = set(request["resolved_request"]["metric_ids"])
    claimed_metrics = (
        set(output["used_metrics"])
        if node == "node2" and "used_metrics" in output
        else requested_metrics
    )
    metrics = {item["id"]: item for item in request["metric_rules"]}
    if claimed_metrics != requested_metrics or not claimed_metrics.issubset(metrics):
        raise DatasetError("used_metrics must exactly match resolved metric rules")
    required_fields = list(request["resolved_request"]["dimensions"])
    required_fields.extend(item["field"] for item in request["resolved_request"]["filters"])
    for metric_id in claimed_metrics:
        metric = metrics[metric_id]
        if metric["source"]["kind"] == "column":
            required_fields.append(metric["source"]["field"])
        if metric["time_field"] is not None:
            required_fields.append(metric["time_field"])
        required_fields.extend(metric["dimensions"])
        required_fields.extend(item["field"] for item in metric["required_filters"])
        if metric["result_field"].casefold() not in {
            alias.casefold() for alias in result.projection_aliases
        }:
            raise DatasetError("metric result_field must be a SQL projection alias")
    if not {_field_identity(item) for item in required_fields}.issubset(physical_columns):
        raise DatasetError("resolved metric fields must be referenced by SQL")

    inferred_joins = _inferred_join_ids(request, result, physical_tables)
    if node == "node2" and "used_assets" in output:
        if {_canonical_fqn(item) for item in output["used_assets"]} != physical_tables:
            raise DatasetError("used_assets must exactly match SQL physical tables")
        claimed_columns = {_field_identity(item) for item in output["used_columns"]}
        if claimed_columns != physical_columns:
            raise DatasetError("used_columns must exactly match SQL physical columns")
        if set(output["used_joins"]) != inferred_joins:
            raise DatasetError("used_joins must exactly match SQL join edges")


def _physical_columns(
    result: SqlValidationResult, assets: dict[str, set[str]]
) -> set[tuple[str, str]]:
    aliases = {item.casefold() for item in result.projection_aliases}
    columns: set[tuple[str, str]] = set()
    for column in result.columns:
        if column.source_table is None:
            if column.name.casefold() in aliases:
                continue
            raise DatasetError(f"SQL column {column.sql!r} has no physical source")
        identity = (column.source_table, column.name.casefold())
        if identity[0] not in assets or identity[1] not in assets[identity[0]]:
            raise DatasetError("SQL column is outside schema_context")
        columns.add(identity)
    return columns


def _inferred_join_ids(
    request: dict[str, Any], result: SqlValidationResult, physical_tables: set[str]
) -> set[str]:
    inferred: set[str] = set()
    for join in result.joins:
        candidates = [
            edge
            for edge in request["join_graph"]["edges"]
            if _canonical_fqn(edge["right"]) == join.source
            and _canonical_fqn(edge["left"]) in physical_tables
            and edge["kind"].casefold() == join.kind.casefold()
        ]
        if len(candidates) != 1:
            raise DatasetError("each SQL join must resolve to one join_graph edge")
        inferred.add(candidates[0]["id"])
    return inferred


def _validate_parameter_contexts(
    result: SqlValidationResult, parameters: dict[str, dict[str, Any]]
) -> None:
    assert result.expression is not None
    for placeholder in result.expression.find_all(exp.Placeholder):
        value_type = parameters[str(placeholder.this)]["type"]
        parent = placeholder.parent
        valid_date = isinstance(parent, exp.Cast) and _cast_type(parent) == exp.DataType.Type.DATE
        valid_timestamp = isinstance(parent, exp.FromISO8601Timestamp) or (
            isinstance(parent, exp.Cast)
            and _cast_type(parent)
            in {exp.DataType.Type.TIMESTAMP, exp.DataType.Type.TIMESTAMPTZ}
        )
        if (value_type == "date" and not valid_date) or (
            value_type == "timestamp" and not valid_timestamp
        ):
            raise DatasetError(f"{value_type} placeholder requires explicit conversion")


def _cast_type(node: exp.Cast) -> exp.DataType.Type | None:
    target = node.args.get("to")
    return target.this if isinstance(target, exp.DataType) else None


def _field_identity(field: dict[str, str]) -> tuple[str, str]:
    return _canonical_fqn(field["asset_fqn"]), field["column"].casefold()


def _canonical_fqn(value: str) -> str:
    try:
        return canonicalize_table_fqn(value)
    except ValueError as error:
        raise DatasetError("schema_context contains an invalid table FQN") from error


def _validate_sql(value: Any, *, max_limit: int = 1_000) -> SqlValidationResult:
    if not isinstance(value, str) or not value.strip():
        raise DatasetError("SQL must be a non-empty string")
    result = validate_sql(value.strip(), max_limit=max_limit)
    if result.violations:
        codes = ", ".join(item.code for item in result.violations)
        raise DatasetError(f"SQL policy violation: {codes}")
    return result


def _reject_pii(value: Any) -> None:
    text = _stable_json(value)
    if any(pattern.search(text) for pattern in PII_PATTERNS):
        raise DatasetError("possible email address or Korean mobile number detected")


def _stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def main() -> int:
    """full-spec을 chat dataset으로 build하거나 기존 compiled dataset의 무결성만 검증한다."""
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
