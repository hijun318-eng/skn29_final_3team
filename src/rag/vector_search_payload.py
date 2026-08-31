from __future__ import annotations

import hashlib
import json
from dataclasses import asdict

from .access_policy import SearchDecision
from .p2_contracts import P2GateStatus, RagToolContract, build_retrieval_envelope


def hash_search_input(
    query: str,
    recent_utterances: tuple[str, ...],
    selected_document_ids: tuple[str, ...],
    resolved_question: str | None = None,
    domains: tuple[str, ...] = (),
    intent: str = "REGULATION_CHECK",
) -> str:
    audited_input = json.dumps(
        {
            "query": query,
            "resolved_question": resolved_question or query,
            "domains": list(domains),
            "intent": intent,
            "recent_utterances": list(recent_utterances),
            "selected_document_ids": list(selected_document_ids),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(audited_input.encode("utf-8")).hexdigest()


def build_search_payload(
    query_hash: str,
    decision: SearchDecision,
    results: list[dict[str, object]],
    latency_ms: float,
    request_id: str,
    trace_id: str | None,
    as_of: str | None,
    recent_utterance_count: int,
    selected_document_ids: tuple[str, ...],
    retrieval_mode: str = "HYBRID",
    domains: tuple[str, ...] = (),
    intent: str = "REGULATION_CHECK",
    resolved_with_context: bool = False,
    model_revision: str | None = None,
    embedding_dimension: int | None = None,
    corpus_release_id: str | None = None,
    corpus_manifest_sha256: str | None = None,
    processing_profile_sha256: str | None = None,
    answer_query: str | None = None,
) -> dict[str, object]:
    return {
        "request_id": request_id,
        "trace_id": trace_id or request_id,
        "execution_state": asdict(P2GateStatus()),
        "tool": RagToolContract().public_metadata(),
        "retrieval_release": {
            "schema_version": "RagRetrievalRelease.v2",
            "release_id": corpus_release_id,
            "model_revision": model_revision,
            "embedding_dimension": embedding_dimension,
            "corpus_manifest_sha256": corpus_manifest_sha256,
            "processing_profile_sha256": processing_profile_sha256,
        },
        "query_hash": query_hash,
        "answer_query": answer_query,
        "search_mode": retrieval_mode,
        "context": {
            "recent_utterance_count": recent_utterance_count,
            "selected_document_ids": list(selected_document_ids),
            "domains": list(domains),
            "intent": intent,
            "resolved_with_context": resolved_with_context,
        },
        "policy": {
            "role": decision.role,
            "allow_unresolved_validity": decision.allow_unresolved_validity,
            "minimum_score": decision.minimum_score,
        },
        "no_evidence": not results,
        "latency_ms": round(latency_ms, 3),
        "results": results,
        "evidence": build_retrieval_envelope(
            request_id, as_of, results, trace_id=trace_id
        ),
    }
