"""검증된 DataHub 거버넌스 aspect를 분석 context로 투영하는 불변 runtime 도메인 값이다."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Any

from app.adapters.datahub_metadata_values import GovernedMetadataError, clone_mapping
from app.adapters.datahub_metric_governance import runtime_metric_permitted
from app.authorization import role_is_entitled
from app.services.context.values import _typed_value_is_valid
from src.data.governance_contract import (
    canonical_json,
    metric_source_kind,
    ratio_operand_ids,
)


DERIVED_DIMENSION_ID_PREFIX = "derived_"


@dataclass(frozen=True)
class GlossaryMetricTerm:
    """승인된 metric의 식별자·동의어·계산 규칙·release checksum·native governance를 함께 보존한다."""
    id: str
    urn: str
    label: str
    aliases: tuple[str, ...]
    definition: str
    unit: str
    version: str
    checksum: str
    catalog_checksum: str
    metric_rule: dict[str, Any]
    owner_urns: frozenset[str]
    domain_urn: str
    lifecycle_urn: str

    def as_dict(self) -> dict[str, Any]:
        """모델 context에 공개 가능한 metric 정의만 새 dict로 내보내 내부 rule·권한 정보의 변경을 막는다.

        ratio metric은 물리 계산 규칙이 없는 대신 승인된 분자·분모 id와 zero_policy를
        ``metric_rule``에서 그대로 노출한다 — resolver가 후보 집합 대조에만 쓰고, 값 자체는
        여전히 DataHub 승인 term이 결정한다.
        """
        result: dict[str, Any] = {
            "id": self.id,
            "urn": self.urn,
            "label": self.label,
            "aliases": list(self.aliases),
            "definition": self.definition,
            "unit": self.unit,
            "version": self.version,
            "checksum": self.checksum,
        }
        if metric_source_kind(self.metric_rule) == "ratio":
            operands = ratio_operand_ids(self.metric_rule)
            source = self.metric_rule.get("source")
            result["kind"] = "ratio"
            result["numerator_metric_id"] = operands[0] if operands else None
            result["denominator_metric_id"] = operands[1] if operands else None
            result["zero_policy"] = (
                source.get("zero_policy") if isinstance(source, dict) else None
            )
        return result

    @property
    def searchable_text(self) -> str:
        """label·aliases·definition을 결합해 정적 키워드 사전 없이 Unicode lexical matching에 사용할 문자열을 만든다."""
        return " ".join((self.label, *self.aliases, self.definition))


@dataclass(frozen=True)
class GlossaryDimensionMemberTerm:
    """승인 Dimension Member의 canonical value와 DataHub native governance receipt다."""

    id: str
    dimension_id: str
    urn: str
    label: str
    aliases: tuple[str, ...]
    definition: str
    canonical_value: str
    version: str
    checksum: str
    catalog_checksum: str
    owner_urns: frozenset[str]
    domain_urn: str
    lifecycle_urn: str


@dataclass(frozen=True)
class GovernedDataset:
    """한 dataset의 release fingerprint, entitlement, schema, metric, join·time·query 정책을 불변으로 묶는다."""
    contract_version: str
    urn: str
    fqn: str
    name: str
    description: str
    context_release: str
    policy_version: str
    catalog_checksum: str
    manifest_checksum: str
    release_manifest: dict[str, Any]
    semantic_checksum: str
    schema_context_version: str
    governance_urns: dict[str, Any]
    catalog_asset: dict[str, Any]
    schema_hash: str
    table_type: str
    trino_schema_checksum: str
    trino_schema_columns: tuple[dict[str, Any], ...]
    schema_version: str
    seed_version: str
    synthetic: bool
    allowed_roles: frozenset[str]
    allowed_domains: frozenset[str]
    grain: dict[str, Any]
    columns: tuple[dict[str, Any], ...]
    field_terms: dict[str, frozenset[str]]
    dataset_terms: frozenset[str]
    metrics: tuple[dict[str, Any], ...]
    metric_rules: tuple[dict[str, Any], ...]
    dimensions: tuple[dict[str, Any], ...]
    join_graph: dict[str, Any]
    time_metadata: dict[str, Any]
    time_rules: dict[str, Any]
    parameter_contract: dict[str, Any]
    query_policy: dict[str, Any]
    owner_urns: frozenset[str]
    domain_urn: str
    lifecycle_urn: str

    @property
    def metric_term_urns(self) -> frozenset[str]:
        """dataset metric이 참조하는 Glossary Term URN 집합을 중복 없는 불변 값으로 반환한다."""
        return frozenset(
            str(metric["term_urn"])
            for metric in self.metrics
            if isinstance(metric.get("term_urn"), str)
        )

    def entitled(self, context: dict[str, Any]) -> bool:
        """요청 role 또는 domain 중 하나가 DataHub entitlement와 일치할 때만 asset 접근을 허용한다."""
        raw_role = context.get("role")
        role = str(getattr(raw_role, "value", raw_role) or "")
        raw_domains = context.get("domains") or ()
        domains = (
            {str(item) for item in raw_domains}
            if isinstance(raw_domains, (list, tuple, set, frozenset))
            else set()
        )
        decisions = []
        if self.allowed_roles:
            decisions.append(role_is_entitled(role, self.allowed_roles))
        if self.allowed_domains:
            decisions.append(bool(self.allowed_domains & domains))
        return any(decisions)

    def candidate_asset(
        self,
        terms: dict[str, GlossaryMetricTerm],
        join_ids: tuple[str, ...],
        join_graph: dict[str, Any],
        request_context: dict[str, Any],
    ) -> dict[str, Any]:
        """실행 파라미터를 요구하지 않는 Node 1용 최소권한 후보 projection을 반환한다."""

        return self._project_asset(
            terms,
            join_ids,
            join_graph,
            parameters=None,
            request_context=request_context,
        )

    def runtime_asset(
        self,
        terms: dict[str, GlossaryMetricTerm],
        join_ids: tuple[str, ...],
        join_graph: dict[str, Any],
        parameters: dict[str, Any],
        request_context: dict[str, Any],
    ) -> dict[str, Any]:
        """검증된 term·join·typed parameter를 결합해 SQL 생성기가 소비할 asset context를 만든다."""

        return self._project_asset(
            terms,
            join_ids,
            join_graph,
            parameters=parameters,
            request_context=request_context,
        )

    def _project_asset(
        self,
        terms: dict[str, GlossaryMetricTerm],
        join_ids: tuple[str, ...],
        join_graph: dict[str, Any],
        *,
        parameters: dict[str, Any] | None,
        request_context: dict[str, Any],
    ) -> dict[str, Any]:
        """후보와 실행 projection의 공통 필드를 만들고 실행 단계에서만 필터 값을 바인딩한다."""

        parameter_types = _parameter_types(self.parameter_contract)
        raw_role = request_context.get("role")
        role = str(getattr(raw_role, "value", raw_role) or "")
        metrics = []
        for raw in self.metrics:
            if not runtime_metric_permitted(raw, role):
                continue
            term_urn = raw.get("term_urn")
            term = terms.get(str(term_urn)) if isinstance(term_urn, str) else None
            if raw.get("visibility") == "BUSINESS" and term is None:
                raise GovernedMetadataError(
                    "DataHub business metric is missing its Glossary term"
                )
            filters = (
                []
                if parameters is None
                else [
                    _runtime_filter(item, parameter_types, parameters)
                    for item in raw["required_filters"]
                ]
            )
            raw_rule = raw.get("metric_rule")
            raw_governance = (
                raw_rule.get("governance")
                if isinstance(raw_rule, dict)
                else None
            )
            semantic = (
                raw_governance.get("semantic")
                if isinstance(raw_governance, dict)
                else None
            )
            metrics.append(
                {
                    "id": raw["id"],
                    "asset_fqn": self.fqn,
                    "field": raw["field"],
                    "aggregation": raw["aggregation"],
                    "time_field": raw["time_field"],
                    "result_field": raw["result_field"],
                    "unit": str(raw.get("unit") or (term.unit if term else "")),
                    "reduction": raw["reduction"],
                    "dimensions": [dict(item) for item in raw["dimensions"]],
                    "required_filters": filters,
                    "visibility": raw["visibility"],
                    "governance_version": raw["governance_version"],
                    "allowed_roles": list(raw["allowed_roles"]),
                    "contains_pii": raw["contains_pii"],
                    "allowed_join_ids": list(raw["allowed_join_ids"]),
                    "join_required": raw["join_required"],
                    "query_strategies": list(raw["query_strategies"]),
                    # SUPPORT 지표는 Glossary Term을 발행하지 않지만, 검증된 v2 rule의
                    # 의미 정보는 resolver가 "미지원 지표"를 식별하는 데 필요하다.
                    # 계산식·권한·물리 필드는 노출하지 않고 semantic projection만 전달한다.
                    "semantic": clone_mapping(semantic) if isinstance(semantic, dict) else None,
                }
            )
        dimensions = self._project_dimensions(metrics)
        return {
            "urn": self.urn,
            "fqn": self.fqn,
            "name": self.name,
            "description": self.description,
            "schema_version": self.schema_version,
            "seed_version": self.seed_version,
            "synthetic": self.synthetic,
            "context_release": self.context_release,
            "policy_version": self.policy_version,
            "contract_version": self.contract_version,
            "grain": dict(self.grain),
            "join_ids": list(join_ids),
            "join_graph": clone_mapping(join_graph),
            "metrics": metrics,
            "entitled_metric_ids": sorted(
                item["id"] for item in metrics if item["visibility"] == "BUSINESS"
            ),
            "dimensions": dimensions,
            "required_filters": [],
            "time_metadata": clone_mapping(self.time_metadata),
            "query_policy": clone_mapping(self.query_policy),
        }

    def _project_dimensions(
        self,
        metrics: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Metric binding에 선언된 local typed dimension을 후보 projection에 보완한다.

        전역 dimension registry를 바꾸지 않는다. 현재 dataset의 실행 Metric이 실제로
        선언한 필드 중 typed catalog column role이 ``dimension``이거나 grain key
        ``identifier``인 필드만 release-bound lexical evidence와 함께 추가한다. 컬럼은
        하나의 role만 가질 수 있으므로, metric이 명시적으로 dimension으로 결속한 grain
        key까지 거부하면 승인된 다중 grain metric을 후보로 만들 수 없다. 임의 attribute는
        계속 열지 않는다.
        """

        result = [clone_mapping(item) for item in self.dimensions]
        existing_fields = {
            (str(item.get("asset_fqn") or ""), str(item.get("column") or ""))
            for item in result
        }
        typed_columns = {
            str(item.get("name") or ""): item
            for item in self.catalog_asset.get("columns", ())
            if isinstance(item, dict) and item.get("name")
        }
        declared_fields = {
            (str(item.get("asset_fqn") or ""), str(item.get("column") or ""))
            for metric in metrics
            for item in metric.get("dimensions", ())
            if isinstance(item, dict)
        }
        for asset_fqn, column in sorted(declared_fields):
            if asset_fqn != self.fqn or (asset_fqn, column) in existing_fields:
                continue
            typed = typed_columns.get(column)
            description = typed.get("description") if isinstance(typed, dict) else None
            if (
                not isinstance(typed, dict)
                or typed.get("role") not in {"dimension", "identifier"}
                or not isinstance(description, str)
                or not description.strip()
            ):
                raise GovernedMetadataError(
                    "Metric dimension lacks a typed governed catalog column"
                )
            identity = f"{asset_fqn}.{column}"
            aliases = list(
                dict.fromkeys(
                    value
                    for value in (
                        column,
                        column.replace("_", " "),
                        description.strip(),
                    )
                    if value
                )
            )
            result.append(
                {
                    "id": f"{DERIVED_DIMENSION_ID_PREFIX}{sha256(identity.encode('utf-8')).hexdigest()[:16]}",
                    "aliases": aliases,
                    "definition": description.strip(),
                    "asset_fqn": asset_fqn,
                    "column": column,
                }
            )
            existing_fields.add((asset_fqn, column))
        if len(result) > 64:
            raise GovernedMetadataError(
                "Projected DataHub dimensions exceed the bounded contract"
            )
        return result

    def schema_payload(self) -> dict[str, Any]:
        """검증된 dataset URN과 column 계약의 방어적 복사본을 schema 조회 응답으로 반환한다."""
        return {
            "urn": self.urn,
            "columns": [dict(item) for item in self.columns],
        }


