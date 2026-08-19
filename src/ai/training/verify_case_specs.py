"""verify 사례 명세 학습·평가 데이터의 생성, 실행, 검증 절차와 CLI 진입점을 제공한다.

Validate structured Node 2 cases and execute explicitly bound SQL in Trino.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.ai.sql_binding import SqlBindingError, bind_sql_parameters
from src.ai.training.dataset import DatasetError, load_specs, summarize, validate_model_output, write_jsonl

BACKEND = Path(__file__).resolve().parents[3] / "app" / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.services.context_builder import (  # noqa: E402
    ContextAsset,
    ContextMetric,
    ContextPackage,
)
from app.services.pipeline_context_contract import GovernedJoin, enrich_context_package  # noqa: E402
from app.services.pipeline_sql_guard import validate_parsed_semantics  # noqa: E402


BINDING_MANIFEST_VERSION = "SERVER-BINDINGS-v1"
_TRINO_SERVER = "https://trino:8443"
_TRINO_CA_PATH = "/run/secrets/trino-ca.pem"
_DOCKER_CONTAINER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
_TRINO_USER = re.compile(r"[a-z][a-z0-9_-]{2,63}")


class PlanContractError(ValueError):
    """모델 plan·governance·binding 검증 실패를 안정된 machine code와 제한된 detail로 전달한다."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class _ServerBinding:
    name: str
    value_type: str
    value: str | bool | int | float


