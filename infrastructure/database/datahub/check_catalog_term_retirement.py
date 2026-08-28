"""봉인한 baseline과 live DataHub를 비교해 기술형 Term 정리 가능 여부만 확인한다."""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
BACKEND = ROOT / "app" / "backend"
for entry in (str(ROOT), str(BACKEND), str(HERE)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from app.adapters.datahub_catalog import DataHubCatalogClient  # noqa: E402
from export_catalog_baseline import (  # noqa: E402
    build_catalog_baseline,
    validate_catalog_baseline,
)
from src.data.governance_contract import canonical_json, canonical_sha256  # noqa: E402


RETIREMENT_CHECK_SCHEMA_VERSION = (
    "answervice.datahub-technical-glossary-retirement-check.v1"
)
RETIREMENT_ACTION = "SOFT_DELETE_STATUS_PRESERVING_IDENTITY"
_MAX_BASELINE_BYTES = 2_000_000
_MAX_CHECK_BYTES = 100_000
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def load_catalog_baseline(path: Path) -> dict[str, Any]:
    """크기가 제한된 절대 경로의 baseline을 checksum까지 검증해 읽는다."""

    if not path.is_absolute():
        raise ValueError("catalog baseline path must be absolute")
    target = path.resolve(strict=True)
    if not target.is_file() or target.stat().st_size > _MAX_BASELINE_BYTES:
        raise ValueError("catalog baseline is unavailable or too large")
    with target.open("r", encoding="utf-8") as stream:
        document = json.load(stream)
    if not isinstance(document, dict):
        raise ValueError("catalog baseline must be an object")
    validate_catalog_baseline(document)
    return document


def load_retirement_check(path: Path) -> dict[str, Any]:
    """크기가 제한된 절대 경로의 retirement check를 checksum까지 검증한다."""

    if not path.is_absolute():
        raise ValueError("retirement check path must be absolute")
    target = path.resolve(strict=True)
    if not target.is_file() or target.stat().st_size > _MAX_CHECK_BYTES:
        raise ValueError("retirement check is unavailable or too large")
    with target.open("r", encoding="utf-8") as stream:
        document = json.load(stream)
    if not isinstance(document, dict):
        raise ValueError("retirement check must be an object")
    validate_retirement_check(document)
    return document


def build_retirement_check(
    baseline: Mapping[str, Any], current: Mapping[str, Any]
) -> dict[str, Any]:
    """정리 대상 상태만 CAS 비교하고 mutation 없는 결정론적 check를 만든다."""

    validate_catalog_baseline(baseline)
    validate_catalog_baseline(current)
    baseline_scope = _retirement_scope(baseline)
    current_scope = _retirement_scope(current)
    if baseline_scope != current_scope:
        raise ValueError("live technical Glossary scope differs from the baseline")
    if baseline_scope["datasets"]:
        raise ValueError("technical Glossary Terms are still associated with datasets")

    terms = baseline_scope["terms"]
    if any(term.get("removed") is not False for term in terms):
        raise ValueError("technical Glossary retirement targets are not all active")
    target_urns = [term["urn"] for term in terms]
    payload = {
        "schema_version": RETIREMENT_CHECK_SCHEMA_VERSION,
        "status": "CHECKED_WITHOUT_MUTATION",
        "action": RETIREMENT_ACTION,
        "baseline_content_sha256": baseline["content_sha256"],
        "checked_scope_sha256": canonical_sha256(baseline_scope),
        "target_urns_sha256": canonical_sha256(target_urns),
        "technical_terms": len(target_urns),
        "affected_datasets": 0,
        "preconditions": {
            "all_targets_active": True,
            "all_targets_orphaned": True,
            "required_removed_transition": {"from": False, "to": True},
        },
    }
    document = {**payload, "check_sha256": canonical_sha256(payload)}
    validate_retirement_check(document)
    return document


def validate_retirement_check(document: Mapping[str, Any]) -> None:
    """check 문서의 의미·checksum을 publish 전 재사용할 수 있도록 검증한다."""

    if set(document) != {
        "schema_version",
        "status",
        "action",
        "baseline_content_sha256",
        "checked_scope_sha256",
        "target_urns_sha256",
        "technical_terms",
        "affected_datasets",
        "preconditions",
        "check_sha256",
    }:
        raise ValueError("retirement check fields are invalid")
    if document.get("schema_version") != RETIREMENT_CHECK_SCHEMA_VERSION:
        raise ValueError("retirement check schema version is invalid")
    if document.get("status") != "CHECKED_WITHOUT_MUTATION":
        raise ValueError("retirement check status is invalid")
    if document.get("action") != RETIREMENT_ACTION:
        raise ValueError("retirement check action is invalid")
    for field in (
        "baseline_content_sha256",
        "checked_scope_sha256",
        "target_urns_sha256",
        "check_sha256",
    ):
        if not isinstance(document.get(field), str) or not _SHA256.fullmatch(
            document[field]
        ):
            raise ValueError(f"retirement check {field} is invalid")
    if (
        not isinstance(document.get("technical_terms"), int)
        or isinstance(document.get("technical_terms"), bool)
        or document["technical_terms"] <= 0
        or document.get("affected_datasets") != 0
    ):
        raise ValueError("retirement check inventory is invalid")
    if document.get("preconditions") != {
        "all_targets_active": True,
        "all_targets_orphaned": True,
        "required_removed_transition": {"from": False, "to": True},
    }:
        raise ValueError("retirement check preconditions are invalid")
    payload = dict(document)
    checksum = payload.pop("check_sha256")
    if canonical_sha256(payload) != checksum:
        raise ValueError("retirement check checksum does not match its content")


def write_retirement_check(
    document: Mapping[str, Any], output: Path
) -> dict[str, Any]:
    """기존 파일을 덮어쓰지 않고 check 문서와 최소 receipt를 생성한다."""

    validate_retirement_check(document)
    if not output.is_absolute():
        raise ValueError("retirement check output path must be absolute")
    parent = output.parent.resolve(strict=True)
    if not parent.is_dir():
        raise ValueError("retirement check output directory is unavailable")
    target = parent / output.name
    with target.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(canonical_json(document))
        stream.write("\n")
    return {
        "schema_version": "answervice.datahub-retirement-check-receipt.v1",
        "status": document["status"],
        "check_sha256": document["check_sha256"],
        "technical_terms": document["technical_terms"],
        "affected_datasets": document["affected_datasets"],
        "output": str(target),
    }


def _retirement_scope(document: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "scope": document["scope"],
        "terms": document["terms"],
        "datasets": document["datasets"],
    }


def _arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args(argv)


async def _async_main(argv: Sequence[str] | None = None) -> int:
    arguments = _arguments(argv)
    baseline = load_catalog_baseline(arguments.baseline)
    async with DataHubCatalogClient.from_env(
        timeout_seconds=30,
        page_size=100,
        max_entities=10_000,
    ) as client:
        current = await build_catalog_baseline(client)
    checked = build_retirement_check(baseline, current)
    print(canonical_json(write_retirement_check(checked, arguments.output)))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """민감정보 없이 receipt만 출력하고 예상 실패는 유형만 반환한다."""

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
