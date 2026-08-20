"""P0 Gold draft를 검사하거나 봉인된 manifest의 반복 관측 bundle을 평가한다."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evals.p0_gold import P0GoldError, validate_manifest  # noqa: E402
from evals.p0_gold_scoring import evaluate_observations  # noqa: E402


def main() -> int:
    """명시적 파일만 읽어 draft 상태 또는 봉인 Gold의 정량 결과를 JSON으로 출력한다."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--semantic-candidate", type=Path, required=True)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--check", action="store_true")
    action.add_argument("--observations", type=Path)
    parser.add_argument("--repeat", type=int, default=1)
    arguments = parser.parse_args()
    try:
        manifest = _load_json(arguments.manifest, 1_000_000, "manifest")
        case_path = _case_path(arguments.manifest, manifest)
        case_bytes = _read(case_path, 5_000_000, "case file")
        cases = _jsonl(case_bytes, "case file")
        candidate = _load_json(
            arguments.semantic_candidate,
            1_000_000,
            "semantic candidate",
        )
        summary = validate_manifest(
            manifest,
            cases,
            candidate,
            observed_case_content_sha256=hashlib.sha256(case_bytes).hexdigest(),
        )
        if arguments.observations is not None:
            observations = _jsonl(
                _read(arguments.observations, 10_000_000, "observations"),
                "observations",
            )
            summary = evaluate_observations(
                cases,
                summary,
                observations,
                repeat=arguments.repeat,
            )
    except (OSError, UnicodeError, json.JSONDecodeError, P0GoldError) as error:
        print(
            json.dumps(
                {"status": "INVALID", "error": str(error)},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
            file=sys.stderr,
        )
        return 2
    print(
        json.dumps(
            summary,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


def _case_path(manifest_path: Path, manifest_value: object) -> Path:
    """case_file을 manifest 형제 파일로만 제한해 경로 탈출을 막는다."""

    if not isinstance(manifest_value, dict):
        raise P0GoldError("manifest must be an object")
    relative = manifest_value.get("case_file")
    relative_path = Path(relative) if isinstance(relative, str) else None
    if (
        relative_path is None
        or not relative
        or relative_path.is_absolute()
        or len(relative_path.parts) != 1
    ):
        raise P0GoldError("manifest case_file must be one sibling filename")
    parent = manifest_path.resolve().parent
    target = (parent / relative).resolve()
    try:
        target.relative_to(parent)
    except ValueError as error:
        raise P0GoldError("manifest case_file escaped its directory") from error
    return target


def _load_json(path: Path, limit: int, context: str) -> Any:
    """크기가 제한된 UTF-8 JSON 문서를 읽는다."""

    return json.loads(_read(path, limit, context).decode("utf-8"))


def _read(path: Path, limit: int, context: str) -> bytes:
    """일반 파일 하나만 허용하고 최대 크기를 넘으면 읽지 않는다."""

    target = path.resolve()
    if not target.is_file() or target.stat().st_size > limit:
        raise P0GoldError(f"{context} is unavailable or too large")
    return target.read_bytes()


def _jsonl(payload: bytes, context: str) -> list[object]:
    """빈 줄 없는 UTF-8 JSONL을 순서가 보존된 case 목록으로 변환한다."""

    text = payload.decode("utf-8")
    lines = text.splitlines()
    if not lines or any(not line.strip() for line in lines):
        raise P0GoldError(f"{context} must be non-empty JSONL without blank lines")
    return [json.loads(line) for line in lines]


if __name__ == "__main__":
    raise SystemExit(main())
