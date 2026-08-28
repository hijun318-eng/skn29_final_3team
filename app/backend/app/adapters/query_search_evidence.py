"""DataHub 검색 증거의 Unicode ranking과 derived Metric runtime projection을 담당한다."""

from __future__ import annotations

import unicodedata
from typing import Any, Mapping

from app.adapters.datahub_metric_governance import (
    runtime_metric_permitted,
    runtime_metric_policy,
)
from app.adapters.datahub_metadata_types import (
    DERIVED_DIMENSION_ID_PREFIX,
    GlossaryMetricTerm,
)
from src.data.governance_contract import metric_source_kind, ratio_operand_ids


def ranked_matches(
    query_tokens,
    datasets,
    terms,
    semantic_hits,
    *,
    search_only: bool = False,
):
    """DataHub가 돌려준 검색 순위를 우선 신호로, 어휘 overlap을 보조 신호로 Dataset을 정렬한다.

    ``semantic_hits``는 semantic 또는 lexical 검색이 돌려준 순서 그대로의 hit이며 index가
    곧 rank다. Glossary Term hit은 그 용어를 실제로 보유한 dataset으로만 전달해, 검색이
    용어를 맞혔을 때 해당 자산이 후보에 들어오게 한다. 이 함수는 순위만 계산하고 권한은
    보지 않으므로 호출자가 반드시 entitlement filter를 뒤에 적용해야 한다.
    """

    search_rank = {hit.urn: index for index, hit in enumerate(semantic_hits)}
    ranked = []
    for dataset in datasets:
        asset_tokens = _dataset_tokens(dataset, terms)
        overlap = len(query_tokens & asset_tokens)
        rank = min(
            (
                value
                for value in (
                    search_rank.get(dataset.urn),
                    *(
                        search_rank.get(term_urn)
                        for term_urn in dataset.dataset_terms
                    ),
                )
                if value is not None
            ),
            default=None,
        )
        if rank is not None or (overlap and not search_only):
            # 외부 검색을 사용하는 mode에서는 DataHub 반환 rank가 overlap보다
            # 먼저다. overlap은 canonical metadata 검증과 동률 보조 신호일 뿐이다.
            score = (
                rank is not None,
                -(rank if rank is not None else 0),
                overlap,
                dataset.fqn,
            )
            ranked.append((score, dataset))
    return tuple(
        item for item in sorted(ranked, key=lambda item: item[0], reverse=True)
    )


