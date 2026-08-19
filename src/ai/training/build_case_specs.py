"""build 사례 명세 학습·평가 데이터의 생성, 실행, 검증 절차와 CLI 진입점을 제공한다.

Select already reviewed full case specifications without generating content.
"""

from __future__ import annotations

import argparse
import copy
import json
from collections import Counter
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from src.ai.training.dataset import load_specs, write_jsonl


class IncompleteScenarioError(ValueError):
    """질문·Context·expected SQL이 없는 scenario ledger를 full case로 변환하려는 시도를 거부한다."""


def build_case(_record: dict[str, Any], **_legacy_options: Any) -> dict[str, Any]:
    """폐기된 scenario→질문·Context·정답 SQL 자동 생성 경로를 항상 거부한다.

    입력이나 legacy option을 변환하지 않고 ``IncompleteScenarioError``를 발생시켜, 사람이
    검토한 full spec만 ``dataset.load_specs`` 경로로 들어오게 한다.
    """
    raise IncompleteScenarioError(
        "build_case no longer generates questions, Context, or SQL; "
        "provide a human-authored full spec validated by dataset.load_specs"
    )


def select_specs(
    specs: Iterable[dict[str, Any]],
    *,
    splits: Iterable[str] = (),
    nodes: Iterable[str] = (),
    review_statuses: Iterable[str] = (),
    case_ids: Iterable[str] = (),
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """명세 후보를 거버넌스 제약과 입력 증거로 판정해 하나의 결과로 좁힌다.

    Return an unchanged, deterministic subset using explicit metadata only.
    """
    if limit is not None and limit < 0:
        raise ValueError("limit must be non-negative")
    split_filter = frozenset(splits)
    node_filter = frozenset(nodes)
    review_filter = frozenset(review_statuses)
    case_filter = frozenset(case_ids)
    ordered = sorted(specs, key=lambda item: str(item["case_id"]))
    selected = [
        item
        for item in ordered
        if (not split_filter or item["split"] in split_filter)
        and (not node_filter or item["node"] in node_filter)
        and (not review_filter or item["review_status"] in review_filter)
        and (not case_filter or item["case_id"] in case_filter)
    ]
    if limit is not None:
        selected = selected[:limit]
    return copy.deepcopy(selected)


def summarize(specs: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """선택된 full spec 수와 split·node·review status별 건수를 정렬된 사전으로 집계한다.

    iterable은 한 번 materialize하며 원본 case 내용이나 검토 상태를 수정하지 않는다.
    """
    materialized = list(specs)
    return {
        "total": len(materialized),
        "splits": dict(sorted(Counter(item["split"] for item in materialized).items())),
        "nodes": dict(sorted(Counter(item["node"] for item in materialized).items())),
        "review_statuses": dict(
            sorted(Counter(item["review_status"] for item in materialized).items())
        ),
    }


def main(argv: list[str] | None = None) -> int:
    """사람이 검토한 full-spec JSONL을 split·node·review status·case ID로 선택해 새 JSONL로 쓴다."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="human-authored full-spec JSONL")
    parser.add_argument("output", type=Path, help="selected full-spec JSONL")
    parser.add_argument("--split", action="append", default=[])
    parser.add_argument("--node", action="append", default=[])
    parser.add_argument("--review-status", action="append", default=[])
    parser.add_argument("--case-id", action="append", default=[])
    parser.add_argument("--limit", type=int)
    args = parser.parse_args(argv)

    validated = load_specs(args.source)
    selected = select_specs(
        validated,
        splits=args.split,
        nodes=args.node,
        review_statuses=args.review_status,
        case_ids=args.case_id,
        limit=args.limit,
    )
    if not selected:
        raise ValueError("selection produced no full specifications")
    write_jsonl(args.output, selected)
    print(json.dumps(summarize(selected), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
