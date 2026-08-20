"""명시적으로 승인된 Metric 폐기를 live release에 멱등 적용하고 재조회한다.

``--check``는 mutation 없이 predecessor·target·decision checksum을 만든다.
``--publish``는 그 세 checksum이 모두 일치할 때만 새 release를 upsert한 뒤 과거
Glossary Term을 soft-delete하며, 중간 실패 후 재실행해도 남은 단계만 수행한다.
``--verify``는 DataHub·Trino release와 retired Term status를 읽기 전용으로 확인한다.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from time import monotonic
from typing import Any


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

from http_client import DataHubMetadataAdminClient  # noqa: E402
from metadata_wire import validated_audit_stamp  # noqa: E402
from metric_retirement import (  # noqa: E402
    build_retired_release,
    metric_retirement_check,
    validate_retirement_decision,
)
from publish_semantic_catalog import publish_bundle  # noqa: E402
from release_builder import ReleaseNotReady, inspect_release  # noqa: E402
from release_datahub import (  # noqa: E402
    DataHubDiscoveryClient,
    DataHubDiscoveryError,
    DataHubTerm,
)
from release_scope import load_release_scopes_with_serving  # noqa: E402
from release_trino import TrinoDiscoveryError, TrinoMetadataClient  # noqa: E402
from src.data.datahub_connection import DataHubConnectionSettings  # noqa: E402
from src.data.governance_contract import (  # noqa: E402
    canonical_json,
    canonical_sha256,
    catalog_hash,
)


_MAX_DECISION_BYTES = 1_000_000
_SHA256_LENGTH = 64


class MetricRetirementReadbackError(RuntimeError):
    """target release 또는 retired Term status가 제한 시간 안에 수렴하지 않았음을 나타낸다."""


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """상호 배타적인 점검·발행·검증 모드와 실행 경계값을 파싱한다."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--decision", type=Path, required=True)
    parser.add_argument(
        "--recipe-dir", type=Path, default=HERE / "recipes"
    )
    parser.add_argument("--serving-schema", required=True)
    parser.add_argument(
        "--trino-server", default=os.getenv("TRINO_URL", "https://127.0.0.1:18443")
    )
    parser.add_argument("--trino-user", default=os.getenv("TRINO_DATAHUB_USER"))
    parser.add_argument(
        "--trino-ca-file",
        type=Path,
        default=os.getenv("TRINO_TLS_CA_FILE")
        or os.getenv("TRINO_TLS_CA_HOST_FILE"),
    )
    parser.add_argument("--actor", default=os.getenv("DATAHUB_PUBLISH_ACTOR_URN"))
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--verify-timeout", type=float, default=30.0)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--publish", action="store_true")
    mode.add_argument("--verify", action="store_true")
    parser.add_argument("--expected-decision-sha256")
    parser.add_argument("--expected-previous-catalog-sha256")
    parser.add_argument("--expected-target-catalog-sha256")
    return parser.parse_args(argv)


def load_decision(path: Path) -> dict[str, Any]:
    """크기가 제한된 UTF-8 결정문을 읽고 retirement 계약을 검증한다."""

    target = path.resolve()
    if not target.is_file() or target.stat().st_size > _MAX_DECISION_BYTES:
        raise ValueError("metric retirement decision is unavailable or too large")
    with target.open("r", encoding="utf-8") as stream:
        value = json.load(stream)
    return validate_retirement_decision(value)