def load_binding_manifest(path: Path) -> dict[str, dict[str, dict[str, Any]]]:
    """모델·SFT 데이터 밖에 보관된 server binding manifest의 version과 case mapping을 검증한다."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise PlanContractError("BINDING_MANIFEST_INVALID", str(error)) from error
    if (
        not isinstance(payload, dict)
        or set(payload) != {"version", "cases"}
        or payload["version"] != BINDING_MANIFEST_VERSION
        or not isinstance(payload["cases"], dict)
    ):
        raise PlanContractError("BINDING_MANIFEST_INVALID")
    cases = payload["cases"]
    if any(not isinstance(key, str) or not isinstance(value, dict) for key, value in cases.items()):
        raise PlanContractError("BINDING_MANIFEST_INVALID")
    return cases


def _typed_bindings(request: dict[str, Any], supplied: Mapping[str, object] | None) -> dict[str, dict[str, Any]]:
    specs = {
        item["name"]: item["type"]
        for item in request["parameter_contract"]["parameters"]
    }
    if supplied is None:
        raise PlanContractError("BINDINGS_REQUIRED")
    if set(supplied) != set(specs):
        raise PlanContractError("PARAMETER_CONTRACT_MISMATCH")
    bindings: dict[str, dict[str, Any]] = {}
    for name, value in supplied.items():
        if (
            not isinstance(value, Mapping)
            or set(value) != {"value_type", "value"}
            or value["value_type"] != specs[name]
        ):
            raise PlanContractError("PARAMETER_CONTRACT_MISMATCH")
        bindings[name] = {
            "value_type": value["value_type"],
            "value": value["value"],
        }
    return bindings


def _runtime_package(request: dict[str, Any], bindings: dict[str, dict[str, Any]]) -> Any:
    schema_assets = request["schema_context"]["assets"]
    edge_values = request["join_graph"]["edges"]
    join_ids_by_asset = {
        asset["fqn"]: tuple(
            edge["id"]
            for edge in edge_values
            if asset["fqn"] in {edge["left"], edge["right"]}
        )
        for asset in schema_assets
    }
    assets = tuple(
        ContextAsset(
            urn=asset["urn"],
            fqn=asset["fqn"],
            columns=tuple(column["name"] for column in asset["columns"]),
            join_ids=join_ids_by_asset[asset["fqn"]],
            column_types=tuple(
                (column["name"], column["native_type"])
                for column in asset["columns"]
            ),
        )
        for asset in schema_assets
    )
    approved = {asset.fqn: frozenset(asset.columns) for asset in assets}
    joins = tuple(
        GovernedJoin.from_mapping(edge, approved_assets=approved)
        for edge in edge_values
    )
    rules = {
        rule["id"]: rule
        for rule in request["metric_rules"]
        if rule["id"] in request["resolved_request"]["metric_ids"]
    }
    if len(rules) != len(request["resolved_request"]["metric_ids"]):
        raise PlanContractError("METRIC_RULE_MISMATCH")
    metrics = tuple(_runtime_metric(rule) for rule in rules.values())
    parameter_bindings = tuple(
        _ServerBinding(name, value["value_type"], value["value"])
        for name, value in bindings.items()
    )
    contract_hash = _hash_payload(request)
    package = ContextPackage(
        context_release=request["schema_context"]["version"],
        policy_version=_hash_payload(request["query_policy"]),
        time_version=_hash_payload(request["time_rules"]),
        entitlement_hash=contract_hash,
        assets=assets,
        dataset_count=len(assets),
        column_count=sum(len(asset.columns) for asset in assets),
        token_count=1,
        token_limit=6_000,
        package_hash=contract_hash,
        approved_join_ids=tuple(join.id for join in joins),
        metrics=metrics,
        parameter_bindings=parameter_bindings,
    )
    runtime_contracts = {
        name: request[name]
        for name in (
            "schema_context",
            "metric_rules",
            "join_graph",
            "time_rules",
            "parameter_contract",
            "query_policy",
        )
    }
    runtime_contracts["metric_rules"] = list(rules.values())
    return enrich_context_package(package, runtime_contracts, joins)


def _runtime_metric(rule: dict[str, Any]) -> ContextMetric:
    time_field = rule["time_field"]
    if not isinstance(time_field, dict):
        raise PlanContractError("METRIC_RULE_MISMATCH")
    source = rule["source"]
    if source.get("kind") != "column" or not isinstance(source.get("field"), dict):
        raise PlanContractError("METRIC_RULE_MISMATCH")
    field = source["field"]
    if field["asset_fqn"] != time_field["asset_fqn"]:
        raise PlanContractError("METRIC_RULE_MISMATCH")
    return ContextMetric(
        id=rule["id"],
        asset_fqn=field["asset_fqn"],
        field=field["column"],
        aggregation=rule["aggregation"],
        time_field=time_field["column"],
        required_filters=(),
        result_field=rule["result_field"],
        unit=rule["unit"],
    )


def validate_output(
    node: str, request: dict[str, Any], output: dict[str, Any],
    bindings: Mapping[str, object] | None,
) -> dict[str, Any]:
    """출력 계약과 도메인 불변식을 검사하고 위반 시 명시적 오류를 발생시킨다.

    Validate one untrusted model output and bind only server-owned values.
    """
    try:
        checked = validate_model_output(node, output, request)
    except (DatasetError, KeyError, TypeError, ValueError) as error:
        raise PlanContractError("MODEL_SCHEMA_INVALID", str(error)) from error
    typed = _typed_bindings(request, bindings)
    try:
        package = _runtime_package(request, typed)
    except PlanContractError:
        raise
    except (KeyError, TypeError, ValueError) as error:
        raise PlanContractError("CONTEXT_SCHEMA_INVALID", str(error)) from error
    assert checked.expression is not None
    plan = None
    if node == "node2":
        plan = {
            "declared_assets": output["used_assets"],
            "declared_columns": output["used_columns"],
            "declared_joins": output["used_joins"],
            "declared_metrics": output["used_metrics"],
        }
    semantic = validate_parsed_semantics(checked, package, plan)
    if not semantic.ok:
        raise PlanContractError(
            semantic.violation or "SQL_GOVERNANCE_FAILED", semantic.detail
        )
    try:
        executable_sql = bind_sql_parameters(checked.expression, typed)
    except (SqlBindingError, TypeError, ValueError) as error:
        raise PlanContractError("PARAMETER_CONTRACT_MISMATCH", str(error)) from error
    return {
        "sql": checked.canonical_sql,
        "executable_sql": executable_sql,
        "ast_evidence": semantic.ast_evidence,
        "references": [dict(item) for item in semantic.references],
    }


def validate_g2(case: dict[str, Any], bindings: Mapping[str, object] | None) -> dict[str, Any]:
    """G2 계약과 도메인 불변식을 검사하고 위반 시 명시적 오류를 발생시킨다."""
    plan = validate_output(
        case["node"],
        case["input"],
        case["expected_output"],
        bindings,
    )
    if case["node"] == "node2_repair":
        rejected = {"corrected_sql": case["input"]["rejected_sql"]}
        try:
            validate_output("node2_repair", case["input"], rejected, bindings)
        except PlanContractError:
            pass
        else:
            raise PlanContractError("REJECTED_SQL_ACCEPTED")
    return plan


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


def _trino_cli_command(container: str, user: str) -> list[str]:
    if _DOCKER_CONTAINER.fullmatch(container) is None or _TRINO_USER.fullmatch(user) is None:
        raise ValueError("Trino container or user is invalid")
    return [
        "docker",
        "exec",
        "-i",
        "--env",
        "TRINO_PASSWORD",
        container,
        "trino",
        "--server",
        _TRINO_SERVER,
        "--user",
        user,
        "--password",
        "--truststore-path",
        _TRINO_CA_PATH,
        "--output-format",
        "JSON",
    ]


def _trino_cli_environment(password: str) -> dict[str, str]:
    if not isinstance(password, str) or not password or "\x00" in password:
        raise ValueError("Trino password is required")
    environment = dict(os.environ)
    environment["TRINO_PASSWORD"] = password
    return environment


def _execute(
    sql: str,
    *,
    container: str,
    user: str,
    password: str,
    timeout: float | None = None,
) -> subprocess.CompletedProcess[str]:
    """AST 검증·binding을 마친 SQL을 인증된 Trino CLI의 stdin으로만 전달한다.

    비밀번호는 child 환경과 이름만 지정한 ``docker exec --env``를 통해 전달하므로 process
    argv와 diagnostic에 포함되지 않는다. HTTPS와 배포 CA truststore는 고정해 insecure
    fallback이나 caller 임의 endpoint를 허용하지 않는다.
    """
    return subprocess.run(
        _trino_cli_command(container, user),
        input=sql + "\n",
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=_trino_cli_environment(password),
        timeout=timeout,
    )


def verify_case(
    case: dict[str, Any],
    *,
    bindings: Mapping[str, object] | None,
    container: str,
    user: str,
    password: str,
) -> None:
    """사례 계약과 도메인 불변식을 검사하고 위반 시 명시적 오류를 발생시킨다."""
    plan = validate_g2(case, bindings)
    result = _execute(
        plan["executable_sql"], container=container, user=user, password=password
    )
    if result.returncode:
        detail = (result.stderr or result.stdout).strip().splitlines()[-1]
        raise ValueError(f"{case['case_id']}: Trino failed: {detail}")
    case["trino_status"] = "PASS"
    case["result_sha256"] = _result_hash(result.stdout)


def verify_batch(
    cases: list[dict[str, Any]],
    *,
    binding_manifest: Mapping[str, Mapping[str, object]],
    container: str,
    user: str,
    password: str,
) -> None:
    """batch 계약과 도메인 불변식을 검사하고 위반 시 명시적 오류를 발생시킨다."""
    statements: list[str] = []
    markers: list[str] = []
    for case in cases:
        plan = validate_g2(case, binding_manifest.get(case["case_id"]))
        marker = hashlib.sha256(case["case_id"].encode()).hexdigest()
        markers.append(marker)
        statements.extend(
            (plan["executable_sql"] + ";", f"SELECT '{marker}' AS __case_marker LIMIT 1;")
        )
    result = subprocess.run(
        _trino_cli_command(container, user),
        input="\n".join(statements) + "\n",
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=_trino_cli_environment(password),
    )
    if result.returncode:
        detail = "\n".join((result.stderr or result.stdout).strip().splitlines()[-12:])
        raise ValueError(f"batch verification failed:\n{detail}")
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
        if verified >= len(cases) or marker != markers[verified]:
            raise ValueError("batch result marker mismatch")
        cases[verified]["trino_status"] = "PASS"
        cases[verified]["result_sha256"] = _rows_hash(rows)
        rows = []
        verified += 1
    if verified != len(cases) or rows:
        raise ValueError(f"batch result boundary mismatch: {verified}/{len(cases)}")


def _hash_payload(value: object) -> str:
    canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def main() -> int:
    """full-spec SQL을 G2·server binding 후 인증 Trino에서 실행해 case별 result hash를 확정한다."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--bindings", type=Path, required=True)
    parser.add_argument("--container", required=True)
    parser.add_argument("--user", default=os.getenv("TRINO_RUNTIME_USER", ""))
    parser.add_argument("--batch-size", type=int, default=0)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    password = os.getenv("TRINO_RUNTIME_PASSWORD", "")
    _trino_cli_command(args.container, args.user)
    _trino_cli_environment(password)
    cases = load_specs(args.output if args.resume and args.output.exists() else args.source)
    manifest = load_binding_manifest(args.bindings)
    if args.batch_size:
        pending = [case for case in cases if case["trino_status"] != "PASS"]
        for start in range(0, len(pending), args.batch_size):
            batch = pending[start : start + args.batch_size]
            verify_batch(
                batch,
                binding_manifest=manifest,
                container=args.container,
                user=args.user,
                password=password,
            )
            write_jsonl(args.output, cases)
    else:
        for case in cases:
            verify_case(
                case,
                bindings=manifest.get(case["case_id"]),
                container=args.container,
                user=args.user,
                password=password,
            )
    write_jsonl(args.output, cases)
    load_specs(args.output)
    print(json.dumps(summarize(cases), ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
