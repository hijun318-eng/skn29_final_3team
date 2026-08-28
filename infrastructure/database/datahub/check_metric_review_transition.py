"""D2 Metric 검토안과 live DataHub·Trino release의 기능 제거 위험을 읽기 전용 검사한다."""

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

from metric_review_contract import validate_metric_review  # noqa: E402
from metric_review_transition import (  # noqa: E402
    READY_STATUS,
    plan_metric_review_transition,
)
from release_builder import build_active_release_bundle  # noqa: E402
from release_datahub import DataHubDiscoveryClient  # noqa: E402
from release_scope import load_release_scopes_with_serving  # noqa: E402
from release_trino import TrinoMetadataClient  # noqa: E402
from runtime_governance_draft import build_draft  # noqa: E402
from src.data.datahub_connection import DataHubConnectionSettings  # noqa: E402
from src.data.governance_contract import canonical_json  # noqa: E402


_MAX_CANDIDATE_BYTES = 1_000_000
_DEPRECATION_REVIEW_EXIT_CODE = 3


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """검토안·SQL 근거와 하나의 live serving release 선택을 해석한다."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--sql-directory", type=Path, required=True)
    parser.add_argument(
        "--recipe-dir",
        type=Path,
        default=HERE / "recipes",
        help="directory containing environment-backed *.runtime.yml recipes",
    )
    parser.add_argument(
        "--serving-schema",
        required=True,
        help="single live Trino serving schema selected for the transition",
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
    )
    parser.add_argument("--timeout", type=float, default=20.0)
    # 발행 경로가 없는 검사기임을 operator command에 명시적으로 남긴다.
    parser.add_argument("--check", action="store_true", required=True)
    return parser.parse_args(argv)


async def check_live_transition(
    candidate: dict[str, object],
    args: argparse.Namespace,
) -> dict[str, object]:
    """SQL 근거를 검증하고 live release를 재구성해 Metric 기능 차이를 반환한다.

    DataHub에는 read API만 호출하고 Trino에는 metadata discovery query만 실행한다.
    기존 BUSINESS Metric 제거 후보가 있더라도 결과를 숨기지 않으며, caller가 별도
    승인 없이 policy compilation으로 넘어가지 못하도록 상태를 반환한다.
    """

    _validation, _baseline, transition = await load_live_review_context(
        candidate,
        args,
    )
    return transition


async def load_live_review_context(
    candidate: dict[str, object],
    args: argparse.Namespace,
) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    """검증 receipt·active baseline·전환 계획을 한 discovery 시점에서 함께 반환한다.

    승인 CLI가 transition 검사와 policy decision 작성 사이에 다른 release를 읽지
    않도록 read-only discovery 결과를 공유한다. Manifest 밖의 base-ingested 신규
    asset은 후속 authoring 후보일 수 있으므로 baseline으로 승격하지 않되, 현재 manifest
    구성원은 live Trino와 다시 일치해야 한다. 반환값 자체는 승인이나 발행 권한을
    만들지 않는다.
    """

    review_schema = candidate.get("serving_schema")
    release_id = candidate.get("release_id")
    if not isinstance(review_schema, str) or not isinstance(release_id, str):
        raise ValueError("metric review release identity is unavailable")
    evidence = build_draft(
        args.sql_directory,
        review_schema,
        release_id,
    )
    validation = validate_metric_review(candidate, evidence)
    password = os.getenv("TRINO_DATAHUB_PASSWORD")
    if (
        not isinstance(args.trino_user, str)
        or not args.trino_user.strip()
        or not isinstance(password, str)
        or not password
        or not isinstance(args.trino_ca_file, Path)
        or args.timeout <= 0
    ):
        raise ValueError("transition check credentials, CA, and timeout are required")

    settings = DataHubConnectionSettings.from_env()
    scopes = load_release_scopes_with_serving(
        tuple(sorted(args.recipe_dir.resolve().glob("*.runtime.yml"))),
        os.environ,
        args.serving_schema,
    )
    if review_schema not in {
        f"{scope.catalog}.{scope.schema}" for scope in scopes
    }:
        raise ValueError("metric review and selected live serving release differ")
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
        baseline = await build_active_release_bundle(scopes, trino, datahub)
    transition = plan_metric_review_transition(candidate, validation, baseline)
    return validation, baseline, transition


def load_candidate(path: Path) -> dict[str, object]:
    """크기가 제한된 UTF-8 JSON 검토안 하나만 읽는다."""

    target = path.resolve()
    if not target.is_file() or target.stat().st_size > _MAX_CANDIDATE_BYTES:
        raise ValueError("metric review candidate is unavailable or too large")
    with target.open("r", encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise ValueError("metric review candidate must be one JSON object")
    return value


async def async_main(argv: list[str] | None = None) -> int:
    """검사 결과를 canonical JSON으로 출력하고 제거 검토 필요 시 non-zero를 반환한다."""

    args = parse_args(argv)
    result = await check_live_transition(load_candidate(args.candidate), args)
    print(canonical_json(result))
    return 0 if result["status"] == READY_STATUS else _DEPRECATION_REVIEW_EXIT_CODE


def main(argv: list[str] | None = None) -> int:
    """비밀정보나 외부 응답 본문 없이 제한된 오류 유형과 종료 코드를 반환한다."""

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
