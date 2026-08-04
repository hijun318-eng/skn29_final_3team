"""Select a deterministic 20-case smoke across every product domain and SQL node."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any


STRATUM_QUOTAS = {
    ("banquet", "node2"): 2,
    ("banquet", "node2_repair"): 1,
    ("crm", "node2"): 2,
    ("crm", "node2_repair"): 2,
    ("facility", "node2"): 1,
    ("facility", "node2_repair"): 2,
    ("pms", "node2"): 2,
    ("pms", "node2_repair"): 2,
    ("pms_crm", "node2"): 2,
    ("pms_crm", "node2_repair"): 1,
    ("pos", "node2"): 1,
    ("pos", "node2_repair"): 2,
}


def _stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _rank(case: dict[str, Any]) -> str:
    material = {
        "candidate_id": case["candidate_id"],
        "semantic_signature_sha256": case["semantic_signature_sha256"],
    }
    return hashlib.sha256(_stable_json(material).encode()).hexdigest()


def select_smoke20(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    slice_counts: Counter[str] = Counter()
    for stratum, quota in STRATUM_QUOTAS.items():
        pool = sorted(
            (case for case in cases if (case["domain"], case["node"]) == stratum),
            key=_rank,
        )
        by_slice = {
            name: [case for case in pool if case["evaluation_slice"] == name]
            for name in ("ID", "OOD")
        }
        if quota == 2:
            if not all(by_slice.values()):
                raise ValueError(f"{stratum} needs one ID and one OOD case")
            chosen = [by_slice["ID"][0], by_slice["OOD"][0]]
        else:
            preferred = min(("ID", "OOD"), key=lambda name: (slice_counts[name], name))
            available = by_slice[preferred] or by_slice["OOD" if preferred == "ID" else "ID"]
            if not available:
                raise ValueError(f"{stratum} has no eligible case")
            chosen = [available[0]]
        selected.extend(chosen)
        slice_counts.update(case["evaluation_slice"] for case in chosen)
    return sorted(selected, key=lambda case: (case["domain"], case["node"], case["evaluation_slice"]))


def reproduce_previous(previous: list[dict[str, Any]], cases: list[dict[str, Any]]) -> dict[str, Any]:
    metadata = {case["case_id"]: case for case in cases}
    return {
        "total": len(previous),
        "valid_json": sum(bool(item["valid_json"]) for item in previous),
        "g2_pass": sum(item["g2"] == "PASS" for item in previous),
        "trino_pass": sum(item["trino"] == "PASS" for item in previous),
        "failure_counts": dict(sorted(Counter(item["g2"] for item in previous if item["g2"] != "PASS").items())),
        "domains": dict(sorted(Counter(metadata[item["case_id"]]["domain"] for item in previous).items())),
        "nodes": dict(sorted(Counter(metadata[item["case_id"]]["node"] for item in previous).items())),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("validation_manifest", type=Path)
    parser.add_argument("previous_eval", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    source = json.loads(args.validation_manifest.read_text(encoding="utf-8"))
    previous = [json.loads(line) for line in args.previous_eval.read_text(encoding="utf-8").splitlines() if line]
    cases = select_smoke20(source["cases"])
    manifest = {
        "manifest_version": "BASE-SMOKE-v2.0.0",
        "source_manifest": str(args.validation_manifest).replace("\\", "/"),
        "source_content_sha256": source["content_sha256"],
        "previous_failure_reproduction": reproduce_previous(previous, source["cases"]),
        "content_sha256": hashlib.sha256(_stable_json(cases).encode()).hexdigest(),
        "counts": {
            "total": len(cases),
            "domains": dict(sorted(Counter(case["domain"] for case in cases).items())),
            "nodes": dict(sorted(Counter(case["node"] for case in cases).items())),
            "slices": dict(sorted(Counter(case["evaluation_slice"] for case in cases).items())),
        },
        "cases": cases,
    }
    if manifest["counts"] != {
        "total": 20,
        "domains": {"banquet": 3, "crm": 4, "facility": 3, "pms": 4, "pms_crm": 3, "pos": 3},
        "nodes": {"node2": 10, "node2_repair": 10},
        "slices": {"ID": 10, "OOD": 10},
    }:
        raise ValueError(f"unexpected smoke distribution: {manifest['counts']}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"content_sha256": manifest["content_sha256"], **manifest["counts"]}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
