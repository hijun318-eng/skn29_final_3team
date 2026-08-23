"""Metric 검색의 catalog 자기일관성·봉인 Gold·fail-closed 경계를 함께 채점한다."""

from __future__ import annotations

import hashlib
import json
import unicodedata
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any


METRIC_RETRIEVAL_VERSION = "answervice.metric_retrieval.v3"
METRIC_RETRIEVAL_GOLD_VERSION = "answervice.metric_retrieval_gold.v1"
POSITIVE_EXACT = "positive_catalog_exact"
POSITIVE_DEFINITION = "positive_definition_overlap"
POSITIVE_HELDOUT_KOREAN = "positive_heldout_korean"
NEGATIVE_SUPPORT = "negative_support_only"
NEGATIVE_DIMENSION = "negative_dimension_only"
NEGATIVE_ENTITLEMENT = "negative_out_of_entitlement"
NEGATIVE_OUT_OF_SCOPE = "negative_out_of_scope"
NEGATIVE_HELDOUT_KOREAN = "negative_heldout_korean"

_POSITIVE_KINDS = frozenset(
    {POSITIVE_EXACT, POSITIVE_DEFINITION, POSITIVE_HELDOUT_KOREAN}
)
_NEGATIVE_KINDS = frozenset(
    {
        NEGATIVE_SUPPORT,
        NEGATIVE_DIMENSION,
        NEGATIVE_ENTITLEMENT,
        NEGATIVE_OUT_OF_SCOPE,
        NEGATIVE_HELDOUT_KOREAN,
    }
)
_SAFE_CLOSURE_ERRORS = frozenset(
    {"NoEntitledAssetsError", "NoMetricMatchError", "UnsupportedSemanticError"}
)


class MetricRetrievalError(ValueError):
    """검색 probe나 관측이 bounded 평가 계약을 위반했음을 나타낸다."""


@dataclass(frozen=True)
class MetricRetrievalProbe:
    """평가 종류와 기대 결과를 가진 bounded 검색 probe다."""

    kind: str
    query: str
    normalized_query: str
    expected_metric_ids: tuple[str, ...] = ()
    case_id: str | None = None
    split: str | None = None


@dataclass(frozen=True)
class MetricRetrievalGold:
    """내용 hash로 봉인된 독립 한국어 검색 Gold manifest다."""

    dataset_id: str
    sealed_at: str
    source: str
    content_sha256: str
    thresholds: Mapping[str, float | int]
    probes: tuple[MetricRetrievalProbe, ...]


@dataclass(frozen=True)
class MetricRetrievalObservation:
    """한 probe에 대해 runtime 후보 검색이 반환한 rank 순 Metric과 typed 실패다."""

    query: str
    ranked_metric_ids: tuple[str, ...]
    error_type: str | None = None


