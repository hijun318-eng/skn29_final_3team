"""활성 semantic release를 DataHub native Metric shadow로 검사·발행·재조회한다.

``--check``는 조회 전용 DataHub identity와 Trino metadata principal로 현재 release를
재구성하고 projection checksum만 만든다. ``--publish``는 별도 최소권한 identity로 그
exact projection을 out-of-place upsert한다. ``--verify``는 다시 조회 전용 identity를
사용해 Rest.li aspect와 GraphQL 관계가 모두 수렴했는지 확인한다. 어느 모드도 Backend
runtime source를 native Metric으로 전환하지 않는다.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from time import monotonic
from typing import Any


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
for entry in (str(ROOT), str(HERE)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from http_client import (  # noqa: E402
    DataHubAdminError,
    DataHubMetadataAdminClient,
)
from native_metric_publication import (  # noqa: E402
    probe_native_metric_model,
    publish_native_metric_shadow,
    verify_native_metric_shadow,
)
from native_metric_shadow import (  # noqa: E402
    NativeMetricShadowError,
    native_metric_shadow_projection,
)
from release_builder import build_active_release_bundle  # noqa: E402
from release_datahub import DataHubDiscoveryClient  # noqa: E402
from release_scope import load_release_scopes_with_serving  # noqa: E402
from release_trino import TrinoMetadataClient  # noqa: E402
from src.data.datahub_connection import (  # noqa: E402
    DataHubConnectionSettings,
)
from src.data.governance_contract import (  # noqa: E402
    canonical_json,
    catalog_hash,
)


_SHA256_LENGTH = 64


class NativeMetricShadowReadbackError(RuntimeError):
    """native aspect 또는 graph index가 제한 시간 안에 수렴하지 않았음을 알린다."""


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """상호 배타적 workflow mode와 live release discovery 경계를 해석한다."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recipe-dir", type=Path, default=HERE / "recipes")
    parser.add_argument("--serving-schema")
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
    )
    parser.add_argument("--actor", default=os.getenv("DATAHUB_PUBLISH_ACTOR_URN"))
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--verify-timeout", type=float, default=30.0)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--probe", action="store_true")
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--publish", action="store_true")
    mode.add_argument("--verify", action="store_true")
    parser.add_argument("--expected-catalog-sha256")
    parser.add_argument("--expected-projection-sha256")
    return parser.parse_args(argv)


async def execute_native_metric_shadow(
    arguments: argparse.Namespace,
) -> dict[str, Any]:
    """현재 live release 하나에 대해 요청한 native shadow Gate 단계를 수행한다."""

    _validate_mode_arguments(arguments)
    read_settings = DataHubConnectionSettings.from_env()
    if arguments.probe:
        async with DataHubMetadataAdminClient(
            read_settings.base_url,
            token=read_settings.token,
            ca_file=read_settings.ca_file,
            timeout_seconds=arguments.timeout,
        ) as client:
            return await probe_native_metric_model(client)

    bundle = await _discover_active_release(arguments, read_settings)
    projection = native_metric_shadow_projection(bundle)
    if arguments.check:
        return {**projection, "status": "CHECKED_NOT_PUBLISHED"}

    if (
        catalog_hash(bundle) != arguments.expected_catalog_sha256
        or projection["projection_sha256"]
        != arguments.expected_projection_sha256
    ):
        raise NativeMetricShadowError(
            "live native Metric shadow differs from the checked release"
        )

    if arguments.publish:
        publish_settings = DataHubConnectionSettings.from_publish_env()
        if arguments.actor != publish_settings.actor_urn:
            raise NativeMetricShadowError(
                "native Metric actor must match the publish service identity"
            )
        return await publish_native_metric_shadow(
            publish_settings.base_url,
            bundle,
            actor_urn=publish_settings.actor_urn,
            expected_projection_sha256=arguments.expected_projection_sha256,
            token=publish_settings.token,
            ca_file=publish_settings.ca_file,
            timeout=arguments.timeout,
        )

    return await _verify_readback(
        read_settings,
        bundle,
        expected_projection_sha256=arguments.expected_projection_sha256,
        timeout=arguments.timeout,
        verify_timeout=arguments.verify_timeout,
    )