def _parameter_types(contract: dict[str, Any]) -> dict[str, str]:
    values = contract.get("parameters")
    if contract.get("style") != "named" or not isinstance(values, list):
        raise GovernedMetadataError("DataHub parameter contract is invalid")
    return {
        str(item["name"]): str(item["type"])
        for item in values
        if isinstance(item, dict) and item.get("scope") == "filter"
    }


def _runtime_filter(
    value: dict[str, Any],
    parameter_types: dict[str, str],
    parameters: dict[str, Any],
) -> dict[str, Any]:
    name = str(value["parameter"])
    value_type = parameter_types.get(name)
    if name not in parameters or value_type is None:
        raise GovernedMetadataError(
            f"required governed parameter {name!r} is unavailable"
        )
    raw_value = parameters[name]
    if not _typed_value_is_valid(value_type, raw_value):
        raise GovernedMetadataError(
            f"required governed parameter {name!r} has an invalid type"
        )
    return {
        "field": value["field"],
        "operator": value["operator"],
        "parameter": name,
        "value_type": value_type,
        "value": raw_value,
    }


def metric_rule_projection(
    dataset: GovernedDataset,
    metric: dict[str, Any],
    term: GlossaryMetricTerm,
) -> dict[str, Any]:
    """dataset 내부 metric을 Glossary Term의 canonical 계산 규칙 shape로 투영해 checksum 비교 입력을 만든다."""
    published_rule = metric.get("metric_rule")
    if isinstance(published_rule, dict):
        return clone_mapping(published_rule)
    return {
        "id": metric["id"],
        "source": {
            "kind": "column",
            "field": {"asset_fqn": dataset.fqn, "column": metric["field"]},
        },
        "aggregation": metric["aggregation"],
        "result_field": metric["result_field"],
        "unit": term.unit,
        "time_field": {
            "asset_fqn": dataset.fqn,
            "column": metric["time_field"],
        },
        "reduction": metric["reduction"],
        "dimensions": [dict(item) for item in metric["dimensions"]],
        "required_filters": [
            {
                "field": {"asset_fqn": dataset.fqn, "column": item["field"]},
                "operator": item["operator"],
                "parameter": item["parameter"],
            }
            for item in metric["required_filters"]
        ],
    }


def metric_rule_matches(
    dataset: GovernedDataset,
    metric: dict[str, Any],
    term: GlossaryMetricTerm,
) -> bool:
    """runtime metric 투영과 Glossary metric rule의 canonical JSON이 완전히 동일한지 비교한다."""
    return canonical_json(metric_rule_projection(dataset, metric, term)) == canonical_json(
        term.metric_rule
    )