def with_ratio_metrics(assets, terms, context):
    """권한 있는 두 operand가 모두 있을 때만 공개 ratio를 runtime 후보로 투영한다."""

    result = []
    metric_asset_indexes: dict[str, int] = {}
    metrics_by_id: dict[str, dict[str, Any]] = {}
    for index, asset in enumerate(assets):
        item = dict(asset)
        metrics = [dict(metric) for metric in asset.get("metrics", ())]
        item["metrics"] = metrics
        result.append(item)
        for metric in metrics:
            metric_id = str(metric.get("id") or "")
            if metric_id:
                metric_asset_indexes[metric_id] = index
                metrics_by_id[metric_id] = metric
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
        ratio_dimensions = set.intersection(
            *(
                _metric_dimension_fields(
                    operand,
                    metrics_by_id=metrics_by_id,
                    terms=terms,
                    visiting=frozenset({term.id}),
                )
                for operand in operands
            )
        )
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
                "dimensions": [
                    {"asset_fqn": asset_fqn, "column": column}
                    for asset_fqn, column in sorted(ratio_dimensions)
                ],
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
    query_text: str,
    query_tokens: frozenset[str],
    asset_priorities: Mapping[str, int],
    max_candidate_metrics: int,
    preferred_metric_ids: tuple[str, ...] = (),
    search_metric_ranks: Mapping[str, int] | None = None,
    require_search_metric: bool = False,
    governed_phrases: tuple[str, ...] = (),
    governed_specialization_ids: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    """release Glossary·DataHub 검색 증거가 강한 Metric만 선택 후보로 남긴다."""

    metric_records = [
        (asset, metric)
        for asset in assets
        for metric in asset.get("metrics", ())
        if isinstance(metric, dict) and isinstance(metric.get("id"), str)
    ]
    metrics_by_id = {str(metric["id"]): metric for _asset, metric in metric_records}
    normalized_query = _normalized_phrase(query_text)
    governed_phrase_forms = frozenset(
        normalized.replace(" ", "")
        for value in governed_phrases
        if (normalized := _normalized_phrase(value))
    )
    specialization_ids = frozenset(governed_specialization_ids)
    dimension_tokens = _candidate_dimension_tokens(assets)
    exact_dimension_query = normalized_query in _candidate_dimension_phrases(assets)
    metric_query_tokens = frozenset(
        token
        for token in query_tokens
        if unicode_tokens(token).isdisjoint(dimension_tokens)
    )
    unranked = tuple(
        (
            (
                int(normalized_query in exact_phrases),
                int(
                    bool(metric_query_tokens)
                    and metric_query_tokens.issubset(
                        _metric_definition_tokens(
                            metric,
                            terms.get(str(metric["id"])),
                        )
                    )
                ),
                int(
                    str(metric["id"]) in specialization_ids
                    or any(
                        phrase.replace(" ", "") in governed_phrase_forms
                        for phrase in exact_phrases
                    )
                ),
                len(
                    metric_query_tokens
                    & _metric_tokens(metric, terms.get(str(metric["id"])))
                ),
                int(asset_priorities.get(str(asset.get("fqn") or ""), 0)),
                str(metric["id"]),
            )
            for asset, metric in metric_records
            for exact_phrases in (
                _metric_exact_phrases(
                    metric,
                    terms.get(str(metric["id"])),
                ),
            )
        )
    )
    external_ranks = search_metric_ranks or {}
    ranked = sorted(
        unranked,
        key=(
            lambda item: (
                -item[0],
                -item[1],
                -item[2],
                -item[3],
                item[5] not in external_ranks,
                external_ranks.get(item[5], 0),
                -item[4],
                item[5],
            )
            if require_search_metric
            else (-item[0], -item[1], -item[2], -item[3], -item[4], item[5])
        ),
    )
    direct = [item for item in ranked if any(item[:4])]
    preferred = tuple(
        dict.fromkeys(
            metric_id
            for metric_id in preferred_metric_ids
            if metric_id in metrics_by_id
            and metrics_by_id[metric_id].get("visibility", "BUSINESS")
            == "BUSINESS"
        )
    )
    strongest_business_score = max(
        (
            (exact, definition, hint, overlap)
            for exact, definition, hint, overlap, _priority, metric_id in direct
            if metrics_by_id[metric_id].get("visibility", "BUSINESS")
            == "BUSINESS"
        ),
        default=(0, 0, 0, 0),
    )
    strongest_support_score = max(
        (
            (exact, definition, hint, overlap)
            for exact, definition, hint, overlap, _priority, metric_id in direct
            if metrics_by_id[metric_id].get("visibility") == "SUPPORT"
        ),
        default=(0, 0, 0, 0),
    )
    exact_business_query = any(
        exact
        and metrics_by_id[metric_id].get("visibility", "BUSINESS") == "BUSINESS"
        for exact, _definition, _hint, _overlap, _priority, metric_id in direct
    )
    ranked_business_ids = [
        metric_id
        for exact, definition, hint, overlap, priority, metric_id in (
            ranked if require_search_metric else direct
        )
        if metrics_by_id[metric_id].get("visibility", "BUSINESS") == "BUSINESS"
        and metric_id not in preferred
        # Dimension 식별자만 정확히 요청한 경우, 부분 문구·정의 overlap이 같은
        # Dataset의 BUSINESS Metric으로 의미를 바꾸지 못한다. BUSINESS 식별자와
        # 정확히 충돌하는 승인 문구만 모호성 후보로 남긴다.
        and (not exact_dimension_query or exact_business_query)
        # DataHub mode는 반드시 Search가 찾은 Term 또는 Dataset 안에서만 움직인다.
        # Dataset hit 안에서는 승인된 local Glossary evidence로 Metric을 구분한다.
        # 이는 전체 snapshot fallback이 아니며 join으로 확장된 미검색 asset(priority=0)은
        # 선택 후보가 될 수 없다.
        and (
            not require_search_metric
            or metric_id in external_ranks
            or (priority > 0 and any((exact, definition, hint, overlap)))
        )
        and (exact, definition, hint, overlap) >= strongest_support_score
    ]
    selectable_ids = set(preferred)
    selectable_ids.update(
        ranked_business_ids[: max(0, max_candidate_metrics - len(preferred))]
    )
    directly_matched_support_ids = [
        metric_id
        for exact, definition, hint, overlap, _priority, metric_id in direct
        if metrics_by_id[metric_id].get("visibility") == "SUPPORT"
        and (exact, definition, hint, overlap) >= strongest_business_score
    ]
    selectable_ids.update(
        directly_matched_support_ids[:max_candidate_metrics]
    )

    ordered_selectable_ids = tuple(
        dict.fromkeys(
            (
                *preferred,
                *(
                    metric_id
                    for (
                        _exact,
                        _definition,
                        _hint,
                        _overlap,
                        _priority,
                        metric_id,
                    ) in ranked
                    if metric_id in selectable_ids and metric_id not in preferred
                ),
            )
        )
    )
    candidate_ranks = {
        metric_id: index
        for index, metric_id in enumerate(ordered_selectable_ids, start=1)
    }

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
            metric["candidate_rank"] = candidate_ranks.get(metric_id)
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


