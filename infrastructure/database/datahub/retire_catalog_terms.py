"""봉인된 exact URN만 soft-delete·복원하고 live read-back 영수증을 남긴다."""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from collections.abc import Awaitable, Callable, Mapping, Sequence
from pathlib import Path
from time import time_ns
from typing import Any


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
BACKEND = ROOT / "app" / "backend"
for entry in (str(ROOT), str(BACKEND), str(HERE)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from app.adapters.datahub_catalog import DataHubCatalogClient  # noqa: E402
from check_catalog_term_retirement import (  # noqa: E402
    build_retirement_check,
    load_catalog_baseline,
    load_retirement_check,
    validate_retirement_check,
)
from export_catalog_baseline import (  # noqa: E402
    read_catalog_retirement_scope,
    read_visible_technical_term_urns,
    validate_catalog_baseline,
)
from http_client import DataHubMetadataAdminClient  # noqa: E402
from metadata_wire import validated_audit_stamp  # noqa: E402
from src.data.datahub_connection import DataHubConnectionSettings  # noqa: E402
from src.data.governance_contract import canonical_json, canonical_sha256  # noqa: E402


STATUS_RECEIPT_SCHEMA_VERSION = (
    "answervice.datahub-technical-glossary-status-receipt.v1"
)
_WRITE_CONCURRENCY = 8
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ScopeReader = Callable[[Any, Sequence[str]], Awaitable[dict[str, Any]]]
_VisibilityReader = Callable[[Any], Awaitable[tuple[str, ...]]]


async def apply_catalog_term_status(
    baseline: Mapping[str, Any],
    checked: Mapping[str, Any],
    *,
    expected_check_sha256: str,
    reader: Any,
    admin: Any,
    actor_urn: str,
    removed: bool,
    scope_reader: _ScopeReader = read_catalog_retirement_scope,
    visibility_reader: _VisibilityReader = read_visible_technical_term_urns,
) -> dict[str, Any]:
    """현재 exact scope를 확인한 뒤 남은 status 변경만 수행하고 재조회한다."""

    if not isinstance(removed, bool):
        raise ValueError("catalog term removed status must be boolean")
    if not isinstance(actor_urn, str) or not actor_urn.startswith(
        "urn:li:corpuser:service_"
    ):
        raise ValueError("catalog term mutation actor must be a service account")
    target_urns = _validated_inputs(baseline, checked, expected_check_sha256)
    current = await scope_reader(reader, target_urns)
    states = _assert_live_scope(baseline, current)
    _assert_visible_targets(
        target_urns, states, await visibility_reader(reader)
    )
    pending = [urn for urn in target_urns if states[urn] is not removed]
    audit = validated_audit_stamp(
        {"actor": actor_urn, "time": time_ns() // 1_000_000}
    )
    await _set_removed(admin, pending, removed=removed, audit=audit)

    readback = await scope_reader(reader, target_urns)
    verified_states = _assert_live_scope(baseline, readback)
    if any(value is not removed for value in verified_states.values()):
        raise ValueError("DataHub technical Glossary status did not converge")
    _assert_visible_targets(
        target_urns, verified_states, await visibility_reader(reader)
    )
    operation = "SOFT_DELETE" if removed else "RESTORE"
    return _status_receipt(
        baseline,
        checked,
        operation=operation,
        actor_urn=actor_urn,
        changed_terms=len(pending),
        removed_terms=len(target_urns) if removed else 0,
    )


async def verify_catalog_term_status(
    baseline: Mapping[str, Any],
    checked: Mapping[str, Any],
    *,
    expected_check_sha256: str,
    reader: Any,
    removed: bool,
    scope_reader: _ScopeReader = read_catalog_retirement_scope,
    visibility_reader: _VisibilityReader = read_visible_technical_term_urns,
) -> dict[str, Any]:
    """mutation 권한 없이 exact scope가 기대한 retired/restored 상태인지 확인한다."""

    if not isinstance(removed, bool):
        raise ValueError("catalog term removed status must be boolean")
    target_urns = _validated_inputs(baseline, checked, expected_check_sha256)
    current = await scope_reader(reader, target_urns)
    states = _assert_live_scope(baseline, current)
    if any(value is not removed for value in states.values()):
        raise ValueError("DataHub technical Glossary status differs from expectation")
    _assert_visible_targets(target_urns, states, await visibility_reader(reader))
    operation = "VERIFY_RETIRED" if removed else "VERIFY_RESTORED"
    return _status_receipt(
        baseline,
        checked,
        operation=operation,
        actor_urn=None,
        changed_terms=0,
        removed_terms=len(target_urns) if removed else 0,
    )


def validate_status_receipt(document: Mapping[str, Any]) -> None:
    """상태 전환 영수증의 mode·개수·checksum을 엄격히 검증한다."""

    if set(document) != {
        "schema_version",
        "status",
        "operation",
        "actor_urn",
        "baseline_content_sha256",
        "check_sha256",
        "checked_scope_sha256",
        "target_urns_sha256",
        "technical_terms",
        "changed_terms",
        "active_terms_after",
        "removed_terms_after",
        "receipt_sha256",
    }:
        raise ValueError("catalog term status receipt fields are invalid")
    operation = document.get("operation")
    expected_status = {
        "SOFT_DELETE": "SOFT_DELETED_AND_VERIFIED",
        "RESTORE": "RESTORED_AND_VERIFIED",
        "VERIFY_RETIRED": "RETIRED_STATE_VERIFIED",
        "VERIFY_RESTORED": "RESTORED_STATE_VERIFIED",
    }
    if (
        document.get("schema_version") != STATUS_RECEIPT_SCHEMA_VERSION
        or operation not in expected_status
        or document.get("status") != expected_status[operation]
    ):
        raise ValueError("catalog term status receipt mode is invalid")
    actor = document.get("actor_urn")
    if operation in {"SOFT_DELETE", "RESTORE"}:
        if not isinstance(actor, str) or not actor.startswith(
            "urn:li:corpuser:service_"
        ):
            raise ValueError("catalog term status receipt actor is invalid")
    elif actor is not None:
        raise ValueError("read-only status receipt must not contain an actor")
    for field in (
        "baseline_content_sha256",
        "check_sha256",
        "checked_scope_sha256",
        "target_urns_sha256",
        "receipt_sha256",
    ):
        if not isinstance(document.get(field), str) or not _SHA256.fullmatch(
            document[field]
        ):
            raise ValueError(f"catalog term status receipt {field} is invalid")
    counts = [
        document.get("technical_terms"),
        document.get("changed_terms"),
        document.get("active_terms_after"),
        document.get("removed_terms_after"),
    ]
    if any(
        not isinstance(value, int) or isinstance(value, bool) or value < 0
        for value in counts
    ):
        raise ValueError("catalog term status receipt counts are invalid")
    total, changed, active, removed = counts
    if total <= 0 or changed > total or active + removed != total:
        raise ValueError("catalog term status receipt inventory is inconsistent")
    if operation in {"SOFT_DELETE", "VERIFY_RETIRED"} and (
        active != 0 or removed != total
    ):
        raise ValueError("retired status receipt inventory is invalid")
    if operation in {"RESTORE", "VERIFY_RESTORED"} and (
        active != total or removed != 0
    ):
        raise ValueError("restored status receipt inventory is invalid")
    payload = dict(document)
    checksum = payload.pop("receipt_sha256")
    if canonical_sha256(payload) != checksum:
        raise ValueError("catalog term status receipt checksum differs")


def write_status_receipt(
    document: Mapping[str, Any], output: Path
) -> dict[str, Any]:
    """검증된 상태 영수증을 덮어쓰기 없이 보존한다."""

    validate_status_receipt(document)
    if not output.is_absolute():
        raise ValueError("catalog term status receipt path must be absolute")
    parent = output.parent.resolve(strict=True)
    if not parent.is_dir():
        raise ValueError("catalog term status receipt directory is unavailable")
    target = parent / output.name
    with target.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(canonical_json(document))
        stream.write("\n")
    return {
        "schema_version": "answervice.datahub-status-operation-receipt.v1",
        "status": document["status"],
        "receipt_sha256": document["receipt_sha256"],
        "technical_terms": document["technical_terms"],
        "changed_terms": document["changed_terms"],
        "output": str(target),
    }


def validate_receipt_output_path(output: Path) -> Path:
    """mutation 전에 영수증 경로가 신규 생성 가능한 절대 경로인지 확인한다."""

    if not output.is_absolute():
        raise ValueError("catalog term status receipt path must be absolute")
    parent = output.parent.resolve(strict=True)
    if not parent.is_dir():
        raise ValueError("catalog term status receipt directory is unavailable")
    target = parent / output.name
    if target.exists():
        raise ValueError("catalog term status receipt already exists")
    return target


def _validated_inputs(
    baseline: Mapping[str, Any],
    checked: Mapping[str, Any],
    expected_check_sha256: str,
) -> tuple[str, ...]:
    validate_catalog_baseline(baseline)
    validate_retirement_check(checked)
    if not isinstance(expected_check_sha256, str) or not _SHA256.fullmatch(
        expected_check_sha256
    ):
        raise ValueError("expected retirement check SHA-256 is invalid")
    if checked["check_sha256"] != expected_check_sha256:
        raise ValueError("retirement check differs from the expected checksum")
    expected = build_retirement_check(baseline, baseline)
    if dict(checked) != expected:
        raise ValueError("retirement check is not bound to the supplied baseline")
    target_urns = tuple(term["urn"] for term in baseline["terms"])
    if canonical_sha256(list(target_urns)) != checked["target_urns_sha256"]:
        raise ValueError("retirement target identities differ from the check")
    return target_urns


def _assert_live_scope(
    baseline: Mapping[str, Any], current: Mapping[str, Any]
) -> dict[str, bool]:
    if set(current) != {"scope", "terms", "datasets"}:
        raise ValueError("live retirement scope fields are invalid")
    if current.get("scope") != baseline.get("scope"):
        raise ValueError("live retirement scope identifier differs")
    if current.get("datasets") != baseline.get("datasets"):
        raise ValueError("technical Glossary dataset associations changed")
    baseline_terms = baseline.get("terms")
    current_terms = current.get("terms")
    if not isinstance(baseline_terms, list) or not isinstance(current_terms, list):
        raise ValueError("live retirement term snapshots are invalid")
    if len(baseline_terms) != len(current_terms):
        raise ValueError("live retirement term membership differs")

    states: dict[str, bool] = {}
    for expected, observed in zip(baseline_terms, current_terms, strict=True):
        if not isinstance(expected, Mapping) or not isinstance(observed, Mapping):
            raise ValueError("live retirement term snapshot is invalid")
        expected_shape = dict(expected)
        observed_shape = dict(observed)
        expected_removed = expected_shape.pop("removed", None)
        observed_removed = observed_shape.pop("removed", None)
        if expected_removed is not False or not isinstance(observed_removed, bool):
            raise ValueError("live retirement status is invalid")
        if expected_shape != observed_shape:
            raise ValueError("live retirement term metadata differs from baseline")
        urn = expected_shape.get("urn")
        if not isinstance(urn, str) or urn in states:
            raise ValueError("live retirement term identity is invalid")
        states[urn] = observed_removed
    return states


def _assert_visible_targets(
    target_urns: Sequence[str],
    states: Mapping[str, bool],
    visible_technical_urns: Sequence[str],
) -> None:
    visible = tuple(visible_technical_urns)
    if visible != tuple(sorted(set(visible))):
        raise ValueError("visible technical Glossary identities are not canonical")
    expected = {urn for urn in target_urns if states[urn] is False}
    if set(visible) != expected:
        raise ValueError("DataHub active Glossary visibility differs from status")


async def _set_removed(
    admin: Any,
    urns: Sequence[str],
    *,
    removed: bool,
    audit: Mapping[str, Any],
) -> None:
    semaphore = asyncio.Semaphore(_WRITE_CONCURRENCY)

    async def update(urn: str) -> None:
        async with semaphore:
            await admin.upsert_entity(
                "glossaryTerm", urn, {"status": {"removed": removed}}, audit
            )

    await asyncio.gather(*(update(urn) for urn in urns))


def _status_receipt(
    baseline: Mapping[str, Any],
    checked: Mapping[str, Any],
    *,
    operation: str,
    actor_urn: str | None,
    changed_terms: int,
    removed_terms: int,
) -> dict[str, Any]:
    total = checked["technical_terms"]
    status = {
        "SOFT_DELETE": "SOFT_DELETED_AND_VERIFIED",
        "RESTORE": "RESTORED_AND_VERIFIED",
        "VERIFY_RETIRED": "RETIRED_STATE_VERIFIED",
        "VERIFY_RESTORED": "RESTORED_STATE_VERIFIED",
    }[operation]
    payload = {
        "schema_version": STATUS_RECEIPT_SCHEMA_VERSION,
        "status": status,
        "operation": operation,
        "actor_urn": actor_urn,
        "baseline_content_sha256": baseline["content_sha256"],
        "check_sha256": checked["check_sha256"],
        "checked_scope_sha256": checked["checked_scope_sha256"],
        "target_urns_sha256": checked["target_urns_sha256"],
        "technical_terms": total,
        "changed_terms": changed_terms,
        "active_terms_after": total - removed_terms,
        "removed_terms_after": removed_terms,
    }
    document = {**payload, "receipt_sha256": canonical_sha256(payload)}
    validate_status_receipt(document)
    return document


def _arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--check", type=Path, required=True)
    parser.add_argument("--expected-check-sha256", required=True)
    parser.add_argument("--receipt-output", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=30.0)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--publish", action="store_true")
    mode.add_argument("--restore", action="store_true")
    mode.add_argument("--verify-retired", action="store_true")
    mode.add_argument("--verify-restored", action="store_true")
    return parser.parse_args(argv)


async def _async_main(argv: Sequence[str] | None = None) -> int:
    arguments = _arguments(argv)
    if arguments.timeout <= 0:
        raise ValueError("DataHub status operation timeout must be positive")
    validate_receipt_output_path(arguments.receipt_output)
    baseline = load_catalog_baseline(arguments.baseline)
    checked = load_retirement_check(arguments.check)
    async with DataHubCatalogClient.from_env(
        timeout_seconds=arguments.timeout,
        page_size=100,
        max_entities=10_000,
    ) as reader:
        if arguments.publish or arguments.restore:
            settings = DataHubConnectionSettings.from_publish_env()
            async with DataHubMetadataAdminClient(
                settings.base_url,
                token=settings.token,
                ca_file=settings.ca_file,
                timeout_seconds=arguments.timeout,
            ) as admin:
                receipt = await apply_catalog_term_status(
                    baseline,
                    checked,
                    expected_check_sha256=arguments.expected_check_sha256,
                    reader=reader,
                    admin=admin,
                    actor_urn=settings.actor_urn,
                    removed=arguments.publish,
                )
        else:
            receipt = await verify_catalog_term_status(
                baseline,
                checked,
                expected_check_sha256=arguments.expected_check_sha256,
                reader=reader,
                removed=arguments.verify_retired,
            )
    result = write_status_receipt(receipt, arguments.receipt_output)
    print(canonical_json(result))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """예상 실패 시 credential·URN을 출력하지 않고 오류 유형만 반환한다."""

    try:
        return asyncio.run(_async_main(argv))
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as error:
        print(
            json.dumps(
                {"status": "ERROR", "error_type": type(error).__name__},
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
