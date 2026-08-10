"""Build deterministic Validation-ID/OOD cases without touching Gold or Acceptance."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from src.ai.training.build_case_specs import CONTEXT_CONTRACT, _read_jsonl, _urn, build_case
from src.ai.training.dataset import load_specs, write_jsonl


SIGNATURE_FIELDS = (
    "domain",
    "metric_id",
    "aggregation",
    "dimension",
    "filter_shape",
    "output_shape",
    "period_shape",
    "node",
)
DOMAIN_QUOTAS = {
    "pms": 27,
    "crm": 17,
    "pms_crm": 14,
    "pos": 10,
    "facility": 4,
    "banquet": 3,
}


def semantic_signature(record: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(record.get(field) for field in SIGNATURE_FIELDS)


def _select(pool: list[dict[str, Any]], quotas: dict[str, int]) -> list[dict[str, Any]]:
    selected = []
    for domain, quota in quotas.items():
        candidates = sorted(
            (record for record in pool if record["domain"] == domain),
            key=lambda record: record["candidate_id"],
        )
        if len(candidates) < quota:
            raise ValueError(f"{domain} needs {quota} cases, found {len(candidates)}")
        selected.extend(candidates[:quota])
    return sorted(selected, key=lambda record: record["candidate_id"])


def select_validation_v2(
    records: list[dict[str, Any]],
    quotas: dict[str, int] = DOMAIN_QUOTAS,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    train_signatures = {
        semantic_signature(record)
        for record in records
        if record["target_split"] == "train"
    }
    eligible = [
        record
        for record in records
        if record["target_split"] in {"validation", "reserve"}
    ]
    validation_id = _select(
        [record for record in eligible if semantic_signature(record) in train_signatures],
        quotas,
    )
    validation_ood = _select(
        [record for record in eligible if semantic_signature(record) not in train_signatures],
        quotas,
    )
    return validation_id, validation_ood


def _stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _validate_product_context(cases: list[dict[str, Any]]) -> None:
    context = json.loads(CONTEXT_CONTRACT.read_text(encoding="utf-8"))
    root = CONTEXT_CONTRACT.parents[2]
    views = json.loads((root / context["view_contract"]).read_text(encoding="utf-8"))["views"]
    allowed_fqns = {view["fqn"] for view in views} | {
        asset["fqn"] for asset in context["raw_assets"]
    }
    for case in cases:
        for asset in case["input"]["context_package"]["assets"]:
            fqn = asset["trino_fqn"]
            if fqn not in allowed_fqns or asset["urn"] != _urn(fqn):
                raise ValueError(f"case uses an asset outside the product Context: {fqn}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ledger", type=Path)
    parser.add_argument("cases", type=Path)
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args()

    records = _read_jsonl(args.ledger)
    validation_id, validation_ood = select_validation_v2(records)
    selected = [("ID", record) for record in validation_id] + [
        ("OOD", record) for record in validation_ood
    ]
    cases = []
    manifest_cases = []
    for evaluation_slice, source in selected:
        record = {**source, "target_split": "validation"}
        case = build_case(record)
        cases.append(case)
        signature = semantic_signature(source)
        manifest_cases.append(
            {
                "case_id": case["case_id"],
                "candidate_id": source["candidate_id"],
                "source_split": source["target_split"],
                "evaluation_slice": evaluation_slice,
                "domain": source["domain"],
                "node": source["node"],
                "semantic_signature_sha256": hashlib.sha256(
                    _stable_json(signature).encode("utf-8")
                ).hexdigest(),
            }
        )

    write_jsonl(args.cases, cases)
    load_specs(args.cases)
    _validate_product_context(cases)
    content_sha256 = hashlib.sha256(_stable_json(manifest_cases).encode("utf-8")).hexdigest()
    manifest = {
        "manifest_version": "VALIDATION-v2.0.0",
        "signature_fields": list(SIGNATURE_FIELDS),
        "source_sha256": hashlib.sha256(args.ledger.read_bytes()).hexdigest(),
        "content_sha256": content_sha256,
        "counts": {
            "total": len(cases),
            "ID": len(validation_id),
            "OOD": len(validation_ood),
            "domains": dict(sorted(Counter(case["domain"] for case in cases).items())),
        },
        "cases": manifest_cases,
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest["counts"], ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
