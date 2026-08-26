import hashlib
from dataclasses import asdict
from typing import Callable, List, Dict, Any

from .vector_models import VectorSearchResult


class EvidencePacker:
    def __init__(self, tokenizer_fn: Callable[[str], int], budget: int):
        """
        tokenizer_fn: Function that takes text and returns token count.
        budget: Maximum available tokens for evidence context.
        """
        self.tokenizer_fn = tokenizer_fn
        self.budget = budget

    def pack(self, candidates: List[VectorSearchResult]) -> Dict[str, Any]:
        """
        Packs the candidates into a context string within the budget.
        Retains original retrieval order, drops chunks that exceed budget without splitting them.
        Prevents duplicate content by checksum.
        """
        packed_evidence = []
        packed_ids = []
        rejected_ids = []
        seen_checksums = set()
        current_tokens = 0

        for candidate in candidates:
            text_to_pack = candidate.content

            checksum = hashlib.sha256(text_to_pack.encode("utf-8")).hexdigest()

            if checksum in seen_checksums:
                rejected_ids.append({"evidence_id": candidate.evidence_id, "reason": "DUPLICATE_CHECKSUM"})
                continue

            block_text = f"[{candidate.citation}] ({candidate.evidence_id})\n{text_to_pack}"
            token_count = self.tokenizer_fn(block_text)

            if current_tokens + token_count <= self.budget:
                block = asdict(candidate)
                block["text"] = text_to_pack
                packed_evidence.append(block)
                packed_ids.append(candidate.evidence_id)
                current_tokens += token_count
                seen_checksums.add(checksum)
            else:
                rejected_ids.append({"evidence_id": candidate.evidence_id, "reason": "BUDGET_EXCEEDED"})

        return {
            "evidence_blocks": packed_evidence,
            "packed_ids": packed_ids,
            "rejected_ids": rejected_ids,
            "used_tokens": current_tokens
        }
