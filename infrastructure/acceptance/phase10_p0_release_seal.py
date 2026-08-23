#!/usr/bin/env python3
"""Seal the approved Phase 10 semantic core and P0 Gold to one active release.

The versioned repository manifest deliberately remains DRAFT because the
product release ID is derived from the repository source receipt.  This tool
creates the immutable SEALED evaluation bundle under ``.tmp`` only after the
current source, active product manifest, runtime projection, approved semantic
core, and the separately accepted Phase 9 additive JOIN capability agree.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import psycopg
from psycopg.rows import dict_row
from sqlalchemy.engine import URL, make_url


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "app" / "backend"
DATAHUB = ROOT / "infrastructure" / "database" / "datahub"
HERE = Path(__file__).resolve().parent
for entry in (str(ROOT), str(BACKEND), str(DATAHUB), str(HERE)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from app.adapters.runtime_catalog_projection import (  # noqa: E402
    RuntimeCatalogProjection,
)
from app.capability_contracts import (  # noqa: E402
    ProductReleaseEvidenceManifest,
    SourceReceipt,
)
from evals.p0_gold import canonical_sha256, validate_manifest  # noqa: E402
from metric_review_contract import validate_metric_review  # noqa: E402
from phase10_candidate_release import (  # noqa: E402
    PHASE9_PREFIX,
    PHASE10_PREFIX,
    TARGET_DATABASE,
)
from phase4_runtime_catalog_projection import _source_receipt  # noqa: E402
from runtime_governance_draft import build_draft  # noqa: E402


TARGET_PROJECT = "answervice-phase2b-datahub"
TARGET_HOST = "127.0.0.1"
TARGET_PORT = 55440
TARGET_USER = "phase10_runtime"
REVIEWER = "urn:li:corpGroup:answervice_runtime_stewards"
SEAL_VERSION = "answervice.phase10_p0_release_seal.v1"
BINDING_VERSION = "answervice.approved_semantic_runtime_binding.v1"
SYNTHETIC_NOTICE = "DEMO_SYNTHETIC_SCENARIO_NOT_WALKERHILL_ACTUAL_PERFORMANCE"

SEMANTIC_PATH = ROOT / "evals" / "semantic_review" / "answervice_d2_metrics.v1.json"
GOLD_CASE_PATH = ROOT / "evals" / "p0_gold" / "answervice_v4_3.p0.candidate.v2.jsonl"
GOLD_MANIFEST_PATH = (
    ROOT / "evals" / "p0_gold" / "answervice_v4_3.p0.candidate.v2.manifest.json"
)
SQL_DIRECTORY = (
    ROOT
    / "infrastructure"
    / "database"
    / "releases"
    / "walkerhill_v4_3_20260815_derived_1"
    / "01_V4.3_생성_및_서빙_SQL"
    / "06_trino_serving"
)
OUTPUT_DIRECTORY = ROOT / ".tmp" / "phase10-p0-sealed-v2"
OUTPUT_MANIFEST = OUTPUT_DIRECTORY / GOLD_MANIFEST_PATH.name
OUTPUT_CASES = OUTPUT_DIRECTORY / GOLD_CASE_PATH.name
OUTPUT_SEMANTIC = OUTPUT_DIRECTORY / SEMANTIC_PATH.name
OUTPUT_RECEIPT = OUTPUT_DIRECTORY / "phase10_p0_release_seal.receipt.json"
OUTPUT_FILES = frozenset(
    {OUTPUT_MANIFEST.name, OUTPUT_CASES.name, OUTPUT_SEMANTIC.name, OUTPUT_RECEIPT.name}
)


class Phase10P0ReleaseSealError(RuntimeError):
    """The approved semantic, Gold, source, or active release binding differs."""


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-project", required=True)
    parser.add_argument("--database-url", required=True)
    return parser.parse_args(argv)


def _database_url(value: str) -> URL:
    url = make_url(value)
    if (
        url.drivername != "postgresql+psycopg"
        or url.host not in {TARGET_HOST, "localhost", "::1"}
        or url.port != TARGET_PORT
        or url.database != TARGET_DATABASE
        or url.username != TARGET_USER
        or url.password is not None
        or url.query
    ):
        raise Phase10P0ReleaseSealError(
            "Phase 10 P0 seal database is outside the isolated boundary"
        )
    return url


def validate_boundary(args: argparse.Namespace) -> URL:
    if args.target_project != TARGET_PROJECT:
        raise Phase10P0ReleaseSealError(
            "Phase 10 P0 seal target project is outside the approved boundary"
        )
    return _database_url(args.database_url)


def _connect(url: URL) -> psycopg.Connection[Any]:
    return psycopg.connect(
        host=url.host,
        port=url.port,
        dbname=url.database,
        user=url.username,
        row_factory=dict_row,
    )


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise Phase10P0ReleaseSealError("P0 seal JSON input is unavailable") from error
    if not isinstance(value, dict):
        raise Phase10P0ReleaseSealError("P0 seal JSON input must be an object")
    return value


def _load_cases(path: Path) -> tuple[bytes, list[dict[str, Any]]]:
    try:
        payload = path.read_bytes()
        values = [
            json.loads(line)
            for line in payload.decode("utf-8").splitlines()
            if line
        ]
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise Phase10P0ReleaseSealError("P0 seal Gold input is unavailable") from error
    if len(values) != 55 or any(not isinstance(value, dict) for value in values):
        raise Phase10P0ReleaseSealError("P0 seal Gold case inventory differs")
    return payload, values


def _load_release_state(
    url: URL,
) -> tuple[
    int,
    ProductReleaseEvidenceManifest,
    RuntimeCatalogProjection,
    ProductReleaseEvidenceManifest,
]:
    with _connect(url) as connection:
        row = connection.execute(
            """
            SELECT a.generation, m.manifest_json,
                   p.projection_json, p.projection_sha256
            FROM governance.runtime_catalog_active_pointer a
            JOIN governance.product_release_manifests m
              ON m.product_release_id = a.product_release_id
            JOIN governance.runtime_catalog_projections p
              ON p.projection_id = a.projection_id
            WHERE a.pointer_name = 'analysis'
            """
        ).fetchone()
        basis_rows = connection.execute(
            """
            SELECT manifest_json
            FROM governance.product_release_manifests
            ORDER BY product_release_id
            """
        ).fetchall()
    if row is None:
        raise Phase10P0ReleaseSealError("active Phase 10 release is unavailable")
    try:
        manifest = ProductReleaseEvidenceManifest.model_validate(row["manifest_json"])
        projection = RuntimeCatalogProjection.from_document(
            row["projection_json"],
            expected_projection_sha256=str(row["projection_sha256"]),
        )
        candidates = [
            ProductReleaseEvidenceManifest.model_validate(item["manifest_json"])
            for item in basis_rows
        ]
    except (KeyError, TypeError, ValueError) as error:
        raise Phase10P0ReleaseSealError("active Phase 10 release is invalid") from error
    phase9 = [
        item
        for item in candidates
        if item.product_release_id.startswith(PHASE9_PREFIX)
        and item.evidence.catalog.release_id == projection.catalog_release_id
        and item.evidence.catalog.manifest_sha256 == projection.manifest_sha256
        and item.evidence.catalog.projection_sha256 == projection.projection_sha256
    ]
    if len(phase9) != 1:
        raise Phase10P0ReleaseSealError(
            "active semantic projection lacks one exact Phase 9 capability basis"
        )
    if (
        not manifest.product_release_id.startswith(PHASE10_PREFIX)
        or manifest.evidence.catalog.release_id != projection.catalog_release_id
        or manifest.evidence.catalog.manifest_sha256 != projection.manifest_sha256
        or manifest.evidence.catalog.projection_sha256 != projection.projection_sha256
        or manifest.evidence.release_vector.data_release_id
        != projection.catalog_release_id
        or manifest.evidence.release_vector.semantic_release_id
        != projection.catalog_release_id
    ):
        raise Phase10P0ReleaseSealError(
            "active Phase 10 product and semantic projection binding differs"
        )
    return int(row["generation"]), manifest, projection, phase9[0]


def _source_assets(
    metric_id: str,
    rules: Mapping[str, Mapping[str, Any]],
    trail: frozenset[str] = frozenset(),
) -> tuple[str, ...]:
    if metric_id in trail:
        raise Phase10P0ReleaseSealError("runtime semantic ratio contains a cycle")
    rule = rules.get(metric_id)
    if rule is None:
        raise Phase10P0ReleaseSealError("runtime semantic ratio operand is unavailable")
    source = rule.get("source")
    if not isinstance(source, Mapping):
        raise Phase10P0ReleaseSealError("runtime semantic source is invalid")
    if source.get("kind") == "column":
        field = source.get("field")
        if not isinstance(field, Mapping) or not isinstance(field.get("asset_fqn"), str):
            raise Phase10P0ReleaseSealError("runtime semantic column source is invalid")
        return (str(field["asset_fqn"]),)
    if source.get("kind") != "ratio":
        raise Phase10P0ReleaseSealError("runtime semantic source kind is unsupported")
    operands = (source.get("numerator_metric_id"), source.get("denominator_metric_id"))
    if any(not isinstance(value, str) for value in operands):
        raise Phase10P0ReleaseSealError("runtime semantic ratio source is invalid")
    return tuple(
        sorted(
            {
                asset
                for operand in operands
                for asset in _source_assets(str(operand), rules, trail | {metric_id})
            }
        )
    )


def _runtime_time(
    metric_id: str,
    rule: Mapping[str, Any],
    rules: Mapping[str, Mapping[str, Any]],
    time_rules: Mapping[str, Any],
) -> dict[str, Any]:
    governance = rule.get("governance")
    time = governance.get("time") if isinstance(governance, Mapping) else None
    fields = time_rules.get("fields") if isinstance(time_rules, Mapping) else None
    if not isinstance(time, Mapping) or not isinstance(fields, list):
        raise Phase10P0ReleaseSealError("runtime semantic time policy is invalid")
    assets = _source_assets(metric_id, rules)
    if len(assets) != 1:
        raise Phase10P0ReleaseSealError("runtime metric must resolve one time asset")
    matching = [
        item
        for item in fields
        if isinstance(item, Mapping)
        and item.get("field")
        == {"asset_fqn": assets[0], "column": time.get("field")}
    ]
    if len(matching) != 1:
        raise Phase10P0ReleaseSealError("runtime metric time field is not uniquely governed")
    field_policy = matching[0]
    if (
        time.get("timezone") != time_rules.get("timezone")
        or time.get("interval") != time_rules.get("interval")
    ):
        raise Phase10P0ReleaseSealError("runtime metric and release time policy differ")
    return {
        "field": time.get("field"),
        "semantics": time.get("semantics"),
        "timezone": time.get("timezone"),
        "interval": time.get("interval"),
        "bucket": field_policy.get("bucket"),
        "timezone_mode": field_policy.get("timezone_mode"),
    }


def _normalize_core_lists(value: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize fields whose contract meaning is a set, not authoring order."""

    result = deepcopy(dict(value))
    result["aliases"] = sorted({result["name"], *result["aliases"]})
    result["grain"]["keys"] = sorted(result["grain"]["keys"])
    result["grain"]["dimensions"] = sorted(result["grain"]["dimensions"])
    result["permission"]["roles"] = sorted(result["permission"]["roles"])
    return result


