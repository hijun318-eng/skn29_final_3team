from __future__ import annotations

import hashlib
import json

from .pdf_ingestion import PDF_PARSER_CONTRACT_VERSION
from .token_chunker import (
    TOKEN_CHUNKER_DEFAULT_MIN_TOKENS,
    TOKEN_CHUNKER_SCHEMA_VERSION,
)


PROCESSING_PROFILE_VERSION = "RagProcessingProfile.v1"


def processing_profile_sha256(max_tokens: int, overlap_tokens: int) -> str:
    """Hash every parser/chunker input that can change persisted chunk semantics."""

    if (
        type(max_tokens) is not int
        or type(overlap_tokens) is not int
        or max_tokens <= 0
        or overlap_tokens < 0
        or overlap_tokens >= max_tokens
    ):
        raise ValueError("RAG processing profile limits are invalid")
    canonical = json.dumps(
        {
            "schema_version": PROCESSING_PROFILE_VERSION,
            "parser_contract_version": PDF_PARSER_CONTRACT_VERSION,
            "chunker_schema_version": TOKEN_CHUNKER_SCHEMA_VERSION,
            "chunk_max_tokens": max_tokens,
            "chunk_overlap_tokens": overlap_tokens,
            "chunk_min_tokens": TOKEN_CHUNKER_DEFAULT_MIN_TOKENS,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
