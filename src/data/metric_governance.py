"""Metric Rule 버전과 DataHub runtime property 집합의 공통 권위 계약이다.

publisher, live read-back, Backend가 같은 exact key 집합으로 v1과 v2를 구분한다.
v2는 질문 문구가 아니라 발행된 ``governance`` metadata만으로 노출·권한·실행
정책을 결정하며, 일부 필드만 추가된 혼합 rule은 지원 버전으로 간주하지 않는다.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any


RUNTIME_GOVERNANCE_VERSION_V1 = "ANSWERVICE-RUNTIME-GOVERNANCE-v1"
RUNTIME_GOVERNANCE_VERSION_V2 = "ANSWERVICE-RUNTIME-GOVERNANCE-v2"
RUNTIME_GOVERNANCE_VERSION = RUNTIME_GOVERNANCE_VERSION_V2
SUPPORTED_RUNTIME_GOVERNANCE_VERSIONS = frozenset(
    {RUNTIME_GOVERNANCE_VERSION_V1, RUNTIME_GOVERNANCE_VERSION_V2}
)
RATIO_ZERO_POLICIES = frozenset({"null_on_zero_denominator"})

DATASET_RUNTIME_PROPERTY_KEYS_V1 = frozenset(
    {
        "contract_version",
        "approval_status",
        "catalog_version",
        "catalog_sha256",
        "schema_context_version",
        "governance_urns",
        "release_manifest",
        "manifest_sha256",
        "fqn",
        "policy_version",
        "schema_version",
        "seed_version",
        "synthetic",
        "entitlements",
        "grain",
        "typed_columns",
        "column_roles",
        "metrics",
        "dimensions",
        "join_graph",
        "time_rules",
        "parameter_contract",
        "query_policy",
    }
)
DATASET_RUNTIME_PROPERTY_KEYS_V2 = DATASET_RUNTIME_PROPERTY_KEYS_V1 | frozenset(
    {"metric_rules"}
)
DATASET_RUNTIME_PROPERTY_KEYS = DATASET_RUNTIME_PROPERTY_KEYS_V2
TERM_RUNTIME_PROPERTY_KEYS = frozenset(
    {
        "metric_id",
        "aliases",
        "approval_status",
        "catalog_sha256",
        "glossary_sha256",
        "glossary_version",
        "metric_rule",
        "unit",
    }
)

METRIC_RULE_KEYS_V1 = frozenset(
    {
        "id",
        "source",
        "aggregation",
        "result_field",
        "unit",
        "time_field",
        "reduction",
        "dimensions",
        "required_filters",
    }
)
METRIC_RULE_KEYS_V2 = METRIC_RULE_KEYS_V1 | frozenset({"governance"})
METRIC_VISIBILITIES = frozenset({"BUSINESS", "SUPPORT"})
QUERY_STRATEGIES = frozenset(
    {"VIEW_REUSE", "VIEW_COMPOSE", "RAW_APPROVED_DETAIL"}
)


def metric_rule_contract_version(metric: Mapping[str, Any]) -> str:
    """Metric Rule exact key 집합에서 v1 또는 v2를 판정하고 혼합 shape는 거부한다."""

    keys = frozenset(metric)
    if keys == METRIC_RULE_KEYS_V1:
        return RUNTIME_GOVERNANCE_VERSION_V1
    if keys == METRIC_RULE_KEYS_V2:
        return RUNTIME_GOVERNANCE_VERSION_V2
    raise ValueError("metric rule fields do not match a supported governance version")


def metric_contract_version(metrics: Iterable[Mapping[str, Any]]) -> str:
    """한 release의 모든 Metric Rule이 공유하는 단일 runtime 계약 버전을 반환한다."""

    versions = {metric_rule_contract_version(metric) for metric in metrics}
    if len(versions) != 1:
        raise ValueError("one semantic release cannot mix metric governance versions")
    try:
        return next(iter(versions))
    except StopIteration as error:
        raise ValueError("semantic release requires at least one metric rule") from error


def runtime_governance_version(bundle: Mapping[str, Any]) -> str:
    """검증 bundle의 Metric Rule 집합에서 DataHub runtime property 버전을 계산한다."""

    values = bundle.get("metric_rules")
    if not isinstance(values, list) or any(not isinstance(item, Mapping) for item in values):
        raise ValueError("semantic bundle metric rules are unavailable")
    return metric_contract_version(values)


def dataset_runtime_property_keys(version: str) -> frozenset[str]:
    """명시된 runtime 버전이 허용하는 dataset custom property exact set을 반환한다."""

    if version == RUNTIME_GOVERNANCE_VERSION_V1:
        return DATASET_RUNTIME_PROPERTY_KEYS_V1
    if version == RUNTIME_GOVERNANCE_VERSION_V2:
        return DATASET_RUNTIME_PROPERTY_KEYS_V2
    raise ValueError("runtime governance version is unsupported")


def metric_governance(metric: Mapping[str, Any]) -> Mapping[str, Any] | None:
    """v2 Rule의 governance 객체를 반환하며 v1 Rule은 명시적으로 ``None``을 반환한다."""

    if metric_rule_contract_version(metric) == RUNTIME_GOVERNANCE_VERSION_V1:
        return None
    value = metric.get("governance")
    if not isinstance(value, Mapping):
        raise ValueError("v2 metric governance must be an object")
    return value


def metric_visibility(metric: Mapping[str, Any]) -> str:
    """v1은 기존 공개 Metric으로, v2는 선언된 BUSINESS/SUPPORT visibility로 해석한다."""

    governance = metric_governance(metric)
    if governance is None:
        return "BUSINESS"
    value = governance.get("visibility")
    if value not in METRIC_VISIBILITIES:
        raise ValueError("metric visibility is invalid")
    return str(value)


def business_metric_ids(metrics: Iterable[Mapping[str, Any]]) -> frozenset[str]:
    """Glossary Term을 가져야 하는 BUSINESS Metric ID 집합을 반환한다."""

    return frozenset(
        str(metric["id"])
        for metric in metrics
        if metric_visibility(metric) == "BUSINESS"
    )