def governed_metric_specialization_ids(
    terms: Mapping[str, GlossaryMetricTerm],
    governed_phrases: tuple[str, ...],
    max_metric_count: int,
) -> tuple[str, ...]:
    """일반 승인 문구를 포함하는 더 구체적인 Glossary Metric을 bounded 후보로 찾는다.

    질문 어휘나 값 목록을 별도 사전에 넣지 않는다. 먼저 질문에서 실제로 매치된 승인
    label/alias와 정확히 같은 Glossary 문구를 anchor로 복원한 뒤, 그 anchor가 완전한
    token 연속열로 들어 있는 다른 승인 label/alias만 specialization으로 인정한다.
    단일 token은 지나치게 넓은 family를 만들 수 있어 확장하지 않는다.
    """

    if max_metric_count < 1:
        raise ValueError("governed metric specialization bound must be positive")
    normalized_by_id = {
        metric_id: tuple(
            dict.fromkeys(
                normalized
                for value in (term.label, *term.aliases)
                if (normalized := _normalized_phrase(value))
            )
        )
        for metric_id, term in terms.items()
    }
    hint_forms = {
        normalized.replace(" ", "")
        for value in governed_phrases
        if (normalized := _normalized_phrase(value))
    }
    anchors = {
        tuple(phrase.split())
        for phrases in normalized_by_id.values()
        for phrase in phrases
        if phrase.replace(" ", "") in hint_forms and len(phrase.split()) >= 2
    }
    if not anchors:
        return ()

    ranked: list[tuple[int, str]] = []
    for metric_id, phrases in normalized_by_id.items():
        added_token_counts = [
            len(tokens) - len(anchor)
            for phrase in phrases
            for tokens in (tuple(phrase.split()),)
            for anchor in anchors
            if len(tokens) >= len(anchor)
            and any(
                tokens[index : index + len(anchor)] == anchor
                for index in range(len(tokens) - len(anchor) + 1)
            )
        ]
        if added_token_counts:
            ranked.append((min(added_token_counts), metric_id))
    return tuple(
        metric_id
        for _added_tokens, metric_id in sorted(ranked)[:max_metric_count]
    )


def _candidate_dimension_tokens(assets: list[dict[str, Any]]) -> frozenset[str]:
    """후보 asset의 승인 Dimension 식별자·별칭을 Metric overlap 증거와 분리한다.

    Dimension만 말한 질문이 Metric 정의 안의 같은 단어 때문에 임의 BUSINESS
    Metric으로 번지는 것을 막는다. Metric의 exact label·alias 일치는 별도 강한
    증거로 유지하므로, 같은 단어가 실제 Metric 이름인 경우까지 차단하지 않는다.
    """

    values: list[str] = []
    for asset in assets:
        for dimension in asset.get("dimensions", ()):
            if not isinstance(dimension, Mapping):
                continue
            if str(dimension.get("id") or "").startswith(
                DERIVED_DIMENSION_ID_PREFIX
            ):
                # Metric binding에서 보완한 차원은 Node1 후보에는 필요하지만, 같은
                # Metric의 어휘를 검색 전에 제거하는 전역 dimension stop-token은 아니다.
                continue
            values.extend(
                str(dimension.get(name) or "")
                for name in ("id", "name", "column", "field")
            )
            aliases = dimension.get("aliases")
            if isinstance(aliases, (list, tuple)):
                values.extend(map(str, aliases))
    return unicode_tokens(" ".join(values))


def _candidate_dimension_phrases(
    assets: list[dict[str, Any]],
) -> frozenset[str]:
    """승인된 전역 Dimension 식별 문구를 exact closure 경계로 만든다."""

    values: list[str] = []
    for asset in assets:
        for dimension in asset.get("dimensions", ()):
            if not isinstance(dimension, Mapping) or str(
                dimension.get("id") or ""
            ).startswith(DERIVED_DIMENSION_ID_PREFIX):
                continue
            values.extend(
                str(dimension.get(name) or "")
                for name in ("id", "name", "column", "field")
            )
            aliases = dimension.get("aliases")
            if isinstance(aliases, (list, tuple)):
                values.extend(map(str, aliases))
    return frozenset(
        normalized
        for value in values
        if (normalized := _normalized_phrase(value))
    )


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
        expanded.update(part for part in token.split("_") if part)
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


def _metric_exact_phrases(
    metric: Mapping[str, Any],
    term: GlossaryMetricTerm | None,
) -> frozenset[str]:
    """승인 label·alias와 식별 필드만 정의 토큰보다 강한 exact-match 증거로 만든다."""

    values = [str(metric.get("id") or ""), str(metric.get("result_field") or "")]
    if term is not None:
        values.extend((term.label, *term.aliases))
    semantic = metric.get("semantic")
    if isinstance(semantic, Mapping):
        values.append(str(semantic.get("name") or ""))
        aliases = semantic.get("aliases")
        if isinstance(aliases, (list, tuple)):
            values.extend(map(str, aliases))
    return frozenset(
        normalized
        for value in values
        if (normalized := _normalized_phrase(value))
    )


def _metric_definition_tokens(
    metric: Mapping[str, Any],
    term: GlossaryMetricTerm | None,
) -> frozenset[str]:
    """승인 definition만 추출해 질문 전체가 정의 안에 포함되는 강한 증거를 만든다."""

    values: list[str] = []
    if term is not None:
        values.append(term.definition)
    semantic = metric.get("semantic")
    if isinstance(semantic, Mapping):
        values.append(str(semantic.get("definition") or ""))
    return unicode_tokens(" ".join(values))


def _normalized_phrase(value: str) -> str:
    """exact-match용 문구를 NFKC·casefold·공백 기준으로만 정규화한다."""

    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


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
