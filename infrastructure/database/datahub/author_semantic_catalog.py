"""크기가 제한된 표준 입력으로 DataHub catalog를 검사하거나 명시적으로 발행한다.

This command never accepts a policy file path. Check mode binds semantic policy to
live physical metadata without mutation. Publication requires the exact target and
predecessor checksums returned by that check, then verifies live convergence.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from time import monotonic


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

from http_client import DataHubMetadataAdminClient  # noqa: E402
from native_semantic_publication import (  # noqa: E402
    publish_native_semantic_shadow,
    verify_native_semantic_shadow,
)
from native_semantic_shadow import native_semantic_shadow_projection  # noqa: E402
from publication_check import (  # noqa: E402
    publication_check,
    verify_expected_release,
)
from publish_semantic_catalog import publish_bundle  # noqa: E402
from release_builder import build_active_release_bundle  # noqa: E402
from release_bundle import SemanticBundleError  # noqa: E402
from release_datahub import DataHubDiscoveryClient, DataHubDiscoveryError  # noqa: E402
from release_scope import load_release_scopes_with_serving  # noqa: E402
from release_trino import TrinoDiscoveryError, TrinoMetadataClient  # noqa: E402
from semantic_authoring import build_authoring_candidate  # noqa: E402
from src.data.governance_contract import canonical_json, catalog_hash  # noqa: E402
from src.data.datahub_connection import DataHubConnectionSettings  # noqa: E402


class PublicationReadbackError(RuntimeError):
    """발행한 메타데이터가 제한 시간 안에 정확한 live release로 수렴하지 않았음을 나타낸다."""


_MAX_POLICY_BYTES = 5_000_000


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """제한된 endpoint와 상호 배타적인 check/publish 모드를 해석한다."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--recipe-dir",
        type=Path,
        default=HERE / "recipes",
        help="directory containing environment-backed *.runtime.yml recipes",
    )
    parser.add_argument(
        "--serving-schema",
        required=True,
        help="single live Trino serving schema bound to this release",
    )
    parser.add_argument(
        "--trino-server",
        default=os.getenv("TRINO_URL", "https://127.0.0.1:18443"),
    )
    parser.add_argument("--trino-user", default=os.getenv("TRINO_DATAHUB_USER"))
    parser.add_argument(
        "--trino-ca-file",
        type=Path,
        default=os.getenv("TRINO_TLS_CA_FILE")
        or os.getenv("TRINO_TLS_CA_HOST_FILE"),
        help="absolute CA PEM path for Trino server verification",
    )
    parser.add_argument("--actor", default=os.getenv("DATAHUB_PUBLISH_ACTOR_URN"))
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--verify-timeout", type=float, default=30.0)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--check",
        action="store_true",
        help="discover and validate the release without mutating DataHub",
    )
    mode.add_argument(
        "--publish",
        action="store_true",
        help="publish only when both expected checksums match a prior check",
    )
    parser.add_argument("--expected-catalog-sha256")
    parser.add_argument("--expected-previous-catalog-sha256")
    return parser.parse_args(argv)


def load_stdin_document() -> dict[str, object]:
    """파일 fallback 없이 크기가 제한된 policy 객체 하나를 표준 입력에서 읽는다."""

    if sys.stdin.isatty():
        raise ValueError("semantic policy must be supplied on stdin")
    raw = sys.stdin.read(_MAX_POLICY_BYTES + 1)
    if len(raw.encode("utf-8")) > _MAX_POLICY_BYTES:
        raise ValueError("stdin semantic document exceeds its size bound")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ValueError("stdin semantic document is not valid JSON") from error
    if not isinstance(value, dict):
        raise ValueError("stdin semantic document must be one JSON object")
    return value


async def author_and_verify(
    document: dict[str, object],
    args: argparse.Namespace,
) -> dict[str, object]:
    """표준 입력 policy를 live metadata에 결합하고 요청된 release 흐름을 실행한다."""

    # WHY: password CLI 옵션은 process list와 shell history에 secret을 남긴다.
    # credential은 배포 환경에서만 받고 오류·출력에는 이름조차 포함하지 않는다.
    trino_password = os.getenv("TRINO_DATAHUB_PASSWORD")
    if (
        not isinstance(args.trino_user, str)
        or not args.trino_user.strip()
        or not isinstance(trino_password, str)
        or not trino_password
        or not isinstance(args.trino_ca_file, Path)
        or not isinstance(args.actor, str)
        or not args.actor.strip()
        or args.timeout <= 0
        or args.verify_timeout <= 0
    ):
        raise ValueError(
            "Trino credentials, CA file, publication actor, and positive timeouts are required"
        )
    if args.check and (
        args.expected_catalog_sha256 is not None
        or args.expected_previous_catalog_sha256 is not None
    ):
        raise ValueError("check mode does not accept expected publication checksums")
    if args.publish and (
        not args.expected_catalog_sha256
        or not args.expected_previous_catalog_sha256
    ):
        raise ValueError("publish mode requires both checked catalog checksums")
    # WHY: read-only 검사는 mutation token을 요구하지 않는다. 발행 모드만 최소권한
    # publish identity를 읽어 검사와 mutation credential 경계를 섞지 않는다.
    datahub_settings = (
        DataHubConnectionSettings.from_env()
        if args.check
        else DataHubConnectionSettings.from_publish_env()
    )
    recipe_paths = tuple(sorted(args.recipe_dir.resolve().glob("*.runtime.yml")))
    scopes = load_release_scopes_with_serving(
        recipe_paths,
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
            datahub_settings.base_url,
            token=datahub_settings.token,
            ca_file=datahub_settings.ca_file,
            timeout_seconds=args.timeout,
        ) as datahub,
    ):
        async def publisher(bundle):
            """검증된 bundle의 legacy/native surface를 하나의 운영 경로로 발행한다."""

            return await _publish_datahub_release(
                bundle,
                datahub_settings,
                actor_urn=args.actor,
                timeout=args.timeout,
            )

        return await apply_authoring_release(
            document,
            scopes,
            trino,
            datahub,
            publisher,
            actor=args.actor,
            verify_timeout=args.verify_timeout,
            check_only=args.check,
            expected_catalog_sha256=args.expected_catalog_sha256,
            expected_previous_catalog_sha256=(
                args.expected_previous_catalog_sha256
            ),
        )


