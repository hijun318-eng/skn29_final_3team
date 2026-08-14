"""Versioned model wire contracts and deterministic grounding checks."""

from __future__ import annotations

import json
import re
from collections import Counter
from hashlib import sha256
from pathlib import Path
from typing import Any

from .prompt_registry import get_prompt
from .schema import ContractError, schema_definition, schema_sha256, validate_payload


MODEL_CONTRACTS = {
    "node1": {
        "schema_id": "answervice.node1.interpretation.v2",
        "schema_version": "2.0.0",
        "prompt_id": "node1.interpretation.v2",
    },
    "node3": {
        "schema_id": "answervice.node3.narrative.v2",
        "schema_version": "2.0.0",
        "prompt_id": "node3.narrative.v2",
    },
}

_RELEASE_MANIFEST_PATH = (
    Path(__file__).with_name("contracts") / "model_release.v2.json"
)
_CUTOVER_GATES = {
    "compatibility",
    "node1_critical",
    "node1_language_worst_slice",
    "node3_critical",
    "latency_token_cost",
    "legacy_regression",
}

_NUMBER = re.compile(r"[-+]?\d[\d,]*(?:\.\d+)?%?")
_INTERNAL = re.compile(
    r"(?i)(?:\burn:|\b(?:query|artifact|trace|policy)_id\b|"
    r"\b(?:select|from|join|where|group\s+by)\b|"
    r"\b[a-z_][a-z0-9_]*\.[a-z_][a-z0-9_]*\.[a-z_][a-z0-9_]*\b)"
)
_UNSUPPORTED_CLAIM = re.compile(r"(?:때문|원인|영향을\s*받|예측|예상|권고|추천|해야\s*합니다)")


def canonical_json(payload: Any) -> str:
    """Return the one provider-independent representation of model input."""
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def canonical_json_sha256(payload: Any) -> str:
    return sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def canonical_messages(prompt_id: str, payload: Any) -> list[dict[str, str]]:
    """Build byte-equivalent chat messages for every provider adapter."""
    return [
        {"role": "system", "content": get_prompt(prompt_id).text},
        {"role": "user", "content": canonical_json(payload)},
    ]


def model_contract_manifest(node: str) -> dict[str, str]:
    try:
        contract = MODEL_CONTRACTS[node]
    except KeyError as error:
        raise ContractError(f"unsupported v2 model node: {node}") from error
    prompt = get_prompt(contract["prompt_id"])
    return {
        **contract,
        "prompt_version": prompt.version,
        "prompt_sha256": str(prompt.metadata()["hash"]),
        "schema_sha256": schema_sha256("v2"),
    }


def model_release_manifest() -> dict[str, Any]:
    """Load and verify the explicit candidate, cutover, and rollback contract."""
    payload = json.loads(_RELEASE_MANIFEST_PATH.read_text(encoding="utf-8"))
    if set(payload) != {
        "manifest_version",
        "state",
        "automatic_cutover",
        "active",
        "candidate",
        "cutover_gates",
        "rollback",
    }:
        raise ContractError("model release manifest fields are invalid")
    if (
        payload["manifest_version"] != "MODEL-RELEASE-v2.0.0"
        or payload["state"] != "CANDIDATE"
        or payload["automatic_cutover"] is not False
        or set(payload["active"]) != set(MODEL_CONTRACTS)
        or set(payload["candidate"]) != set(MODEL_CONTRACTS)
        or set(payload["cutover_gates"]) != _CUTOVER_GATES
        or any(
            status not in {"NOT_RUN", "PASS", "FAIL"}
            for status in payload["cutover_gates"].values()
        )
    ):
        raise ContractError("model release candidate metadata is invalid")

    for node, active in payload["active"].items():
        prompt = get_prompt(active["prompt_id"])
        if (
            active["schema_contract"] != "v1"
            or active["schema_sha256"] != schema_sha256("v1")
            or active["prompt_sha256"] != prompt.metadata()["hash"]
        ):
            raise ContractError(f"active {node} release hash is stale")
    for node, candidate in payload["candidate"].items():
        expected = model_contract_manifest(node)
        if any(candidate.get(key) != value for key, value in expected.items()):
            raise ContractError(f"candidate {node} release hash is stale")
        if candidate.get("schema_contract") != "v2":
            raise ContractError(f"candidate {node} schema contract is invalid")

    rollback = payload["rollback"]
    if rollback != {
        "node1_prompt_id": payload["active"]["node1"]["prompt_id"],
        "node3_prompt_id": payload["active"]["node3"]["prompt_id"],
        "schema_contract": "v1",
    }:
        raise ContractError("model release rollback target is invalid")
    return payload


def v2_response_schema(node: str) -> dict[str, Any]:
    if node not in MODEL_CONTRACTS:
        raise ContractError(f"unsupported v2 model node: {node}")
    return schema_definition(f"{node}_response", contract="v2")


