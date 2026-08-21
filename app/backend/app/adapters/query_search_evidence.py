"""DataHub 검색 증거의 Unicode ranking과 derived Metric runtime projection을 담당한다."""

from __future__ import annotations

import asyncio
import unicodedata
from typing import Any, Mapping

from app.adapters.datahub_metric_governance import (
    runtime_metric_permitted,
    runtime_metric_policy,
)
from app.adapters.datahub_metadata_types import GlossaryMetricTerm
from src.data.governance_contract import metric_source_kind, ratio_operand_ids


async def gather_snapshot_and_semantic(loader, catalog, query):
    """같은 요청의 catalog snapshot과 semantic search 결과를 병렬로 읽는다."""

    return tuple(
        await asyncio.gather(loader.load(), catalog.semantic_search(query))
    )


def ranked_matches(query_tokens, datasets, terms, semantic_hits):
    """어휘 overlap과 DataHub semantic rank를 결합해 Dataset 후보를 정렬한다."""

    semantic_rank = {hit.urn: index for index, hit in enumerate(semantic_hits)}
    ranked = []
    for dataset in datasets:
        asset_tokens = _dataset_tokens(dataset, terms)
        overlap = len(query_tokens & asset_tokens)
        rank = semantic_rank.get(dataset.urn)
        if overlap or rank is not None:
            score = (rank is not None, overlap, -(rank or 0), dataset.fqn)
            ranked.append((score, dataset))
    return tuple(
        item for item in sorted(ranked, key=lambda item: item[0], reverse=True)
    )


def with_ratio_metrics(assets, terms, context):
    """권한 있는 두 operand가 모두 있을 때만 공개 ratio를 runtime 후보로 투영한다."""

    result = []
    metric_asset_indexes: dict[str, int] = {}
    for index, asset in enumerate(assets):
        item = dict(asset)
        metrics = [dict(metric) for metric in asset.get("metrics", ())]
        item["metrics"] = metrics
        result.append(item)
        for metric in metrics:
            metric_id = str(metric.get("id") or "")
            if metric_id:
                metric_asset_indexes[metric_id] = index
    raw_role = context.get("role")
    role = str(getattr(raw_role, "value", raw_role) or "")
    for term in sorted(terms.values(), key=lambda item: item.id):
        if metric_source_kind(term.metric_rule) != "ratio":
            continue
        operands = ratio_operand_ids(term.metric_rule)
        source = term.metric_rule.get("source")
        policy = runtime_metric_policy(term.metric_rule)
        if (
            operands is None
            or not isinstance(source, dict)
            or any(operand not in metric_asset_indexes for operand in operands)
            or policy["visibility"] != "BUSINESS"
            or not runtime_metric_permitted(policy, role)
        ):
            continue
        carrier = metric_asset_indexes[operands[0]]
        result[carrier]["metrics"].append(
            {
                "id": term.id,
                "asset_fqn": "",
                "field": "",
                "aggregation": "ratio",
                "time_field": "",
                "required_filters": [],
                "result_field": term.metric_rule["result_field"],
                "unit": term.unit,
                "reduction": "ratio",
                "numerator_metric_id": operands[0],
                "denominator_metric_id": operands[1],
                "zero_policy": source["zero_policy"],
                **policy,
            }
        )
    for asset in result:
        asset["entitled_metric_ids"] = sorted(
            str(metric["id"])
            for metric in asset["metrics"]
            if metric.get("visibility", "BUSINESS") == "BUSINESS"
        )
    return result