async def _publish_datahub_release(
    bundle: dict[str, object],
    settings: DataHubConnectionSettings,
    *,
    actor_urn: str,
    timeout: float,
) -> dict[str, object]:
    """canonical bundle에서 legacy와 native semantic surface를 함께 발행·검증한다."""

    projection = native_semantic_shadow_projection(bundle)
    legacy = await publish_bundle(
        settings.base_url,
        bundle,
        actor_urn=actor_urn,
        token=settings.token,
        ca_file=settings.ca_file,
        timeout=timeout,
    )
    async with DataHubMetadataAdminClient(
        settings.base_url,
        token=settings.token,
        ca_file=settings.ca_file,
        timeout_seconds=timeout,
    ) as client:
        native_published = await publish_native_semantic_shadow(
            client,
            bundle,
            actor_urn=actor_urn,
            expected_projection_sha256=projection["projection_sha256"],
        )
        native_verified = await verify_native_semantic_shadow(
            client,
            bundle,
            expected_projection_sha256=projection["projection_sha256"],
        )
    return {
        **legacy,
        "native_semantic_projection_sha256": projection["projection_sha256"],
        "native_semantic_readback_sha256": native_verified[
            "readback_projection_sha256"
        ],
        "native_semantic_published_entity_count": native_published[
            "published_entity_count"
        ],
        "native_semantic_rest_aspect_equality": native_verified[
            "rest_aspect_equality"
        ],
    }


async def apply_authoring_release(
    document,
    scopes,
    trino,
    datahub,
    publisher,
    *,
    actor: str,
    verify_timeout: float,
    check_only: bool = False,
    expected_catalog_sha256: str | None = None,
    expected_previous_catalog_sha256: str | None = None,
) -> dict[str, object]:
    """policy 하나를 live 검사하거나 확인된 checksum과 대조해 발행·재조회한다.

    Publication is explicit and covers the exact target and physical predecessor.
    A successful return additionally requires DataHub and Trino readback convergence.
    """

    candidate = await build_authoring_candidate(document, scopes, trino, datahub)
    bundle = candidate.bundle
    check = publication_check(
        document,
        bundle,
        actor=actor,
        previous_catalog_sha256=candidate.previous_catalog_sha256,
    )
    if check_only:
        return {"status": "CHECKED", "publication_check": check}
    if expected_catalog_sha256 is None or expected_previous_catalog_sha256 is None:
        raise ValueError("publication checksums are required")
    verify_expected_release(
        check,
        expected_catalog_sha256=expected_catalog_sha256,
        expected_previous_catalog_sha256=expected_previous_catalog_sha256,
    )
    published = await publisher(bundle)
    await _verify_convergence(
        bundle,
        scopes,
        trino,
        datahub,
        timeout_seconds=verify_timeout,
    )
    return {
        **published,
        "status": "PUBLISHED_AND_VERIFIED",
        "policy_source": "checked_stdin",
        "catalog_sha256": check["catalog_sha256"],
        "previous_catalog_sha256": check["previous_catalog_sha256"],
    }


async def _verify_convergence(
    bundle,
    scopes,
    trino,
    datahub,
    *,
    timeout_seconds: float,
) -> None:
    expected = catalog_hash(bundle)
    deadline = monotonic() + timeout_seconds
    last_error = None
    while True:
        try:
            active = await build_active_release_bundle(scopes, trino, datahub)
            if catalog_hash(active) == expected:
                return
        except (
            DataHubDiscoveryError,
            SemanticBundleError,
            TrinoDiscoveryError,
            OSError,
        ) as error:
            last_error = error
        remaining = deadline - monotonic()
        if remaining <= 0:
            failure = PublicationReadbackError(
                "live DataHub and Trino did not converge to the published release"
            )
            raise failure from last_error
        await asyncio.sleep(min(0.5, remaining))


async def async_main(argv: list[str] | None = None) -> int:
    """authoring을 실행하고 정규화된 기계 판독 결과 하나를 출력한다."""

    args = parse_args(argv)
    result = await author_and_verify(load_stdin_document(), args)
    print(canonical_json(result))
    return 0


def main(argv: list[str] | None = None) -> int:
    """제한된 운영 실패를 비밀정보가 없는 오류 결과와 종료 코드로 변환한다."""

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
