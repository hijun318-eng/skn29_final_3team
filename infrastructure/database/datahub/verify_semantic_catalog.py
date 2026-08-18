"""schema 비종속 semantic bundle을 로컬 DataHub의 정확한 재조회로 검증한다."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
import httpx


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))
from http_client import DataHubMetadataAdminClient  # noqa: E402
from metadata_aspects import aspect_counts  # noqa: E402
from metadata_contract import load_bundle  # noqa: E402
from metadata_graphql import verify_graphql  # noqa: E402
from metadata_rest import preflight_owner_entities, verify_rest_aspects  # noqa: E402
from src.data.governance_contract import catalog_hash  # noqa: E402
from src.data.datahub_connection import DataHubConnectionSettings  # noqa: E402


async def verify(
    server: str,
    bundle_path: Path,
    *,
    token: str | None = None,
    ca_file: str | Path | None = None,
    timeout: float = 30.0,
    http: httpx.AsyncClient | None = None,
) -> dict[str, object]:
    """정규 bundle을 live DataHub REST 및 GraphQL 재조회 결과와 대조한다."""

    bundle = load_bundle(bundle_path)
    async with DataHubMetadataAdminClient(
        server,
        token=token,
        ca_file=ca_file,
        timeout_seconds=timeout,
        http=http,
    ) as client:
        await preflight_owner_entities(client, bundle)
        await verify_rest_aspects(client, bundle)
        await verify_graphql(client, bundle)
    return {
        "status": "VERIFIED",
        "catalog_version": bundle["catalog_version"],
        "catalog_sha256": catalog_hash(bundle),
        **aspect_counts(bundle),
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """bundle 경로와 제한된 로컬 DataHub endpoint 옵션을 해석한다."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=30.0)
    return parser.parse_args(argv)


async def async_main(argv: list[str] | None = None) -> int:
    """검증을 실행하고 기계 판독 가능한 증거 객체 하나를 출력한다."""

    args = parse_args(argv)
    settings = DataHubConnectionSettings.from_env()
    result = await verify(
        settings.base_url,
        args.bundle.resolve(),
        token=settings.token,
        ca_file=settings.ca_file,
        timeout=args.timeout,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


def main(argv: list[str] | None = None) -> int:
    """비동기 verifier를 일반적인 CLI entry point와 연결한다."""

    return asyncio.run(async_main(argv))


if __name__ == "__main__":
    raise SystemExit(main())