def _candidate_core(metric: Mapping[str, Any]) -> dict[str, Any]:
    return _normalize_core_lists({
        key: deepcopy(metric[key])
        for key in (
            "id",
            "name",
            "visibility",
            "definition",
            "formula",
            "source",
            "grain",
            "time",
            "aliases",
            "permission",
            "unit",
            "result_field",
        )
    })


def _runtime_core(
    rule: Mapping[str, Any],
    rules: Mapping[str, Mapping[str, Any]],
    time_rules: Mapping[str, Any],
) -> dict[str, Any]:
    metric_id = str(rule.get("id") or "")
    governance = rule.get("governance")
    source = rule.get("source")
    if not isinstance(governance, Mapping) or not isinstance(source, Mapping):
        raise Phase10P0ReleaseSealError("runtime metric governance is invalid")
    semantic = governance.get("semantic")
    if not isinstance(semantic, Mapping):
        raise Phase10P0ReleaseSealError("runtime metric semantic text is invalid")
    if source.get("kind") == "column":
        field = source.get("field")
        if not isinstance(field, Mapping):
            raise Phase10P0ReleaseSealError("runtime metric field is invalid")
        normalized_source = {
            "kind": "COLUMN",
            "asset_fqn": field.get("asset_fqn"),
            "column": field.get("column"),
        }
        formula = {
            "kind": "COLUMN",
            "aggregation": rule.get("aggregation"),
            "reduction": rule.get("reduction"),
        }
    elif source.get("kind") == "ratio":
        numerator = source.get("numerator_metric_id")
        denominator = source.get("denominator_metric_id")
        if rule.get("aggregation") != "ratio" or rule.get("reduction") != "ratio":
            raise Phase10P0ReleaseSealError("runtime ratio formula is invalid")
        normalized_source = {
            "kind": "METRIC_OPERANDS",
            "metric_ids": [numerator, denominator],
        }
        formula = {
            "kind": "RATIO",
            "numerator_metric_id": numerator,
            "denominator_metric_id": denominator,
            "zero_policy": source.get("zero_policy"),
        }
    else:
        raise Phase10P0ReleaseSealError("runtime metric source kind is unsupported")
    return _normalize_core_lists({
        "id": metric_id,
        "name": semantic.get("name"),
        "visibility": governance.get("visibility"),
        "definition": semantic.get("definition"),
        "formula": formula,
        "source": normalized_source,
        "grain": deepcopy(governance.get("grain")),
        "time": _runtime_time(metric_id, rule, rules, time_rules),
        "aliases": deepcopy(semantic.get("aliases")),
        "permission": deepcopy(governance.get("permission")),
        "unit": rule.get("unit"),
        "result_field": rule.get("result_field"),
    })


