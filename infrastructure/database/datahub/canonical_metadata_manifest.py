"""분할된 Git metadata manifest를 하나의 checksum-bound P0 계약으로 읽는다."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator
from sqlglot import exp, parse
from sqlglot.errors import ParseError

from src.data.governance_contract import canonical_json, canonical_sha256


SCHEMA_VERSION = "answervice.canonical-metadata.v1"
REVIEW_REQUIRED = "REVIEW_REQUIRED"
_MAX_FILE_BYTES = 8_000_000
_DATASET_SCOPES = ("pms", "pos", "crm", "banquet", "facility", "serving")
_STABLE_ID_VERSION = re.compile(
    r"(?:^|[._-])v\d+(?:[._-]\d+)+|20\d{6}", re.IGNORECASE
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class CanonicalMetadataManifest:
    """검증된 manifest의 JSON 복사본·inventory·review 차단 사유를 보존한다."""

    content_sha256: str
    inventory: dict[str, int]
    review_required: tuple[str, ...]
    _document_json: str

    @property
    def status(self) -> str:
        """미해결 검토 항목이 하나라도 있으면 READY 대신 REVIEW_REQUIRED를 반환한다."""

        return REVIEW_REQUIRED if self.review_required else "READY"

    def as_document(self) -> dict[str, Any]:
        """검증 때 봉인한 JSON을 새 사본으로 복원하고 객체 형태가 아니면 거부한다."""

        value = json.loads(self._document_json)
        if not isinstance(value, dict):  # pragma: no cover - 생성자가 보장한다.
            raise ValueError("canonical metadata manifest is unavailable")
        return value


def load_canonical_metadata_manifest(root: Path) -> CanonicalMetadataManifest:
    """고정된 10개 YAML 파일만 읽어 단일 canonical document로 병합한다."""

    directory = root.resolve(strict=True)
    if not directory.is_dir():
        raise ValueError("canonical metadata root must be a directory")
    expected_root = {
        "schema.json",
        "domains.yml",
        "glossary.yml",
        "semantics.yml",
        "quality.yml",
        "datasets",
    }
    if {item.name for item in directory.iterdir()} != expected_root:
        raise ValueError("canonical metadata root files differ")
    dataset_dir = directory / "datasets"
    expected_datasets = {f"{scope}.yml" for scope in _DATASET_SCOPES}
    if (
        not dataset_dir.is_dir()
        or {item.name for item in dataset_dir.iterdir()} != expected_datasets
    ):
        raise ValueError("canonical metadata dataset files differ")

    schema = _json_file(directory / "schema.json")
    domains = _yaml_file(directory / "domains.yml")
    glossary = _yaml_file(directory / "glossary.yml")
    semantics = _yaml_file(directory / "semantics.yml")
    quality = _yaml_file(directory / "quality.yml")
    dataset_documents = [
        _yaml_file(dataset_dir / f"{scope}.yml") for scope in _DATASET_SCOPES
    ]
    versioned = [domains, glossary, semantics, quality, *dataset_documents]
    if any(item.get("schema_version") != SCHEMA_VERSION for item in versioned):
        raise ValueError("canonical metadata file schema versions differ")
    datasets: list[dict[str, Any]] = []
    for scope, document in zip(_DATASET_SCOPES, dataset_documents, strict=True):
        if document.get("source_scope") != scope:
            raise ValueError("canonical metadata dataset source scope differs")
        values = document.get("datasets")
        if not isinstance(values, list) or any(
            not isinstance(item, dict) for item in values
        ):
            raise ValueError("canonical metadata datasets must be objects")
        if any(item.get("source_system") != scope.upper() for item in values):
            raise ValueError("canonical metadata source system differs from its file")
        datasets.extend(values)

    document = {
        "schema_version": SCHEMA_VERSION,
        "schema_sha256": canonical_sha256(schema),
        "source": domains.get("source"),
        "domains": domains.get("domains"),
        "owner_groups": domains.get("owner_groups"),
        "lifecycles": domains.get("lifecycles"),
        "datasets": datasets,
        "glossary_terms": glossary.get("glossary_terms"),
        "authoring": semantics.get("authoring"),
        "metrics": semantics.get("metrics"),
        "dimensions": semantics.get("dimensions"),
        "join_graph": semantics.get("join_graph"),
        "time_rules": semantics.get("time_rules"),
        "parameter_contract": semantics.get("parameter_contract"),
        "query_policy": semantics.get("query_policy"),
        "quality_policies": quality.get("quality_policies"),
    }
    return validate_canonical_metadata_document(
        document, schema_document=schema
    )


def compile_semantic_authoring_policy(
    manifest: CanonicalMetadataManifest,
) -> dict[str, Any]:
    """검토 완료 canonical manifest를 기존 semantic authoring 입력으로 변환한다.

    Dataset identity와 물리 type/nullability는 포함하지 않는다. 기존 authoring
    단계가 동일하게 live DataHub·Trino에서 다시 결합하므로 Git manifest가 runtime
    projection을 우회하거나 물리 schema를 고정하는 경로가 되지 않는다.
    """

    if manifest.status != "READY":
        raise ValueError("canonical metadata manifest is not ready for authoring")
    document = manifest.as_document()
    authoring = document["authoring"]
    metrics = {
        str(item["metric_id"]): item for item in document["metrics"]
    }
    glossary = {
        str(item["term_id"]): item
        for item in document["glossary_terms"]
        if item["kind"] == "BUSINESS_METRIC"
    }
    business_ids = {
        metric_id
        for metric_id, metric in metrics.items()
        if metric["visibility"] == "BUSINESS"
    }
    if set(glossary) != business_ids:
        raise ValueError(
            "canonical business Glossary membership differs from Business Metrics"
        )

    metric_terms = []
    metric_rules = []
    for metric_id in sorted(metrics):
        metric = metrics[metric_id]
        rule = _detached(metric["runtime_rule"])
        metric_rules.append(rule)
        if metric_id not in business_ids:
            continue
        term = glossary[metric_id]
        governance = rule.get("governance")
        semantic = governance.get("semantic") if isinstance(governance, dict) else None
        if not isinstance(semantic, dict):
            raise ValueError("canonical Business Metric semantic contract is missing")
        aliases = semantic.get("aliases")
        if (
            metric.get("term_urn") != term["urn"]
            or semantic.get("name") != term["korean_name"]
            or semantic.get("definition") != term["definition"]
            or not isinstance(aliases, list)
            or set(map(str, aliases)) != set(map(str, term["aliases"]))
            or metric.get("owner_group_urn") != term["owner_group_urn"]
        ):
            raise ValueError(
                "canonical Business Metric and Glossary semantics differ"
            )
        metric_terms.append(
            {
                "id": metric_id,
                "urn": term["urn"],
                "name": semantic["name"],
                "definition": semantic["definition"],
                "aliases": _detached(aliases),
                "unit": metric["unit"],
                "version": authoring["glossary_version"],
                "approval_status": "APPROVED",
                "owner_urn": term["owner_group_urn"],
                "domain_urn": term["domain_urn"],
                "approved_lifecycle_urn": term["lifecycle_urn"],
            }
        )

    assets = []
    role_map = {
        "identifier": "identifier",
        "dimension": "dimension",
        "measure": "measure",
        "timestamp": "time",
        "attribute": "attribute",
    }
    for dataset in sorted(document["datasets"], key=lambda item: item["fqn"]):
        columns = []
        for column in dataset["columns"]:
            role = role_map.get(column["semantic_role"])
            if role is None:
                raise ValueError(
                    "canonical Column semantic role is not authoring-ready"
                )
            columns.append(
                {
                    "name": column["column_name"],
                    "logical_type": column["logical_type"],
                    "is_part_of_key": column["authoring_is_part_of_key"],
                    "role": role,
                }
            )
        dataset_authoring = dataset["authoring"]
        assets.append(
            {
                "fqn": dataset["fqn"],
                "schema_version": dataset_authoring["schema_version"],
                "seed_version": dataset_authoring["seed_version"],
                "synthetic": dataset_authoring["synthetic"],
                "approval_status": dataset_authoring["approval_status"],
                "entitlements": _detached(dataset_authoring["entitlements"]),
                "grain": _detached(dataset["grain"]),
                "columns": columns,
                "owner_urn": dataset["owner_group_urn"],
                "domain_urn": dataset["domain_urn"],
                "approved_lifecycle_urn": dataset_authoring[
                    "approved_lifecycle_urn"
                ],
            }
        )

    return _detached(
        {
            "contract_version": authoring["contract_version"],
            "catalog_version": authoring["catalog_version"],
            "policy_version": authoring["policy_version"],
            "schema_context_version": authoring["schema_context_version"],
            "governance_entities": {
                "owners": document["owner_groups"],
                "domains": document["domains"],
                "approved_lifecycles": document["lifecycles"],
            },
            "assets": assets,
            "metric_rules": metric_rules,
            "metric_terms": metric_terms,
            "dimensions": document["dimensions"],
            "join_graph": document["join_graph"],
            "time_rules": document["time_rules"],
            "parameter_contract": document["parameter_contract"],
            "query_policy": document["query_policy"],
        }
    )


def _detached(value: Any) -> Any:
    """canonical JSON round-trip으로 호출자 변경과 내부 manifest를 분리한다."""

    return json.loads(canonical_json(value))


def validate_canonical_metadata_document(
    document: dict[str, Any],
    *,
    schema_document: dict[str, Any] | None = None,
) -> CanonicalMetadataManifest:
    """JSON Schema와 entity reference·lifecycle·visibility 불변식을 함께 검증한다."""

    schema = schema_document or _json_file(
        Path(__file__).resolve().parent / "metadata" / "schema.json"
    )
    if document.get("schema_sha256") != canonical_sha256(schema):
        raise ValueError("canonical metadata schema checksum differs")
    errors = sorted(
        Draft202012Validator(schema).iter_errors(document),
        key=lambda item: tuple(str(part) for part in item.absolute_path),
    )
    if errors:
        path = ".".join(str(part) for part in errors[0].absolute_path) or "$"
        raise ValueError(f"canonical metadata schema validation failed at {path}")

    domains = _unique(document["domains"], "urn", "domain")
    owners = _unique(document["owner_groups"], "urn", "owner group")
    lifecycles = _unique(document["lifecycles"], "urn", "lifecycle")
    datasets = _unique(document["datasets"], "dataset_id", "dataset")
    dataset_urns = _unique(document["datasets"], "physical_urn", "dataset URN")
    dataset_fqns = _unique(document["datasets"], "fqn", "dataset FQN")
    terms = _unique(document["glossary_terms"], "term_id", "Glossary Term")
    term_urns = _unique(document["glossary_terms"], "urn", "Glossary Term URN")
    metrics = _unique(document["metrics"], "metric_id", "Metric")
    quality = _unique(document["quality_policies"], "dataset_id", "quality policy")
    if set(quality) != set(datasets):
        raise ValueError("quality policy membership differs from Dataset membership")
    if len(dataset_urns) != len(datasets) or len(dataset_fqns) != len(datasets):
        raise ValueError("canonical Dataset identities are not one-to-one")

    review_paths = tuple(sorted(_review_paths(document)))
    for dataset_id, dataset in datasets.items():
        if _STABLE_ID_VERSION.search(dataset_id):
            raise ValueError("stable Dataset ID contains a release version")
        _reference(dataset["domain_urn"], domains, "Dataset Domain")
        _reference(dataset["owner_group_urn"], owners, "Dataset owner")
        _reference(
            dataset["authoring"]["approved_lifecycle_urn"],
            lifecycles,
            "Dataset lifecycle",
        )
        columns = _unique(dataset["columns"], "column_name", "Column")
        for column in columns.values():
            for term_urn in column.get("term_urns", []):
                _reference(term_urn, term_urns, "Column Glossary Term")
        if dataset["lifecycle"] == "CERTIFIED" and _has_review_marker(dataset):
            raise ValueError(
                "CERTIFIED Dataset cannot contain REVIEW_REQUIRED metadata"
            )
        _validate_quality_policy(dataset, quality[dataset_id])

    lineage_edges, source_roots, lineage_exceptions = _validate_lineage_contracts(
        datasets, quality
    )

    for term_id, term in terms.items():
        if _STABLE_ID_VERSION.search(term_id):
            raise ValueError("stable Glossary Term ID contains a release version")
        _reference(term["domain_urn"], domains, "Glossary Domain")
        _reference(term["owner_group_urn"], owners, "Glossary owner")
        _reference(term["lifecycle_urn"], lifecycles, "Glossary lifecycle")

    business_metrics = 0
    support_metrics = 0
    for metric_id, metric in metrics.items():
        if _STABLE_ID_VERSION.search(metric_id):
            raise ValueError("stable Metric ID contains a release version")
        rule = metric["runtime_rule"]
        if rule.get("id") != metric_id:
            raise ValueError("Metric runtime rule identity differs")
        governance = rule.get("governance")
        runtime_visibility = (
            governance.get("visibility") if isinstance(governance, dict) else None
        )
        visibility = metric["visibility"]
        if visibility == "BUSINESS":
            business_metrics += 1
            if metric["user_selectable"] is not True or runtime_visibility != "BUSINESS":
                raise ValueError("Business Metric selection contract differs")
            _reference(metric["term_urn"], term_urns, "Business Metric Term")
        else:
            support_metrics += 1
            if metric["user_selectable"] is not False or runtime_visibility != "SUPPORT":
                raise ValueError("Support Metric selection contract differs")
            if metric.get("term_urn") is not None:
                raise ValueError("Support Metric must not expose a Glossary Term")
        _reference(metric["owner_group_urn"], owners, "Metric owner")
        _validate_metric_query(metric["validation_query"])
        if metric["lifecycle"] == "CERTIFIED" and _has_review_marker(metric):
            raise ValueError("CERTIFIED Metric cannot contain REVIEW_REQUIRED metadata")

    source = document["source"]
    for name in (
        "datahub_baseline_sha256",
        "runtime_baseline_sha256",
        "active_projection_sha256",
    ):
        if not _SHA256.fullmatch(source[name]):
            raise ValueError("canonical metadata source checksum is invalid")

    inventory = {
        "domains": len(domains),
        "owner_groups": len(owners),
        "datasets": len(datasets),
        "columns": sum(len(item["columns"]) for item in datasets.values()),
        "glossary_terms": len(terms),
        "business_metrics": business_metrics,
        "support_metrics": support_metrics,
        "quality_policies": len(quality),
        "lineage_edges": len(lineage_edges),
        "source_roots": len(source_roots),
        "lineage_exceptions": len(lineage_exceptions),
    }
    detached = json.loads(canonical_json(document))
    return CanonicalMetadataManifest(
        content_sha256=canonical_sha256(detached),
        inventory=inventory,
        review_required=review_paths,
        _document_json=canonical_json(detached),
    )


def _yaml_file(path: Path) -> dict[str, Any]:
    try:
        if path.stat().st_size > _MAX_FILE_BYTES:
            raise ValueError("canonical metadata file exceeds its size bound")
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise ValueError("canonical metadata YAML is unreadable") from error
    if not isinstance(value, dict):
        raise ValueError("canonical metadata YAML root must be an object")
    return value


def _json_file(path: Path) -> dict[str, Any]:
    try:
        if path.stat().st_size > _MAX_FILE_BYTES:
            raise ValueError("canonical metadata schema exceeds its size bound")
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("canonical metadata schema is unreadable") from error
    if not isinstance(value, dict):
        raise ValueError("canonical metadata schema root must be an object")
    Draft202012Validator.check_schema(value)
    return value


def _unique(
    values: list[dict[str, Any]], key: str, context: str
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for item in values:
        identity = item.get(key)
        if not isinstance(identity, str) or not identity or identity in result:
            raise ValueError(f"canonical {context} identities are invalid")
        result[identity] = item
    return result


def _reference(value: object, identities: dict[str, Any], context: str) -> None:
    if not isinstance(value, str) or value not in identities:
        raise ValueError(f"canonical {context} reference is unresolved")


def _has_review_marker(value: object) -> bool:
    if value == REVIEW_REQUIRED:
        return True
    if isinstance(value, dict):
        return any(_has_review_marker(item) for item in value.values())
    if isinstance(value, list):
        return any(_has_review_marker(item) for item in value)
    return False


def _validate_metric_query(value: str) -> None:
    if value == REVIEW_REQUIRED:
        return
    try:
        statements = parse(value, read="trino")
    except ParseError as error:
        raise ValueError(
            "Metric validation query must be a single read-only Trino SELECT"
        ) from error
    if len(statements) != 1 or not isinstance(statements[0], exp.Select):
        raise ValueError(
            "Metric validation query must be a single read-only Trino SELECT"
        )
    aliases = [item.alias_or_name for item in statements[0].expressions]
    if aliases != ["metric_id", "violation_count"]:
        raise ValueError(
            "Metric validation query must return metric_id and violation_count"
        )


def _validate_quality_policy(
    dataset: dict[str, Any], policy: dict[str, Any]
) -> None:
    """Dataset 계약에서 결정되는 기본 품질 규칙이 임의 문자열로 이탈하지 못하게 한다."""

    expected_schema = canonical_sha256(
        [
            [
                dataset["physical_urn"],
                column["column_name"],
                column["data_type"],
                column["nullable"],
            ]
            for column in dataset["columns"]
        ]
    )
    if policy["schema_fingerprint_sha256"] != expected_schema:
        raise ValueError("quality schema fingerprint differs from Dataset schema")

    primary_key = dataset["primary_key"]
    expected_keys = (
        REVIEW_REQUIRED
        if primary_key == REVIEW_REQUIRED
        else "NOT_NULL:" + ",".join(primary_key)
    )
    if policy["required_keys"] != expected_keys:
        raise ValueError("quality required keys differ from Dataset primary key")

    event_time = dataset["event_time"]
    expected_timestamp = (
        event_time
        if isinstance(event_time, str)
        else "VALID_DATE_OR_TIMESTAMP:" + ",".join(event_time)
    )
    if policy["timestamp_validity"] != expected_timestamp:
        raise ValueError("quality timestamp rule differs from Dataset event time")

    freshness_contracts = {
        (
            "ON_DATA_RELEASE",
            "ACTIVE_DATA_RELEASE_SEED_VERSION_MATCH",
        ): "SEED_VERSION_MATCHES_ACTIVE_DATA_RELEASE",
        (
            "QUERY_TIME_VIEW",
            "UPSTREAM_ACTIVE_DATA_RELEASE_WATERMARK",
        ): "UPSTREAM_FRESHNESS_PROPAGATED",
    }
    expected_freshness = freshness_contracts.get(
        (dataset["update_frequency"], dataset["freshness_slo"]),
        REVIEW_REQUIRED,
    )
    if policy["freshness"] != expected_freshness:
        raise ValueError("quality freshness rule differs from Dataset freshness contract")
    if policy["row_count"] != "COUNT_GT_ZERO":
        raise ValueError("quality row count rule is unsupported")
    if dataset["lifecycle"] == "CERTIFIED" and policy["status"] != "ENFORCED":
        raise ValueError("CERTIFIED Dataset requires an ENFORCED quality policy")


def _validate_lineage_contracts(
    datasets: dict[str, dict[str, Any]],
    quality: dict[str, dict[str, Any]],
) -> tuple[set[tuple[str, str]], set[str], set[str]]:
    """모든 Dataset이 정본 upstream, graph root, 승인 예외 중 하나만 갖도록 검증한다."""

    edges: set[tuple[str, str]] = set()
    roots: set[str] = set()
    exceptions: set[str] = set()
    for dataset_id, dataset in datasets.items():
        lineage = quality[dataset_id]["lineage"]
        if lineage == REVIEW_REQUIRED:
            continue
        mode = lineage["mode"]
        if mode == "SOURCE_ROOT":
            if dataset["source_system"] == "SERVING":
                raise ValueError("Serving Dataset cannot claim SOURCE_ROOT lineage")
            roots.add(dataset_id)
            continue
        if mode == "APPROVED_EXCEPTION":
            exception_id = lineage["exception_id"]
            if exception_id in exceptions:
                raise ValueError("lineage exception identity is duplicate")
            exceptions.add(exception_id)
            continue
        upstream_ids = lineage["upstream_dataset_ids"]
        if upstream_ids != sorted(upstream_ids):
            raise ValueError("lineage upstream Dataset identities must be sorted")
        for upstream_id in upstream_ids:
            if upstream_id not in datasets or upstream_id == dataset_id:
                raise ValueError("lineage upstream Dataset reference is unresolved")
            edges.add((upstream_id, dataset_id))
    if len(edges) != sum(
        len(policy["lineage"].get("upstream_dataset_ids", []))
        for policy in quality.values()
        if isinstance(policy["lineage"], dict)
    ):
        raise ValueError("lineage edge identity is duplicate")
    return edges, roots, exceptions


def _review_paths(value: object, path: str = "$"):
    if value == REVIEW_REQUIRED:
        yield path
    elif isinstance(value, dict):
        for key in sorted(value):
            yield from _review_paths(value[key], f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _review_paths(item, f"{path}[{index}]")