async def execute_metric_retirement(
    decision: dict[str, Any], args: argparse.Namespace
) -> dict[str, Any]:
    """현재 release를 다시 발견해 check/publish/verify 중 하나를 수행한다."""

    _validate_mode_arguments(args)
    trino_password = os.getenv("TRINO_DATAHUB_PASSWORD")
    if (
        not isinstance(args.trino_user, str)
        or not args.trino_user.strip()
        or not isinstance(trino_password, str)
        or not trino_password
        or not isinstance(args.trino_ca_file, Path)
        or args.timeout <= 0
        or args.verify_timeout <= 0
    ):
        raise ValueError("retirement Trino credentials, CA, and timeouts are required")

    settings = (
        DataHubConnectionSettings.from_publish_env()
        if args.publish
        else DataHubConnectionSettings.from_env()
    )
    if args.publish and args.actor != settings.actor_urn:
        raise ValueError("retirement actor must match the publish service identity")
    scopes = load_release_scopes_with_serving(
        tuple(sorted(args.recipe_dir.resolve().glob("*.runtime.yml"))),
        os.environ,
        args.serving_schema,
    )
    async with (
        TrinoMetadataClient(
            args.trino_server,
            args.trino_user,
            trino_password,
            ca_file=args.trino_ca_file,
            timeout_seconds=args.timeout,
        ) as trino,
        DataHubDiscoveryClient(
            settings.base_url,
            token=settings.token,
            ca_file=settings.ca_file,
            timeout_seconds=args.timeout,
        ) as datahub,
    ):
        discovered = await inspect_release(scopes, trino, datahub)
        if discovered.bundle is None:
            raise ReleaseNotReady(discovered.report)
        current = discovered.bundle

        if args.check:
            checked = metric_retirement_check(current, decision)
            terms = await _decision_terms(datahub, decision)
            _assert_term_state(terms, decision, removed=False)
            return {"status": "CHECKED", "retirement_check": checked}

        _assert_expected_decision(decision, args.expected_decision_sha256)
        expected_target = str(args.expected_target_catalog_sha256)
        current_sha256 = catalog_hash(current)
        if args.verify:
            _assert_target_release(current, decision, expected_target)
            terms = await _decision_terms(datahub, decision)
            _assert_term_state(terms, decision, removed=True)
            return _verified_result(decision, current_sha256, "VERIFIED")

        expected_previous = str(args.expected_previous_catalog_sha256)
        published = False
        if current_sha256 == expected_previous:
            checked = metric_retirement_check(current, decision)
            _assert_check_matches(checked, args)
            terms = await _decision_terms(datahub, decision)
            _assert_term_state(terms, decision, removed=False)
            target = build_retired_release(current, decision)
            await publish_bundle(
                settings.base_url,
                target,
                actor_urn=args.actor,
                token=settings.token,
                ca_file=settings.ca_file,
                timeout=args.timeout,
            )
            published = True
        elif (
            current.get("catalog_version") == decision["target_catalog_version"]
            and current_sha256 == expected_target
        ):
            # Bundle upsert 뒤 Term status 단계에서 중단된 실행은 여기서 재개한다.
            terms = await _decision_terms(datahub, decision)
        else:
            raise ValueError("live semantic release differs from checked retirement state")

        await _mark_terms_removed(
            settings,
            args.actor,
            terms,
            timeout=args.timeout,
        )
        await _verify_convergence(
            decision,
            expected_target,
            scopes,
            trino,
            datahub,
            timeout_seconds=args.verify_timeout,
        )
        verified_terms = await _decision_terms(datahub, decision)
        _assert_term_state(verified_terms, decision, removed=True)
        return _verified_result(
            decision,
            expected_target,
            "PUBLISHED_AND_VERIFIED" if published else "ALREADY_APPLIED_AND_VERIFIED",
        )


async def _decision_terms(
    datahub: DataHubDiscoveryClient, decision: dict[str, Any]
) -> tuple[DataHubTerm, ...]:
    urns = tuple(item["term_urn"] for item in decision["retirements"])
    return await datahub.discover_terms(urns)


def _assert_term_state(
    terms: tuple[DataHubTerm, ...],
    decision: dict[str, Any],
    *,
    removed: bool,
) -> None:
    expected = {
        item["term_urn"]: item["metric_id"] for item in decision["retirements"]
    }
    observed = {term.urn: term for term in terms}
    if set(observed) != set(expected):
        raise ValueError("retirement Glossary Term membership differs")
    for urn, metric_id in expected.items():
        term = observed[urn]
        if (
            term.custom_properties.get("answervice.metric_id") != metric_id
            or term.removed is not removed
            or term.lifecycle is None
        ):
            raise ValueError("retirement Glossary Term state differs")