def compact_candidate_assets(
    assets: list[dict[str, Any]],
    terms: Mapping[str, GlossaryMetricTerm],
    query_tokens: frozenset[str],
    asset_priorities: Mapping[str, int],
    max_candidate_metrics: int,
    preferred_metric_ids: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    """DataHub 용어 증거가 강한 Metric만 선택 후보로 남기고 계산 의존성은 비선택 실행 항목으로 보존한다."""

    metric_records = [
        (asset, metric)
        for asset in assets
        for metric in asset.get("metrics", ())
        if isinstance(metric, dict) and isinstance(metric.get("id"), str)
    ]
    metrics_by_id = {str(metric["id"]): metric for _asset, metric in metric_records}
    ranked = sorted(
        (
            (
                len(query_tokens & _metric_tokens(metric, terms.get(str(metric["id"])))),
                int(asset_priorities.get(str(asset.get("fqn") or ""), 0)),
                str(metric["id"]),
            )
            for asset, metric in metric_records
        ),
        key=lambda item: (-item[0], -item[1], item[2]),
    )
    direct = [item for item in ranked if item[0] > 0]
    preferred = tuple(
        dict.fromkeys(
            metric_id
            for metric_id in preferred_metric_ids
            if metric_id in metrics_by_id
            and metrics_by_id[metric_id].get("visibility", "BUSINESS")
            == "BUSINESS"
        )
    )
    ranked_business_ids = [
        metric_id
        for _overlap, _priority, metric_id in (direct or ranked)
        if metrics_by_id[metric_id].get("visibility", "BUSINESS") == "BUSINESS"
        and metric_id not in preferred
    ]
    selectable_ids = set(preferred)
    selectable_ids.update(
        ranked_business_ids[: max(0, max_candidate_metrics - len(preferred))]
    )
    strongest_business_overlap = max(
        (
            overlap
            for overlap, _priority, metric_id in direct
            if metrics_by_id[metric_id].get("visibility", "BUSINESS")
            == "BUSINESS"
        ),
        default=0,
    )
    directly_matched_support_ids = [
        metric_id
        for overlap, _priority, metric_id in direct
        if metrics_by_id[metric_id].get("visibility") == "SUPPORT"
        and overlap >= strongest_business_overlap
    ]
    selectable_ids.update(
        directly_matched_support_ids[:max_candidate_metrics]
    )

    # SUPPORT만 직접 일치해도 Node 1이 "미공개 지표"로 분류할 수 있어야 하지만,
    # 후보 계약에는 사용자가 선택할 수 있는 BUSINESS Metric도 최소 하나 있어야 한다.
    if not any(
        metrics_by_id[metric_id].get("visibility", "BUSINESS") == "BUSINESS"
        for metric_id in selectable_ids
    ):
        fallback = next(
            (
                metric_id
                for _overlap, _priority, metric_id in ranked
                if metrics_by_id[metric_id].get("visibility", "BUSINESS")
                == "BUSINESS"
            ),
            None,
        )
        if fallback is not None:
            selectable_ids.add(fallback)

    execution_ids = set(selectable_ids)
    for metric_id in tuple(selectable_ids):
        term = terms.get(metric_id)
        operands = ratio_operand_ids(term.metric_rule) if term is not None else None
        if operands is not None:
            execution_ids.update(operands)

    dimension_fields: set[tuple[str, str]] = set()
    for metric_id in selectable_ids:
        metric = metrics_by_id.get(metric_id)
        if metric is None or metric.get("visibility", "BUSINESS") != "BUSINESS":
            continue
        dimension_fields.update(
            _metric_dimension_fields(metric_id, metrics_by_id, terms, frozenset())
        )

    result: list[dict[str, Any]] = []
    for asset in assets:
        item = dict(asset)
        metrics = []
        for raw_metric in asset.get("metrics", ()):
            if not isinstance(raw_metric, dict):
                continue
            metric_id = str(raw_metric.get("id") or "")
            if metric_id not in execution_ids:
                continue
            metric = dict(raw_metric)
            metric["candidate_selectable"] = metric_id in selectable_ids
            metrics.append(metric)
        item["metrics"] = metrics
        item["entitled_metric_ids"] = sorted(
            str(metric["id"])
            for metric in metrics
            if metric.get("visibility", "BUSINESS") == "BUSINESS"
            and metric.get("candidate_selectable") is True
        )
        item["dimensions"] = [
            dict(dimension)
            for dimension in asset.get("dimensions", ())
            if isinstance(dimension, dict)
            and (
                str(dimension.get("asset_fqn") or asset.get("fqn") or ""),
                str(dimension.get("column") or dimension.get("field") or ""),
            )
            in dimension_fields
        ]
        result.append(item)
    return result


def unicode_tokens(value: str) -> frozenset[str]:
    """Unicode 문자·숫자를 언어 중립 token으로 만들고 한국어 조사를 보조 분리한다."""

    normalized = unicodedata.normalize("NFKC", value).casefold()
    tokens: list[str] = []
    current: list[str] = []
    for character in normalized:
        category = unicodedata.category(character)
        if category[:1] in {"L", "N", "M"} or character == "_":
            current.append(character)
        elif current:
            tokens.append("".join(current))
            current = []
    if current:
        tokens.append("".join(current))
    particles = (
        "에서는", "에서", "으로", "에는", "별로", "마다", "부터", "까지",
        "은", "는", "이", "가", "을", "를", "의", "에", "로", "별", "도", "과", "와", "만",
    )
    expanded = set(tokens)
    for token in tokens:
        for particle in particles:
            if len(token) > len(particle) + 1 and token.endswith(particle):
                expanded.add(token[:-len(particle)])
                break
    return frozenset(expanded)


def _dataset_tokens(dataset, terms):
    values = [dataset.name, dataset.description, dataset.fqn]
    values.extend(str(column["name"]) for column in dataset.columns)
    values.extend(
        term.searchable_text
        for term in terms.values()
        if term.urn in dataset.dataset_terms
    )
    for dimension in dataset.dimensions:
        if dimension.get("asset_fqn") == dataset.fqn:
            values.extend(map(str, dimension.get("aliases", ())))
    # SUPPORT metric은 사용자 선택용 Glossary Term이 없지만, 사용자가 그 값을 직접
    # 요청했을 때 올바른 자산까지 recall해야 typed availability 오류를 줄 수 있다.
    # 검증된 local metric rule의 semantic만 검색 증거로 사용한다.
    for metric in dataset.metrics:
        rule = metric.get("metric_rule")
        governance = rule.get("governance") if isinstance(rule, dict) else None
        semantic = governance.get("semantic") if isinstance(governance, dict) else None
        if isinstance(semantic, dict):
            values.append(str(semantic.get("name") or ""))
            values.append(str(semantic.get("definition") or ""))
            aliases = semantic.get("aliases")
            if isinstance(aliases, (list, tuple)):
                values.extend(map(str, aliases))
    return unicode_tokens(" ".join(values))


def _metric_tokens(
    metric: Mapping[str, Any],
    term: GlossaryMetricTerm | None,
) -> frozenset[str]:
    """Metric ID와 DataHub Glossary/승인 SUPPORT semantic만 후보 ranking용 token으로 만든다."""

    values = [str(metric.get("id") or ""), str(metric.get("result_field") or "")]
    if term is not None:
        values.append(term.searchable_text)
    semantic = metric.get("semantic")
    if isinstance(semantic, Mapping):
        values.extend(
            (
                str(semantic.get("name") or ""),
                str(semantic.get("definition") or ""),
            )
        )
        aliases = semantic.get("aliases")
        if isinstance(aliases, (list, tuple)):
            values.extend(map(str, aliases))
    return unicode_tokens(" ".join(values))


def _metric_dimension_fields(
    metric_id: str,
    metrics_by_id: Mapping[str, Mapping[str, Any]],
    terms: Mapping[str, GlossaryMetricTerm],
    visiting: frozenset[str],
) -> set[tuple[str, str]]:
    """column Metric 차원 또는 ratio operand 공통 차원을 후보용 qualified field 집합으로 계산한다."""

    metric = metrics_by_id.get(metric_id)
    if metric is None or metric_id in visiting:
        return set()
    term = terms.get(metric_id)
    operands = ratio_operand_ids(term.metric_rule) if term is not None else None
    if operands is not None:
        scopes = [
            _metric_dimension_fields(
                operand_id,
                metrics_by_id,
                terms,
                visiting | {metric_id},
            )
            for operand_id in operands
        ]
        return set.intersection(*scopes)
    return {
        (str(item.get("asset_fqn") or ""), str(item.get("column") or ""))
        for item in metric.get("dimensions", ())
        if isinstance(item, Mapping)
        and str(item.get("asset_fqn") or "")
        and str(item.get("column") or "")
    }
