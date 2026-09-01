"""문서 metadata와 구조 경로를 dense embedding 입력으로 결정론적으로 조합한다."""

from __future__ import annotations

from collections.abc import Callable

from .token_chunker import TOKEN_PATTERN
from .vector_models import PdfChunk, PdfDocument


EMBEDDING_INPUT_CONTRACT_VERSION = "document-section-content-v1.0"
_MAXIMUM_INPUT_CHARACTERS = 12_000
_METADATA_LIMITS = {
    "title": 200,
    "version": 100,
    "document_type": 100,
    "owner_team": 100,
    "section_title": 500,
}


class EmbeddingInputBuilder:
    """저장 evidence는 변경하지 않고 bounded dense 입력을 별도로 생성한다."""

    def __init__(
        self,
        maximum_tokens: int,
        token_counter: Callable[[str], int] | None = None,
    ) -> None:
        if type(maximum_tokens) is not int or maximum_tokens < 256:
            raise ValueError("RAG embedding input token limit is invalid")
        self._maximum_tokens = maximum_tokens
        self._token_counter = token_counter

    def build(self, document: PdfDocument, chunk: PdfChunk) -> str:
        """문서·chunk provenance를 확인하고 metadata context를 붙인 입력을 반환한다."""

        if chunk.manual_id != document.manual_id or not chunk.content.strip():
            raise ValueError("RAG embedding input provenance is invalid")
        metadata = {
            "title": self._metadata_value(document.title, "title"),
            "version": self._metadata_value(document.version, "version"),
            "document_type": self._metadata_value(
                document.document_type,
                "document_type",
            ),
            "owner_team": self._metadata_value(document.owner_team, "owner_team"),
            "section_title": self._metadata_value(
                chunk.section_title,
                "section_title",
            ),
        }
        value = "\n".join(
            (
                "[DOCUMENT_CONTEXT]",
                f"title: {metadata['title']}",
                f"version: {metadata['version']}",
                f"document_type: {metadata['document_type']}",
                f"owner_team: {metadata['owner_team']}",
                f"section: {metadata['section_title']}",
                "[CONTENT]",
                chunk.content,
            )
        )
        if (
            len(value) > _MAXIMUM_INPUT_CHARACTERS
            or self.token_count(value) > self._maximum_tokens
        ):
            raise ValueError("RAG embedding input exceeds the configured context limit")
        return value

    def token_count(self, value: str) -> int:
        """provider tokenizer가 있으면 사용하고 없으면 보수적 문자·token 상한을 센다."""

        count = (
            self._token_counter(value)
            if self._token_counter is not None
            else max(len(TOKEN_PATTERN.findall(value)), len(value))
        )
        if type(count) is not int or count < 0:
            raise ValueError("RAG embedding token counter returned an invalid value")
        return count

    @staticmethod
    def _metadata_value(value: str, field: str) -> str:
        normalized = " ".join(value.split())
        if not normalized or len(normalized) > _METADATA_LIMITS[field]:
            raise ValueError(f"RAG embedding {field} metadata is invalid")
        return normalized