def semantic_runtime_binding(
    candidate: Mapping[str, Any],
    bundle: Mapping[str, Any],
) -> dict[str, Any]:
    """Compare the approved core exactly and expose every additive capability."""

    candidate_metrics = candidate.get("metrics")
    runtime_metrics = bundle.get("metric_rules")
    time_rules = bundle.get("time_rules")
    if (
        not isinstance(candidate_metrics, list)
        or not isinstance(runtime_metrics, list)
        or not isinstance(time_rules, Mapping)
    ):
        raise Phase10P0ReleaseSealError("semantic binding inputs are invalid")
    candidates = {str(item.get("id")): item for item in candidate_metrics}
    rules = {str(item.get("id")): item for item in runtime_metrics}
    if len(candidates) != len(candidate_metrics) or set(candidates) != set(rules):
        raise Phase10P0ReleaseSealError("approved and runtime metric inventories differ")

    approved_core = [_candidate_core(candidates[key]) for key in sorted(candidates)]
    runtime_core = [
        _runtime_core(rules[key], rules, time_rules) for key in sorted(rules)
    ]
    if approved_core != runtime_core:
        for approved, runtime in zip(approved_core, runtime_core, strict=True):
            differences = [key for key in approved if approved[key] != runtime.get(key)]
            if differences:
                raise Phase10P0ReleaseSealError(
                    "approved semantic core differs for "
                    f"{approved['id']}: {','.join(sorted(differences))}"
                )
        raise Phase10P0ReleaseSealError("approved semantic core differs")

    extensions: list[dict[str, Any]] = []
    for metric_id in sorted(candidates):
        approved = candidates[metric_id]
        runtime = rules[metric_id]
        governance = runtime["governance"]
        approved_join = approved["join"]
        runtime_join = governance["join"]
        approved_edges = set(approved_join["allowed_edge_ids"])
        runtime_edges = set(runtime_join["allowed_edge_ids"])
        approved_strategies = set(approved["query_strategies"])
        runtime_strategies = set(governance["query_strategies"])
        if (
            approved_join["required"] != runtime_join["required"]
            or not approved_edges <= runtime_edges
            or not approved_strategies <= runtime_strategies
        ):
            raise Phase10P0ReleaseSealError(
                f"runtime capability narrows or changes approved metric {metric_id}"
            )
        added_edges = sorted(runtime_edges - approved_edges)
        added_strategies = sorted(runtime_strategies - approved_strategies)
        if added_edges or added_strategies:
            extensions.append(
                {
                    "metric_id": metric_id,
                    "added_join_ids": added_edges,
                    "added_query_strategies": added_strategies,
                }
            )

    terms = bundle.get("metric_terms")
    if not isinstance(terms, list):
        raise Phase10P0ReleaseSealError("runtime business term inventory is invalid")
    business = {
        metric_id: metric
        for metric_id, metric in candidates.items()
        if metric.get("visibility") == "BUSINESS"
    }
    runtime_terms = {str(term.get("id")): term for term in terms}
    if set(runtime_terms) != set(business):
        raise Phase10P0ReleaseSealError("approved business terms and runtime terms differ")
    for metric_id, metric in business.items():
        term = runtime_terms[metric_id]
        if (
            term.get("name") != metric.get("name")
            or term.get("definition") != metric.get("definition")
            or set(term.get("aliases") or []) | {term.get("name")}
            != set(metric.get("aliases") or []) | {metric.get("name")}
            or term.get("unit") != metric.get("unit")
            or term.get("approval_status") != "APPROVED"
            or term.get("owner_urn") != REVIEWER
        ):
            raise Phase10P0ReleaseSealError(
                f"approved business term differs for {metric_id}"
            )

    extension_payload = {
        "mode": (
            "APPROVED_CORE_PLUS_PHASE9_ADDITIVE_CAPABILITY"
            if extensions
            else "EXACT_APPROVED_RUNTIME"
        ),
        "metrics": extensions,
    }
    return {
        "schema_version": BINDING_VERSION,
        "approved_core_sha256": canonical_sha256(approved_core),
        "runtime_core_sha256": canonical_sha256(runtime_core),
        "core_exact": True,
        "capability_extension": extension_payload,
        "capability_extension_sha256": canonical_sha256(extension_payload),
    }


