"""live DataHub와 Trino만 사용해 거버넌스 release bundle을 점검하거나 생성한다."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

from release_builder import inspect_release  # noqa: E402
from release_datahub import DataHubDiscoveryClient  # noqa: E402
from release_scope import load_release_scopes_with_serving  # noqa: E402
from release_trino import TrinoMetadataClient  # noqa: E402
from src.data.governance_contract import canonical_json  # noqa: E402
from src.data.datahub_connection import DataHubConnectionSettings  # noqa: E402


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """live discovery endpoint와 READY bundle 필수 여부를 명령행에서 해석한다."""

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
        help="single live Trino serving schema bound to this approval candidate",
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
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument(
        "--build",
        action="store_true",
        help="include the bundle in stdout and fail unless both stages are ready",
    )
    return parser.parse_args(argv)


async def async_main(argv: list[str] | None = None) -> int:
    """DataHub와 Trino를 점검하고 준비된 경우에만 대조 완료 bundle을 출력한다."""

    args = parse_args(argv)
    # Password는 argv에 허용하지 않는다. process environment에서만 읽어 shell
    # history와 OS process inspection에 credential이 남는 경로를 차단한다.
    trino_password = os.getenv("TRINO_DATAHUB_PASSWORD")
    if (
        not isinstance(args.trino_user, str)
        or not args.trino_user.strip()
        or not isinstance(trino_password, str)
        or not trino_password
        or not isinstance(args.trino_ca_file, Path)
    ):
        raise ValueError("Trino credentials and CA file are required")
    datahub_settings = DataHubConnectionSettings.from_env()
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
        result = await inspect_release(scopes, trino, datahub)
    ready = result.bundle is not None
    output: dict[str, object] = {
        "status": "READY" if ready else "NOT_READY",
        "report": result.report.as_dict(),
    }
    if args.build and ready:
        output["bundle"] = result.bundle
    print(canonical_json(output))
    return 0 if ready or not args.build else 2


def main(argv: list[str] | None = None) -> int:
    """endpoint 응답 본문을 노출하지 않고 비동기 점검기를 실행한다."""

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
