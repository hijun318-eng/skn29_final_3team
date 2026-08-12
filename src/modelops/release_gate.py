"""Fail-closed production adoption gate for the configured SQL LoRA."""

from collections.abc import Mapping


REQUIRED_EVIDENCE = (
    "immutable_base_lora_comparison",
    "lora_serving_slo",
    "explicit_p0_adoption_approval",
)


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def production_release_ready(
    decision: Mapping[str, object],
    candidate: Mapping[str, object],
    comparison: Mapping[str, object],
) -> bool:
    """Return true only when every independent production approval is explicit."""
    decision_release = _mapping(decision.get("production_release"))
    candidate_release = _mapping(candidate.get("production_release"))
    evidence = _mapping(candidate_release.get("required_evidence"))
    captured_evidence = _mapping(comparison.get("captured_evidence"))
    comparison_evidence = _mapping(captured_evidence.get("comparison"))
    return bool(
        decision_release.get("status") == "APPROVED"
        and decision_release.get("ready") is True
        and candidate_release.get("status") == "APPROVED"
        and candidate_release.get("ready") is True
        and all(evidence.get(key) is True for key in REQUIRED_EVIDENCE)
        and comparison_evidence.get("status") == "READY"
        and comparison_evidence.get("comparable") is True
    )