def load_metric_retrieval_gold(path: str | Path) -> MetricRetrievalGold:
    """봉인 manifest의 schema와 canonical hash를 검증한 뒤 probe로 변환한다."""

    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise MetricRetrievalError("retrieval Gold manifest is unreadable") from error
    required = {
        "schema_version",
        "dataset_id",
        "status",
        "sealed_at",
        "source",
        "thresholds",
        "cases",
        "content_sha256",
    }
    if not isinstance(document, dict) or set(document) != required:
        raise MetricRetrievalError("retrieval Gold manifest shape is invalid")
    if (
        document["schema_version"] != METRIC_RETRIEVAL_GOLD_VERSION
        or document["status"] != "SEALED"
        or not _identifier(document["dataset_id"])
        or not isinstance(document["sealed_at"], str)
        or not document["sealed_at"].strip()
        or not isinstance(document["source"], str)
        or not document["source"].strip()
    ):
        raise MetricRetrievalError("retrieval Gold manifest identity is invalid")

    content_sha256 = document["content_sha256"]
    if (
        not isinstance(content_sha256, str)
        or len(content_sha256) != 64
        or any(character not in "0123456789abcdef" for character in content_sha256)
    ):
        raise MetricRetrievalError("retrieval Gold manifest hash is invalid")
    unhashed = dict(document)
    unhashed.pop("content_sha256")
    canonical = json.dumps(
        unhashed,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    if hashlib.sha256(canonical).hexdigest() != content_sha256:
        raise MetricRetrievalError("retrieval Gold manifest hash differs from content")

    thresholds = _gold_thresholds(document["thresholds"])
    raw_cases = document["cases"]
    if not isinstance(raw_cases, list) or not 2 <= len(raw_cases) <= 200:
        raise MetricRetrievalError("retrieval Gold cases are missing or unbounded")
    probes: list[MetricRetrievalProbe] = []
    case_ids: set[str] = set()
    queries: set[str] = set()
    splits: set[str] = set()
    for raw in raw_cases:
        if not isinstance(raw, dict) or set(raw) != {
            "case_id",
            "split",
            "kind",
            "query",
            "expected_metric_ids",
        }:
            raise MetricRetrievalError("retrieval Gold case shape is invalid")
        case_id = raw["case_id"]
        split = raw["split"]
        kind = raw["kind"]
        query = raw["query"]
        expected = raw["expected_metric_ids"]
        if (
            not _identifier(case_id)
            or case_id in case_ids
            or split not in {"calibration", "heldout"}
            or kind not in {POSITIVE_HELDOUT_KOREAN, NEGATIVE_HELDOUT_KOREAN}
            or not isinstance(query, str)
            or not any("\uac00" <= character <= "\ud7a3" for character in query)
            or not isinstance(expected, list)
            or any(not _identifier(item) for item in expected)
            or len(expected) != len(set(expected))
            or (kind == POSITIVE_HELDOUT_KOREAN and not expected)
            or (kind == NEGATIVE_HELDOUT_KOREAN and bool(expected))
        ):
            raise MetricRetrievalError("retrieval Gold case is invalid")
        normalized = normalize_retrieval_query(query)
        if normalized in queries:
            raise MetricRetrievalError("retrieval Gold contains a duplicate query")
        case_ids.add(case_id)
        queries.add(normalized)
        splits.add(split)
        probes.append(
            MetricRetrievalProbe(
                kind=kind,
                query=query,
                normalized_query=normalized,
                expected_metric_ids=tuple(expected),
                case_id=case_id,
                split=split,
            )
        )
    if splits != {"calibration", "heldout"}:
        raise MetricRetrievalError("retrieval Gold must contain calibration and heldout splits")
    return MetricRetrievalGold(
        dataset_id=document["dataset_id"],
        sealed_at=document["sealed_at"].strip(),
        source=document["source"].strip(),
        content_sha256=content_sha256,
        thresholds=thresholds,
        probes=tuple(probes),
    )


def build_metric_retrieval_probes(
    terms: Mapping[str, Mapping[str, object]],
    eligible_metric_ids: Iterable[str],
    *,
    support_phrases: Iterable[str] = (),
    dimension_phrases: Iterable[str] = (),
    forbidden_terms: Mapping[str, Mapping[str, object]] | None = None,
    out_of_scope_query: str | None = None,
) -> tuple[MetricRetrievalProbe, ...]:
    """카탈로그의 서로 다른 증거원으로 positive·negative probe를 만든다.

    label·alias는 exact 자기일관성에만 사용한다. definition probe는 모든 label·alias
    token을 제거한 나머지 설명 token으로 만들며, 실제 paraphrase Gold Set으로 간주하지
    않는다. negative probe는 승인 BUSINESS exact 문구와 충돌하면 모호한 질의이므로
    제외한다.
    """

    metric_ids = tuple(sorted(set(eligible_metric_ids)))
    if not metric_ids or any(not _identifier(item) for item in metric_ids):
        raise MetricRetrievalError("eligible metric ids must be non-empty identifiers")

    exact_groups: dict[str, set[str]] = {}
    exact_displays: dict[str, str] = {}
    eligible_exact_phrases: set[str] = set()
    validated_terms: dict[str, tuple[str, tuple[str, ...], str]] = {}
    for metric_id in metric_ids:
        label, aliases, definition = _validated_term(terms.get(metric_id))
        validated_terms[metric_id] = (label, aliases, definition)
        for phrase in dict.fromkeys((label, *aliases)):
            normalized = normalize_retrieval_query(phrase)
            exact_groups.setdefault(normalized, set()).add(metric_id)
            exact_displays.setdefault(normalized, phrase)
            eligible_exact_phrases.add(normalized)

    probes = [
        MetricRetrievalProbe(
            kind=POSITIVE_EXACT,
            query=exact_displays[normalized],
            normalized_query=normalized,
            expected_metric_ids=tuple(sorted(expected_ids)),
        )
        for normalized, expected_ids in sorted(exact_groups.items())
    ]

    definition_groups: dict[str, set[str]] = {}
    definition_displays: dict[str, str] = {}
    for metric_id in metric_ids:
        label, aliases, definition = validated_terms[metric_id]
        identity_tokens = set(_unicode_words(" ".join((label, *aliases))))
        description_tokens = tuple(
            token for token in _unicode_words(definition) if token not in identity_tokens
        )
        query = _bounded_query(description_tokens)
        if query is None:
            continue
        normalized = normalize_retrieval_query(query)
        if normalized in eligible_exact_phrases:
            continue
        definition_groups.setdefault(normalized, set()).add(metric_id)
        definition_displays.setdefault(normalized, query)
    probes.extend(
        MetricRetrievalProbe(
            kind=POSITIVE_DEFINITION,
            query=definition_displays[normalized],
            normalized_query=normalized,
            expected_metric_ids=tuple(sorted(expected_ids)),
        )
        for normalized, expected_ids in sorted(definition_groups.items())
    )

    used_queries = {item.normalized_query for item in probes}
    negative_inputs: list[tuple[str, str]] = []
    negative_inputs.extend((NEGATIVE_SUPPORT, item) for item in support_phrases)
    negative_inputs.extend((NEGATIVE_DIMENSION, item) for item in dimension_phrases)
    if forbidden_terms is not None:
        for metric_id in sorted(forbidden_terms):
            label, aliases, _definition = _validated_term(forbidden_terms[metric_id])
            negative_inputs.extend(
                (NEGATIVE_ENTITLEMENT, item)
                for item in dict.fromkeys((label, *aliases))
            )
    if out_of_scope_query is not None:
        negative_inputs.append((NEGATIVE_OUT_OF_SCOPE, out_of_scope_query))

    for kind, raw_query in negative_inputs:
        query = _text(raw_query, "negative probe query")
        normalized = normalize_retrieval_query(query)
        if normalized in eligible_exact_phrases or normalized in used_queries:
            continue
        probes.append(
            MetricRetrievalProbe(
                kind=kind,
                query=query,
                normalized_query=normalized,
            )
        )
        used_queries.add(normalized)

    if not any(item.kind in _NEGATIVE_KINDS for item in probes):
        raise MetricRetrievalError("at least one negative closure probe is required")
    return tuple(probes)


def evaluate_metric_retrieval(
    probes: Sequence[MetricRetrievalProbe],
    observations: Sequence[MetricRetrievalObservation],
    *,
    top_k: int,
    max_candidates: int,
) -> dict[str, Any]:
    """positive 검색 품질과 negative closure·오염을 별도 지표로 집계한다."""

    if (
        not probes
        or len(probes) != len(observations)
        or len({item.normalized_query for item in probes}) != len(probes)
        or isinstance(top_k, bool)
        or not isinstance(top_k, int)
        or top_k < 1
        or isinstance(max_candidates, bool)
        or not isinstance(max_candidates, int)
        or max_candidates < 1
    ):
        raise MetricRetrievalError("retrieval evaluation bounds are invalid")

    cases: list[dict[str, Any]] = []
    for probe, observation in zip(probes, observations, strict=True):
        if observation.query != probe.query:
            raise MetricRetrievalError("retrieval observation order differs from probes")
        if probe.normalized_query != normalize_retrieval_query(probe.query):
            raise MetricRetrievalError("retrieval probe normalization is invalid")
        if probe.kind not in _POSITIVE_KINDS | _NEGATIVE_KINDS:
            raise MetricRetrievalError("retrieval probe kind is invalid")
        if probe.kind in {POSITIVE_HELDOUT_KOREAN, NEGATIVE_HELDOUT_KOREAN}:
            if not _identifier(probe.case_id) or probe.split not in {
                "calibration",
                "heldout",
            }:
                raise MetricRetrievalError("held-out retrieval probe identity is invalid")
        ranked = observation.ranked_metric_ids
        if (
            len(ranked) > max_candidates
            or len(ranked) != len(set(ranked))
            or any(not _identifier(item) for item in ranked)
            or (
                observation.error_type is not None
                and (
                    not isinstance(observation.error_type, str)
                    or not observation.error_type
                    or ranked
                )
            )
        ):
            raise MetricRetrievalError("retrieval observation is invalid")

        if probe.kind in _POSITIVE_KINDS:
            expected = set(probe.expected_metric_ids)
            if (
                not expected
                or len(expected) != len(probe.expected_metric_ids)
                or any(not _identifier(item) for item in expected)
            ):
                raise MetricRetrievalError("positive retrieval expectation is invalid")
            top = ranked[:top_k]
            recalled = expected.intersection(top)
            first_rank = next(
                (
                    index
                    for index, metric_id in enumerate(ranked, start=1)
                    if metric_id in expected
                ),
                None,
            )
            cases.append(
                {
                    "case_id": probe.case_id,
                    "split": probe.split,
                    "kind": probe.kind,
                    "query": probe.query,
                    "expected_metric_ids": sorted(expected),
                    "ranked_metric_ids": list(ranked),
                    "top1_hit": bool(ranked and ranked[0] in expected),
                    "recall_at_k": _score(len(recalled) / len(expected)),
                    "precision_at_k": _score(len(recalled) / len(top)) if top else 0.0,
                    "reciprocal_rank": _score(1.0 / first_rank) if first_rank else 0.0,
                    "error_type": observation.error_type,
                }
            )
            continue

        if probe.expected_metric_ids:
            raise MetricRetrievalError("negative retrieval probe cannot expect metrics")
        infrastructure_error = (
            observation.error_type is not None
            and observation.error_type not in _SAFE_CLOSURE_ERRORS
        )
        contaminated = bool(ranked)
        cases.append(
            {
                "case_id": probe.case_id,
                "split": probe.split,
                "kind": probe.kind,
                "query": probe.query,
                "expected_metric_ids": [],
                "ranked_metric_ids": list(ranked),
                "closed": not contaminated and not infrastructure_error,
                "contaminated": contaminated,
                "infrastructure_error": infrastructure_error,
                "error_type": observation.error_type,
            }
        )

    exact = _positive_summary(cases, POSITIVE_EXACT)
    definition = _positive_summary(cases, POSITIVE_DEFINITION)
    heldout = _positive_summary(
        cases,
        POSITIVE_HELDOUT_KOREAN,
        split="heldout",
    )
    negative_cases = [item for item in cases if item["kind"] in _NEGATIVE_KINDS]
    if not negative_cases:
        raise MetricRetrievalError("negative closure observations are missing")
    closed_count = sum(bool(item["closed"]) for item in negative_cases)
    contaminated_count = sum(bool(item["contaminated"]) for item in negative_cases)
    infrastructure_error_count = sum(
        bool(item["infrastructure_error"]) for item in negative_cases
    )
    kind_counts = Counter(item.kind for item in probes)
    heldout_negative = _negative_summary(
        [
            item
            for item in cases
            if item["kind"] == NEGATIVE_HELDOUT_KOREAN
            and item["split"] == "heldout"
        ]
    )
    has_gold = any(
        item.kind in {POSITIVE_HELDOUT_KOREAN, NEGATIVE_HELDOUT_KOREAN}
        for item in probes
    )

    return {
        "contract_version": METRIC_RETRIEVAL_VERSION,
        "evaluation_scope": (
            "CATALOG_DERIVED_AND_SEALED_KOREAN_HELDOUT"
            if has_gold
            else "CATALOG_DERIVED_STRUCTURE_AND_CLOSURE"
        ),
        "probe_count": len(probes),
        "probe_kind_counts": dict(sorted(kind_counts.items())),
        "top_k": top_k,
        "max_candidates": max_candidates,
        "catalog_exact_self_consistency": exact,
        "definition_overlap_retrieval": definition,
        "negative_closure": {
            "probe_count": len(negative_cases),
            "closure_rate": _score(closed_count / len(negative_cases)),
            "contamination_rate": _score(contaminated_count / len(negative_cases)),
            "contaminated_probe_count": contaminated_count,
            "infrastructure_error_count": infrastructure_error_count,
            "max_observed_candidate_count": max(
                len(item["ranked_metric_ids"]) for item in negative_cases
            ),
        },
        "natural_language_paraphrase": {
            **heldout,
            "negative_closure": heldout_negative,
            **(
                {}
                if heldout["scorable"]
                else {
                    "score": None,
                    "reason": "독립적으로 작성·봉인된 한국어 held-out Gold가 없습니다.",
                }
            ),
        },
        "cases": cases,
    }


def normalize_retrieval_query(value: str) -> str:
    """표시 문구를 바꾸지 않고 동등성 판정용 NFKC·casefold·공백 정규화를 수행한다."""

    if not isinstance(value, str):
        raise MetricRetrievalError("retrieval query must be text")
    normalized = " ".join(unicodedata.normalize("NFKC", value).casefold().split())
    if not normalized or len(normalized) > 512:
        raise MetricRetrievalError("retrieval query is empty or too long")
    return normalized


def _positive_summary(
    cases: Sequence[Mapping[str, Any]],
    kind: str,
    *,
    split: str | None = None,
) -> dict[str, Any]:
    selected = [
        item
        for item in cases
        if item["kind"] == kind and (split is None or item["split"] == split)
    ]
    if not selected:
        return {
            "scorable": False,
            "probe_count": 0,
            "top1_accuracy": None,
            "recall_at_k": None,
            "precision_at_k": None,
            "mean_reciprocal_rank": None,
            "retrieval_error_count": 0,
        }
    count = len(selected)
    return {
        "scorable": True,
        "probe_count": count,
        "top1_accuracy": _score(sum(bool(item["top1_hit"]) for item in selected) / count),
        "recall_at_k": _score(sum(float(item["recall_at_k"]) for item in selected) / count),
        "precision_at_k": _score(
            sum(float(item["precision_at_k"]) for item in selected) / count
        ),
        "mean_reciprocal_rank": _score(
            sum(float(item["reciprocal_rank"]) for item in selected) / count
        ),
        "retrieval_error_count": sum(item["error_type"] is not None for item in selected),
    }


def _negative_summary(cases: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """선택된 negative case의 안전 폐쇄와 기반 장애를 분리해 집계한다."""

    if not cases:
        return {
            "scorable": False,
            "probe_count": 0,
            "closure_rate": None,
            "contamination_rate": None,
            "contaminated_probe_count": 0,
            "infrastructure_error_count": 0,
        }
    count = len(cases)
    closed = sum(bool(item["closed"]) for item in cases)
    contaminated = sum(bool(item["contaminated"]) for item in cases)
    infrastructure_errors = sum(bool(item["infrastructure_error"]) for item in cases)
    return {
        "scorable": True,
        "probe_count": count,
        "closure_rate": _score(closed / count),
        "contamination_rate": _score(contaminated / count),
        "contaminated_probe_count": contaminated,
        "infrastructure_error_count": infrastructure_errors,
    }


def _gold_thresholds(value: object) -> dict[str, float | int]:
    required = {
        "min_baseline_heldout_top1",
        "min_baseline_heldout_recall_at_k",
        "min_baseline_heldout_mrr",
        "max_unauthorized_exposure_count",
        "max_production_diff_count",
        "max_candidate_warm_p95_ms",
    }
    if not isinstance(value, dict) or set(value) != required:
        raise MetricRetrievalError("retrieval Gold thresholds are invalid")
    result: dict[str, float | int] = {}
    for name in (
        "min_baseline_heldout_top1",
        "min_baseline_heldout_recall_at_k",
        "min_baseline_heldout_mrr",
    ):
        score = value[name]
        if isinstance(score, bool) or not isinstance(score, (int, float)) or not 0 <= score <= 1:
            raise MetricRetrievalError("retrieval Gold quality threshold is invalid")
        result[name] = float(score)
    for name in ("max_unauthorized_exposure_count", "max_production_diff_count"):
        bound = value[name]
        if isinstance(bound, bool) or not isinstance(bound, int) or bound < 0:
            raise MetricRetrievalError("retrieval Gold count threshold is invalid")
        result[name] = bound
    latency = value["max_candidate_warm_p95_ms"]
    if isinstance(latency, bool) or not isinstance(latency, (int, float)) or latency <= 0:
        raise MetricRetrievalError("retrieval Gold latency threshold is invalid")
    result["max_candidate_warm_p95_ms"] = float(latency)
    return result


def _validated_term(value: object) -> tuple[str, tuple[str, ...], str]:
    if not isinstance(value, Mapping):
        raise MetricRetrievalError("eligible metric is missing its catalog term")
    label = value.get("label")
    aliases = value.get("aliases")
    definition = value.get("definition")
    if (
        not isinstance(label, str)
        or not label.strip()
        or not isinstance(aliases, (list, tuple))
        or any(not isinstance(item, str) or not item.strip() for item in aliases)
        or not isinstance(definition, str)
        or not definition.strip()
    ):
        raise MetricRetrievalError("catalog metric term is invalid")
    return label.strip(), tuple(item.strip() for item in aliases), definition.strip()


def _unicode_words(value: str) -> tuple[str, ...]:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    words: list[str] = []
    current: list[str] = []
    for character in normalized:
        if unicodedata.category(character)[:1] in {"L", "N", "M"} or character == "_":
            current.append(character)
        elif current:
            words.append("".join(current))
            current = []
    if current:
        words.append("".join(current))
    return tuple(words)


def _bounded_query(tokens: Sequence[str]) -> str | None:
    selected: list[str] = []
    size = 0
    for token in tokens:
        addition = len(token) + int(bool(selected))
        if size + addition > 512:
            break
        selected.append(token)
        size += addition
    return " ".join(selected) or None


def _text(value: object, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MetricRetrievalError(f"{context} must be non-empty text")
    return value.strip()


def _identifier(value: object) -> bool:
    """Metric 식별자를 평가 파일에 안전한 bounded 문자열로 제한한다."""

    return (
        isinstance(value, str)
        and bool(value)
        and len(value) <= 128
        and value == value.strip()
    )


def _score(value: float) -> float:
    """환경별 부동소수 표현 차이를 없애기 위해 점수를 고정 정밀도로 반올림한다."""

    return round(value, 6)
