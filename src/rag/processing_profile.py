"""parser·chunker·embedding 입력 계약을 release 처리 profile hash로 봉인한다."""

from __future__ import annotations

import hashlib
import json

from .docx_ingestion import DOCX_PARSER_CONTRACT_VERSION
from .embedding_input import EMBEDDING_INPUT_CONTRACT_VERSION
from .pdf_ingestion import PDF_PARSER_CONTRACT_VERSION
from .token_chunker import (
    TOKEN_CHUNKER_DEFAULT_MIN_TOKENS,
    TOKEN_CHUNKER_SCHEMA_VERSION,
)


PROCESSING_PROFILE_VERSION = "RagProcessingProfile.v1"


def processing_profile_sha256(max_tokens: int, overlap_tokens: int) -> str:
    """재적재 필요성을 판정할 처리 계약과 token 설정의 canonical SHA를 만든다."""

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
            "parser_contracts": {
                "docx": DOCX_PARSER_CONTRACT_VERSION,
                "pdf": PDF_PARSER_CONTRACT_VERSION,
            },
            "chunker_schema_version": TOKEN_CHUNKER_SCHEMA_VERSION,
            "chunk_max_tokens": max_tokens,
            "chunk_overlap_tokens": overlap_tokens,
            "chunk_min_tokens": TOKEN_CHUNKER_DEFAULT_MIN_TOKENS,
            "embedding_input_contract_version": EMBEDDING_INPUT_CONTRACT_VERSION,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