def validate_node1_exchange(request: dict[str, Any], response: dict[str, Any]) -> None:
    validate_payload("node1_request", request, contract="v2")
    validate_payload("node1_response", response, contract="v2")
    _validate_scalar_text(request)
    _validate_scalar_text(response)

    terms = request["business_terms"]
    _unique((term["id"] for term in terms), "node1_request.business_terms.id")
    term_by_id = {term["id"]: term for term in terms}
    value_ids: dict[str, set[str]] = {}
    for term in terms:
        _unique(
            (value["id"] for value in term["values"]),
            f"node1_request.business_terms.{term['id']}.values.id",
        )
        value_ids[term["id"]] = {value["id"] for value in term["values"]}

    question = request["question"]
    for key, kind in (("metric_candidates", "metric"), ("dimension_candidates", "dimension")):
        candidates = response[key]
        _unique((item["id"] for item in candidates), f"node1_response.{key}.id")
        for item in candidates:
            term = term_by_id.get(item["id"])
            if term is None or term["kind"] != kind:
                raise ContractError(f"node1_response.{key}: candidate is outside approved {kind} terms")
            _validate_span(question, item["matched_text"], item["span"], key)

    filters = response["filter_candidates"]
    _unique(
        ((item["dimension_id"], item["value_id"]) for item in filters),
        "node1_response.filter_candidates.dimension_id/value_id",
    )
    for item in filters:
        term = term_by_id.get(item["dimension_id"])
        if (
            term is None
            or term["kind"] != "dimension"
            or item["value_id"] not in value_ids[item["dimension_id"]]
        ):
            raise ContractError("node1_response.filter_candidates: value is outside approved catalog")
        _validate_span(question, item["matched_text"], item["span"], "filter_candidates")

    periods = response["period_mentions"]
    _unique(
        ((item["role"], item["span"]["start_scalar"], item["span"]["end_scalar"]) for item in periods),
        "node1_response.period_mentions.role/span",
    )
    for item in periods:
        _validate_span(question, item["source_text"], item["span"], "period_mentions")

    selected_intent = response["selected_intent"]
    if selected_intent is not None and (
        selected_intent not in request["allowed_intents"]
        or selected_intent not in response["intent_candidates"]
    ):
        raise ContractError("node1_response.selected_intent is not an approved candidate")
    if len(response["intent_candidates"]) != 1 and selected_intent is not None:
        raise ContractError("node1_response.selected_intent requires exactly one intent candidate")
    selected_metric = response["selected_metric_id"]
    metric_ids = [item["id"] for item in response["metric_candidates"]]
    if selected_metric is not None and metric_ids.count(selected_metric) != 1:
        raise ContractError("node1_response.selected_metric_id is not exactly one candidate")
    if len(metric_ids) != 1 and selected_metric is not None:
        raise ContractError("node1_response.selected_metric_id requires exactly one metric candidate")

    ambiguity = set(response["ambiguity_codes"])
    if ambiguity.intersection({"INTENT_AMBIGUOUS", "MULTIPLE_INTENTS", "OUT_OF_SCOPE"}) and selected_intent is not None:
        raise ContractError("node1_response.selected_intent must be null for competing intent")
    if ambiguity.intersection({"METRIC_AMBIGUOUS", "MULTIPLE_METRICS", "OUT_OF_SCOPE"}) and selected_metric is not None:
        raise ContractError("node1_response.selected_metric_id must be null for competing metric")
    if "METRIC" in response["missing_requirements"] and selected_metric is not None:
        raise ContractError("node1_response.selected_metric_id conflicts with missing metric")

    if selected_intent is not None:
        _validate_period_roles(
            selected_intent,
            [item["role"] for item in periods],
            set(response["missing_requirements"]),
        )


