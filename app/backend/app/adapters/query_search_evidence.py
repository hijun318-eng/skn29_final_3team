"""DataHub 검색 증거의 Unicode ranking과 derived Metric runtime projection을 담당한다."""

from __future__ import annotations

import asyncio
import unicodedata

from app.adapters.datahub_metric_governance import (
    runtime_metric_permitted,
    runtime_metric_policy,
)
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
    return unicode_tokens(" ".join(values))
