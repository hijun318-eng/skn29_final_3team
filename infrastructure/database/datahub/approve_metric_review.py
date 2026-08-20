"""검증된 Metric review와 live predecessor를 v2 정책 승인 receipt로 만든다.

이 명령은 DataHub나 Trino를 변경하지 않는다. 출력된 checksum-bound receipt는
``preflight_policy_decisions.py``의 stdin으로 전달할 수 있으며, 실제 publication은
별도의 optimistic-concurrency 명령이 필요하다.
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

from check_metric_review_transition import (  # noqa: E402
    load_candidate,
    load_live_review_context,
)
from metric_review_decision import build_metric_review_approval  # noqa: E402
from src.data.governance_contract import canonical_json  # noqa: E402


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """live release 선택과 명시적인 successor version을 해석한다."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--sql-directory", type=Path, required=True)
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
    parser.add_argument("--catalog-version", required=True)
    parser.add_argument("--policy-version", required=True)
    parser.add_argument("--schema-context-version", required=True)
    parser.add_argument("--schema-version", required=True)
    parser.add_argument("--seed-version", required=True)
    parser.add_argument("--glossary-version", required=True)
    parser.add_argument(
        "--output",
        type=Path,
        help="new repository-external file for the checksum-bound approval receipt",
    )
    parser.add_argument(
        "--approve",
        action="store_true",
        required=True,
        help="create a policy-decision approval receipt without publishing it",
    )
    return parser.parse_args(argv)


async def async_main(argv: list[str] | None = None) -> int:
    """한 live snapshot에 review 검증·제거 gate·결정 checksum을 묶어 출력한다."""

    args = parse_args(argv)
    candidate = load_candidate(args.candidate)
    validation, baseline, _transition = await load_live_review_context(candidate, args)
    approval = build_metric_review_approval(
        candidate,
        validation,
        baseline,
        catalog_version=args.catalog_version,
        policy_version=args.policy_version,
        schema_context_version=args.schema_context_version,
        schema_version=args.schema_version,
        seed_version=args.seed_version,
        glossary_version=args.glossary_version,
    )
    if args.output is None:
        print(canonical_json(approval))
    else:
        write_approval_receipt(args.output, approval)
        print(
            canonical_json(
                {
                    "status": approval["status"],
                    "review_candidate_sha256": approval["review_candidate_sha256"],
                    "baseline_catalog_sha256": approval["baseline_catalog_sha256"],
                    "decision_sha256": approval["decision_sha256"],
                    "business_metric_ids": approval["business_metric_ids"],
                    "support_metric_ids": approval["support_metric_ids"],
                    "output": str(args.output.resolve()),
                }
            )
        )
    return 0


def write_approval_receipt(path: Path, approval: dict[str, object]) -> None:
    """기존 파일을 덮지 않고 repository 밖 절대 경로에 receipt를 기록한다."""

    target = path.expanduser()
    if not target.is_absolute() or not target.parent.is_dir():
        raise ValueError("approval output must have an existing absolute parent")
    resolved_parent = target.parent.resolve()
    try:
        resolved_parent.relative_to(ROOT.resolve())
    except ValueError:
        pass
    else:
        raise ValueError("approval output must remain outside the repository")
    with target.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(canonical_json(approval))
        stream.write("\n")


def main(argv: list[str] | None = None) -> int:
    """비밀정보와 외부 응답 본문을 제외한 오류 유형만 stderr에 남긴다."""

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