def validate_node3_exchange(request: dict[str, Any], response: dict[str, Any]) -> None:
    validate_payload("node3_request", request, contract="v2")
    validate_payload("node3_response", response, contract="v2")
    _validate_scalar_text(request)
    _validate_scalar_text(response)

    facts = request["facts"]
    limitations = request["limitations"]
    _unique((item["id"] for item in facts), "node3_request.facts.id")
    _unique((item["code"] for item in limitations), "node3_request.limitations.code")
    for fact in facts:
        scalar_count = sum(
            len(value)
            for value in (
                fact["subject_text"],
                fact["period_text"],
                fact["value_text"],
                fact["comparison_text"],
            )
            if value is not None
        )
        if scalar_count > 140:
            raise ContractError(f"node3_request.facts.{fact['id']}: public text exceeds 140 scalars")
        for value in (fact["subject_text"], fact["period_text"], fact["value_text"], fact["comparison_text"]):
            if value is not None and _INTERNAL.search(value):
                raise ContractError(f"node3_request.facts.{fact['id']}: internal identifier or SQL is forbidden")
    for limitation in limitations:
        if _INTERNAL.search(limitation["public_text"]):
            raise ContractError(f"node3_request.limitations.{limitation['code']}: internal identifier or SQL is forbidden")

    required = {
        *(f"fact:{item['id']}" for item in facts if item["required_in_summary"]),
        *(f"limitation:{item['code']}" for item in limitations if item["required_in_summary"]),
    }
    if not 1 <= len(required) <= 3:
        raise ContractError("node3_request: required sources must contain 1 to 3 items")

    facts_by_id = {item["id"]: item for item in facts}
    limitations_by_code = {item["code"]: item for item in limitations}
    referenced: list[str] = []
    sentence_texts: list[str] = []
    for sentence in response["sentences"]:
        sentence_texts.append(sentence["text"])
        if _INTERNAL.search(sentence["text"]):
            raise ContractError("node3_response.sentences: internal identifier or SQL is forbidden")
        if _UNSUPPORTED_CLAIM.search(sentence["text"]):
            raise ContractError("node3_response.sentences: causal, predictive, or prescriptive claim is forbidden")
        if sentence["fact_ids"]:
            fact_id = sentence["fact_ids"][0]
            fact = facts_by_id.get(fact_id)
            if fact is None:
                raise ContractError("node3_response.sentences.fact_ids: unknown fact")
            referenced.append(f"fact:{fact_id}")
            _validate_fact_sentence(fact, sentence["text"])
        else:
            code = sentence["limitation_codes"][0]
            limitation = limitations_by_code.get(code)
            if limitation is None:
                raise ContractError("node3_response.sentences.limitation_codes: unknown limitation")
            referenced.append(f"limitation:{code}")
            if sentence["text"] != limitation["public_text"]:
                raise ContractError("node3_response.sentences: limitation text must be exact")

    _unique(referenced, "node3_response.sentences.source")
    _unique(sentence_texts, "node3_response.sentences.text")
    if set(referenced) != required or len(referenced) != len(required):
        raise ContractError("node3_response.sentences: required sources must be referenced exactly once")


def _validate_fact_sentence(fact: dict[str, Any], text: str) -> None:
    required_text = [fact["subject_text"], fact["period_text"]]
    if fact["value_text"] is not None:
        required_text.append(fact["value_text"])
    if fact["comparison_text"] is not None:
        required_text.append(fact["comparison_text"])
    if any(item not in text for item in required_text):
        raise ContractError("node3_response.sentences: fact text is not preserved")
    allowed = " ".join(required_text)
    if any(token not in allowed for token in _NUMBER.findall(text)):
        raise ContractError("node3_response.sentences: number is outside the referenced fact")
    if fact["type"] == "empty_result" and re.search(r"(?:^|\D)0(?:\D|$)", text):
        raise ContractError("node3_response.sentences: empty result must not become zero")


def _validate_period_roles(intent: str, roles: list[str], missing: set[str]) -> None:
    role_counts = Counter(roles)
    if any(count != 1 for count in role_counts.values()):
        raise ContractError("node1_response.period_mentions: period roles must be unique")
    if intent in {"aggregate", "trend", "rank"}:
        if "PRIMARY_PERIOD" not in missing and roles != ["primary"]:
            raise ContractError("node1_response.period_mentions: intent requires one primary period")
        if any(role != "primary" for role in roles):
            raise ContractError("node1_response.period_mentions: non-compare intent has comparison period")
        return
    role_set = set(roles)
    structures = ({"baseline", "comparison"}, {"primary", "comparison_rule"})
    if role_set and not any(role_set.issubset(structure) for structure in structures):
        raise ContractError("node1_response.period_mentions: compare period roles are mixed")
    valid = role_set in structures and len(roles) == 2
    comparison_missing = missing.intersection(
        {"PRIMARY_PERIOD", "BASELINE_PERIOD", "COMPARISON_PERIOD", "COMPARISON_RULE"}
    )
    if not comparison_missing and not valid:
        raise ContractError("node1_response.period_mentions: compare period structure is invalid")


def _validate_span(question: str, text: str, span: dict[str, int], path: str) -> None:
    start = span["start_scalar"]
    end = span["end_scalar"]
    if start >= end or end > len(question) or question[start:end] != text:
        raise ContractError(f"node1_response.{path}: span does not match the original question")


def _validate_scalar_text(value: Any) -> None:
    if isinstance(value, str):
        if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
            raise ContractError("model payload contains a non-scalar Unicode surrogate")
        return
    if isinstance(value, dict):
        for item in value.values():
            _validate_scalar_text(item)
    elif isinstance(value, list):
        for item in value:
            _validate_scalar_text(item)


def _unique(values, path: str) -> None:
    items = list(values)
    if len(items) != len(set(items)):
        raise ContractError(f"{path}: values must be unique")
