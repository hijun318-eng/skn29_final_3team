"""Run the sealed P0 Gold twice through the isolated Phase 10 product API."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic
from typing import Any
from uuid import uuid4

import httpx
import psycopg
from dotenv import dotenv_values
from psycopg.rows import dict_row
from sqlalchemy.engine import URL, make_url


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evals.p0_gold import canonical_sha256, validate_manifest  # noqa: E402
from evals.p0_gold_scoring import evaluate_observations  # noqa: E402
from infrastructure.acceptance.phase10_p0_release_seal import (  # noqa: E402
    SYNTHETIC_NOTICE,
    validate_release_seal_receipt,
)


TARGET_PROJECT = "answervice-phase2b-datahub"
TARGET_SERVER = "http://127.0.0.1:48000"
TARGET_HOST = "127.0.0.1"
TARGET_PORT = 55440
TARGET_DATABASE = "phase10_p0_same_release_acceptance"
TARGET_USER = "phase10_runtime"
REPEAT = 2
CONTRACT_VERSION = "OPENAPI-v1.0.0"
LEASE_VERSION = "answervice.phase10_p0_product_eval_lease.v1"
RECEIPT_VERSION = "answervice.phase10_p0_product_eval_receipt.v1"

ENV_FILE = ROOT / "infrastructure" / "database" / ".env"
SEALED_DIRECTORY = ROOT / ".tmp" / "phase10-p0-sealed-v2"
SEALED_MANIFEST = SEALED_DIRECTORY / "answervice_v4_3.p0.candidate.v2.manifest.json"
SEALED_CASES = SEALED_DIRECTORY / "answervice_v4_3.p0.candidate.v2.jsonl"
SEALED_SEMANTIC = SEALED_DIRECTORY / "answervice_d2_metrics.v1.json"
SEALED_RECEIPT = SEALED_DIRECTORY / "phase10_p0_release_seal.receipt.json"

OUTPUT_LEASE = ROOT / ".tmp" / "phase10-p0-product-eval.lease.json"
OUTPUT_PARTIAL = ROOT / ".tmp" / "phase10-p0-product-eval.partial.jsonl"
OUTPUT_OBSERVATIONS = ROOT / ".tmp" / "phase10-p0-product-observations.jsonl"
OUTPUT_RECEIPT = ROOT / ".tmp" / "phase10-p0-product-eval.receipt.json"

_OUTPUT_KEYS = {
    "route",
    "resolved_request",
    "query_strategy",
    "assets",
    "join_ids",
    "allow_or_block",
    "error_code",
    "result",
}
_RESOLVED_KEYS = {
    "business_terms",
    "metric_ids",
    "dimensions",
    "period",
    "time_rule",
    "grain",
    "chart_type",
    "operations",
}
_NUMBER = re.compile(r"^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$")


class Phase10P0ProductEvalError(RuntimeError):
    """The product evaluation boundary, evidence, or response contract differs."""


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-project", required=True)
    parser.add_argument("--target-server", required=True)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--repeat", type=int, default=REPEAT)
    parser.add_argument("--timeout", type=float, default=180.0)
    return parser.parse_args(argv)


def _database_url(value: str) -> URL:
    url = make_url(value)
    if (
        url.drivername != "postgresql+psycopg"
        or url.host not in {TARGET_HOST, "localhost", "::1"}
        or url.port != TARGET_PORT
        or url.database != TARGET_DATABASE
        or url.username != TARGET_USER
        or url.password is not None
        or url.query
    ):
        raise Phase10P0ProductEvalError(
            "Phase 10 product evaluation database is outside the isolated boundary"
        )
    return url


def validate_boundary(args: argparse.Namespace) -> URL:
    if args.target_project != TARGET_PROJECT:
        raise Phase10P0ProductEvalError(
            "Phase 10 product evaluation project is outside the approved boundary"
        )
    endpoint = httpx.URL(args.target_server)
    if (
        args.target_server.rstrip("/") != TARGET_SERVER
        or endpoint.scheme != "http"
        or endpoint.host not in {TARGET_HOST, "localhost", "::1"}
        or endpoint.port != 48000
        or endpoint.username
        or endpoint.password
        or endpoint.query
        or endpoint.fragment
        or endpoint.path not in {"", "/"}
    ):
        raise Phase10P0ProductEvalError(
            "Phase 10 product evaluation API is outside the isolated boundary"
        )
    try:
        env_file = args.env_file.resolve(strict=True)
    except OSError as error:
        raise Phase10P0ProductEvalError(
            "Phase 10 product evaluation environment is unavailable"
        ) from error
    if env_file != ENV_FILE.resolve(strict=True) or not env_file.is_file():
        raise Phase10P0ProductEvalError(
            "Phase 10 product evaluation environment differs"
        )
    if args.repeat != REPEAT:
        raise Phase10P0ProductEvalError("Phase 10 P0 evaluation requires exactly two repeats")
    if args.timeout <= 0 or args.timeout > 300:
        raise Phase10P0ProductEvalError(
            "Phase 10 product evaluation timeout is outside the bound"
        )
    return _database_url(args.database_url)


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise Phase10P0ProductEvalError("sealed product evaluation JSON is unavailable") from error
    if not isinstance(value, dict):
        raise Phase10P0ProductEvalError("sealed product evaluation JSON must be an object")
    return value


def _load_cases(path: Path) -> tuple[bytes, list[dict[str, Any]]]:
    try:
        payload = path.read_bytes()
        rows = [
            json.loads(line)
            for line in payload.decode("utf-8").splitlines()
            if line.strip()
        ]
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise Phase10P0ProductEvalError("sealed product evaluation cases are unavailable") from error
    if len(rows) != 55 or any(not isinstance(row, dict) for row in rows):
        raise Phase10P0ProductEvalError("sealed product evaluation case inventory differs")
    return payload, rows


def _sha256(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as error:
        raise Phase10P0ProductEvalError("product evaluation input is unreadable") from error


def _sealed_inputs() -> tuple[
    dict[str, Any], list[dict[str, Any]], dict[str, Any], dict[str, Any], dict[str, Any]
]:
    manifest = _load_json(SEALED_MANIFEST)
    case_payload, cases = _load_cases(SEALED_CASES)
    semantic = _load_json(SEALED_SEMANTIC)
    receipt = _load_json(SEALED_RECEIPT)
    validate_release_seal_receipt(receipt)
    validation = validate_manifest(
        manifest,
        cases,
        semantic,
        observed_case_content_sha256=hashlib.sha256(case_payload).hexdigest(),
    )
    product = receipt.get("product_release")
    release = receipt.get("semantic_release")
    gold = receipt.get("gold")
    if (
        validation.get("status") != "VALID_SEALED_GOLD"
        or validation.get("scorable") is not True
        or validation.get("case_counts") != {
            "MULTI_TURN": 10,
            "SAFETY": 15,
            "STRUCTURED": 30,
        }
        or not isinstance(product, Mapping)
        or not isinstance(release, Mapping)
        or not isinstance(gold, Mapping)
        or manifest.get("product_release_id") != product.get("product_release_id")
        or manifest.get("semantic_release_id") != release.get("release_id")
        or validation.get("manifest_sha256") != gold.get("manifest_sha256")
        or validation.get("case_content_sha256") != gold.get("case_content_sha256")
    ):
        raise Phase10P0ProductEvalError("sealed P0 evaluation binding differs")
    return manifest, cases, semantic, receipt, validation


def _connect(url: URL) -> psycopg.Connection[Any]:
    return psycopg.connect(
        host=url.host,
        port=url.port,
        dbname=url.database,
        user=url.username,
        row_factory=dict_row,
    )


def _active_release(url: URL) -> dict[str, Any]:
    try:
        with _connect(url) as connection:
            row = connection.execute(
                """
                SELECT a.generation, a.product_release_id, a.projection_id,
                       p.catalog_release_id, p.projection_sha256
                FROM governance.runtime_catalog_active_pointer a
                JOIN governance.runtime_catalog_projections p
                  ON p.projection_id = a.projection_id
                WHERE a.pointer_name = 'analysis'
                """
            ).fetchone()
    except psycopg.Error as error:
        raise Phase10P0ProductEvalError(
            "isolated Phase 10 active release is unreadable"
        ) from error
    if row is None:
        raise Phase10P0ProductEvalError("isolated Phase 10 active release is unavailable")
    return {
        "generation": int(row["generation"]),
        "product_release_id": str(row["product_release_id"]),
        "projection_id": str(row["projection_id"]),
        "semantic_release_id": str(row["catalog_release_id"]),
        "projection_sha256": str(row["projection_sha256"]),
    }


def _assert_active_release(active: Mapping[str, Any], receipt: Mapping[str, Any]) -> None:
    product = receipt.get("product_release")
    semantic = receipt.get("semantic_release")
    if (
        not isinstance(product, Mapping)
        or not isinstance(semantic, Mapping)
        or active.get("generation") != receipt.get("active_generation")
        or active.get("product_release_id") != product.get("product_release_id")
        or active.get("semantic_release_id") != semantic.get("release_id")
        or active.get("projection_sha256") != semantic.get("projection_sha256")
    ):
        raise Phase10P0ProductEvalError(
            "active Phase 10 release differs from the P0 seal"
        )


def _credentials(path: Path) -> tuple[str, str]:
    values = dotenv_values(path)
    username = str(values.get("ANALYST_LOGIN_ID") or "").strip()
    password = str(values.get("ANALYST_LOGIN_PASSWORD") or "")
    role = str(values.get("ANALYST_LOGIN_ROLE") or "").strip().lower()
    if not username or not password or role != "analyst":
        raise Phase10P0ProductEvalError(
            "isolated analyst evaluation credential is incomplete"
        )
    return username, password


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        temporary.write_bytes(payload)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode(
        "utf-8"
    )


def _jsonl_bytes(values: Sequence[Mapping[str, Any]]) -> bytes:
    return (
        "".join(
            json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            + "\n"
            for value in values
        )
    ).encode("utf-8")


def _checked_document(payload: Mapping[str, Any]) -> dict[str, Any]:
    document = dict(payload)
    document["receipt_sha256"] = canonical_sha256(document)
    return document


def validate_lease(document: Mapping[str, Any], expected: Mapping[str, Any]) -> None:
    checksum = document.get("receipt_sha256")
    payload = {key: value for key, value in document.items() if key != "receipt_sha256"}
    if (
        payload != dict(expected)
        or payload.get("schema_version") != LEASE_VERSION
        or checksum != canonical_sha256(payload)
    ):
        raise Phase10P0ProductEvalError("Phase 10 product evaluation lease differs")


def _lease_payload(
    active: Mapping[str, Any], receipt: Mapping[str, Any], validation: Mapping[str, Any]
) -> dict[str, Any]:
    return {
        "schema_version": LEASE_VERSION,
        "target_project": TARGET_PROJECT,
        "target_server": TARGET_SERVER,
        "target_database": TARGET_DATABASE,
        "active_generation": active["generation"],
        "product_release_id": active["product_release_id"],
        "semantic_release_id": active["semantic_release_id"],
        "projection_sha256": active["projection_sha256"],
        "seal_receipt_sha256": receipt["receipt_sha256"],
        "gold_manifest_sha256": validation["manifest_sha256"],
        "gold_case_content_sha256": validation["case_content_sha256"],
        "semantic_file_sha256": _sha256(SEALED_SEMANTIC),
        "repeat": REPEAT,
        "case_count": 55,
        "historical_evidence_mixed": False,
        "skipped_evidence_count": 0,
    }


def _prepare_lease(payload: Mapping[str, Any]) -> None:
    if OUTPUT_LEASE.exists():
        validate_lease(_load_json(OUTPUT_LEASE), payload)
        return
    unrelated = [path for path in (OUTPUT_PARTIAL, OUTPUT_OBSERVATIONS, OUTPUT_RECEIPT) if path.exists()]
    if unrelated:
        raise Phase10P0ProductEvalError(
            "product evaluation output exists without its exact lease"
        )
    _atomic_write(OUTPUT_LEASE, _json_bytes(_checked_document(payload)))


def _validate_output(value: object) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != _OUTPUT_KEYS:
        raise Phase10P0ProductEvalError("product observation output contract differs")
    resolved = value.get("resolved_request")
    if not isinstance(resolved, dict) or set(resolved) != _RESOLVED_KEYS:
        raise Phase10P0ProductEvalError("product resolved request contract differs")
    return value


def _load_partial(cases: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    if not OUTPUT_PARTIAL.exists():
        return []
    case_ids = {str(case["case_id"]) for case in cases}
    try:
        values = [
            json.loads(line)
            for line in OUTPUT_PARTIAL.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise Phase10P0ProductEvalError("product evaluation partial evidence is invalid") from error
    seen: set[tuple[str, int]] = set()
    for row in values:
        if not isinstance(row, dict) or set(row) != {
            "case_id",
            "attempt",
            "latency_ms",
            "output",
            "evidence",
        }:
            raise Phase10P0ProductEvalError("product evaluation partial row differs")
        key = (str(row["case_id"]), row["attempt"])
        if (
            key[0] not in case_ids
            or not isinstance(key[1], int)
            or isinstance(key[1], bool)
            or key[1] not in range(1, REPEAT + 1)
            or key in seen
            or not isinstance(row["latency_ms"], (int, float))
            or isinstance(row["latency_ms"], bool)
            or row["latency_ms"] < 0
            or not isinstance(row["evidence"], dict)
        ):
            raise Phase10P0ProductEvalError("product evaluation partial identity differs")
        _validate_output(row["output"])
        seen.add(key)
    return values


def _semantic_maps(semantic: Mapping[str, Any]) -> tuple[dict[str, Mapping[str, Any]], dict[str, str]]:
    metrics = semantic.get("metrics")
    if not isinstance(metrics, list):
        raise Phase10P0ProductEvalError("sealed semantic metric inventory differs")
    by_id: dict[str, Mapping[str, Any]] = {}
    by_field: dict[str, str] = {}
    for value in metrics:
        if not isinstance(value, Mapping):
            raise Phase10P0ProductEvalError("sealed semantic metric entry differs")
        metric_id = value.get("id")
        result_field = value.get("result_field")
        if (
            not isinstance(metric_id, str)
            or not metric_id
            or not isinstance(result_field, str)
            or not result_field
            or metric_id in by_id
            or result_field in by_field
        ):
            raise Phase10P0ProductEvalError("sealed semantic metric identity differs")
        by_id[metric_id] = value
        by_field[result_field] = metric_id
    return by_id, by_field


def _unique_texts(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        if isinstance(item, str) and item and item not in result:
            result.append(item)
    return result


def _metric_ids(slots: Mapping[str, Any]) -> list[str]:
    values = _unique_texts(slots.get("metric_ids"))
    single = slots.get("metric_id")
    if isinstance(single, str) and single and single not in values:
        values.insert(0, single)
    return values


def _dimensions(slots: Mapping[str, Any]) -> list[str]:
    values = slots.get("dimension_fields")
    if not isinstance(values, list):
        return []
    result: list[str] = []
    for item in values:
        column = item.get("column") if isinstance(item, Mapping) else None
        if isinstance(column, str) and column and column not in result:
            result.append(column)
    return result


def _period(slots: Mapping[str, Any]) -> dict[str, str] | None:
    periods = []
    for field in ("time_range", "comparison_time_range"):
        value = slots.get(field)
        if not isinstance(value, Mapping):
            continue
        start, end = value.get("start"), value.get("end_exclusive")
        if isinstance(start, str) and isinstance(end, str) and start < end:
            periods.append((start, end))
    if not periods:
        return None
    return {
        "start": min(item[0] for item in periods),
        "end_exclusive": max(item[1] for item in periods),
    }


def _operations(slots: Mapping[str, Any]) -> list[str]:
    changes = slots.get("change_set")
    if not isinstance(changes, list):
        return []
    fields = {
        "metric_id": "metric_ids",
        "metric_ids": "metric_ids",
        "dimension_fields": "dimensions",
        "dimensions": "dimensions",
        "user_filters": "filters",
        "filters": "filters",
        "time_range": "period",
        "period": "period",
        "comparison_time_range": "comparison_period",
        "comparison_period": "comparison_period",
        "target_chart_type": "chart_type",
        "chart_type": "chart_type",
    }
    result: list[str] = []
    for value in changes:
        if not isinstance(value, Mapping):
            continue
        operation = value.get("operation")
        field = fields.get(str(value.get("field") or ""))
        if operation not in {"SET", "CLEAR", "ADD_VALUE", "REMOVE_VALUE"} or field is None:
            continue
        item = f"{operation}:{field}"
        if item not in result:
            result.append(item)
    return result


def _time_rule(metric_ids: Sequence[str], by_id: Mapping[str, Mapping[str, Any]]) -> str | None:
    rules: set[str] = set()
    for metric_id in metric_ids:
        metric = by_id.get(metric_id)
        time_contract = metric.get("time") if isinstance(metric, Mapping) else None
        if not isinstance(time_contract, Mapping):
            return None
        semantics, interval = time_contract.get("semantics"), time_contract.get("interval")
        if not isinstance(semantics, str) or not isinstance(interval, str):
            return None
        rules.add(f"{semantics}:{interval}")
    return next(iter(rules)) if len(rules) == 1 else None


def _source_plan(turns: Sequence[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    if not turns:
        return None
    final = turns[-1]
    slots = final.get("resolved_slots")
    direct = slots.get("analysis_plan_observation") if isinstance(slots, Mapping) else None
    if isinstance(direct, Mapping):
        return direct
    source_ids = {
        str(value) for value in (final.get("source_turn_ids") or []) if isinstance(value, str)
    }
    for turn in reversed(turns[:-1]):
        if source_ids and str(turn.get("turn_id")) not in source_ids:
            continue
        candidate_slots = turn.get("resolved_slots")
        candidate = (
            candidate_slots.get("analysis_plan_observation")
            if isinstance(candidate_slots, Mapping)
            else None
        )
        if isinstance(candidate, Mapping):
            return candidate
    return None


def _dimension_grain(column: str) -> str:
    if column.endswith("_at_booking"):
        return f"booking_{column.removesuffix('_at_booking')}"
    if column.endswith("_at_stay"):
        return f"stay_{column.removesuffix('_at_stay')}"
    aliases = {"hotel_code": "hotel", "selected_category": "category"}
    return aliases.get(column, column.removesuffix("_code"))


def _grain(
    dimensions: Sequence[str],
    metric_ids: Sequence[str],
    turns: Sequence[Mapping[str, Any]],
    by_id: Mapping[str, Mapping[str, Any]],
) -> str | None:
    plan = _source_plan(turns)
    raw_bucket = plan.get("time_bucket") if isinstance(plan, Mapping) else None
    bucket = raw_bucket.lower() if isinstance(raw_bucket, str) and raw_bucket else None
    if bucket in {"none", "null"}:
        bucket = None
    if bucket in {"day", "daily"}:
        semantics = {
            str((by_id.get(metric_id) or {}).get("time", {}).get("semantics") or "")
            for metric_id in metric_ids
        }
        bucket = "business_day" if semantics == {"BUSINESS_DATE"} else "day"
    parts = ([bucket] if bucket else []) + [_dimension_grain(value) for value in dimensions]
    return "_".join(part for part in parts if part) or None


def _number(value: object) -> object:
    if not isinstance(value, str) or not _NUMBER.fullmatch(value):
        return value
    try:
        if "." not in value:
            return int(value)
        number = float(value)
        return int(number) if number.is_integer() else number
    except (ValueError, OverflowError):
        return value


def normalize_result(
    snapshot: object,
    result_fields: Mapping[str, str],
    metric_ids: Sequence[str],
) -> object:
    if not isinstance(snapshot, Mapping):
        return None
    raw_columns, raw_rows = snapshot.get("columns"), snapshot.get("rows")
    if not isinstance(raw_columns, list) or not isinstance(raw_rows, list):
        return None
    columns: list[str] = []
    for value in raw_columns:
        if not isinstance(value, str) or not value:
            return None
        mapped = result_fields.get(value, value)
        if mapped in columns:
            return None
        columns.append(mapped)
    rows: list[list[object]] = []
    for raw_row in raw_rows:
        if not isinstance(raw_row, Mapping):
            return None
        rows.append([_number(raw_row.get(raw)) for raw in raw_columns])
    if len(columns) == 1 and len(rows) == 1 and columns[0] in set(metric_ids):
        value = rows[0][0]
        return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None
    return {"columns": columns, "rows": rows}


def _empty_resolved() -> dict[str, Any]:
    return {
        "business_terms": [],
        "metric_ids": [],
        "dimensions": [],
        "period": None,
        "time_rule": None,
        "grain": None,
        "chart_type": None,
        "operations": [],
    }


def normalize_product_output(
    turns: Sequence[Mapping[str, Any]],
    semantic: Mapping[str, Any],
    *,
    product_error_code: str | None = None,
) -> dict[str, Any]:
    by_id, by_field = _semantic_maps(semantic)
    if not turns:
        return _validate_output(
            {
                "route": None,
                "resolved_request": _empty_resolved(),
                "query_strategy": None,
                "assets": [],
                "join_ids": [],
                "allow_or_block": "BLOCK",
                "error_code": product_error_code or "PRODUCT_RESPONSE_UNAVAILABLE",
                "result": None,
            }
        )
    final = turns[-1]
    slots_value = final.get("resolved_slots")
    slots = slots_value if isinstance(slots_value, Mapping) else {}
    metric_ids = _metric_ids(slots)
    dimensions = _dimensions(slots)
    terminal = str(final.get("terminal_status") or "")
    allowed = terminal in {"SUCCEEDED", "PARTIAL"} and product_error_code is None
    plan = _source_plan(turns) if allowed and final.get("route") == "ANALYSIS" else None
    query_strategy = plan.get("query_strategy") if isinstance(plan, Mapping) else None
    assets = _unique_texts(plan.get("source_assets")) if isinstance(plan, Mapping) else []
    join_ids = _unique_texts(plan.get("join_ids")) if isinstance(plan, Mapping) else []
    reason = product_error_code or final.get("reason_code")
    chart = slots.get("target_chart_type")
    resolved = {
        "business_terms": _unique_texts(slots.get("business_terms")),
        "metric_ids": metric_ids,
        "dimensions": dimensions,
        "period": _period(slots),
        "time_rule": _time_rule(metric_ids, by_id),
        "grain": _grain(dimensions, metric_ids, turns, by_id),
        "chart_type": chart.upper() if isinstance(chart, str) and chart else None,
        "operations": _operations(slots),
    }
    output = {
        "route": final.get("route"),
        "resolved_request": resolved,
        "query_strategy": query_strategy,
        "assets": assets,
        "join_ids": join_ids,
        "allow_or_block": "ALLOW" if allowed else "BLOCK",
        "error_code": None if allowed else str(reason or "PRODUCT_BLOCKED_WITHOUT_CODE"),
        "result": (
            normalize_result(final.get("data_snapshot_json"), by_field, metric_ids)
            if allowed
            else None
        ),
    }
    return _validate_output(output)


def _response_json(response: httpx.Response) -> dict[str, Any]:
    try:
        value = response.json()
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def _response_error_code(response: httpx.Response, payload: Mapping[str, Any]) -> str:
    error = payload.get("error")
    if isinstance(error, Mapping) and isinstance(error.get("code"), str):
        return str(error["code"])
    detail = payload.get("detail")
    if isinstance(detail, Mapping) and isinstance(detail.get("code"), str):
        return str(detail["code"])
    return f"HTTP_{response.status_code}"


def _headers(trace_id: str) -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "X-Contract-Version": CONTRACT_VERSION,
        "X-Timezone": "Asia/Seoul",
        "X-Trace-Id": trace_id,
    }


def _release_turn(
    turn: Mapping[str, Any], product_release_id: str, semantic_release_id: str
) -> None:
    if (
        turn.get("product_release_id") != product_release_id
        or turn.get("semantic_release_id") != semantic_release_id
    ):
        raise Phase10P0ProductEvalError(
            "product turn release differs from the sealed Phase 10 release"
        )


def _model_and_query_evidence(command_results: Sequence[Mapping[str, Any]]) -> tuple[
    dict[str, int], list[str]
]:
    nodes: Counter[str] = Counter()
    query_ids: set[str] = set()
    for command in command_results:
        response = command.get("analysis_response")
        data = response.get("data") if isinstance(response, Mapping) else None
        artifact = data.get("artifact") if isinstance(data, Mapping) else None
        result = data.get("result") if isinstance(data, Mapping) else None
        evidence = result.get("evidence") if isinstance(result, Mapping) else None
        query_id = artifact.get("query_id") if isinstance(artifact, Mapping) else None
        evidence_query = evidence.get("query_id") if isinstance(evidence, Mapping) else None
        for value in (query_id, evidence_query):
            if isinstance(value, str) and value:
                query_ids.add(value)
        models = evidence.get("models") if isinstance(evidence, Mapping) else None
        if isinstance(models, list):
            for model in models:
                node = model.get("node") if isinstance(model, Mapping) else None
                if isinstance(node, str) and node:
                    nodes[node] += 1
    return dict(sorted(nodes.items())), sorted(query_ids)


async def _execute_case(
    client: httpx.AsyncClient,
    case: Mapping[str, Any],
    attempt: int,
    semantic: Mapping[str, Any],
    product_release_id: str,
    semantic_release_id: str,
) -> dict[str, Any]:
    case_id = str(case["case_id"])
    started = monotonic()
    create = await client.post(
        "/conversations",
        headers=_headers(f"p0-{uuid4().hex}"),
        json={"title": f"Phase10 P0 {case_id} attempt {attempt}"},
    )
    if create.status_code >= 400:
        raise Phase10P0ProductEvalError(
            "isolated product conversation creation failed"
        )
    create_payload = _response_json(create)
    conversation = create_payload.get("data")
    conversation_id = conversation.get("conversation_id") if isinstance(conversation, Mapping) else None
    if not isinstance(conversation_id, str) or not conversation_id:
        raise Phase10P0ProductEvalError(
            "isolated product conversation response differs"
        )

    utterances = case.get("utterances")
    if not isinstance(utterances, list) or not utterances:
        raise Phase10P0ProductEvalError("sealed P0 utterance inventory differs")
    head: str | None = None
    turns: list[Mapping[str, Any]] = []
    command_results: list[Mapping[str, Any]] = []
    final_error: str | None = None
    for turn_number, utterance in enumerate(utterances, start=1):
        if not isinstance(utterance, str) or not utterance:
            raise Phase10P0ProductEvalError("sealed P0 utterance differs")
        response = await client.post(
            f"/conversations/{conversation_id}/commands",
            headers=_headers(f"p0-{uuid4().hex}"),
            json={
                "user_message": utterance,
                "expected_head_turn_id": head,
                "idempotency_key": (
                    f"phase10-p0-{case_id.lower()}-{attempt}-{turn_number}-{uuid4().hex}"
                )[:128],
            },
        )
        payload = _response_json(response)
        if response.status_code >= 400:
            final_error = _response_error_code(response, payload)
            break
        result = payload.get("data")
        if not isinstance(result, Mapping):
            final_error = "PRODUCT_COMMAND_RESPONSE_INVALID"
            break
        command_results.append(result)
        turn = result.get("turn")
        if isinstance(turn, Mapping):
            _release_turn(turn, product_release_id, semantic_release_id)
            turns.append(turn)
        conversation_state = result.get("conversation")
        next_head = (
            conversation_state.get("head_turn_id")
            if isinstance(conversation_state, Mapping)
            else None
        )
        if isinstance(next_head, str) and next_head:
            head = next_head
        elif isinstance(turn, Mapping) and isinstance(turn.get("turn_id"), str):
            head = str(turn["turn_id"])
        else:
            final_error = str(result.get("code") or "PRODUCT_TURN_NOT_PERSISTED")
            break

    if final_error is None and command_results:
        final_result = command_results[-1]
        final_status = str(final_result.get("status") or "")
        if final_status not in {"SUCCESS", "PARTIAL"}:
            code = final_result.get("code")
            final_error = str(code) if isinstance(code, str) and code else None
    output = normalize_product_output(
        turns,
        semantic,
        product_error_code=final_error,
    )
    latency_ms = round((monotonic() - started) * 1000, 3)
    model_counts, query_ids = _model_and_query_evidence(command_results)
    final_turn = turns[-1] if turns else {}
    evidence = {
        "conversation_id": conversation_id,
        "final_turn_id": final_turn.get("turn_id"),
        "request_ids": sorted(
            {
                str(turn["request_id"])
                for turn in turns
                if turn.get("request_id") is not None
            }
        ),
        "artifact_ids": sorted(
            {
                str(turn["artifact_id"])
                for turn in turns
                if turn.get("artifact_id") is not None
            }
        ),
        "query_ids": query_ids,
        "product_release_id": final_turn.get("product_release_id") or product_release_id,
        "semantic_release_id": final_turn.get("semantic_release_id") or semantic_release_id,
        "terminal_status": final_turn.get("terminal_status") or "NO_PERSISTED_TURN",
        "product_error_code": final_error,
        "model_invocation_count_by_node": model_counts,
        "node2_model_invocation_count": sum(
            count for node, count in model_counts.items() if node.lower() == "node2"
        ),
        "output_sha256": canonical_sha256(output),
    }
    return {
        "case_id": case_id,
        "attempt": attempt,
        "latency_ms": latency_ms,
        "output": output,
        "evidence": evidence,
    }


async def _authenticate(
    client: httpx.AsyncClient, username: str, password: str
) -> None:
    readiness = await client.get("/readiness")
    readiness_payload = _response_json(readiness)
    data = readiness_payload.get("data")
    dependencies = data.get("dependencies") if isinstance(data, Mapping) else None
    if (
        readiness.status_code != 200
        or not isinstance(data, Mapping)
        or data.get("status") != "ready"
        or not isinstance(dependencies, Mapping)
        or not dependencies
        or any(value not in {"ready", "not_required"} for value in dependencies.values())
    ):
        raise Phase10P0ProductEvalError(
            "isolated product is not ready for P0 evaluation"
        )
    login = await client.post(
        "/auth/login",
        headers={"Content-Type": "application/json"},
        json={"username": username, "password": password},
    )
    payload = _response_json(login)
    session = payload.get("data")
    if (
        login.status_code != 200
        or not isinstance(session, Mapping)
        or str(session.get("role") or "").lower() != "analyst"
    ):
        raise Phase10P0ProductEvalError(
            "isolated analyst product session could not be established"
        )


def _evaluation_receipt(
    *,
    active: Mapping[str, Any],
    seal: Mapping[str, Any],
    validation: Mapping[str, Any],
    scoring: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    observations_sha256 = hashlib.sha256(_jsonl_bytes([
        {
            "case_id": row["case_id"],
            "attempt": row["attempt"],
            "latency_ms": row["latency_ms"],
            "output": row["output"],
        }
        for row in rows
    ])).hexdigest()
    node_counts: Counter[str] = Counter()
    for row in rows:
        evidence = row.get("evidence")
        counts = evidence.get("model_invocation_count_by_node") if isinstance(evidence, Mapping) else None
        if isinstance(counts, Mapping):
            for node, count in counts.items():
                if isinstance(node, str) and isinstance(count, int) and not isinstance(count, bool):
                    node_counts[node] += count
    passed = scoring.get("passed") == 55 and scoring.get("deterministic") == 55
    payload = {
        "schema_version": RECEIPT_VERSION,
        "status": "PASSED" if passed else "BLOCKED",
        "target_project": TARGET_PROJECT,
        "target_server": TARGET_SERVER,
        "content_notice": SYNTHETIC_NOTICE,
        "active_generation": active["generation"],
        "product_release_id": active["product_release_id"],
        "semantic_release_id": active["semantic_release_id"],
        "projection_sha256": active["projection_sha256"],
        "seal_receipt_sha256": seal["receipt_sha256"],
        "gold_manifest_sha256": validation["manifest_sha256"],
        "case_count": 55,
        "repeat": REPEAT,
        "observation_count": len(rows),
        "observations_file": OUTPUT_OBSERVATIONS.relative_to(ROOT).as_posix(),
        "observations_sha256": observations_sha256,
        "model_invocation_count_by_node": dict(sorted(node_counts.items())),
        "scoring": dict(scoring),
        "historical_evidence_mixed": False,
        "skipped_evidence_count": 0,
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
    }
    return _checked_document(payload)


def validate_evaluation_receipt(
    document: Mapping[str, Any],
    *,
    observations_sha256: str | None = None,
    active_generation: int | None = None,
    product_release_id: str | None = None,
    semantic_release_id: str | None = None,
    seal_receipt_sha256: str | None = None,
) -> None:
    checksum = document.get("receipt_sha256")
    payload = {key: value for key, value in document.items() if key != "receipt_sha256"}
    scoring = document.get("scoring")
    status = document.get("status")
    passed = isinstance(scoring, Mapping) and scoring.get("passed") == 55
    deterministic = (
        isinstance(scoring, Mapping) and scoring.get("deterministic") == 55
    )
    if (
        document.get("schema_version") != RECEIPT_VERSION
        or status not in {"PASSED", "BLOCKED"}
        or document.get("target_project") != TARGET_PROJECT
        or document.get("target_server") != TARGET_SERVER
        or document.get("content_notice") != SYNTHETIC_NOTICE
        or document.get("case_count") != 55
        or document.get("repeat") != REPEAT
        or document.get("observation_count") != 55 * REPEAT
        or document.get("observations_file")
        != OUTPUT_OBSERVATIONS.relative_to(ROOT).as_posix()
        or not isinstance(document.get("observations_sha256"), str)
        or len(str(document.get("observations_sha256"))) != 64
        or not isinstance(scoring, Mapping)
        or scoring.get("total") != 55
        or scoring.get("repeat") != REPEAT
        or (status == "PASSED") != (passed and deterministic)
        or document.get("historical_evidence_mixed") is not False
        or document.get("skipped_evidence_count") != 0
        or not isinstance(checksum, str)
        or checksum != canonical_sha256(payload)
        or (
            observations_sha256 is not None
            and document.get("observations_sha256") != observations_sha256
        )
        or (
            active_generation is not None
            and document.get("active_generation") != active_generation
        )
        or (
            product_release_id is not None
            and document.get("product_release_id") != product_release_id
        )
        or (
            semantic_release_id is not None
            and document.get("semantic_release_id") != semantic_release_id
        )
        or (
            seal_receipt_sha256 is not None
            and document.get("seal_receipt_sha256") != seal_receipt_sha256
        )
    ):
        raise Phase10P0ProductEvalError(
            "Phase 10 P0 product evaluation receipt differs"
        )


async def run_async(args: argparse.Namespace) -> dict[str, Any]:
    url = validate_boundary(args)
    _manifest, cases, semantic, seal, validation = _sealed_inputs()
    active = _active_release(url)
    _assert_active_release(active, seal)
    lease = _lease_payload(active, seal, validation)
    _prepare_lease(lease)
    rows = _load_partial(cases)
    completed = {(str(row["case_id"]), int(row["attempt"])) for row in rows}
    username, password = _credentials(args.env_file)
    try:
        async with httpx.AsyncClient(
            base_url=TARGET_SERVER,
            timeout=httpx.Timeout(args.timeout),
            trust_env=False,
        ) as client:
            await _authenticate(client, username, password)
            for case in cases:
                case_id = str(case["case_id"])
                for attempt in range(1, REPEAT + 1):
                    if (case_id, attempt) in completed:
                        continue
                    row = await _execute_case(
                        client,
                        case,
                        attempt,
                        semantic,
                        str(active["product_release_id"]),
                        str(active["semantic_release_id"]),
                    )
                    rows.append(row)
                    completed.add((case_id, attempt))
                    _atomic_write(OUTPUT_PARTIAL, _jsonl_bytes(rows))
                    print(
                        json.dumps(
                            {
                                "status": "P0_PRODUCT_CASE_RECORDED",
                                "case_id": case_id,
                                "attempt": attempt,
                                "completed": len(rows),
                                "total": len(cases) * REPEAT,
                                "allow_or_block": row["output"]["allow_or_block"],
                                "latency_ms": row["latency_ms"],
                            },
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                        flush=True,
                    )
    except httpx.HTTPError as error:
        raise Phase10P0ProductEvalError(
            "isolated product transport failed during P0 evaluation"
        ) from error

    if len(rows) != len(cases) * REPEAT:
        raise Phase10P0ProductEvalError("P0 product evaluation did not record every repeat")
    _assert_active_release(_active_release(url), seal)
    observations = [
        {
            "case_id": row["case_id"],
            "attempt": row["attempt"],
            "latency_ms": row["latency_ms"],
            "output": row["output"],
        }
        for row in rows
    ]
    _atomic_write(OUTPUT_OBSERVATIONS, _jsonl_bytes(observations))
    scoring = evaluate_observations(
        cases,
        validation,
        observations,
        repeat=REPEAT,
    )
    receipt = _evaluation_receipt(
        active=active,
        seal=seal,
        validation=validation,
        scoring=scoring,
        rows=rows,
    )
    validate_evaluation_receipt(
        receipt,
        observations_sha256=hashlib.sha256(_jsonl_bytes(observations)).hexdigest(),
        active_generation=int(active["generation"]),
        product_release_id=str(active["product_release_id"]),
        semantic_release_id=str(active["semantic_release_id"]),
        seal_receipt_sha256=str(seal["receipt_sha256"]),
    )
    _atomic_write(OUTPUT_RECEIPT, _json_bytes(receipt))
    return {
        "status": f"PHASE10_P0_PRODUCT_EVAL_{receipt['status']}",
        "target_project": TARGET_PROJECT,
        "product_release_id": active["product_release_id"],
        "semantic_release_id": active["semantic_release_id"],
        "case_count": 55,
        "repeat": REPEAT,
        "observation_count": len(observations),
        "passed": scoring["passed"],
        "deterministic": scoring["deterministic"],
        "accuracy": scoring["accuracy"],
        "receipt_sha256": receipt["receipt_sha256"],
        "observations": OUTPUT_OBSERVATIONS.relative_to(ROOT).as_posix(),
        "receipt": OUTPUT_RECEIPT.relative_to(ROOT).as_posix(),
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    return asyncio.run(run_async(args))


def main(argv: list[str] | None = None) -> int:
    try:
        result = run(parse_args(argv))
    except (OSError, RuntimeError, ValueError, psycopg.Error) as error:
        message = (
            str(error)
            if isinstance(error, Phase10P0ProductEvalError)
            else "Phase 10 P0 product evaluation failed"
        )
        print(
            json.dumps(
                {"status": "PHASE10_P0_PRODUCT_EVAL_ERROR", "error": message},
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"].endswith("PASSED") else 2


if __name__ == "__main__":
    raise SystemExit(main())
