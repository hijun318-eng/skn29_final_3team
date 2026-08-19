"""승인 전 metric 검토안을 release SQL과 대조하고 비발행 요약을 출력한다."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from metric_review_contract import validate_metric_review
from runtime_governance_draft import build_draft


_MAX_CANDIDATE_BYTES = 1_000_000


def main() -> int:
    """명시된 검토안과 SQL release를 읽기 전용으로 대조한다."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--sql-directory", type=Path, required=True)
    parser.add_argument("--serving-schema", required=True)
    parser.add_argument("--release-id", required=True)
    # --check는 값을 읽지 않는 필수 플래그다. 이 도구에는 발행 경로가 없고 읽기 전용
    # 대조만 수행하므로, check→publish 2단계 어휘를 쓰는 다른 발행 도구와 호출 형태를
    # 맞춰 "--publish 없이 실행했다"는 사실을 명령줄에 명시적으로 남기기 위해 요구한다.
    parser.add_argument("--check", action="store_true", required=True)
    arguments = parser.parse_args()
    document = _load(arguments.candidate)
    evidence = build_draft(
        arguments.sql_directory,
        arguments.serving_schema,
        arguments.release_id,
    )
    result = validate_metric_review(document, evidence)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0


def _load(path: Path) -> object:
    """크기가 제한된 UTF-8 JSON 검토안 하나를 읽는다."""

    target = path.resolve()
    if not target.is_file() or target.stat().st_size > _MAX_CANDIDATE_BYTES:
        raise ValueError("metric review candidate is unavailable or too large")
    with target.open("r", encoding="utf-8") as stream:
        return json.load(stream)


if __name__ == "__main__":
    raise SystemExit(main())
