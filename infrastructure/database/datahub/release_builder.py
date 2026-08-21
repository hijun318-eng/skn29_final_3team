"""physical ingestion 완전성과 semantic release readiness를 분리해 검증한다."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any, Protocol

from release_bundle import (
    ReleaseBinding,
    SemanticBundleError,
    assemble_release_bundle,
    catalog_snapshot_bindings,
    release_term_urns,
    semantic_surface_issues,
)
from release_datahub import (
    DataHubDataset,
    DataHubDiscoveryError,
    DataHubTerm,
    PROPERTY_PREFIX,
)
from release_scope import ReleaseScope
from release_trino import PhysicalRelation, TrinoInventory
from src.data.metric_governance import (
    SUPPORTED_RUNTIME_GOVERNANCE_VERSIONS,
    dataset_runtime_property_keys,
)
from src.data.governance_contract import trino_schema_sha256


@dataclass(frozen=True)
class ReadinessStage:
    """release gate 하나의 요구·관측 수량과 identity 문제를 표현한다."""

    status: str
    expected_dataset_count: int
    observed_dataset_count: int
    expected_column_count: int
    observed_column_count: int
    expected_term_count: int
    observed_term_count: int
    issues: tuple[str, ...]

    @property
    def ready(self) -> bool:
        """명시적인 READY 종결 상태일 때만 참을 반환한다."""

        return self.status == "READY"


@dataclass(frozen=True)
class ReleaseReadinessReport:
    """physical ingestion과 semantic governance gate의 증거를 함께 보관한다."""

    scope_count: int
    trino_query_ids: tuple[str, ...]
    base_ingestion: ReadinessStage
    semantic_release: ReadinessStage

    def as_dict(self) -> dict[str, Any]:
        """stage를 숨기지 않는 JSON 직렬화 가능 증거 객체를 반환한다."""

        return asdict(self)


@dataclass(frozen=True)
class ReleaseDiscoveryResult:
    """readiness report와 선택적인 검증 완료 release bundle을 결합한다."""

    report: ReleaseReadinessReport
    bundle: dict[str, Any] | None


class ReleaseNotReady(RuntimeError):
    """readiness stage가 불완전한 상태에서 release bundle을 요청했음을 나타낸다."""

    def __init__(self, report: ReleaseReadinessReport) -> None:
        super().__init__("live DataHub and Trino metadata are not release-ready")
        self.report = report


class TrinoDiscoveryPort(Protocol):
    """runtime Trino scope에서 physical relation을 발견하는 port 계약이다."""

    async def discover(self, scopes: tuple[ReleaseScope, ...]) -> TrinoInventory:
        """지정된 runtime scope의 physical inventory와 query 증거를 반환한다."""
        ...


class DataHubDiscoveryPort(Protocol):
    """DataHub dataset과 참조 glossary term을 읽는 port 계약이다."""

    async def discover_datasets(
        self, scopes: tuple[ReleaseScope, ...]
    ) -> tuple[DataHubDataset, ...]:
        """지정된 runtime scope에 속한 DataHub dataset 전체를 반환한다."""
        ...

    async def discover_terms(self, urns: tuple[str, ...]) -> tuple[DataHubTerm, ...]:
        """release가 명시한 정확한 URN의 glossary term 전체를 반환한다."""
        ...


async def inspect_release(
    scopes: tuple[ReleaseScope, ...],
    trino: TrinoDiscoveryPort,
    datahub: DataHubDiscoveryPort,
) -> ReleaseDiscoveryResult:
    """live metadata를 발견하고 두 stage가 모두 통과한 경우에만 bundle을 반환한다."""

    inventory: TrinoInventory = await trino.discover(scopes)
    datasets: tuple[DataHubDataset, ...] = await datahub.discover_datasets(scopes)
    base, bindings = reconcile_base(scopes, inventory, datasets)
    if not base.ready:
        semantic = _blocked_semantic(base, bindings)
        return ReleaseDiscoveryResult(
            ReleaseReadinessReport(
                len(scopes), inventory.query_ids, base, semantic
            ),
            None,
        )
    issues = semantic_surface_issues(bindings)
    governed_count, governed_columns = _governed_counts(bindings)
    if issues:
        semantic = _semantic_stage(
            base,
            governed_count,
            governed_columns,
            expected_terms=0,
            observed_terms=0,
            issues=issues,
        )
        return ReleaseDiscoveryResult(
            ReleaseReadinessReport(
                len(scopes), inventory.query_ids, base, semantic
            ),
            None,
        )
    try:
        term_urns = release_term_urns(bindings)
        terms = await datahub.discover_terms(term_urns)
        bundle = assemble_release_bundle(bindings, terms)
    except (DataHubDiscoveryError, SemanticBundleError) as error:
        semantic = _semantic_stage(
            base,
            governed_count,
            governed_columns,
            expected_terms=_expected_term_count(bindings),
            observed_terms=0,
            issues=(f"semantic_contract:{error}",),
        )
        return ReleaseDiscoveryResult(
            ReleaseReadinessReport(
                len(scopes), inventory.query_ids, base, semantic
            ),
            None,
        )
    semantic = _semantic_stage(
        base,
        governed_count,
        governed_columns,
        expected_terms=len(term_urns),
        observed_terms=len(terms),
        issues=(),
    )
    return ReleaseDiscoveryResult(
        ReleaseReadinessReport(len(scopes), inventory.query_ids, base, semantic),
        bundle,
    )


async def build_release_bundle(
    scopes: tuple[ReleaseScope, ...],
    trino: TrinoDiscoveryPort,
    datahub: DataHubDiscoveryPort,
) -> dict[str, Any]:
    """완전히 대조된 live bundle만 반환하고 아니면 증거가 포함된 예외를 발생시킨다."""

    result = await inspect_release(scopes, trino, datahub)
    if result.bundle is None:
        raise ReleaseNotReady(result.report)
    return result.bundle


async def build_active_release_bundle(
    scopes: tuple[ReleaseScope, ...],
    trino: TrinoDiscoveryPort,
    datahub: DataHubDiscoveryPort,
) -> dict[str, Any]:
    """미승인 물리 자산과 분리해 manifest가 지정한 현재 active release를 재구성한다.

    전체 scoped catalog는 신규 base-ingested 후보를 포함할 수 있다. 이 함수는
    ``answervice.*`` publication property가 하나라도 있는 Dataset을 숨기지 않고 모두
    predecessor 후보로 모은 뒤, 단일 manifest의 exact membership과 DataHub aspect를
    재검증한다. manifest 밖의 무거버넌스 Dataset은 runtime release에 넣지 않지만,
    manifest 구성원 전부는 live Trino fingerprint와 다시 일치해야 한다.
    """

    inventory: TrinoInventory = await trino.discover(scopes)
    datasets: tuple[DataHubDataset, ...] = await datahub.discover_datasets(scopes)
    governed = tuple(
        dataset
        for dataset in datasets
        if any(
            key.startswith(PROPERTY_PREFIX)
            for key in dataset.custom_properties
        )
    )
    bindings = catalog_snapshot_bindings(governed)
    term_urns = release_term_urns(bindings)
    terms = await datahub.discover_terms(term_urns)
    bundle = assemble_release_bundle(bindings, terms)
    _verify_active_trino_release(bundle, inventory)
    return bundle


def _verify_active_trino_release(
    bundle: Mapping[str, Any],
    inventory: TrinoInventory,
) -> None:
    """active manifest 구성원의 live Trino relation identity와 schema만 exact 대조한다."""

    relations = {relation.fqn: relation for relation in inventory.relations}
    if len(relations) != len(inventory.relations):
        raise SemanticBundleError("live Trino inventory contains duplicate relations")
    for asset in bundle["schema_context"]["assets"]:
        relation = relations.get(str(asset["fqn"]))
        if relation is None:
            raise SemanticBundleError(
                f"active release is missing from live Trino: {asset['fqn']}"
            )
        live_projection = {
            "fqn": relation.fqn,
            "table_type": relation.table_type,
            "columns": [column.contract_value() for column in relation.columns],
        }
        if trino_schema_sha256(live_projection) != trino_schema_sha256(asset):
            raise SemanticBundleError(
                f"active release Trino schema differs: {asset['fqn']}"
            )


def reconcile_base(
    scopes: tuple[ReleaseScope, ...],
    inventory: TrinoInventory,
    datasets: tuple[DataHubDataset, ...],
) -> tuple[ReadinessStage, tuple[ReleaseBinding, ...]]:
    """live Trino relation과 DataHub dataset을 정확한 scoped identity로 대조한다."""

    issues: list[str] = []
    scoped: dict[ReleaseScope, list[DataHubDataset]] = {scope: [] for scope in scopes}
    for dataset in datasets:
        matches = [scope for scope in scopes if _dataset_in_scope(dataset, scope)]
        if len(matches) > 1:
            issues.append(f"ambiguous_dataset:{dataset.urn}")
        elif matches:
            scoped[matches[0]].append(dataset)
    bindings: list[ReleaseBinding] = []
    used: set[str] = set()
    for relation in inventory.relations:
        expected_schema = (
            f"{relation.scope.datahub_namespace}.{relation.name}"
        )
        matches = [
            dataset
            for dataset in scoped[relation.scope]
            if dataset.schema_name == expected_schema
        ]
        if not matches:
            issues.append(f"missing_dataset:{relation.fqn}")
            continue
        if len(matches) > 1:
            issues.append(f"duplicate_dataset:{relation.fqn}")
            continue
        dataset = matches[0]
        used.add(dataset.urn)
        if not _base_fields_match(relation, dataset):
            issues.append(f"schema_fields:{relation.fqn}")
            continue
        bindings.append(ReleaseBinding(relation, dataset))
    for values in scoped.values():
        for dataset in values:
            if dataset.urn not in used:
                issues.append(f"unexpected_dataset:{dataset.urn}")
    observed_datasets = sum(len(values) for values in scoped.values())
    observed_columns = sum(len(dataset.fields) for values in scoped.values() for dataset in values)
    unique_issues = tuple(sorted(set(issues)))
    stage = ReadinessStage(
        status="READY" if not unique_issues else "NOT_READY",
        expected_dataset_count=len(inventory.relations),
        observed_dataset_count=observed_datasets,
        expected_column_count=inventory.column_count,
        observed_column_count=observed_columns,
        expected_term_count=0,
        observed_term_count=0,
        issues=unique_issues,
    )
    return stage, tuple(sorted(bindings, key=lambda item: item.relation.fqn))


def _dataset_in_scope(dataset: DataHubDataset, scope: ReleaseScope) -> bool:
    return (
        dataset.origin == scope.origin
        and dataset.dataset_key_name.startswith(f"{scope.platform_instance}.")
        and dataset.schema_name.startswith(f"{scope.datahub_namespace}.")
    )


def _base_fields_match(
    relation: PhysicalRelation,
    dataset: DataHubDataset,
) -> bool:
    """여기서는 coverage/order와 connector field 완전성만 확인한다.

    Source connectors and Trino expose different native type vocabularies, so treating
    their raw type strings as equal would reject valid base ingestion. Semantic readiness
    compares a connector field fingerprint and a Trino execution fingerprint independently.
    """

    if len(relation.columns) != len(dataset.fields):
        return False
    for trino, datahub in zip(relation.columns, dataset.fields):
        if (
            trino.name != datahub.name
            or datahub.native_type is None
            or datahub.nullable is None
            or datahub.is_part_of_key is None
        ):
            return False
    return True


def _blocked_semantic(
    base: ReadinessStage,
    bindings: tuple[ReleaseBinding, ...],
) -> ReadinessStage:
    issues = ["base_ingestion_not_ready", *semantic_surface_issues(bindings)]
    governed_count, governed_columns = _governed_counts(bindings)
    return _semantic_stage(
        base,
        governed_count,
        governed_columns,
        expected_terms=0,
        observed_terms=0,
        issues=tuple(sorted(set(issues))),
    )


def _semantic_stage(
    base: ReadinessStage,
    governed_datasets: int,
    governed_columns: int,
    *,
    expected_terms: int,
    observed_terms: int,
    issues: tuple[str, ...],
) -> ReadinessStage:
    ready = (
        base.ready
        and not issues
        and governed_datasets == base.expected_dataset_count
        and governed_columns == base.expected_column_count
        and observed_terms == expected_terms
    )
    return ReadinessStage(
        status="READY" if ready else "NOT_READY",
        expected_dataset_count=base.expected_dataset_count,
        observed_dataset_count=governed_datasets,
        expected_column_count=base.expected_column_count,
        observed_column_count=governed_columns,
        expected_term_count=expected_terms,
        observed_term_count=observed_terms,
        issues=tuple(sorted(set(issues))),
    )


def _governed_counts(bindings: tuple[ReleaseBinding, ...]) -> tuple[int, int]:
    count = 0
    columns = 0
    for binding in bindings:
        properties = {
            key.removeprefix(PROPERTY_PREFIX): value
            for key, value in binding.dataset.custom_properties.items()
            if key.startswith(PROPERTY_PREFIX)
        }
        version = properties.get("contract_version")
        if (
            version in SUPPORTED_RUNTIME_GOVERNANCE_VERSIONS
            and set(properties) == dataset_runtime_property_keys(version)
        ):
            count += 1
            columns += len(binding.relation.columns)
    return count, columns


def _expected_term_count(bindings: tuple[ReleaseBinding, ...]) -> int:
    try:
        return len(release_term_urns(bindings))
    except SemanticBundleError:
        return 0