async def _mark_terms_removed(
    settings: DataHubConnectionSettings,
    actor: str,
    terms: tuple[DataHubTerm, ...],
    *,
    timeout: float,
) -> None:
    audit = validated_audit_stamp(
        {"actor": actor, "time": time.time_ns() // 1_000_000}
    )
    async with DataHubMetadataAdminClient(
        settings.base_url,
        token=settings.token,
        ca_file=settings.ca_file,
        timeout_seconds=timeout,
    ) as client:
        for term in terms:
            if term.removed is True:
                continue
            if term.removed is not False or term.lifecycle is None:
                raise ValueError("retirement Glossary Term status is incomplete")
            await client.upsert_entity(
                "glossaryTerm",
                term.urn,
                {
                    "status": {
                        "removed": True,
                        "lifecycleStage": term.lifecycle.urn,
                    }
                },
                audit,
            )


async def _verify_convergence(
    decision,
    expected_target: str,
    scopes,
    trino,
    datahub,
    *,
    timeout_seconds: float,
) -> None:
    deadline = monotonic() + timeout_seconds
    last_error = None
    while True:
        try:
            result = await inspect_release(scopes, trino, datahub)
            if result.bundle is not None:
                _assert_target_release(result.bundle, decision, expected_target)
                return
        except (DataHubDiscoveryError, TrinoDiscoveryError, OSError, ValueError) as error:
            last_error = error
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise MetricRetirementReadbackError(
                "live DataHub and Trino did not converge to the retired release"
            ) from last_error
        await asyncio.sleep(min(0.5, remaining))


def _assert_target_release(
    bundle: dict[str, Any], decision: dict[str, Any], expected_target: str
) -> None:
    retired = {item["metric_id"] for item in decision["retirements"]}
    if (
        bundle.get("catalog_version") != decision["target_catalog_version"]
        or catalog_hash(bundle) != expected_target
        or retired.intersection(item["id"] for item in bundle["metric_rules"])
        or retired.intersection(item["id"] for item in bundle["metric_terms"])
    ):
        raise ValueError("live retirement target release differs")


def _assert_expected_decision(
    decision: dict[str, Any], expected_sha256: object
) -> None:
    if canonical_sha256(decision) != expected_sha256:
        raise ValueError("metric retirement decision differs from checked content")


def _assert_check_matches(check: dict[str, Any], args: argparse.Namespace) -> None:
    if (
        check["decision_sha256"] != args.expected_decision_sha256
        or check["previous_catalog_sha256"]
        != args.expected_previous_catalog_sha256
        or check["target_catalog_sha256"] != args.expected_target_catalog_sha256
    ):
        raise ValueError("metric retirement checksums differ from the prior check")


def _validate_mode_arguments(args: argparse.Namespace) -> None:
    expected = (
        args.expected_decision_sha256,
        args.expected_previous_catalog_sha256,
        args.expected_target_catalog_sha256,
    )
    if args.check and any(value is not None for value in expected):
        raise ValueError("retirement check mode does not accept expected checksums")
    if args.publish and any(not _is_sha256(value) for value in expected):
        raise ValueError("retirement publish mode requires three checked SHA-256 values")
    if args.verify and (
        not _is_sha256(args.expected_decision_sha256)
        or args.expected_previous_catalog_sha256 is not None
        or not _is_sha256(args.expected_target_catalog_sha256)
    ):
        raise ValueError("retirement verify mode requires decision and target SHA-256")
    if args.publish and (not isinstance(args.actor, str) or not args.actor.strip()):
        raise ValueError("retirement publish mode requires an actor")


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == _SHA256_LENGTH
        and all(character in "0123456789abcdef" for character in value)
    )


def _verified_result(
    decision: dict[str, Any], target_sha256: str, status: str
) -> dict[str, Any]:
    return {
        "status": status,
        "decision_id": decision["decision_id"],
        "decision_sha256": canonical_sha256(decision),
        "catalog_version": decision["target_catalog_version"],
        "catalog_sha256": target_sha256,
        "retired_metric_count": len(decision["retirements"]),
    }


async def async_main(argv: list[str] | None = None) -> int:
    """선택한 retirement 단계를 실행하고 정규화한 결과만 출력한다."""

    args = parse_args(argv)
    result = await execute_metric_retirement(load_decision(args.decision), args)
    print(canonical_json(result))
    return 0


def main(argv: list[str] | None = None) -> int:
    """비동기 진입점을 실행하고 예상 가능한 실패를 비민감 오류로 변환한다."""

    try:
        return asyncio.run(async_main(argv))
    except (OSError, RuntimeError, ValueError) as error:
        print(
            json.dumps(
                {"status": "ERROR", "error_type": type(error).__name__},
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
