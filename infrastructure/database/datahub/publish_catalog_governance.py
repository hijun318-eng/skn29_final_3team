"""승인된 live DataHub catalog에 비벡터 거버넌스와 Data Dictionary를 발행한다."""

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

from catalog_governance import (  # noqa: E402
    build_plan,
    discover_catalog,
    publish_plan,
    runtime_scopes,
)
from catalog_governance_verify import verify_plan  # noqa: E402
from http_client import DataHubMetadataAdminClient  # noqa: E402
from src.data.datahub_connection import DataHubConnectionSettings  # noqa: E402


def arguments() -> argparse.Namespace:
    """비밀값 없이 release 경로·버전·recipe 경로만 명령행에서 받는다."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--release-directory", type=Path, required=True)
    parser.add_argument("--release-version", required=True)
    parser.add_argument("--serving-schema", required=True)
    parser.add_argument("--recipe-directory", type=Path, default=HERE / "recipes")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--check",
        action="store_true",
        help="validate the complete live plan without mutating DataHub",
    )
    mode.add_argument(
        "--verify",
        action="store_true",
        help="read back and verify every previously published entity and association",
    )
    return parser.parse_args()


async def run(args: argparse.Namespace) -> dict[str, object]:
    """live scope를 검증한 후 발행 계정으로 거버넌스를 게시한다."""

    settings = DataHubConnectionSettings.from_publish_env()
    scopes = runtime_scopes(args.recipe_directory.resolve(), args.serving_schema)
    async with DataHubMetadataAdminClient(
        settings.base_url,
        token=settings.token,
        ca_file=settings.ca_file,
        timeout_seconds=30,
    ) as client:
        datasets = await discover_catalog(client, scopes)
        plan = build_plan(
            datasets,
            scopes,
            args.release_version,
            settings.actor_urn,
            args.release_directory.resolve(),
        )
        counts = {
            "datasets": len(plan.datasets),
            "fields": sum(len(dataset.fields) for dataset in plan.datasets),
            "domains": len(plan.domains),
            "tags": len(plan.tags),
            "glossary_terms": 0,
            "lineage_edges": len(plan.lineage_edges),
        }
        if args.verify:
            counts = await verify_plan(client, plan, args.release_version)
        elif not args.check:
            counts = await publish_plan(client, plan, args.release_version)
    status = "VERIFIED" if args.verify else "READY" if args.check else "PUBLISHED"
    return {"status": status, **counts}


def main() -> int:
    """민감값을 출력하지 않고 기계 판독 가능한 발행 수량만 반환한다."""

    try:
        result = asyncio.run(run(arguments()))
    except (OSError, RuntimeError, ValueError) as error:
        print(
            json.dumps(
                {"status": "FAILED", "error_type": type(error).__name__},
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
