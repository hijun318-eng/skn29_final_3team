"""SQL-reviewed 신규 view 설명을 DataHub base metadata에 제한적으로 발행한다.

Trino connector가 view COMMENT를 수집하지 못하는 경우에만 semantic authoring 전에
사용한다. stdin의 v2 review와 live Trino/DataHub field identity를 결합하며, 기존
governed Dataset은 수정하지 않는다.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from time import time_ns


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

from author_semantic_catalog import load_stdin_document  # noqa: E402
from http_client import DataHubMetadataAdminClient  # noqa: E402
from release_builder import reconcile_base  # noqa: E402
from release_datahub import DataHubDiscoveryClient  # noqa: E402
from release_scope import load_release_scopes_with_serving  # noqa: E402
from release_trino import TrinoMetadataClient  # noqa: E402
from reviewed_description_publication import (  # noqa: E402
    build_reviewed_description_plan,
    publish_reviewed_description_plan,
)
from runtime_governance_draft import build_draft  # noqa: E402
from semantic_authoring import BaseMetadataNotReady  # noqa: E402
from src.data.datahub_connection import DataHubConnectionSettings  # noqa: E402
from src.data.governance_contract import canonical_json  # noqa: E402


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """설명 발행 범위와 check/publish 모드를 해석한다."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--recipe-dir",
        type=Path,
        default=HERE / "recipes",
    )
    parser.add_argument("--sql-dir", required=True, type=Path)
    parser.add_argument("--release-version", required=True)
    parser.add_argument("--serving-schema", required=True)
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
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--publish", action="store_true")
    parser.add_argument("--expected-plan-sha256")
    return parser.parse_args(argv)


async def stage_descriptions(
    review: dict[str, object], args: argparse.Namespace
) -> dict[str, object]:
    """live identity를 검사하고 명시적 publish에서만 검토 설명을 발행한다."""

    password = os.getenv("TRINO_DATAHUB_PASSWORD")
    if (
        not isinstance(args.trino_user, str)
        or not args.trino_user.strip()
        or not isinstance(password, str)
        or not password
        or not isinstance(args.trino_ca_file, Path)
        or not isinstance(args.actor, str)
        or not args.actor.strip()
        or args.timeout <= 0
    ):
        raise ValueError(
            "Trino credentials, CA file, publication actor, and timeout are required"
        )
    if args.check and args.expected_plan_sha256 is not None:
        raise ValueError("check mode does not accept an expected plan checksum")
    if args.publish and not args.expected_plan_sha256:
        raise ValueError("publish mode requires the checked plan checksum")
    settings = (
        DataHubConnectionSettings.from_env()
        if args.check
        else DataHubConnectionSettings.from_publish_env()
    )
    evidence = build_draft(
        args.sql_dir,
        args.serving_schema,
        args.release_version,
    )
    scopes = load_release_scopes_with_serving(
        tuple(sorted(args.recipe_dir.resolve().glob("*.runtime.yml"))),
        os.environ,
        args.serving_schema.rsplit(".", 1)[-1],
    )
    async with (
        TrinoMetadataClient(
            args.trino_server,
            args.trino_user,
            password,
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
        inventory = await trino.discover(scopes)
        datasets = await datahub.discover_datasets(scopes)
        stage, bindings = reconcile_base(scopes, inventory, datasets)
        if not stage.ready:
            raise BaseMetadataNotReady(stage)
    plan = build_reviewed_description_plan(review, evidence, bindings)
    if args.check:
        return {
            "status": "CHECKED",
            "candidate_sha256": plan.candidate_sha256,
            "plan_sha256": plan.plan_sha256,
            "dataset_count": len(plan.patches),
            "field_count": sum(len(patch.fields) for patch in plan.patches),
        }
    async with DataHubMetadataAdminClient(
        settings.base_url,
        token=settings.token,
        ca_file=settings.ca_file,
        timeout_seconds=args.timeout,
    ) as client:
        return await publish_reviewed_description_plan(
            client,
            plan,
            actor_urn=args.actor,
            expected_plan_sha256=args.expected_plan_sha256,
            clock_ms=time_ns() // 1_000_000,
        )


async def async_main(argv: list[str] | None = None) -> int:
    """stdin review를 실행하고 비밀 없는 정규 영수증을 출력한다."""

    args = parse_args(argv)
    result = await stage_descriptions(load_stdin_document(), args)
    print(canonical_json(result))
    return 0


def main(argv: list[str] | None = None) -> int:
    """예상 가능한 운영 실패를 제한된 오류 결과와 종료 코드로 변환한다."""

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
