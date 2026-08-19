"""build smoke 매니페스트 학습·평가 데이터의 생성, 실행, 검증 절차와 CLI 진입점을 제공한다.

Select a deterministic smoke target from observed structural strata.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from collections import Counter, defaultdict, deque
from collections.abc import Iterable
from pathlib import Path
from typing import Any


REQUIRED_CASE_FIELDS = {
    "case_id",
    "node",
    "evaluation_slice",
    "structural_signature_sha256",
}


def _stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _rank(case: dict[str, Any]) -> str:
    material = {
        "case_id": case["case_id"],
        "node": case["node"],
        "evaluation_slice": case["evaluation_slice"],
        "structural_signature_sha256": case["structural_signature_sha256"],
    }
    return hashlib.sha256(_stable_json(material).encode()).hexdigest()


def _coarse_stratum(case: dict[str, Any]) -> tuple[str, str]:
    return str(case["node"]), str(case["evaluation_slice"])


def _structural_stratum(case: dict[str, Any]) -> tuple[str, str, str]:
    return (*_coarse_stratum(case), str(case["structural_signature_sha256"]))


def _interleave_structures(cases: Iterable[dict[str, Any]]) -> deque[dict[str, Any]]:
    by_signature: dict[str, deque[dict[str, Any]]] = defaultdict(deque)
    for case in sorted(cases, key=_rank):
        by_signature[str(case["structural_signature_sha256"])].append(case)
    signatures = sorted(
        by_signature,
        key=lambda value: hashlib.sha256(value.encode()).hexdigest(),
    )
    interleaved: deque[dict[str, Any]] = deque()
    while any(by_signature.values()):
        for signature in signatures:
            if by_signature[signature]:
                interleaved.append(by_signature[signature].popleft())
    return interleaved


def select_smoke(
    cases: Iterable[dict[str, Any]],
    *,
    target_size: int = 20,
) -> list[dict[str, Any]]:
    """smoke 후보를 거버넌스 제약과 입력 증거로 판정해 하나의 결과로 좁힌다.

    Balance observed node/slice groups while traversing structural signatures.
    """
    if target_size < 1:
        raise ValueError("target_size must be positive")
    materialized = list(cases)
    if target_size > len(materialized):
        raise ValueError("target_size exceeds the number of eligible cases")
    seen: set[str] = set()
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for case in materialized:
        missing = REQUIRED_CASE_FIELDS - set(case)
        if missing:
            raise ValueError(f"case is missing structural metadata: {sorted(missing)}")
        case_id = str(case["case_id"])
        if case_id in seen:
            raise ValueError(f"duplicate case_id: {case_id}")
        seen.add(case_id)
        groups[_coarse_stratum(case)].append(case)

    queues = {
        stratum: _interleave_structures(group)
        for stratum, group in sorted(groups.items())
    }
    selected: list[dict[str, Any]] = []
    while len(selected) < target_size:
        progressed = False
        for stratum in sorted(queues):
            if queues[stratum] and len(selected) < target_size:
                selected.append(queues[stratum].popleft())
                progressed = True
        if not progressed:
            raise ValueError("observed structural strata cannot satisfy target_size")
    return copy.deepcopy(selected)


def main(argv: list[str] | None = None) -> int:
    """validation manifest에서 node·ID/OOD 구조를 균형 선택해 checksum 포함 smoke manifest를 만든다."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("validation_manifest", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--target-size", type=int, default=20)
    args = parser.parse_args(argv)

    source = json.loads(args.validation_manifest.read_text(encoding="utf-8"))
    cases = select_smoke(source["cases"], target_size=args.target_size)
    manifest = {
        "manifest_version": "STRUCTURAL-SMOKE-v1.0.0",
        "source_manifest": str(args.validation_manifest).replace("\\", "/"),
        "source_content_sha256": source["content_sha256"],
        "content_sha256": hashlib.sha256(_stable_json(cases).encode()).hexdigest(),
        "counts": {
            "total": len(cases),
            "nodes": dict(sorted(Counter(case["node"] for case in cases).items())),
            "slices": dict(
                sorted(Counter(case["evaluation_slice"] for case in cases).items())
            ),
            "structural_strata": len({_structural_stratum(case) for case in cases}),
        },
        "cases": cases,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest["counts"], ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
