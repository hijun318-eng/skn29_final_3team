"""검색 근거를 중복 제거하고 토큰 예산 안에서 원래 순서대로 프롬프트에 포장한다."""

import hashlib
from dataclasses import asdict
from typing import Callable, List, Dict, Any

from .vector_models import VectorSearchResult


class EvidencePacker:
    """완전한 검색 청크만 채택하며 checksum 중복과 예산 초과 사유를 추적한다."""

    def __init__(self, tokenizer_fn: Callable[[str], int], budget: int):
        """토큰 수 계산 함수와 근거 전체에 허용할 최대 토큰 예산을 설정한다."""

        self.tokenizer_fn = tokenizer_fn
        self.budget = budget

    def pack(self, candidates: List[VectorSearchResult]) -> Dict[str, Any]:
        """후보 순서를 유지해 예산에 맞는 청크를 선택하고 채택·거절 명세를 반환한다.

        청크를 잘라 넣지 않으며 동일 본문 checksum은 ``DUPLICATE_CHECKSUM``, 남은 예산을
        넘는 청크는 ``BUDGET_EXCEEDED``로 기록한다.
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
