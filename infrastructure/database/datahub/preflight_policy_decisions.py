"""compact 업무 결정을 live DataHub·Trino policy와 발행 확인값으로 확장한다."""

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

from author_semantic_catalog import load_stdin_document  # noqa: E402
from metric_review_decision import (  # noqa: E402
    APPROVAL_CONTRACT_VERSION,
    unwrap_metric_review_approval,
)
from policy_compiler import compile_authoring_policy  # noqa: E402
from release_builder import reconcile_base  # noqa: E402
from release_bundle import ReleaseBinding  # noqa: E402
from release_datahub import DataHubDiscoveryClient  # noqa: E402
from release_scope import load_release_scopes_with_serving  # noqa: E402
from release_trino import TrinoMetadataClient  # noqa: E402
from publication_check import publication_check  # noqa: E402
from semantic_authoring import BaseMetadataNotReady, build_authoring_candidate  # noqa: E402
from src.data.datahub_connection import DataHubConnectionSettings  # noqa: E402
from src.data.governance_contract import canonical_json  # noqa: E402


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """단일 serving release와 bounded live discovery endpoint를 해석한다."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--recipe-dir",
        type=Path,
        default=HERE / "recipes",
        help="directory containing environment-backed *.runtime.yml recipes",
    )
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
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument(
        "--output",
        type=Path,
        help="new repository-external file for the expanded policy and publication check",
    )
    return parser.parse_args(argv)


async def preflight_decisions(
    decision: dict[str, object],
    args: argparse.Namespace,
) -> dict[str, object]:
    """물리 schema를 두 번 대조한 뒤 full policy와 발행 확인값을 반환한다.

    첫 discovery는 compact 결정에 물리 필드를 결합하고, 두 번째 discovery는 그
    사이 schema drift가 없었는지 authoring 본 경로로 다시 검증한다. DataHub에는
    어떤 mutation도 보내지 않는다.
    """

    password = os.getenv("TRINO_DATAHUB_PASSWORD")
    actor = os.getenv("DATAHUB_PUBLISH_ACTOR_URN")
    if (
        not isinstance(args.trino_user, str)
        or not args.trino_user.strip()
        or not isinstance(password, str)
        or not password
        or not isinstance(args.trino_ca_file, Path)
        or not isinstance(actor, str)
        or not actor.strip()
        or args.timeout <= 0
    ):
        raise ValueError("preflight credentials, actor, CA, and timeout are required")
    settings = DataHubConnectionSettings.from_env()
    scopes = load_release_scopes_with_serving(
        tuple(sorted(args.recipe_dir.resolve().glob("*.runtime.yml"))),
        os.environ,
        args.serving_schema,
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
        policy = compile_authoring_policy(decision, bindings)
        candidate = await build_authoring_candidate(policy, scopes, trino, datahub)
    check = publication_check(
        policy,
        candidate.bundle,
        actor=actor,
        previous_catalog_sha256=candidate.previous_catalog_sha256,
    )
    return {"status": "CHECKED", "policy": policy, "publication_check": check}


async def async_main(argv: list[str] | None = None) -> int:
    """stdin 결정 또는 승인 receipt를 preflight하고 canonical JSON을 기록한다."""

    args = parse_args(argv)
    document = load_stdin_document()
    decision = (
        unwrap_metric_review_approval(document)
        if document.get("contract_version") == APPROVAL_CONTRACT_VERSION
        else document
    )
    result = await preflight_decisions(decision, args)
    if args.output is None:
        print(canonical_json(result))
    else:
        write_check_result(args.output, result)
        print(canonical_json({"status": "CHECK_RESULT_WRITTEN"}))
    return 0


def write_check_result(path: Path, result: dict[str, object]) -> None:
    """기존 파일을 덮지 않고 repository 밖 절대 경로에 검사 결과를 기록한다."""

    target = path.expanduser()
    if not target.is_absolute() or not target.parent.is_dir():
        raise ValueError("check output must have an existing absolute parent")
    resolved_parent = target.parent.resolve()
    try:
        resolved_parent.relative_to(ROOT.resolve())
    except ValueError:
        pass
    else:
        raise ValueError("check output must remain outside the repository")
    # WHY: 발행 명령은 이 결과의 두 checksum을 다시 요구한다. 기존 파일을 자동으로
    # 덮어쓰면 사용자가 확인한 목표와 실제 전달한 목표를 구분할 수 없다.
    with target.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(canonical_json(result))
        stream.write("\n")


def main(argv: list[str] | None = None) -> int:
    """비밀정보를 제외한 오류 유형과 실패 종료 코드만 외부에 반환한다."""

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