async def _discover_active_release(
    arguments: argparse.Namespace,
    settings: DataHubConnectionSettings,
) -> dict[str, Any]:
    """조회 전용 DataHub와 Trino를 같은 시점에 읽어 canonical bundle을 재구성한다."""

    password = os.getenv("TRINO_DATAHUB_PASSWORD")
    if (
        not isinstance(arguments.serving_schema, str)
        or not arguments.serving_schema.strip()
        or not isinstance(arguments.trino_user, str)
        or not arguments.trino_user.strip()
        or not isinstance(password, str)
        or not password
        or not isinstance(arguments.trino_ca_file, Path)
    ):
        raise NativeMetricShadowError(
            "native Metric release discovery credentials and scope are required"
        )
    recipe_paths = tuple(
        sorted(arguments.recipe_dir.resolve().glob("*.runtime.yml"))
    )
    scopes = load_release_scopes_with_serving(
        recipe_paths,
        os.environ,
        arguments.serving_schema,
    )
    async with (
        TrinoMetadataClient(
            arguments.trino_server,
            arguments.trino_user,
            password,
            ca_file=arguments.trino_ca_file,
            timeout_seconds=arguments.timeout,
        ) as trino,
        DataHubDiscoveryClient(
            settings.base_url,
            token=settings.token,
            ca_file=settings.ca_file,
            timeout_seconds=arguments.timeout,
        ) as datahub,
    ):
        return await build_active_release_bundle(scopes, trino, datahub)


async def _verify_readback(
    settings: DataHubConnectionSettings,
    bundle: dict[str, Any],
    *,
    expected_projection_sha256: str,
    timeout: float,
    verify_timeout: float,
) -> dict[str, Any]:
    """Rest.li 저장과 GraphQL 관계 index가 모두 보일 때까지 제한적으로 재조회한다."""

    deadline = monotonic() + verify_timeout
    last_error: BaseException | None = None
    async with DataHubMetadataAdminClient(
        settings.base_url,
        token=settings.token,
        ca_file=settings.ca_file,
        timeout_seconds=timeout,
    ) as client:
        while True:
            try:
                return await verify_native_metric_shadow(
                    client,
                    bundle,
                    expected_projection_sha256=expected_projection_sha256,
                )
            except (DataHubAdminError, ValueError) as error:
                last_error = error
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise NativeMetricShadowReadbackError(
                    "native Metric shadow did not converge"
                ) from last_error
            await asyncio.sleep(min(0.5, remaining))


def _validate_mode_arguments(arguments: argparse.Namespace) -> None:
    """mode별 checksum·actor·timeout 조합을 외부 I/O 전에 fail-closed한다."""

    expected = (
        arguments.expected_catalog_sha256,
        arguments.expected_projection_sha256,
    )
    if arguments.timeout <= 0 or arguments.verify_timeout <= 0:
        raise NativeMetricShadowError("native Metric timeouts must be positive")
    if (arguments.probe or arguments.check) and any(
        value is not None for value in expected
    ):
        raise NativeMetricShadowError(
            "native Metric probe/check does not accept expected checksums"
        )
    if (arguments.publish or arguments.verify) and any(
        not _is_sha256(value) for value in expected
    ):
        raise NativeMetricShadowError(
            "native Metric publish/verify requires checked SHA-256 values"
        )
    if arguments.publish and (
        not isinstance(arguments.actor, str) or not arguments.actor.strip()
    ):
        raise NativeMetricShadowError("native Metric publish requires an actor")


def _is_sha256(value: object) -> bool:
    """운영 receipt에 허용하는 lowercase SHA-256 문자열인지 확인한다."""

    return (
        isinstance(value, str)
        and len(value) == _SHA256_LENGTH
        and all(character in "0123456789abcdef" for character in value)
    )


async def async_main(argv: list[str] | None = None) -> int:
    """선택한 Gate를 실행하고 비밀정보 없는 canonical receipt만 출력한다."""

    result = await execute_native_metric_shadow(parse_args(argv))
    print(canonical_json(result))
    return 0


def main(argv: list[str] | None = None) -> int:
    """비동기 workflow의 예상 가능한 실패를 제한된 오류 유형으로 변환한다."""

    try:
        return asyncio.run(async_main(argv))
    except (OSError, RuntimeError, ValueError, UnicodeError, json.JSONDecodeError) as error:
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
