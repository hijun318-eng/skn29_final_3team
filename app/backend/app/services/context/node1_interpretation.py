"""Node1에 전달할 최소 권한·release-bound 해석 Context를 만든다.

DataHub 문자열은 모두 비신뢰 data다. 이 모듈은 승인된 runtime projection의 필드만
allowlist하고 길이·control character·prompt-injection 표식을 검사한다. Node1의 출력은
여전히 실행 권위가 아니며 이후 active projection에서 다시 결속한다.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from app.authorization import permission_snapshot_id
from app.contracts import RequestContext
from app.ports.data_platform import AssetCandidateSet, MetadataUnavailableError


NODE1_INTERPRETATION_CONTEXT_VERSION = "Node1InterpretationContext.v1"

_ALLOWED_AUTHORITIES = frozenset(
    {
        "DATAHUB_NATIVE_METRIC_V1",
        "DATAHUB_GLOSSARY_MIGRATION_V1",
    }
)
_ALLOWED_RETRIEVAL_MODES = frozenset(
    {"lexical", "lexical_shadow", "datahub_lexical", "hybrid"}
)
_INJECTION_MARKERS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"ignore\s+(?:all\s+)?(?:previous|prior)\s+instructions?",
        r"(?:system|developer)\s+(?:prompt|message)",
        r"(?:reveal|print|return)\s+(?:the\s+)?(?:prompt|secret|token)",
        r"<\|(?:system|assistant|developer)\|>",
        r"\[/?INST\]",
        r"이전\s*(?:지시|명령).*무시",
        r"시스템\s*프롬프트",
        r"비밀(?:값|키|정보).*출력",
    )
)


def build_node1_interpretation_context(
    candidates: AssetCandidateSet,
    context: RequestContext,
    metric_terms: Mapping[str, Mapping[str, object]],
    dimension_terms: Mapping[str, Mapping[str, object]],
) -> dict[str, Any]:
    """Entitlement 뒤 후보를 하나의 strict Node1 data context로 봉인한다."""

    if (
        candidates.product_release_id is None
        or candidates.runtime_projection_checksum is None
        or candidates.source_authority not in _ALLOWED_AUTHORITIES
        or candidates.retrieval_mode not in _ALLOWED_RETRIEVAL_MODES
    ):
        raise MetadataUnavailableError(
            "Node1 candidate release, source authority, or retrieval evidence is incomplete"
        )
    if context.product_release_id not in {None, candidates.product_release_id}:
        raise MetadataUnavailableError("Node1 candidate product release changed")
    if context.semantic_release_id not in {None, candidates.context_release}:
        raise MetadataUnavailableError("Node1 candidate semantic release changed")

    permission_receipt = (
        context.permission_snapshot_id
        or permission_snapshot_id(context.user_id, context.role)
    )
    if not permission_receipt or len(permission_receipt) > 160:
        raise MetadataUnavailableError("Node1 permission receipt is invalid")

    assets_by_fqn: dict[str, Mapping[str, object]] = {}
    assets_by_urn: dict[str, Mapping[str, object]] = {}
    metric_records: dict[str, tuple[Mapping[str, object], Mapping[str, object]]] = {}
    for asset in candidates.assets:
        fqn = _safe_text(asset.get("fqn"), "asset fqn", 256)
        urn = _safe_urn(asset.get("urn"), "asset urn")
        if fqn in assets_by_fqn or urn in assets_by_urn:
            raise MetadataUnavailableError("Node1 candidate asset identity is duplicated")
        assets_by_fqn[fqn] = asset
        assets_by_urn[urn] = asset
        for raw_metric in asset.get("metrics", ()):
            if not isinstance(raw_metric, Mapping):
                raise MetadataUnavailableError("Node1 candidate Metric is invalid")
            metric_id = raw_metric.get("id")
            if not isinstance(metric_id, str) or not metric_id.strip():
                raise MetadataUnavailableError("Node1 candidate Metric identity is invalid")
            if metric_id in metric_records:
                raise MetadataUnavailableError("Node1 candidate Metric identity is duplicated")
            metric_records[metric_id] = (asset, raw_metric)

    selectable = {
        metric_id: record
        for metric_id, record in metric_records.items()
        if record[1].get("visibility", "BUSINESS") == "BUSINESS"
        and record[1].get("candidate_selectable") is True
    }
    if not selectable or set(metric_terms) != set(selectable):
        raise MetadataUnavailableError(
            "Node1 interpretation Metric membership differs from the candidate projection"
        )

    ranks: dict[str, int] = {}
    for metric_id, (_asset, metric) in selectable.items():
        rank = metric.get("candidate_rank")
        if isinstance(rank, bool) or not isinstance(rank, int) or rank < 1:
            raise MetadataUnavailableError("Node1 retrieval rank is missing or invalid")
        ranks[metric_id] = rank
    if len(ranks) != len(set(ranks.values())):
        raise MetadataUnavailableError("Node1 retrieval ranks are duplicated")

    dimensions = _dimensions(dimension_terms, assets_by_fqn)
    dimension_by_field = {
        (
            str(term["field"]["asset_fqn"]),
            str(term["field"]["column"]),
        ): identifier
        for identifier, term in dimension_terms.items()
    }
    metrics = [
        _metric_context(
            metric_id,
            selectable[metric_id][0],
            selectable[metric_id][1],
            metric_terms[metric_id],
            dimension_by_field,
            str(candidates.source_authority),
        )
        for metric_id in sorted(selectable, key=lambda item: (ranks[item], item))
    ]
    return {
        "schema_version": NODE1_INTERPRETATION_CONTEXT_VERSION,
        "source_authority": candidates.source_authority,
        "release_evidence": {
            "product_release_id": candidates.product_release_id,
            "semantic_release_id": candidates.context_release,
            "catalog_sha256": candidates.catalog_checksum,
            "canonical_sha256": candidates.canonical_checksum,
            "runtime_projection_sha256": candidates.runtime_projection_checksum,
        },
        "permission_snapshot_id": permission_receipt,
        "retrieval_evidence": {
            "mode": candidates.retrieval_mode,
            "asset_urns": sorted(assets_by_urn),
            "metric_ranks": [
                {"metric_id": metric_id, "rank": ranks[metric_id]}
                for metric_id in sorted(ranks, key=lambda item: (ranks[item], item))
            ],
        },
        "metrics": metrics,
        "dimensions": dimensions,
    }


def _metric_context(
    metric_id: str,
    asset: Mapping[str, object],
    metric: Mapping[str, object],
    term: Mapping[str, object],
    dimension_by_field: Mapping[tuple[str, str], str],
    source_authority: str,
) -> dict[str, Any]:
    if term.get("id") != metric_id:
        raise MetadataUnavailableError("Node1 Metric and Glossary identity differ")
    aliases = _safe_texts(term.get("aliases"), "Metric synonym", 80, 32)
    label = _safe_text(term.get("label"), "Metric label", 160)
    synonyms = list(dict.fromkeys((label, *aliases)))
    metadata = asset.get("time_metadata")
    if not isinstance(metadata, Mapping):
        raise MetadataUnavailableError("Node1 Metric time metadata is missing")
    raw_mode = metadata.get("mode")
    if raw_mode is None and all(
        isinstance(metadata.get(name), str) and str(metadata[name]).strip()
        for name in ("start_parameter", "end_parameter")
    ):
        raw_mode = "range"
    mode = _safe_text(raw_mode, "Metric time mode", 64)
    calendar_id = _safe_text(metadata.get("calendar_id"), "Metric calendar", 128)
    raw_time_field = metric.get("time_field")
    time_field = (
        _safe_text(raw_time_field, "Metric time field", 128)
        if isinstance(raw_time_field, str) and raw_time_field.strip()
        else None
    )
    allowed_dimension_ids = _metric_dimension_ids(metric, dimension_by_field)
    return {
        "datahub_urn": _metric_source_urn(metric, source_authority),
        "canonical_id": _safe_text(metric_id, "Metric canonical ID", 128),
        "canonical_name": _safe_text(term.get("id"), "Metric canonical name", 128),
        "label": label,
        "definition": _safe_text(term.get("definition"), "Metric definition", 1200),
        "synonyms": synonyms,
        "unit": _safe_text(term.get("unit"), "Metric unit", 64),
        "aggregation": _safe_text(metric.get("aggregation"), "Metric aggregation", 64),
        "time_semantics": {
            "mode": mode,
            "calendar_id": calendar_id,
            "time_field": time_field,
        },
        "allowed_dimension_ids": allowed_dimension_ids,
        "allowed_filter_ids": list(allowed_dimension_ids),
        "positive_examples": [],
        "negative_examples": [],
        "approval_status": "APPROVED",
        "quality_status": "ACTIVE_RELEASE_VERIFIED",
        "source_authority": source_authority,
    }


def _dimensions(
    dimension_terms: Mapping[str, Mapping[str, object]],
    assets_by_fqn: Mapping[str, Mapping[str, object]],
) -> list[dict[str, Any]]:
    if len(dimension_terms) > 60:
        raise MetadataUnavailableError("Node1 dimension projection exceeds its bound")
    result: list[dict[str, Any]] = []
    for identifier in sorted(dimension_terms):
        term = dimension_terms[identifier]
        field = term.get("field")
        if not isinstance(field, Mapping):
            raise MetadataUnavailableError("Node1 dimension field is missing")
        fqn = _safe_text(field.get("asset_fqn"), "dimension asset fqn", 256)
        asset = assets_by_fqn.get(fqn)
        if asset is None:
            raise MetadataUnavailableError("Node1 dimension is outside candidate assets")
        aliases = _safe_texts(term.get("aliases"), "dimension synonym", 80, 32)
        result.append(
            {
                "canonical_id": _safe_text(identifier, "dimension canonical ID", 128),
                "label": aliases[0],
                "synonyms": list(dict.fromkeys(aliases)),
                "asset_urn": _safe_urn(asset.get("urn"), "dimension asset URN"),
                "column": _safe_text(field.get("column"), "dimension column", 128),
                "filter_allowed": True,
            }
        )
    return result


def _safe_texts(value: object, context: str, maximum: int, count: int) -> list[str]:
    if not isinstance(value, (list, tuple)) or not value or len(value) > count:
        raise MetadataUnavailableError(f"{context} list is invalid")
    result = [_safe_text(item, context, maximum) for item in value]
    if len(result) != len(set(result)):
        raise MetadataUnavailableError(f"{context} list is duplicated")
    return result


def _safe_urn(value: object, context: str) -> str:
    urn = _safe_text(value, context, 512)
    if not urn.startswith("urn:li:"):
        raise MetadataUnavailableError(f"{context} is not a DataHub URN")
    return urn


def _safe_text(value: object, context: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise MetadataUnavailableError(f"{context} must be text")
    if any(ord(character) < 32 for character in value):
        raise MetadataUnavailableError(f"{context} contains a control character")
    normalized = " ".join(value.split())
    if not normalized or len(normalized) > maximum:
        raise MetadataUnavailableError(f"{context} length is invalid")
    if any(pattern.search(normalized) for pattern in _INJECTION_MARKERS):
        raise MetadataUnavailableError(f"{context} failed the injection gate")
    return normalized


def _metric_source_urn(metric: Mapping[str, object], source_authority: str) -> str:
    if metric.get("source_authority") != source_authority:
        raise MetadataUnavailableError("Node1 Metric source authority differs")
    return _safe_urn(metric.get("source_urn"), "Metric DataHub source URN")


def _metric_dimension_ids(
    metric: Mapping[str, object],
    dimension_by_field: Mapping[tuple[str, str], str],
) -> list[str]:
    raw_dimensions = metric.get("dimensions")
    if not isinstance(raw_dimensions, (list, tuple)):
        raise MetadataUnavailableError("Node1 Metric dimension scope is invalid")
    result: list[str] = []
    for field in raw_dimensions:
        if not isinstance(field, Mapping):
            raise MetadataUnavailableError("Node1 Metric dimension field is invalid")
        asset_fqn = _safe_text(field.get("asset_fqn"), "Metric dimension asset", 256)
        column = _safe_text(field.get("column"), "Metric dimension column", 128)
        identifier = dimension_by_field.get((asset_fqn, column))
        if identifier is None:
            # 물리 Metric rule이 참조해도 별도 승인 dimension term이 없는 field는
            # Node1 권한으로 승격하지 않는다. 허용 목록은 두 projection의 교집합이다.
            continue
        result.append(identifier)
    if len(result) != len(set(result)):
        raise MetadataUnavailableError("Node1 Metric dimension scope is duplicated")
    return sorted(result)
