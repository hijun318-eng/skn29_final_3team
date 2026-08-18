"""build 검증 V2 학습·평가 데이터의 생성, 실행, 검증 절차와 CLI 진입점을 제공한다.

Select ID/OOD validation slices from reviewed full specifications.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from src.ai.training.dataset import load_specs, write_jsonl


SIGNATURE_VERSION = "STRUCTURAL-SIGNATURE-v2"


def structural_signature(spec: dict[str, Any]) -> tuple[Any, ...]:
    """식별자·FQN·질문·날짜를 제외하고 schema topology만 나타내는 signature를 만든다.

    asset grain과 column 유형, join cardinality·조건 수, metric 구조와 time rule 모양만
    보존해 validation 사례가 단순 명칭 암기가 아닌 ID/OOD 구조로 분리되게 한다.
    """
    request = spec["input"]
    context = request.get("schema_context") or request.get("context_package") or {}
    assets = context.get("assets", ())
    joins = (request.get("join_graph") or {}).get("edges")
    if joins is None:
        joins = context.get("joins", ())
    metrics = request.get("metric_rules")
    if metrics is None:
        metrics = context.get("metrics", ())
    time_rules = request.get("time_rules") or context.get("execution_time") or {}
    return (
        tuple(sorted((_asset_shape(item) for item in assets), key=_stable_json)),
        _join_graph_shape(joins),
        tuple(sorted((_metric_shape(item) for item in metrics), key=_stable_json)),
        _time_shape(time_rules),
    )


def select_validation_v2(
    specs: list[dict[str, Any]],
    *,
    limit_per_slice: int | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """검증 V2 후보를 거버넌스 제약과 입력 증거로 판정해 하나의 결과로 좁힌다."""
    if limit_per_slice is not None and limit_per_slice < 0:
        raise ValueError("limit_per_slice must be non-negative")
    train_signatures = {
        structural_signature(item) for item in specs if item["split"] == "train"
    }
    if not train_signatures:
        raise ValueError("at least one reviewed train specification is required")
    eligible = sorted(
        (item for item in specs if item["split"] == "validation"),
        key=lambda item: str(item["case_id"]),
    )
    validation_id = [
        item for item in eligible if structural_signature(item) in train_signatures
    ]
    validation_ood = [
        item for item in eligible if structural_signature(item) not in train_signatures
    ]
    if limit_per_slice is not None:
        validation_id = validation_id[:limit_per_slice]
        validation_ood = validation_ood[:limit_per_slice]
    return copy.deepcopy(validation_id), copy.deepcopy(validation_ood)


def _asset_shape(asset: dict[str, Any]) -> tuple[Any, ...]:
    grain = asset.get("grain") or {}
    columns = tuple(sorted(_column_shape(item) for item in asset.get("columns", ())))
    return (
        str(grain.get("kind") or "unspecified").casefold()
        if isinstance(grain, dict)
        else "unspecified",
        len(grain.get("keys", ())) if isinstance(grain, dict) else 0,
        columns,
    )


def _column_shape(column: Any) -> tuple[Any, ...]:
    if not isinstance(column, dict):
        return ("untyped",)
    return (
        str(column.get("native_type") or column.get("type") or "unknown").casefold(),
        bool(column.get("nullable", True)),
        str(column.get("role") or "unknown").casefold(),
    )


def _join_shape(join: dict[str, Any]) -> tuple[Any, ...]:
    preaggregation = join.get("preaggregation") or {}
    return (
        str(join.get("kind") or "unspecified").casefold(),
        str(join.get("cardinality") or "unspecified").casefold(),
        len(join.get("equality_conditions", ())),
        len(join.get("temporal_conditions", ())),
        bool(preaggregation.get("required")) if isinstance(preaggregation, dict) else False,
        len(preaggregation.get("grain", ())) if isinstance(preaggregation, dict) else 0,
        len(preaggregation.get("keys", ())) if isinstance(preaggregation, dict) else 0,
    )


def _join_graph_shape(joins: Any) -> tuple[Any, ...]:
    """Return an identifier-free edge and node-degree topology signature."""
    edge_shapes: list[tuple[Any, ...]] = []
    incident: dict[str, list[tuple[Any, ...]]] = {}
    directions: dict[str, list[int]] = {}
    for index, join in enumerate(joins):
        shape = _join_shape(join)
        left = str(join.get("left") or f"__missing_left_{index}")
        right = str(join.get("right") or f"__missing_right_{index}")
        edge_shapes.append(shape)
        incident.setdefault(left, []).append(("out",) + shape)
        incident.setdefault(right, []).append(("in",) + shape)
        directions.setdefault(left, [0, 0])[0] += 1
        directions.setdefault(right, [0, 0])[1] += 1
    node_profiles = (
        (
            directions[node][0],
            directions[node][1],
            len(edges),
            tuple(sorted(edges, key=_stable_json)),
        )
        for node, edges in incident.items()
    )
    return (
        tuple(sorted(edge_shapes, key=_stable_json)),
        tuple(sorted(node_profiles, key=_stable_json)),
    )


def _metric_shape(metric: dict[str, Any]) -> tuple[Any, ...]:
    source = metric.get("source") or {}
    if (
        not isinstance(source, dict)
        or source.get("kind") != "column"
        or not isinstance(source.get("field"), dict)
    ):
        raise ValueError("structural signature requires a column-source metric contract")
    filters = metric.get("required_filters", ())
    return (
        str(metric.get("aggregation") or "unspecified").casefold(),
        len(metric.get("dimensions", ())),
        tuple(sorted(str(item.get("operator") or "unknown").casefold() for item in filters)),
        bool(metric.get("time_field")),
    )


def _time_shape(time_rules: dict[str, Any]) -> tuple[Any, ...]:
    fields = time_rules.get("fields", ()) if isinstance(time_rules, dict) else ()
    return (
        str(time_rules.get("interval") or "unspecified").casefold(),
        bool(time_rules.get("start_parameter") or time_rules.get("period_start")),
        bool(time_rules.get("end_parameter") or time_rules.get("period_end_exclusive")),
        tuple(
            sorted(
                (
                    str(item.get("native_type") or "unknown").casefold(),
                    str(item.get("bucket") or "none").casefold(),
                    str(item.get("timezone_mode") or "unspecified").casefold(),
                )
                for item in fields
            )
        ),
    )


def _stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _signature_hash(spec: dict[str, Any]) -> str:
    return hashlib.sha256(_stable_json(structural_signature(spec)).encode()).hexdigest()


def main(argv: list[str] | None = None) -> int:
    """검토 spec을 train 구조와 같은 ID·다른 OOD slice로 나눠 case JSONL과 hash manifest를 쓴다."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("specs", type=Path, help="reviewed full-spec JSONL")
    parser.add_argument("cases", type=Path, help="selected full-spec JSONL")
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--limit-per-slice", type=int)
    args = parser.parse_args(argv)

    specs = load_specs(args.specs)
    validation_id, validation_ood = select_validation_v2(
        specs, limit_per_slice=args.limit_per_slice
    )
    selected = [("ID", item) for item in validation_id] + [
        ("OOD", item) for item in validation_ood
    ]
    if not selected:
        raise ValueError("no validation specifications matched the structural slices")
    cases = [item for _slice, item in selected]
    write_jsonl(args.cases, cases)
    load_specs(args.cases)

    entries = [
        {
            "case_id": item["case_id"],
            "source_split": item["split"],
            "evaluation_slice": evaluation_slice,
            "node": item["node"],
            "structural_signature_sha256": _signature_hash(item),
        }
        for evaluation_slice, item in selected
    ]
    manifest = {
        "manifest_version": "VALIDATION-v3.0.0",
        "signature_version": SIGNATURE_VERSION,
        "source_sha256": hashlib.sha256(args.specs.read_bytes()).hexdigest(),
        "content_sha256": hashlib.sha256(_stable_json(entries).encode()).hexdigest(),
        "counts": {
            "total": len(entries),
            "ID": len(validation_id),
            "OOD": len(validation_ood),
            "nodes": dict(sorted(Counter(item["node"] for item in cases).items())),
        },
        "cases": entries,
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest["counts"], ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
