"""검증된 DataHub snapshot을 DB에 저장 가능한 immutable runtime projection으로 봉인한다.

질문 runtime은 이 문서에서 ``CatalogSnapshot``을 복원한다. 전체 DataHub Scroll·aspect
read-back은 out-of-band compiler만 수행하며, native Metric이 지원된 BUSINESS 범위와
아직 Dataset custom-property migration source를 쓰는 범위를 source-selection manifest에
명시적으로 분리한다.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any

from app.adapters.catalog_snapshot import CatalogSnapshot
from app.adapters.datahub_metadata_types import (
    GlossaryDimensionMemberTerm,
    GlossaryMetricTerm,
    GovernedDataset,
)
from app.adapters.datahub_metadata_values import GovernedMetadataError
from app.adapters.legacy_semantic_release import compile_legacy_semantic_release
from app.services.context.semantic_release import CanonicalSemanticRelease
from src.data.governance_contract import canonical_json, canonical_sha256


RUNTIME_CATALOG_PROJECTION_VERSION = "RuntimeCatalogProjection.v1"
RUNTIME_CATALOG_SOURCE_SELECTION_VERSION = "RuntimeCatalogSourceSelection.v1"

NATIVE_PRIORITY = "NATIVE_PRIORITY"
LEGACY_SHADOW = "LEGACY_SHADOW"

DATAHUB_NATIVE_METRIC_SOURCE = "DATAHUB_NATIVE_METRIC_V1"
DATAHUB_GLOSSARY_MIGRATION_SOURCE = "DATAHUB_GLOSSARY_MIGRATION_V1"
DATAHUB_DATASET_MIGRATION_SOURCE = "DATAHUB_DATASET_RUNTIME_MIGRATION_V2"

_SOURCE_TOP_LEVEL_KEYS = frozenset(
    {
        "schema_version",
        "authority_mode",
        "catalog_release_id",
        "catalog_sha256",
        "canonical_sha256",
        "native_projection_sha256",
        "native_membership_sha256",
        "sections",
        "metrics",
    }
)
_SOURCE_SECTION_KEYS = frozenset(
    {
        "dataset_schema",
        "governance",
        "business_metric",
        "support_metric",
        "dimensions_join_time_policy",
    }
)
_SOURCE_METRIC_KEYS = frozenset(
    {"metric_id", "visibility", "source", "source_urns", "aspect_checksums"}
)
_NATIVE_RECORD_KEYS = frozenset({"urn", "metricInfo", "aiContext", "status"})
_TRINO_FINGERPRINT_KEYS = frozenset(
    {"fqn", "table_type", "column_count", "relation_sha256"}
)
_PROJECTION_PAYLOAD_KEYS = frozenset(
    {
        "schema_version",
        "catalog_release_id",
        "catalog_sha256",
        "canonical_sha256",
        "manifest_sha256",
        "membership_sha256",
        "source_selection_sha256",
        "trino_fingerprint_sha256",
        "source_selection",
        "trino_fingerprints",
        "snapshot",
    }
)
_PROJECTION_DOCUMENT_KEYS = _PROJECTION_PAYLOAD_KEYS | {
    "projection_id",
    "projection_sha256",
}


class RuntimeCatalogProjectionError(ValueError):
    """Projection의 source, membership 또는 checksum이 완결되지 않았음을 나타낸다."""


@dataclass(frozen=True)
class RuntimeCatalogProjection:
    """DB와 runtime 사이에서 전달하는 checksum-bound projection과 typed snapshot이다."""

    projection_id: str
    projection_sha256: str
    catalog_release_id: str
    catalog_sha256: str
    canonical_sha256: str
    manifest_sha256: str
    membership_sha256: str
    source_selection_sha256: str
    trino_fingerprint_sha256: str
    source_selection: dict[str, Any]
    trino_fingerprints: tuple[dict[str, Any], ...]
    snapshot: CatalogSnapshot
    release: CanonicalSemanticRelease
    _document_json: str

    def as_document(self) -> dict[str, Any]:
        """내부 snapshot을 공유하지 않는 canonical JSON 문서 복사본을 반환한다."""

        value = json.loads(self._document_json)
        if not isinstance(value, dict):  # pragma: no cover - 생성자가 보장한다.
            raise RuntimeCatalogProjectionError("runtime projection document is unavailable")
        return value

    def matches_snapshot(self, snapshot: CatalogSnapshot) -> bool:
        """Live snapshot이 projection에 봉인된 canonical 문서와 정확히 같은지 판정한다."""

        return self.as_document()["snapshot"] == _serialize_snapshot(snapshot)

    @classmethod
    def compile(
        cls,
        snapshot: CatalogSnapshot,
        release: CanonicalSemanticRelease,
        *,
        source_selection: Mapping[str, Any],
        trino_fingerprints: tuple[Mapping[str, Any], ...],
    ) -> "RuntimeCatalogProjection":
        """Live 검증이 끝난 snapshot·Trino receipt를 하나의 immutable 문서로 봉인한다."""

        _validate_snapshot_release(snapshot, release)
        selection = _validated_source_selection(source_selection, release)
        fingerprints = _validated_trino_fingerprints(
            trino_fingerprints,
            snapshot,
            release,
        )
        serialized_snapshot = _serialize_snapshot(snapshot)
        membership = _membership_projection(snapshot, selection)
        payload = {
            "schema_version": RUNTIME_CATALOG_PROJECTION_VERSION,
            "catalog_release_id": release.catalog_version,
            "catalog_sha256": release.catalog_checksum,
            "canonical_sha256": release.canonical_checksum,
            "manifest_sha256": release.manifest_checksum,
            "membership_sha256": canonical_sha256(membership),
            "source_selection_sha256": canonical_sha256(selection),
            "trino_fingerprint_sha256": canonical_sha256(fingerprints),
            "source_selection": selection,
            "trino_fingerprints": fingerprints,
            "snapshot": serialized_snapshot,
        }
        if set(payload) != _PROJECTION_PAYLOAD_KEYS:  # pragma: no cover
            raise AssertionError("runtime projection payload construction drifted")
        projection_sha256 = canonical_sha256(payload)
        projection_id = f"runtime-catalog:{projection_sha256}"
        document = {
            **payload,
            "projection_id": projection_id,
            "projection_sha256": projection_sha256,
        }
        return cls.from_document(document)

    @classmethod
    def from_document(
        cls,
        document: Mapping[str, Any],
        *,
        expected_projection_sha256: str | None = None,
    ) -> "RuntimeCatalogProjection":
        """DB JSON을 checksum부터 검증한 뒤 typed snapshot·release로 복원한다."""

        if not isinstance(document, Mapping) or set(document) != _PROJECTION_DOCUMENT_KEYS:
            raise RuntimeCatalogProjectionError("runtime projection document fields differ")
        detached = json.loads(canonical_json(document))
        projection_sha256 = _sha256(
            detached["projection_sha256"], "projection checksum"
        )
        payload = {key: detached[key] for key in _PROJECTION_PAYLOAD_KEYS}
        if canonical_sha256(payload) != projection_sha256:
            raise RuntimeCatalogProjectionError("runtime projection checksum differs")
        if expected_projection_sha256 is not None and projection_sha256 != _sha256(
            expected_projection_sha256, "expected projection checksum"
        ):
            raise RuntimeCatalogProjectionError("active projection pointer checksum differs")
        if detached["projection_id"] != f"runtime-catalog:{projection_sha256}":
            raise RuntimeCatalogProjectionError("runtime projection ID differs")
        if detached["schema_version"] != RUNTIME_CATALOG_PROJECTION_VERSION:
            raise RuntimeCatalogProjectionError("runtime projection version is unsupported")

        snapshot = _deserialize_snapshot(detached["snapshot"])
        try:
            release = compile_legacy_semantic_release(
                snapshot,
                str(detached["catalog_release_id"]),
            )
        except (GovernedMetadataError, TypeError, ValueError) as error:
            raise RuntimeCatalogProjectionError(
                "runtime projection snapshot cannot compile"
            ) from error
        if (
            release.catalog_checksum != detached["catalog_sha256"]
            or release.canonical_checksum != detached["canonical_sha256"]
            or release.manifest_checksum != detached["manifest_sha256"]
        ):
            raise RuntimeCatalogProjectionError("runtime projection release identity differs")
        selection = _validated_source_selection(detached["source_selection"], release)
        fingerprints = _validated_trino_fingerprints(
            tuple(detached["trino_fingerprints"]), snapshot, release
        )
        if (
            canonical_sha256(selection) != detached["source_selection_sha256"]
            or canonical_sha256(fingerprints) != detached["trino_fingerprint_sha256"]
            or canonical_sha256(_membership_projection(snapshot, selection))
            != detached["membership_sha256"]
        ):
            raise RuntimeCatalogProjectionError("runtime projection receipt differs")
        return cls(
            projection_id=str(detached["projection_id"]),
            projection_sha256=projection_sha256,
            catalog_release_id=release.catalog_version,
            catalog_sha256=release.catalog_checksum,
            canonical_sha256=release.canonical_checksum,
            manifest_sha256=release.manifest_checksum,
            membership_sha256=str(detached["membership_sha256"]),
            source_selection_sha256=str(detached["source_selection_sha256"]),
            trino_fingerprint_sha256=str(detached["trino_fingerprint_sha256"]),
            source_selection=selection,
            trino_fingerprints=tuple(fingerprints),
            snapshot=snapshot,
            release=release,
            _document_json=canonical_json(detached),
        )


def build_source_selection_manifest(
    release: CanonicalSemanticRelease,
    *,
    authority_mode: str,
    native_records: Mapping[str, Mapping[str, Any]] | None = None,
    native_projection_sha256: str | None = None,
    native_membership_sha256: str | None = None,
) -> dict[str, Any]:
    """Metric별 native/migration source를 숨김없이 선언하고 aspect checksum으로 봉인한다."""

    if authority_mode not in {NATIVE_PRIORITY, LEGACY_SHADOW}:
        raise RuntimeCatalogProjectionError("runtime source authority mode is invalid")
    bundle = release.as_bundle()
    rules = {str(item["id"]): item for item in bundle["metric_rules"]}
    terms = {str(item["id"]): item for item in bundle["metric_terms"]}
    assets = {str(item["fqn"]): item for item in bundle["schema_context"]["assets"]}
    business_ids = {item.id for item in release.metrics if item.visibility == "BUSINESS"}
    support_ids = set(rules) - business_ids
    if set(terms) != business_ids:
        raise RuntimeCatalogProjectionError("BUSINESS Metric and Glossary membership differ")
    records = dict(native_records or {})
    if authority_mode == NATIVE_PRIORITY:
        if set(records) != business_ids:
            raise RuntimeCatalogProjectionError("native Metric record membership differs")
        native_projection = _sha256(native_projection_sha256, "native projection checksum")
        native_membership = _sha256(native_membership_sha256, "native membership checksum")
    else:
        if records or native_projection_sha256 is not None or native_membership_sha256 is not None:
            raise RuntimeCatalogProjectionError("legacy shadow cannot claim native receipts")
        native_projection = None
        native_membership = None

    metrics: list[dict[str, Any]] = []
    for metric_id in sorted(rules):
        rule = rules[metric_id]
        visibility = "BUSINESS" if metric_id in business_ids else "SUPPORT"
        source_assets = _metric_source_assets(release, metric_id)
        source_urns = [str(assets[fqn]["urn"]) for fqn in source_assets]
        if visibility == "BUSINESS" and authority_mode == NATIVE_PRIORITY:
            record = _validated_native_record(records[metric_id], terms[metric_id])
            source = DATAHUB_NATIVE_METRIC_SOURCE
            source_urns = [str(record["urn"])]
            checksums = {
                name: canonical_sha256(record[name])
                for name in ("metricInfo", "aiContext", "status")
            }
        elif visibility == "BUSINESS":
            source = DATAHUB_GLOSSARY_MIGRATION_SOURCE
            source_urns = [str(terms[metric_id]["urn"])]
            checksums = {
                "metric_rule": canonical_sha256(rule),
                "glossary_term": canonical_sha256(terms[metric_id]),
            }
        else:
            source = DATAHUB_DATASET_MIGRATION_SOURCE
            checksums = {"metric_rule": canonical_sha256(rule)}
        metrics.append(
            {
                "metric_id": metric_id,
                "visibility": visibility,
                "source": source,
                "source_urns": sorted(source_urns),
                "aspect_checksums": dict(sorted(checksums.items())),
            }
        )
    sections = {
        "dataset_schema": "DATAHUB_NATIVE_DATASET_SCHEMA",
        "governance": "DATAHUB_NATIVE_GOVERNANCE",
        "business_metric": (
            DATAHUB_NATIVE_METRIC_SOURCE
            if authority_mode == NATIVE_PRIORITY
            else DATAHUB_GLOSSARY_MIGRATION_SOURCE
        ),
        "support_metric": DATAHUB_DATASET_MIGRATION_SOURCE,
        "dimensions_join_time_policy": DATAHUB_DATASET_MIGRATION_SOURCE,
    }
    return {
        "schema_version": RUNTIME_CATALOG_SOURCE_SELECTION_VERSION,
        "authority_mode": authority_mode,
        "catalog_release_id": release.catalog_version,
        "catalog_sha256": release.catalog_checksum,
        "canonical_sha256": release.canonical_checksum,
        "native_projection_sha256": native_projection,
        "native_membership_sha256": native_membership,
        "sections": sections,
        "metrics": metrics,
    }


def _validated_source_selection(
    value: Mapping[str, Any],
    release: CanonicalSemanticRelease,
) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _SOURCE_TOP_LEVEL_KEYS:
        raise RuntimeCatalogProjectionError("source-selection manifest fields differ")
    detached = json.loads(canonical_json(value))
    if (
        detached["schema_version"] != RUNTIME_CATALOG_SOURCE_SELECTION_VERSION
        or detached["authority_mode"] not in {NATIVE_PRIORITY, LEGACY_SHADOW}
        or detached["catalog_release_id"] != release.catalog_version
        or detached["catalog_sha256"] != release.catalog_checksum
        or detached["canonical_sha256"] != release.canonical_checksum
        or not isinstance(detached["sections"], dict)
        or set(detached["sections"]) != _SOURCE_SECTION_KEYS
        or not isinstance(detached["metrics"], list)
    ):
        raise RuntimeCatalogProjectionError("source-selection identity differs")
    candidate = detached["authority_mode"] == NATIVE_PRIORITY
    if candidate:
        _sha256(detached["native_projection_sha256"], "native projection checksum")
        _sha256(detached["native_membership_sha256"], "native membership checksum")
    elif (
        detached["native_projection_sha256"] is not None
        or detached["native_membership_sha256"] is not None
    ):
        raise RuntimeCatalogProjectionError("legacy source-selection claims native receipts")
    expected_ids = {item.id: item.visibility for item in release.metrics}
    observed: dict[str, Mapping[str, Any]] = {}
    for item in detached["metrics"]:
        if not isinstance(item, Mapping) or set(item) != _SOURCE_METRIC_KEYS:
            raise RuntimeCatalogProjectionError("source-selection Metric fields differ")
        metric_id = item["metric_id"]
        if not isinstance(metric_id, str) or metric_id in observed:
            raise RuntimeCatalogProjectionError("source-selection Metric IDs are invalid")
        observed[metric_id] = item
        expected_visibility = expected_ids.get(metric_id)
        expected_source = (
            DATAHUB_NATIVE_METRIC_SOURCE
            if candidate and expected_visibility == "BUSINESS"
            else DATAHUB_GLOSSARY_MIGRATION_SOURCE
            if expected_visibility == "BUSINESS"
            else DATAHUB_DATASET_MIGRATION_SOURCE
        )
        if (
            item["visibility"] != expected_visibility
            or item["source"] != expected_source
            or not isinstance(item["source_urns"], list)
            or not item["source_urns"]
            or len(item["source_urns"]) != len(set(item["source_urns"]))
            or any(
                not isinstance(urn, str) or not urn.startswith("urn:li:")
                for urn in item["source_urns"]
            )
            or not isinstance(item["aspect_checksums"], dict)
            or not item["aspect_checksums"]
        ):
            raise RuntimeCatalogProjectionError("source-selection Metric receipt differs")
        for checksum in item["aspect_checksums"].values():
            _sha256(checksum, "source aspect checksum")
    if set(observed) != set(expected_ids):
        raise RuntimeCatalogProjectionError("source-selection Metric membership differs")
    if detached["sections"] != {
        "dataset_schema": "DATAHUB_NATIVE_DATASET_SCHEMA",
        "governance": "DATAHUB_NATIVE_GOVERNANCE",
        "business_metric": (
            DATAHUB_NATIVE_METRIC_SOURCE
            if candidate
            else DATAHUB_GLOSSARY_MIGRATION_SOURCE
        ),
        "support_metric": DATAHUB_DATASET_MIGRATION_SOURCE,
        "dimensions_join_time_policy": DATAHUB_DATASET_MIGRATION_SOURCE,
    }:
        raise RuntimeCatalogProjectionError("source-selection section policy differs")
    return detached


def _validated_native_record(
    record: Mapping[str, Any],
    term: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(record, Mapping) or set(record) != _NATIVE_RECORD_KEYS:
        raise RuntimeCatalogProjectionError("native Metric record fields differ")
    detached = json.loads(canonical_json(record))
    info, context, status = (
        detached["metricInfo"],
        detached["aiContext"],
        detached["status"],
    )
    expression = info.get("expression") if isinstance(info, dict) else None
    dialects = expression.get("dialects") if isinstance(expression, dict) else None
    if (
        not isinstance(detached["urn"], str)
        or not detached["urn"].startswith("urn:li:metric:")
        or not isinstance(info, dict)
        or set(info) != {"name", "description", "expression"}
        or info["name"] != term["name"]
        or info["description"] != term["definition"]
        or not isinstance(dialects, list)
        or len(dialects) != 1
        or not isinstance(dialects[0], dict)
        or set(dialects[0]) != {"dialect", "expression"}
        or dialects[0]["dialect"] != "ANSI_SQL"
        or not isinstance(dialects[0]["expression"], str)
        or not dialects[0]["expression"].strip()
        or context != {"synonyms": term["aliases"]}
        or status != {"removed": False}
    ):
        raise RuntimeCatalogProjectionError("native Metric record differs from Glossary source")
    return detached


def _validated_trino_fingerprints(
    values: tuple[Mapping[str, Any], ...],
    snapshot: CatalogSnapshot,
    release: CanonicalSemanticRelease,
) -> list[dict[str, Any]]:
    if not isinstance(values, tuple):
        raise RuntimeCatalogProjectionError("Trino fingerprints must be a tuple")
    expected = {asset.fqn: asset for asset in release.assets}
    datasets = snapshot.datasets_by_fqn
    observed: dict[str, dict[str, Any]] = {}
    for item in values:
        if not isinstance(item, Mapping) or set(item) != _TRINO_FINGERPRINT_KEYS:
            raise RuntimeCatalogProjectionError("Trino fingerprint fields differ")
        detached = json.loads(canonical_json(item))
        fqn = detached["fqn"]
        asset, dataset = expected.get(fqn), datasets.get(fqn)
        if (
            not isinstance(fqn, str)
            or fqn in observed
            or asset is None
            or dataset is None
            or detached["table_type"] != dataset.table_type
            or detached["column_count"] != len(dataset.trino_schema_columns)
            or detached["relation_sha256"] != dataset.trino_schema_checksum
        ):
            raise RuntimeCatalogProjectionError("Trino fingerprint differs from DataHub")
        _sha256(detached["relation_sha256"], "Trino relation checksum")
        observed[fqn] = detached
    if set(observed) != set(expected):
        raise RuntimeCatalogProjectionError("Trino fingerprint membership differs")
    return [observed[fqn] for fqn in sorted(observed)]


def _validate_snapshot_release(
    snapshot: CatalogSnapshot,
    release: CanonicalSemanticRelease,
) -> None:
    try:
        compiled = compile_legacy_semantic_release(snapshot, release.catalog_version)
    except (GovernedMetadataError, TypeError, ValueError) as error:
        raise RuntimeCatalogProjectionError("runtime snapshot cannot compile") from error
    if (
        compiled.catalog_checksum != release.catalog_checksum
        or compiled.canonical_checksum != release.canonical_checksum
        or compiled.manifest_checksum != release.manifest_checksum
    ):
        raise RuntimeCatalogProjectionError("runtime snapshot and release differ")


def _serialize_snapshot(snapshot: CatalogSnapshot) -> dict[str, Any]:
    result = {
        "datasets": [
            _json_safe(asdict(item))
            for item in sorted(snapshot.datasets_by_urn.values(), key=lambda row: row.urn)
        ],
        "terms": [
            _json_safe(asdict(item))
            for item in sorted(snapshot.terms_by_urn.values(), key=lambda row: row.urn)
        ],
        "governance_entities": {
            name: [_json_safe(item) for item in values]
            for name, values in sorted(snapshot.governance_entities.items())
        },
    }
    if snapshot.dimension_member_terms_by_urn:
        result["dimension_member_terms"] = [
            _json_safe(asdict(item))
            for item in sorted(
                snapshot.dimension_member_terms_by_urn.values(),
                key=lambda row: row.urn,
            )
        ]
    return result


def _deserialize_snapshot(value: object) -> CatalogSnapshot:
    base_keys = {"datasets", "terms", "governance_entities"}
    if not isinstance(value, Mapping) or set(value) not in {
        frozenset(base_keys),
        frozenset(base_keys | {"dimension_member_terms"}),
    }:
        raise RuntimeCatalogProjectionError("runtime snapshot fields differ")
    raw_datasets, raw_terms, raw_governance = (
        value["datasets"],
        value["terms"],
        value["governance_entities"],
    )
    if (
        not isinstance(raw_datasets, list)
        or not isinstance(raw_terms, list)
        or not isinstance(raw_governance, Mapping)
    ):
        raise RuntimeCatalogProjectionError("runtime snapshot collections are invalid")
    try:
        datasets = tuple(_dataset_from_json(item) for item in raw_datasets)
        terms = tuple(_term_from_json(item) for item in raw_terms)
        governance = {
            str(name): tuple(dict(item) for item in values)
            for name, values in raw_governance.items()
        }
        members = tuple(
            _dimension_member_term_from_json(item)
            for item in value.get("dimension_member_terms", ())
        )
    except (TypeError, ValueError, KeyError) as error:
        raise RuntimeCatalogProjectionError("runtime snapshot values are invalid") from error
    return CatalogSnapshot(
        datasets_by_urn=_unique_objects(datasets, "urn"),
        datasets_by_fqn=_unique_objects(datasets, "fqn"),
        terms_by_urn=_unique_objects(terms, "urn"),
        terms_by_id=_unique_objects(terms, "id"),
        governance_entities=governance,
        dimension_member_terms_by_urn=_optional_unique_objects(members, "urn"),
    )


def _dataset_from_json(value: object) -> GovernedDataset:
    if not isinstance(value, Mapping):
        raise RuntimeCatalogProjectionError("runtime dataset projection is invalid")
    data = dict(value)
    for name in ("allowed_roles", "allowed_domains", "dataset_terms", "owner_urns"):
        data[name] = frozenset(data[name])
    for name in (
        "trino_schema_columns",
        "columns",
        "metric_rules",
        "dimensions",
    ):
        data[name] = tuple(dict(item) for item in data[name])
    data["metrics"] = tuple(_runtime_metric_from_json(item) for item in data["metrics"])
    data["field_terms"] = {
        str(name): frozenset(urns) for name, urns in data["field_terms"].items()
    }
    return GovernedDataset(**data)


def _runtime_metric_from_json(value: object) -> dict[str, Any]:
    """JSON이 지운 runtime Metric의 tuple 경계를 production parser와 같게 복원한다."""

    if not isinstance(value, Mapping):
        raise RuntimeCatalogProjectionError("runtime Metric projection is invalid")
    metric = dict(value)
    for name in ("allowed_roles", "allowed_join_ids", "query_strategies"):
        values = metric.get(name)
        if not isinstance(values, list):
            raise RuntimeCatalogProjectionError("runtime Metric policy is invalid")
        metric[name] = tuple(values)
    for name in ("dimensions", "required_filters"):
        values = metric.get(name)
        if not isinstance(values, list) or any(
            not isinstance(item, Mapping) for item in values
        ):
            raise RuntimeCatalogProjectionError("runtime Metric scope is invalid")
        metric[name] = tuple(dict(item) for item in values)
    return metric


def _term_from_json(value: object) -> GlossaryMetricTerm:
    if not isinstance(value, Mapping):
        raise RuntimeCatalogProjectionError("runtime term projection is invalid")
    data = dict(value)
    data["aliases"] = tuple(data["aliases"])
    data["owner_urns"] = frozenset(data["owner_urns"])
    return GlossaryMetricTerm(**data)


def _dimension_member_term_from_json(
    value: object,
) -> GlossaryDimensionMemberTerm:
    if not isinstance(value, Mapping):
        raise RuntimeCatalogProjectionError(
            "runtime dimension member term projection is invalid"
        )
    data = dict(value)
    data["aliases"] = tuple(data["aliases"])
    data["owner_urns"] = frozenset(data["owner_urns"])
    return GlossaryDimensionMemberTerm(**data)


def _membership_projection(
    snapshot: CatalogSnapshot,
    selection: Mapping[str, Any],
) -> dict[str, Any]:
    native_urns = sorted(
        urn
        for item in selection["metrics"]
        if item["source"] == DATAHUB_NATIVE_METRIC_SOURCE
        for urn in item["source_urns"]
    )
    result = {
        "dataset_urns": sorted(snapshot.datasets_by_urn),
        "glossary_term_urns": sorted(snapshot.terms_by_urn),
        "native_metric_urns": native_urns,
    }
    if snapshot.dimension_member_terms_by_urn:
        result["dimension_member_term_urns"] = sorted(
            snapshot.dimension_member_terms_by_urn
        )
    return result


def _metric_source_assets(
    release: CanonicalSemanticRelease,
    metric_id: str,
) -> tuple[str, ...]:
    metric = release.metric(metric_id)
    if metric is None or not metric.source_assets:
        raise RuntimeCatalogProjectionError("Metric source asset is unavailable")
    return metric.source_assets


def _unique_objects(values: tuple[Any, ...], attribute: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for value in values:
        key = getattr(value, attribute)
        if not isinstance(key, str) or not key or key in result:
            raise RuntimeCatalogProjectionError("runtime projection identity is duplicate")
        result[key] = value
    if not result:
        raise RuntimeCatalogProjectionError("runtime projection membership is empty")
    return result


def _optional_unique_objects(
    values: tuple[Any, ...],
    attribute: str,
) -> dict[str, Any]:
    if not values:
        return {}
    return _unique_objects(values, attribute)


def _json_safe(value: object) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in sorted(value.items())}
    if isinstance(value, (set, frozenset)):
        return [_json_safe(item) for item in sorted(value)]
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise RuntimeCatalogProjectionError("runtime projection contains a non-JSON value")


def _sha256(value: object, context: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise RuntimeCatalogProjectionError(f"{context} is invalid")
    return value