def _sealed_manifest(
    source: Mapping[str, Any],
    *,
    semantic_release_id: str,
    product_release_id: str,
) -> dict[str, Any]:
    result = deepcopy(dict(source))
    result.update(
        {
            "status": "SEALED",
            "semantic_release_id": semantic_release_id,
            "product_release_id": product_release_id,
        }
    )
    result["provenance"]["notes"] = (
        "Domain-owner approved synthetic semantic mappings, intent and safety decisions, "
        "and independent result assertions; bound by the external Phase 10 release seal."
    )
    return result


def _receipt(
    *,
    generation: int,
    product: ProductReleaseEvidenceManifest,
    projection: RuntimeCatalogProjection,
    phase9: ProductReleaseEvidenceManifest,
    current_source: SourceReceipt,
    semantic: Mapping[str, Any],
    semantic_file_sha256: str,
    cases: list[Mapping[str, Any]],
    case_sha256: str,
    sealed_validation: Mapping[str, Any],
    binding: Mapping[str, Any],
) -> dict[str, Any]:
    reviewed_at = semantic.get("reviewed_at")
    if (
        semantic.get("review_status") != "APPROVED"
        or semantic.get("reviewer") != REVIEWER
        or not isinstance(reviewed_at, str)
        or {case.get("review_status") for case in cases} != {"APPROVED"}
        or {case.get("reviewer") for case in cases} != {REVIEWER}
        or {case.get("reviewed_at") for case in cases} != {reviewed_at}
        or any(case.get("is_synthetic") is not True for case in cases)
    ):
        raise Phase10P0ReleaseSealError("approved semantic and Gold review receipts differ")
    payload: dict[str, Any] = {
        "schema_version": SEAL_VERSION,
        "status": "SEALED",
        "target_project": TARGET_PROJECT,
        "active_generation": generation,
        "content_notice": SYNTHETIC_NOTICE,
        "source": current_source.model_dump(mode="json"),
        "source_receipt_sha256": canonical_sha256(
            current_source.model_dump(mode="json")
        ),
        "review": {
            "reviewer": REVIEWER,
            "reviewed_at": reviewed_at,
            "semantic_candidate_sha256": canonical_sha256(semantic),
            "semantic_file_sha256": semantic_file_sha256,
            "business_metric_count": 10,
            "support_metric_count": 4,
            "gold_case_count": 55,
            "gold_case_sha256": case_sha256,
        },
        "semantic_binding": dict(binding),
        "semantic_release": {
            "release_id": projection.catalog_release_id,
            "catalog_sha256": projection.catalog_sha256,
            "canonical_sha256": projection.canonical_sha256,
            "manifest_sha256": projection.manifest_sha256,
            "projection_sha256": projection.projection_sha256,
            "source_selection_sha256": projection.source_selection_sha256,
        },
        "phase9_capability_basis": {
            "product_release_id": phase9.product_release_id,
            "manifest_sha256": phase9.manifest_sha256,
            "projection_sha256": phase9.evidence.catalog.projection_sha256,
        },
        "product_release": {
            "product_release_id": product.product_release_id,
            "manifest_sha256": product.manifest_sha256,
            "model_release_id": product.evidence.model.release_id,
            "model_manifest_sha256": product.evidence.model.manifest_sha256,
        },
        "gold": {
            "status": sealed_validation["status"],
            "scorable": sealed_validation["scorable"],
            "manifest_sha256": sealed_validation["manifest_sha256"],
            "case_content_sha256": sealed_validation["case_content_sha256"],
            "semantic_candidate_sha256": sealed_validation[
                "semantic_candidate_sha256"
            ],
            "case_counts": sealed_validation["case_counts"],
            "review_counts": sealed_validation["review_counts"],
        },
        "historical_evidence_mixed": False,
        "skipped_evidence_count": 0,
        "sealed_at": datetime.now(timezone.utc).isoformat(),
    }
    payload["receipt_sha256"] = canonical_sha256(payload)
    validate_release_seal_receipt(payload)
    return payload


