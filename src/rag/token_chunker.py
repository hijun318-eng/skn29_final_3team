import hashlib
import re
from typing import Any

from .vector_models import PdfChunk


SECTION_PATTERN = re.compile(r"(?m)^\s*(\d+(?:\.\d+)*)[.)]\s+([^\n]{2,100})")
TOKEN_PATTERN = re.compile(r"[가-힣]|[A-Za-z0-9_]+|[^\s]")
SENTENCE_PATTERN = re.compile(r"(?<=[.!?。])\s+|\n+")


class TokenChunker:
    """모델 tokenizer와 무관하게 문단·문장 경계를 우선하는 재현 가능한 chunker다."""

    def __init__(self, provider: Any, max_tokens: int, overlap_tokens: int, min_tokens: int = 24):
        self.provider = provider
        self.max_tokens = max_tokens
        self.overlap_tokens = overlap_tokens
        self.min_tokens = min_tokens
        self.schema_version = "sentence-v2.0"

    def chunk_blocks(self, manual_id: str, page_number: int, blocks: list[str]) -> list[PdfChunk]:
        chunks: list[PdfChunk] = []
        current_section = "페이지 본문"
        current_buffer: list[str] = []

        def commit_buffer() -> None:
            nonlocal current_buffer
            text = "\n\n".join(current_buffer).strip()
            if not text:
                current_buffer = []
                return
            for piece in self._split_complete_units(text):
                token_count = self._count(piece)
                if token_count >= self.min_tokens:
                    self._add_chunk(chunks, manual_id, page_number, current_section, piece, token_count)
            current_buffer = []

        for block in blocks:
            section_match = SECTION_PATTERN.search(block)
            if section_match:
                commit_buffer()
                current_section = f"{section_match.group(1)}. {section_match.group(2).strip()}"
            current_buffer.append(block)
        commit_buffer()
        return chunks

    def _split_complete_units(self, text: str) -> list[str]:
        units = [unit.strip() for unit in SENTENCE_PATTERN.split(text) if unit.strip()]
        chunks: list[str] = []
        current: list[str] = []
        current_count = 0
        for unit in units:
            unit_count = self._count(unit)
            if current and current_count + unit_count > self.max_tokens:
                chunks.append("\n".join(current))
                current = self._overlap_units(current)
                current_count = self._count("\n".join(current))
            if unit_count > self.max_tokens:
                if current:
                    chunks.append("\n".join(current))
                    current, current_count = [], 0
                chunks.extend(self._split_long_unit(unit))
            else:
                current.append(unit)
                current_count += unit_count
        if current:
            chunks.append("\n".join(current))
        return chunks

    def _overlap_units(self, units: list[str]) -> list[str]:
        overlap: list[str] = []
        count = 0
        for unit in reversed(units):
            unit_count = self._count(unit)
            if count + unit_count > self.overlap_tokens:
                break
            overlap.insert(0, unit)
            count += unit_count
        return overlap

    def _split_long_unit(self, text: str) -> list[str]:
        words = text.split()
        if len(words) <= 1:
            return [text[index:index + self.max_tokens] for index in range(0, len(text), self.max_tokens)]
        pieces: list[str] = []
        current: list[str] = []
        for word in words:
            candidate = " ".join((*current, word))
            if current and self._count(candidate) > self.max_tokens:
                pieces.append(" ".join(current))
                current = [word]
            else:
                current.append(word)
        if current:
            pieces.append(" ".join(current))
        return pieces or [text]

    @staticmethod
    def _count(text: str) -> int:
        return len(TOKEN_PATTERN.findall(text))

    @staticmethod
    def _add_chunk(chunks: list[PdfChunk], manual_id: str, page_number: int, section_title: str, text: str, token_count: int) -> None:
        checksum = hashlib.sha256(text.encode("utf-8")).hexdigest()
        chunk_id = hashlib.sha256(f"{manual_id}|{page_number}|{len(chunks)}|{checksum}".encode("utf-8")).hexdigest()[:32]
        chunks.append(PdfChunk(
            chunk_id=chunk_id,
            manual_id=manual_id,
            page_start=page_number,
            page_end=page_number,
            section_title=section_title,
            content=text,
            checksum=checksum,
            token_count=token_count,
            chunk_index=len(chunks),
        ))
