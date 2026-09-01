"""답변 모델에 전달할 검색 근거를 설정된 컨텍스트 예산 안에서 결정론적으로 선택한다."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping

from .answer_contracts import AnswerContextReceipt


_DEFAULT_LIMITS = {
    "maximum_context_tokens": 4096,
    "reserved_system_tokens": 700,
    "reserved_question_tokens": 512,
    "maximum_output_tokens": 700,
    "maximum_chunks": 10,
}
_CHAT_MESSAGE_OVERHEAD_TOKENS = 8


@dataclass(frozen=True)
class PackedAnswerContext:
    """선택된 완전한 evidence block과 서버가 계산한 예산 사용 영수증을 함께 보존한다."""

    evidence_blocks: tuple[dict[str, Any], ...]
    receipt: AnswerContextReceipt


class AnswerContextPacker:
    """UTF-8 byte 상한으로 청크를 자르지 않고 근거 단위의 컨텍스트 예산을 적용한다.

    OpenAI 계열 byte-level tokenizer에서 하나의 토큰은 최소 한 바이트를 소비하므로 UTF-8
    바이트 수는 실제 토큰 수보다 작아지지 않는 보수적 상한이다. 모델 tokenizer를 런타임에
    추가 호출하지 않아도 재현 가능하며, system·질문·출력 예약분은 설정값으로 따로 차감한다.
    """

    ESTIMATOR_VERSION = "utf8-byte-upper-bound-v1"

    def __init__(self, config: Mapping[str, Any]) -> None:
        limits = {
            key: self._positive_int(config.get(key, default), key)
            for key, default in _DEFAULT_LIMITS.items()
        }
        self.maximum_context_tokens = limits["maximum_context_tokens"]
        self.reserved_system_tokens = limits["reserved_system_tokens"]
        self.reserved_question_tokens = limits["reserved_question_tokens"]
        self.maximum_output_tokens = limits["maximum_output_tokens"]
        self.maximum_chunks = limits["maximum_chunks"]
        self.evidence_token_budget = (
            self.maximum_context_tokens
            - self.reserved_system_tokens
            - self.reserved_question_tokens
            - self.maximum_output_tokens
        )
        if self.evidence_token_budget <= 0:
            raise ValueError("RAG answer context reservations exhaust the model context")

    @staticmethod
    def _positive_int(value: Any, field: str) -> int:
        """bool을 제외한 양의 정수 설정만 허용해 잘못된 예산을 초기화 단계에서 차단한다."""

        if type(value) is not int or value <= 0:
            raise ValueError(f"RAG answer {field} must be a positive integer")
        return value

    @staticmethod
    def conservative_token_count(value: str) -> int:
        """UTF-8 직렬화 바이트 수를 모델 입력 토큰 수의 보수적 상한으로 반환한다."""

        if not isinstance(value, str):
            raise TypeError("RAG answer context token input must be text")
        return len(value.encode("utf-8"))

    def pack(
        self,
        evidence_blocks: list[dict[str, Any]],
        serializer: Callable[[list[dict]], str],
    ) -> PackedAnswerContext:
        """검색 순서를 유지하며 예산에 들어오는 완전한 block만 선택하고 제외 수를 기록한다."""

        if not isinstance(evidence_blocks, list) or any(
            not isinstance(block, dict) for block in evidence_blocks
        ):
            raise ValueError("RAG answer evidence blocks must be dictionaries")
        serializer(evidence_blocks)

        packed: list[dict[str, Any]] = []
        used_tokens = 0
        for block in evidence_blocks:
            if len(packed) >= self.maximum_chunks:
                continue
            block_tokens = self.conservative_token_count(serializer([block]))
            if used_tokens + block_tokens > self.evidence_token_budget:
                continue
            packed.append(block)
            used_tokens += block_tokens

        receipt = AnswerContextReceipt(
            estimator_version=self.ESTIMATOR_VERSION,
            maximum_context_tokens=self.maximum_context_tokens,
            evidence_token_budget=self.evidence_token_budget,
            used_evidence_tokens=used_tokens,
            input_evidence_count=len(evidence_blocks),
            packed_evidence_count=len(packed),
            dropped_evidence_count=len(evidence_blocks) - len(packed),
        )
        return PackedAnswerContext(tuple(packed), receipt)

    def validate_reserved_messages(self, messages: list[dict[str, Any]]) -> None:
        """evidence 없는 system·user prompt가 각 예약분을 넘으면 외부 호출 전에 거부한다."""

        if (
            len(messages) != 2
            or messages[0].get("role") != "system"
            or messages[1].get("role") != "user"
            or not isinstance(messages[0].get("content"), str)
            or not isinstance(messages[1].get("content"), str)
        ):
            raise ValueError("RAG answer prompt must contain one system and one user message")
        system_tokens = (
            self.conservative_token_count(messages[0]["content"])
            + _CHAT_MESSAGE_OVERHEAD_TOKENS
        )
        question_tokens = (
            self.conservative_token_count(messages[1]["content"])
            + _CHAT_MESSAGE_OVERHEAD_TOKENS
        )
        if system_tokens > self.reserved_system_tokens:
            raise ValueError("RAG answer system prompt exceeds its context reservation")
        if question_tokens > self.reserved_question_tokens:
            raise ValueError("RAG answer question exceeds its context reservation")