def validate_release_seal_receipt(document: Mapping[str, Any]) -> None:
    checksum = document.get("receipt_sha256")
    payload = {key: value for key, value in document.items() if key != "receipt_sha256"}
    semantic = document.get("semantic_binding")
    gold = document.get("gold")
    if (
        document.get("schema_version") != SEAL_VERSION
        or document.get("status") != "SEALED"
        or document.get("target_project") != TARGET_PROJECT
        or document.get("content_notice") != SYNTHETIC_NOTICE
        or document.get("historical_evidence_mixed") is not False
        or document.get("skipped_evidence_count") != 0
        or not isinstance(semantic, Mapping)
        or semantic.get("schema_version") != BINDING_VERSION
        or semantic.get("core_exact") is not True
        or semantic.get("approved_core_sha256")
        != semantic.get("runtime_core_sha256")
        or not isinstance(gold, Mapping)
        or gold.get("status") != "VALID_SEALED_GOLD"
        or gold.get("scorable") is not True
        or not isinstance(checksum, str)
        or checksum != canonical_sha256(payload)
    ):
        raise Phase10P0ReleaseSealError("Phase 10 P0 release seal receipt differs")


def _write_bundle(payloads: Mapping[Path, bytes]) -> None:
    OUTPUT_DIRECTORY.mkdir(parents=True, exist_ok=True)
    unexpected = {item.name for item in OUTPUT_DIRECTORY.iterdir()} - OUTPUT_FILES
    if unexpected:
        raise Phase10P0ReleaseSealError(
            "P0 seal output directory contains an unrelated file"
        )
    staged: list[tuple[Path, Path]] = []
    try:
        for path, payload in payloads.items():
            temporary = path.with_suffix(path.suffix + ".tmp")
            temporary.write_bytes(payload)
            staged.append((temporary, path))
        for temporary, path in staged:
            os.replace(temporary, path)
    finally:
        for temporary, _path in staged:
            temporary.unlink(missing_ok=True)


