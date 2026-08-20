"""검증된 live DataHub release에서 schema/entitlement migration policy를 추출한다.

출력은 repository 밖 새 파일에만 기록하며 DataHub를 변경하지 않는다. target의
물리 schema는 이 파일이 아니라 후속 authoring check가 live Trino에서 다시 읽는다.
"""

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

from release_bundle import (  # noqa: E402
    catalog_snapshot_bindings,
    rebase_catalog_snapshot_entitlements,
    release_term_urns,
)
from release_datahub import DataHubDiscoveryClient  # noqa: E402
from release_scope import load_release_scopes_with_serving  # noqa: E402
from semantic_authoring import migrate_authoring_policy  # noqa: E402
from src.data.datahub_connection import DataHubConnectionSettings  # noqa: E402
from src.data.governance_contract import canonical_json  # noqa: E402


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """의미 정책 마이그레이션에 필요한 명시적 입력 인자를 검증한다."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serving-schema", required=True)
    parser.add_argument("--source-catalog-version", required=True)
    parser.add_argument("--target-catalog-version", required=True)
    parser.add_argument("--target-policy-version", required=True)
    parser.add_argument("--target-schema-context-version", required=True)
    parser.add_argument("--role", action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=20.0)
    return parser.parse_args(argv)


async def migrate(args: argparse.Namespace) -> dict[str, object]:
    """live DataHub 계약을 읽어 다음 release의 검토용 정책을 생성한다."""

    if args.timeout <= 0:
        raise ValueError("timeout must be positive")
    settings = DataHubConnectionSettings.from_env()
    scopes = load_release_scopes_with_serving(
        tuple(sorted((HERE / "recipes").glob("*.runtime.yml"))),
        os.environ,
        args.serving_schema,
    )
    async with DataHubDiscoveryClient(
        settings.base_url,
        token=settings.token,
        ca_file=settings.ca_file,
        timeout_seconds=args.timeout,
    ) as datahub:
        datasets = await datahub.discover_datasets(scopes)
        bindings = catalog_snapshot_bindings(datasets)
        terms = await datahub.discover_terms(release_term_urns(bindings))
    source = rebase_catalog_snapshot_entitlements(
        datasets,
        terms,
        tuple(args.role),
    )
    if source["catalog_version"] != args.source_catalog_version:
        raise ValueError("live source catalog version differs from the requested migration")
    policy = migrate_authoring_policy(
        source,
        catalog_version=args.target_catalog_version,
        policy_version=args.target_policy_version,
        schema_context_version=args.target_schema_context_version,
        roles=tuple(args.role),
    )
    return {
        "status": "MIGRATION_POLICY_EXTRACTED",
        "source_catalog_version": source["catalog_version"],
        "source_catalog_sha256": next(
            value
            for key, value in datasets[0].custom_properties.items()
            if key.endswith(".catalog_sha256")
        ),
        "policy": policy,
    }


def write_new_external_file(path: Path, value: dict[str, object]) -> None:
    """추출 결과를 저장소 밖의 새 파일에만 원자적으로 기록한다."""

    target = path.expanduser()
    if not target.is_absolute() or not target.parent.is_dir():
        raise ValueError("output must have an existing absolute parent")
    try:
        target.resolve().parent.relative_to(ROOT.resolve())
    except ValueError:
        pass
    else:
        raise ValueError("output must remain outside the repository")
    with target.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(canonical_json(value))
        stream.write("\n")


async def async_main(argv: list[str] | None = None) -> int:
    """비동기 추출과 외부 파일 기록 절차를 순서대로 실행한다."""

    args = parse_args(argv)
    result = await migrate(args)
    write_new_external_file(args.output, result)
    print(canonical_json({"status": result["status"]}))
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI 실행 실패를 비밀 값 없는 구조화 오류로 변환한다."""

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
