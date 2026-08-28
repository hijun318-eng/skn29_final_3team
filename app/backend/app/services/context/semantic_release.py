"""검증된 semantic publication bundle을 저장소 중립 불변 runtime release로 컴파일한다.

이 모듈은 DataHub custom properties나 향후 native entity를 권위 원본으로 삼지 않는다.
각 저장소 adapter가 동일한 publication bundle을 재구성한 뒤 이 타입으로 컴파일해야 하며,
요청 단위 ``RuntimeContextPackage``는 이 전체 release에서 권한에 맞는 subgraph만 투영한다.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from app.services.context.contract import GovernedJoin
from src.data.governance_contract import (
    SEMANTIC_RELEASE_KEYS,
    canonical_json,
    canonical_sha256,
    release_manifest as build_release_manifest,
    ratio_operand_ids,
)
from src.data.metric_governance import (
    metric_visibility,
    runtime_governance_version,
)


CANONICAL_SEMANTIC_RELEASE_VERSION = "ANSWERVICE-CANONICAL-SEMANTIC-RELEASE-v1"
_COLUMN_ROLES = frozenset(
    {"identifier", "dimension", "measure", "time", "attribute"}
)
_GRAIN_KINDS = frozenset({"row", "event", "periodic", "aggregate"})


class CanonicalSemanticReleaseError(ValueError):
    """검증 완료라고 선언된 bundle을 typed release로 안전하게 컴파일할 수 없음을 나타낸다."""


@dataclass(frozen=True)
class CanonicalColumn:
    """한 semantic asset의 순서·타입·역할이 고정된 컬럼 계약이다."""

    name: str
    native_type: str
    logical_type: str
    ordinal_position: int
    nullable: bool
    is_part_of_key: bool
    role: str


@dataclass(frozen=True)
class CanonicalAsset:
    """release 전체 그래프에서 사용하는 권한·grain·schema가 결합된 asset node다."""

    urn: str
    fqn: str
    description: str
    schema_version: str
    seed_version: str
    synthetic: bool
    grain_kind: str
    grain_keys: tuple[str, ...]
    allowed_roles: tuple[str, ...]
    allowed_domains: tuple[str, ...]
    owner_urn: str
    domain_urn: str
    lifecycle_urn: str
    columns: tuple[CanonicalColumn, ...]


@dataclass(frozen=True)
class CanonicalMetric:
    """물리 source·grain·권한·허용 JOIN을 포함한 release 단위 Metric 계약이다."""

    id: str
    source_kind: str
    source_assets: tuple[str, ...]
    source_field: str | None
    aggregation: str
    reduction: str
    result_field: str
    unit: str
    time_field: str | None
    dimension_fields: tuple[str, ...]
    required_filters: tuple[tuple[str, str, str], ...]
    visibility: str
    grain_kind: str
    grain_keys: tuple[str, ...]
    allowed_join_ids: tuple[str, ...]
    allowed_roles: tuple[str, ...]
    contains_pii: bool | None
    query_strategies: tuple[str, ...]


@dataclass(frozen=True)
class CanonicalDimensionMember:
    """승인된 Dimension 값과 Glossary Term identity를 release 안에 고정한다."""

    id: str
    urn: str
    name: str
    aliases: tuple[str, ...]
    definition: str
    canonical_value: str
    version: str


@dataclass(frozen=True)
class CanonicalDimension:
    """업무 차원 ID를 한 asset의 실제 컬럼에 결속한 release 단위 Dimension 계약이다."""

    id: str
    aliases: tuple[str, ...]
    definition: str
    asset_fqn: str
    column: str
    members: tuple[CanonicalDimensionMember, ...] = ()


@dataclass(frozen=True)
class CanonicalAdjacency:
    """한 asset에서 로컬 그래프 탐색에 사용할 인접 node와 edge index다."""

    asset_fqn: str
    neighbor_fqns: tuple[str, ...]
    join_ids: tuple[str, ...]


@dataclass(frozen=True)
class CanonicalSemanticRelease:
    """전체 활성 semantic release를 저장소와 무관한 불변 typed graph로 보존한다.

    ``source_kind``는 관측 정보일 뿐 semantic identity에 포함되지 않는다. 따라서 Legacy
    custom-properties adapter와 Native shadow adapter가 같은 의미를 재구성하면 동일한
    ``canonical_checksum``을 가져야 한다.
    """

    format_version: str
    runtime_contract_version: str
    source_kind: str
    catalog_version: str
    policy_version: str
    catalog_checksum: str
    glossary_checksum: str
    shared_semantic_checksum: str
    manifest_checksum: str
    canonical_checksum: str
    assets: tuple[CanonicalAsset, ...]
    metrics: tuple[CanonicalMetric, ...]
    dimensions: tuple[CanonicalDimension, ...]
    joins: tuple[GovernedJoin, ...]
    adjacency: tuple[CanonicalAdjacency, ...]
    _bundle_json: str = field(repr=False)
    _manifest_json: str = field(repr=False)

    @classmethod
    def from_validated_bundle(
        cls,
        bundle: Mapping[str, Any],
        *,
        runtime_contract_version: str,
        source_kind: str,
    ) -> CanonicalSemanticRelease:
        """검증된 publication bundle을 방어적으로 복사하고 typed release로 컴파일한다."""

        if not runtime_contract_version or not source_kind.strip():
            raise CanonicalSemanticReleaseError(
                "semantic release version and source kind must be non-empty"
            )
        if set(bundle) != SEMANTIC_RELEASE_KEYS:
            raise CanonicalSemanticReleaseError(
                "semantic release bundle fields do not match the canonical contract"
            )
        try:
            bundle_json = canonical_json(bundle)
            detached = json.loads(bundle_json)
            observed_version = runtime_governance_version(detached)
            if observed_version != runtime_contract_version:
                raise CanonicalSemanticReleaseError(
                    "semantic release runtime contract version is inconsistent"
                )
            assets = _compile_assets(detached)
            approved_assets = {
                asset.fqn: frozenset(column.name for column in asset.columns)
                for asset in assets
            }
            joins = _compile_joins(detached, approved_assets)
            metrics = _compile_metrics(detached, assets, joins)
            dimensions = _compile_dimensions(detached, approved_assets)
            adjacency = _compile_adjacency(assets, joins)
            manifest = build_release_manifest(detached)
        except CanonicalSemanticReleaseError:
            raise
        except (KeyError, TypeError, ValueError) as error:
            raise CanonicalSemanticReleaseError(
                "validated semantic release bundle cannot be compiled"
            ) from error

        manifest_json = canonical_json(manifest)
        canonical_checksum = canonical_sha256(
            {
                "format_version": CANONICAL_SEMANTIC_RELEASE_VERSION,
                "runtime_contract_version": runtime_contract_version,
                "manifest": manifest,
            }
        )
        return cls(
            format_version=CANONICAL_SEMANTIC_RELEASE_VERSION,
            runtime_contract_version=runtime_contract_version,
            source_kind=source_kind,
            catalog_version=_text(detached["catalog_version"], "catalog_version"),
            policy_version=_text(detached["policy_version"], "policy_version"),
            catalog_checksum=_text(manifest["catalog_sha256"], "catalog checksum"),
            glossary_checksum=_text(
                manifest["glossary_sha256"], "glossary checksum"
            ),
            shared_semantic_checksum=_text(
                manifest["shared_semantic_sha256"], "shared semantic checksum"
            ),
            manifest_checksum=canonical_sha256(manifest),
            canonical_checksum=canonical_checksum,
            assets=assets,
            metrics=metrics,
            dimensions=dimensions,
            joins=joins,
            adjacency=adjacency,
            _bundle_json=bundle_json,
            _manifest_json=manifest_json,
        )

    def as_bundle(self) -> dict[str, Any]:
        """내부 불변 상태를 노출하지 않는 publication bundle 복사본을 반환한다."""

        value = json.loads(self._bundle_json)
        if not isinstance(value, dict):  # pragma: no cover - 생성자가 보장하는 방어선이다.
            raise CanonicalSemanticReleaseError("semantic release bundle is unavailable")
        return value

    def as_manifest(self) -> dict[str, Any]:
        """컴파일 시 계산한 release manifest의 방어적 복사본을 반환한다."""

        value = json.loads(self._manifest_json)
        if not isinstance(value, dict):  # pragma: no cover - 생성자가 보장하는 방어선이다.
            raise CanonicalSemanticReleaseError("semantic release manifest is unavailable")
        return value

    def asset(self, fqn: str) -> CanonicalAsset | None:
        """FQN이 일치하는 typed asset을 반환한다."""

        return next((item for item in self.assets if item.fqn == fqn), None)

    def metric(self, metric_id: str) -> CanonicalMetric | None:
        """ID가 일치하는 typed Metric을 반환한다."""

        return next((item for item in self.metrics if item.id == metric_id), None)


@dataclass(frozen=True)
class SemanticReleaseComparison:
    """두 source adapter의 canonical release 동등성 및 불일치 section을 보존한다."""

    equivalent: bool
    left_checksum: str
    right_checksum: str
    differing_sections: tuple[str, ...]


def compare_semantic_releases(
    left: CanonicalSemanticRelease,
    right: CanonicalSemanticRelease,
) -> SemanticReleaseComparison:
    """source 종류를 제외한 release identity를 비교하고 다른 최상위 계약 section을 반환한다."""

    if left.canonical_checksum == right.canonical_checksum:
        return SemanticReleaseComparison(
            equivalent=True,
            left_checksum=left.canonical_checksum,
            right_checksum=right.canonical_checksum,
            differing_sections=(),
        )
    left_bundle = left.as_bundle()
    right_bundle = right.as_bundle()
    differences: list[str] = []
    if left.format_version != right.format_version:
        differences.append("format_version")
    if left.runtime_contract_version != right.runtime_contract_version:
        differences.append("runtime_contract_version")
    for section in sorted(SEMANTIC_RELEASE_KEYS):
        if canonical_json(left_bundle.get(section)) != canonical_json(
            right_bundle.get(section)
        ):
            differences.append(section)
    if not differences:
        differences.append("canonical_identity")
    return SemanticReleaseComparison(
        equivalent=False,
        left_checksum=left.canonical_checksum,
        right_checksum=right.canonical_checksum,
        differing_sections=tuple(differences),
    )


def _compile_assets(bundle: Mapping[str, Any]) -> tuple[CanonicalAsset, ...]:
    schema_context = _mapping(bundle["schema_context"], "schema_context")
    raw_assets = _array(schema_context.get("assets"), "schema_context.assets")
    assets: list[CanonicalAsset] = []
    seen: set[str] = set()
    for raw in raw_assets:
        value = _mapping(raw, "schema asset")
        fqn = _text(value.get("fqn"), "asset fqn")
        if fqn in seen:
            raise CanonicalSemanticReleaseError("semantic release asset FQNs are duplicate")
        seen.add(fqn)
        grain = _mapping(value.get("grain"), f"{fqn} grain")
        entitlements = _mapping(value.get("entitlements"), f"{fqn} entitlements")
        columns = tuple(
            sorted(
                (
                    _compile_column(item, fqn)
                    for item in _array(value.get("columns"), f"{fqn} columns")
                ),
                key=lambda item: item.ordinal_position,
            )
        )
        if not columns or len({item.name for item in columns}) != len(columns):
            raise CanonicalSemanticReleaseError(
                "semantic release asset columns must be non-empty and unique"
            )
        if [item.ordinal_position for item in columns] != list(
            range(1, len(columns) + 1)
        ):
            raise CanonicalSemanticReleaseError(
                "semantic release asset column ordinals must be contiguous"
            )
        column_names = {item.name for item in columns}
        grain_kind = _text(grain.get("kind"), f"{fqn} grain kind")
        grain_keys = _texts(grain.get("keys"), f"{fqn} grain keys")
        if grain_kind not in _GRAIN_KINDS or not grain_keys or not set(
            grain_keys
        ).issubset(column_names):
            raise CanonicalSemanticReleaseError(
                "semantic release asset grain is outside its schema"
            )
        assets.append(
            CanonicalAsset(
                urn=_text(value.get("urn"), f"{fqn} urn"),
                fqn=fqn,
                description=_text(value.get("description"), f"{fqn} description"),
                schema_version=_text(
                    value.get("schema_version"), f"{fqn} schema version"
                ),
                seed_version=_text(value.get("seed_version"), f"{fqn} seed version"),
                synthetic=_boolean(value.get("synthetic"), f"{fqn} synthetic"),
                grain_kind=grain_kind,
                grain_keys=grain_keys,
                allowed_roles=tuple(
                    sorted(_texts(entitlements.get("roles"), f"{fqn} roles"))
                ),
                allowed_domains=tuple(
                    sorted(_texts(entitlements.get("domains"), f"{fqn} domains"))
                ),
                owner_urn=_text(value.get("owner_urn"), f"{fqn} owner"),
                domain_urn=_text(value.get("domain_urn"), f"{fqn} domain"),
                lifecycle_urn=_text(
                    value.get("approved_lifecycle_urn"), f"{fqn} lifecycle"
                ),
                columns=columns,
            )
        )
    if not assets:
        raise CanonicalSemanticReleaseError("semantic release requires assets")
    return tuple(sorted(assets, key=lambda item: item.fqn))


def _compile_column(value: object, fqn: str) -> CanonicalColumn:
    raw = _mapping(value, f"{fqn} column")
    ordinal = raw.get("ordinal_position")
    if not isinstance(ordinal, int) or isinstance(ordinal, bool) or ordinal < 1:
        raise CanonicalSemanticReleaseError("semantic release column ordinal is invalid")
    role = _text(raw.get("role"), f"{fqn} column role")
    if role not in _COLUMN_ROLES:
        raise CanonicalSemanticReleaseError("semantic release column role is invalid")
    return CanonicalColumn(
        name=_text(raw.get("name"), f"{fqn} column name"),
        native_type=_text(raw.get("native_type"), f"{fqn} native type"),
        logical_type=_text(raw.get("logical_type"), f"{fqn} logical type"),
        ordinal_position=ordinal,
        nullable=_boolean(raw.get("nullable"), f"{fqn} nullable"),
        is_part_of_key=_boolean(raw.get("is_part_of_key"), f"{fqn} key flag"),
        role=role,
    )


def _compile_joins(
    bundle: Mapping[str, Any],
    approved_assets: dict[str, frozenset[str]],
) -> tuple[GovernedJoin, ...]:
    graph = _mapping(bundle["join_graph"], "join_graph")
    joins = tuple(
        GovernedJoin.from_mapping(item, approved_assets=approved_assets)
        for item in _array(graph.get("edges"), "join_graph.edges")
    )
    if len({item.id for item in joins}) != len(joins):
        raise CanonicalSemanticReleaseError("semantic release join IDs are duplicate")
    return tuple(sorted(joins, key=lambda item: item.id))


def _compile_metrics(
    bundle: Mapping[str, Any],
    assets: tuple[CanonicalAsset, ...],
    joins: tuple[GovernedJoin, ...],
) -> tuple[CanonicalMetric, ...]:
    rules = tuple(
        _mapping(item, "metric rule")
        for item in _array(bundle["metric_rules"], "metric_rules")
    )
    by_id = {_text(item.get("id"), "metric id"): item for item in rules}
    if not rules or len(by_id) != len(rules):
        raise CanonicalSemanticReleaseError(
            "semantic release metric IDs must be non-empty and unique"
        )
    assets_by_fqn = {item.fqn: item for item in assets}
    join_ids = {item.id for item in joins}
    result: list[CanonicalMetric] = []
    for metric_id in sorted(by_id):
        rule = by_id[metric_id]
        source = _mapping(rule.get("source"), f"{metric_id} source")
        source_kind = _text(source.get("kind"), f"{metric_id} source kind")
        source_assets = _metric_source_assets(metric_id, by_id, frozenset())
        if not set(source_assets).issubset(assets_by_fqn):
            raise CanonicalSemanticReleaseError(
                "semantic release metric references an unknown source asset"
            )
        source_field = (
            _qualified_field(source.get("field"), f"{metric_id} source field")
            if source_kind == "column"
            else None
        )
        if source_kind not in {"column", "ratio"}:
            raise CanonicalSemanticReleaseError(
                "semantic release metric source kind is unsupported"
            )
        if source_field is not None:
            _require_known_field(source_field, assets_by_fqn, f"{metric_id} source")
        governance = rule.get("governance")
        if isinstance(governance, Mapping):
            grain = _mapping(governance.get("grain"), f"{metric_id} grain")
            join = _mapping(governance.get("join"), f"{metric_id} join policy")
            permission = _mapping(
                governance.get("permission"), f"{metric_id} permission"
            )
            allowed_join_ids = tuple(
                sorted(
                    _texts(
                        join.get("allowed_edge_ids"),
                        f"{metric_id} allowed join IDs",
                    )
                )
            )
            allowed_roles = tuple(
                sorted(
                    _texts(permission.get("roles"), f"{metric_id} allowed roles")
                )
            )
            contains_pii: bool | None = _boolean(
                permission.get("contains_pii"), f"{metric_id} PII flag"
            )
            grain_kind = _text(grain.get("kind"), f"{metric_id} grain kind")
            grain_keys = _texts(grain.get("keys"), f"{metric_id} grain keys")
            query_strategies = tuple(
                sorted(
                    _texts(
                        governance.get("query_strategies"),
                        f"{metric_id} query strategies",
                    )
                )
            )
        else:
            source_asset = assets_by_fqn[source_assets[0]]
            allowed_join_ids = ()
            allowed_roles = ()
            contains_pii = None
            grain_kind = source_asset.grain_kind
            grain_keys = source_asset.grain_keys
            query_strategies = ()
        if not set(allowed_join_ids).issubset(join_ids):
            raise CanonicalSemanticReleaseError(
                "semantic release metric allows an unknown join edge"
            )
        time_value = rule.get("time_field")
        time_field = (
            None
            if time_value is None
            else _qualified_field(time_value, f"{metric_id} time field")
        )
        if time_field is not None:
            _require_known_field(time_field, assets_by_fqn, f"{metric_id} time field")
        dimension_fields = tuple(
            _qualified_field(item, f"{metric_id} dimension")
            for item in _array(rule.get("dimensions"), f"{metric_id} dimensions")
        )
        filters = tuple(
            _compile_filter(item, metric_id)
            for item in _array(rule.get("required_filters"), f"{metric_id} filters")
        )
        for field in (*dimension_fields, *(item[0] for item in filters)):
            _require_known_field(field, assets_by_fqn, f"{metric_id} field")
        if len(source_assets) != 1:
            raise CanonicalSemanticReleaseError(
                "semantic release metric operands must resolve one execution asset"
            )
        source_asset = assets_by_fqn[source_assets[0]]
        if (
            source_field is not None
            and not source_field.startswith(f"{source_asset.fqn}.")
        ) or (
            time_field is not None
            and not time_field.startswith(f"{source_asset.fqn}.")
        ) or any(
            not field.startswith(f"{source_asset.fqn}.")
            for field in (item[0] for item in filters)
        ):
            raise CanonicalSemanticReleaseError(
                "semantic release metric calculation fields span multiple execution assets"
            )
        reachable_assets = _reachable_assets(
            source_asset.fqn,
            tuple(item for item in joins if item.id in allowed_join_ids),
        )
        if any(
            _field_asset(field, assets_by_fqn) not in reachable_assets
            for field in dimension_fields
        ):
            raise CanonicalSemanticReleaseError(
                "semantic release metric dimension is outside its approved join graph"
            )
        if not set(grain_keys).issubset(
            {column.name for column in source_asset.columns}
        ):
            raise CanonicalSemanticReleaseError(
                "semantic release metric grain is outside its source schema"
            )
        result.append(
            CanonicalMetric(
                id=metric_id,
                source_kind=source_kind,
                source_assets=source_assets,
                source_field=source_field,
                aggregation=_text(rule.get("aggregation"), f"{metric_id} aggregation"),
                reduction=_text(rule.get("reduction"), f"{metric_id} reduction"),
                result_field=_text(rule.get("result_field"), f"{metric_id} result field"),
                unit=_text(rule.get("unit"), f"{metric_id} unit"),
                time_field=time_field,
                dimension_fields=dimension_fields,
                required_filters=filters,
                visibility=metric_visibility(rule),
                grain_kind=grain_kind,
                grain_keys=grain_keys,
                allowed_join_ids=allowed_join_ids,
                allowed_roles=allowed_roles,
                contains_pii=contains_pii,
                query_strategies=query_strategies,
            )
        )
    return tuple(result)


def _reachable_assets(
    source_fqn: str,
    joins: tuple[GovernedJoin, ...],
) -> frozenset[str]:
    adjacency: dict[str, set[str]] = {}
    for join in joins:
        adjacency.setdefault(join.left, set()).add(join.right)
        adjacency.setdefault(join.right, set()).add(join.left)
    pending = [source_fqn]
    visited: set[str] = set()
    while pending:
        current = pending.pop()
        if current in visited:
            continue
        visited.add(current)
        pending.extend(adjacency.get(current, ()))
    return frozenset(visited)


def _field_asset(
    field: str,
    assets: Mapping[str, CanonicalAsset],
) -> str:
    matches = [fqn for fqn in assets if field.startswith(f"{fqn}.")]
    if len(matches) != 1:
        raise CanonicalSemanticReleaseError(
            "semantic release field does not resolve one asset"
        )
    return matches[0]


def _metric_source_assets(
    metric_id: str,
    rules: Mapping[str, Mapping[str, Any]],
    visiting: frozenset[str],
) -> tuple[str, ...]:
    if metric_id in visiting:
        raise CanonicalSemanticReleaseError("semantic release ratio metrics are cyclic")
    rule = rules.get(metric_id)
    if rule is None:
        raise CanonicalSemanticReleaseError(
            "semantic release ratio references an unknown metric"
        )
    source = _mapping(rule.get("source"), f"{metric_id} source")
    if source.get("kind") == "column":
        field = _mapping(source.get("field"), f"{metric_id} source field")
        return (_text(field.get("asset_fqn"), f"{metric_id} source asset"),)
    if source.get("kind") != "ratio":
        raise CanonicalSemanticReleaseError(
            "semantic release metric source kind is unsupported"
        )
    operands = ratio_operand_ids(rule)
    if operands is None:
        raise CanonicalSemanticReleaseError(
            "semantic release ratio operands are unavailable"
        )
    next_visiting = visiting | {metric_id}
    return tuple(
        sorted(
            {
                asset
                for operand in operands
                for asset in _metric_source_assets(operand, rules, next_visiting)
            }
        )
    )


def _compile_filter(value: object, metric_id: str) -> tuple[str, str, str]:
    raw = _mapping(value, f"{metric_id} filter")
    return (
        _qualified_field(raw.get("field"), f"{metric_id} filter field"),
        _text(raw.get("operator"), f"{metric_id} filter operator"),
        _text(raw.get("parameter"), f"{metric_id} filter parameter"),
    )


def _compile_dimensions(
    bundle: Mapping[str, Any],
    approved_assets: dict[str, frozenset[str]],
) -> tuple[CanonicalDimension, ...]:
    result: list[CanonicalDimension] = []
    seen: set[str] = set()
    for item in _array(bundle["dimensions"], "dimensions"):
        raw = _mapping(item, "dimension")
        dimension_id = _text(raw.get("id"), "dimension id")
        asset_fqn = _text(raw.get("asset_fqn"), f"{dimension_id} asset")
        column = _text(raw.get("column"), f"{dimension_id} column")
        if (
            dimension_id in seen
            or asset_fqn not in approved_assets
            or column not in approved_assets[asset_fqn]
        ):
            raise CanonicalSemanticReleaseError(
                "semantic release dimension binding is invalid"
            )
        seen.add(dimension_id)
        result.append(
            CanonicalDimension(
                id=dimension_id,
                aliases=_texts(raw.get("aliases"), f"{dimension_id} aliases"),
                definition=_text(raw.get("definition"), f"{dimension_id} definition"),
                asset_fqn=asset_fqn,
                column=column,
                members=tuple(
                    CanonicalDimensionMember(
                        id=_text(member.get("id"), f"{dimension_id} member id"),
                        urn=_text(member.get("urn"), f"{dimension_id} member urn"),
                        name=_text(member.get("name"), f"{dimension_id} member name"),
                        aliases=_texts(
                            member.get("aliases"),
                            f"{dimension_id} member aliases",
                        ),
                        definition=_text(
                            member.get("definition"),
                            f"{dimension_id} member definition",
                        ),
                        canonical_value=_text(
                            member.get("canonical_value"),
                            f"{dimension_id} canonical value",
                        ),
                        version=_text(
                            member.get("version"),
                            f"{dimension_id} member version",
                        ),
                    )
                    for member in _array(
                        raw.get("members", []),
                        f"{dimension_id} members",
                    )
                ),
            )
        )
    return tuple(sorted(result, key=lambda item: item.id))


def _compile_adjacency(
    assets: tuple[CanonicalAsset, ...],
    joins: tuple[GovernedJoin, ...],
) -> tuple[CanonicalAdjacency, ...]:
    result = []
    for asset in assets:
        related = tuple(
            item for item in joins if asset.fqn in {item.left, item.right}
        )
        neighbors = {
            item.right if item.left == asset.fqn else item.left for item in related
        }
        result.append(
            CanonicalAdjacency(
                asset_fqn=asset.fqn,
                neighbor_fqns=tuple(sorted(neighbors)),
                join_ids=tuple(sorted(item.id for item in related)),
            )
        )
    return tuple(result)


def _qualified_field(value: object, context: str) -> str:
    raw = _mapping(value, context)
    return f"{_text(raw.get('asset_fqn'), context)}.{_text(raw.get('column'), context)}"


def _require_known_field(
    field: str,
    assets_by_fqn: Mapping[str, CanonicalAsset],
    context: str,
) -> None:
    prefix_matches = [
        (fqn, asset)
        for fqn, asset in assets_by_fqn.items()
        if field.startswith(f"{fqn}.")
    ]
    if not prefix_matches:
        raise CanonicalSemanticReleaseError(
            f"semantic release {context} references an unknown asset"
        )
    matches = [
        asset
        for fqn, asset in prefix_matches
        if field.startswith(f"{fqn}.")
        and field.removeprefix(f"{fqn}.") in {item.name for item in asset.columns}
    ]
    if len(matches) != 1:
        raise CanonicalSemanticReleaseError(
            f"semantic release {context} references an unknown column"
        )


def _mapping(value: object, context: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise CanonicalSemanticReleaseError(f"{context} must be an object")
    return value


def _array(value: object, context: str) -> list[Any]:
    if not isinstance(value, list):
        raise CanonicalSemanticReleaseError(f"{context} must be an array")
    return value


def _texts(value: object, context: str) -> tuple[str, ...]:
    values = _array(value, context)
    result = tuple(_text(item, context) for item in values)
    if len(set(result)) != len(result):
        raise CanonicalSemanticReleaseError(f"{context} values must be unique")
    return result


def _text(value: object, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CanonicalSemanticReleaseError(f"{context} must be non-empty text")
    return value


def _boolean(value: object, context: str) -> bool:
    if not isinstance(value, bool):
        raise CanonicalSemanticReleaseError(f"{context} must be boolean")
    return value