def run(args: argparse.Namespace) -> dict[str, Any]:
    url = validate_boundary(args)
    semantic = _load_json(SEMANTIC_PATH)
    repository_manifest = _load_json(GOLD_MANIFEST_PATH)
    case_payload, cases = _load_cases(GOLD_CASE_PATH)
    case_sha256 = hashlib.sha256(case_payload).hexdigest()
    draft = validate_manifest(
        repository_manifest,
        cases,
        semantic,
        observed_case_content_sha256=case_sha256,
    )
    sql_evidence = build_draft(
        SQL_DIRECTORY,
        str(semantic.get("serving_schema") or ""),
        str(semantic.get("release_id") or ""),
    )
    semantic_validation = validate_metric_review(semantic, sql_evidence)
    if (
        draft["status"] != "VALID_DRAFT"
        or draft["review_counts"] != {"APPROVED": 55}
        or draft["unsealed_result_count"] != 0
        or draft["scorable"] is not False
        or semantic_validation["status"] != "VALID_APPROVED_REVIEW"
        or semantic_validation["business_metric_count"] != 10
        or semantic_validation["support_metric_count"] != 4
    ):
        raise Phase10P0ReleaseSealError("approved P0 source validation differs")

    generation, product, projection, phase9 = _load_release_state(url)
    current_source, _created_at = _source_receipt()
    if product.evidence.source != current_source:
        raise Phase10P0ReleaseSealError(
            "current source differs from the active Phase 10 release"
        )
    data_release_id = str(semantic["release_id"])
    if not (
        projection.catalog_release_id == data_release_id
        or projection.catalog_release_id.startswith(f"{data_release_id}-")
    ):
        raise Phase10P0ReleaseSealError(
            "approved semantic and runtime data release lineage differs"
        )
    binding = semantic_runtime_binding(semantic, projection.release.as_bundle())
    sealed_manifest = _sealed_manifest(
        repository_manifest,
        semantic_release_id=projection.catalog_release_id,
        product_release_id=product.product_release_id,
    )
    sealed_validation = validate_manifest(
        sealed_manifest,
        cases,
        semantic,
        observed_case_content_sha256=case_sha256,
    )
    if sealed_validation["status"] != "VALID_SEALED_GOLD":
        raise Phase10P0ReleaseSealError("P0 Gold external seal validation differs")

    semantic_payload = SEMANTIC_PATH.read_bytes()
    receipt = _receipt(
        generation=generation,
        product=product,
        projection=projection,
        phase9=phase9,
        current_source=current_source,
        semantic=semantic,
        semantic_file_sha256=hashlib.sha256(semantic_payload).hexdigest(),
        cases=cases,
        case_sha256=case_sha256,
        sealed_validation=sealed_validation,
        binding=binding,
    )
    json_payload = lambda value: (  # noqa: E731 - local canonical writer
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")
    _write_bundle(
        {
            OUTPUT_MANIFEST: json_payload(sealed_manifest),
            OUTPUT_CASES: case_payload,
            OUTPUT_SEMANTIC: semantic_payload,
            OUTPUT_RECEIPT: json_payload(receipt),
        }
    )
    return {
        "status": "PHASE10_P0_RELEASE_SEALED",
        "target_project": TARGET_PROJECT,
        "active_generation": generation,
        "product_release_id": product.product_release_id,
        "semantic_release_id": projection.catalog_release_id,
        "semantic_binding_mode": binding["capability_extension"]["mode"],
        "gold_manifest_sha256": sealed_validation["manifest_sha256"],
        "gold_case_count": 55,
        "receipt_sha256": receipt["receipt_sha256"],
        "output_directory": OUTPUT_DIRECTORY.relative_to(ROOT).as_posix(),
    }


def main(argv: list[str] | None = None) -> int:
    try:
        result = run(parse_args(argv))
    except (OSError, RuntimeError, ValueError, psycopg.Error) as error:
        message = (
            str(error)
            if isinstance(error, Phase10P0ReleaseSealError)
            else "Phase 10 P0 release seal operation failed"
        )
        print(
            json.dumps(
                {"status": "PHASE10_P0_RELEASE_SEAL_ERROR", "error": message},
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
