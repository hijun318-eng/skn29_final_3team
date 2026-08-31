"""PDF text와 구조화 DOCX block을 token 한도 안의 검색 chunk로 분할한다."""

import hashlib
import re
from typing import Any

from .vector_models import PdfChunk


SECTION_PATTERN = re.compile(r"(?m)^\s*(\d+(?:\.\d+)*)[.)]\s+([^\n]{2,100})")
TOKEN_PATTERN = re.compile(r"[가-힣]|[A-Za-z0-9_]+|[^\s]")
SENTENCE_PATTERN = re.compile(r"(?<=[.!?。])\s+|\n+")
TABLE_START_PATTERN = re.compile(r"^\[TABLE\b[^\n]*\]")
TABLE_CELL_MARKER_PATTERN = re.compile(r"\[(r\d+c\d+)\b[^\]]*\]\s*")
TOKEN_CHUNKER_SCHEMA_VERSION = "sentence-v2.3-structured-table-v1"
TOKEN_CHUNKER_DEFAULT_MIN_TOKENS = 24


class TokenChunker:
    """모델 tokenizer와 무관하게 문단·문장 경계를 우선하는 재현 가능한 chunker다."""

    def __init__(
        self,
        provider: Any,
        max_tokens: int,
        overlap_tokens: int,
        min_tokens: int = TOKEN_CHUNKER_DEFAULT_MIN_TOKENS,
    ):
        self.provider = provider
        self.max_tokens = max_tokens
        self.overlap_tokens = overlap_tokens
        self.min_tokens = min_tokens
        self.schema_version = TOKEN_CHUNKER_SCHEMA_VERSION

    def chunk_blocks(self, manual_id: str, page_number: int, blocks: list[str]) -> list[PdfChunk]:
        """페이지 text block을 문장 경계와 overlap을 적용한 순서 보존 chunk로 만든다."""

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

    def chunk_structured_blocks(
        self,
        manual_id: str,
        location_index: int,
        section_title: str,
        blocks: list[str],
        *,
        chunk_index_offset: int = 0,
    ) -> list[PdfChunk]:
        """구조 block을 순서대로 pack하고 분할 표마다 identity·header context를 보존한다."""

        if type(chunk_index_offset) is not int or chunk_index_offset < 0:
            raise ValueError("Structured chunk index offset must be a non-negative integer")
        ordered_blocks = [block.strip() for block in blocks if block.strip()]
        if not ordered_blocks:
            return []
        pieces: list[str] = []
        current_blocks: list[str] = []

        def commit_blocks() -> None:
            nonlocal current_blocks
            if current_blocks:
                pieces.append("\n\n".join(current_blocks))
            current_blocks = []

        for block in ordered_blocks:
            block_count = self._count(block)
            if self._is_table_block(block) and block_count > self.max_tokens:
                commit_blocks()
                pieces.extend(self._split_structured_table(block))
                continue
            if block_count > self.max_tokens:
                commit_blocks()
                pieces.extend(self._split_complete_units(block))
                continue
            candidate = "\n\n".join((*current_blocks, block))
            if current_blocks and self._count(candidate) > self.max_tokens:
                commit_blocks()
            current_blocks.append(block)
        commit_blocks()

        chunks: list[PdfChunk] = []
        for piece in pieces:
            if piece.strip():
                self._add_chunk(
                    chunks,
                    manual_id,
                    location_index,
                    section_title,
                    piece,
                    self._count(piece),
                    chunk_index=chunk_index_offset + len(chunks),
                )
        return chunks

    @staticmethod
    def _is_table_block(block: str) -> bool:
        lines = block.splitlines()
        return bool(
            lines
            and TABLE_START_PATTERN.fullmatch(lines[0].strip())
            and lines[-1].strip() == "[/TABLE]"
        )

    def _split_structured_table(self, block: str) -> list[str]:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if len(lines) < 2 or not self._is_table_block(block):
            return self._split_complete_units(block)
        table_identity = lines[0]
        payload_lines = lines[1:-1]
        header_context = self._table_header_context(payload_lines)
        wrapper_probe = self._wrap_table_segment(
            table_identity,
            9999,
            [],
            header_context,
        )
        payload_limit = self.max_tokens - self._count(wrapper_probe)
        if payload_limit < 8:
            raise ValueError("Chunk token limit is too small for structured table context")

        payload_units: list[str] = []
        for line in payload_lines:
            payload_units.extend(self._split_table_line(line, payload_limit))
        if not payload_units:
            payload_units = ["[TABLE_EMPTY]"]

        segment_payloads: list[list[str]] = []
        current: list[str] = []
        for unit in payload_units:
            candidate = [*current, unit]
            wrapped = self._wrap_table_segment(
                table_identity,
                len(segment_payloads) + 1,
                candidate,
                header_context,
            )
            if current and self._count(wrapped) > self.max_tokens:
                segment_payloads.append(current)
                current = [unit]
            else:
                current = candidate
        if current:
            segment_payloads.append(current)

        segments = [
            self._wrap_table_segment(
                table_identity,
                index,
                payload,
                header_context if index > 1 else None,
            )
            for index, payload in enumerate(segment_payloads, start=1)
        ]
        if any(self._count(segment) > self.max_tokens for segment in segments):
            raise ValueError("Structured table segment exceeds the chunk token limit")
        return segments

    def _table_header_context(self, payload_lines: list[str]) -> str | None:
        header = next(
            (line for line in payload_lines if TABLE_CELL_MARKER_PATTERN.search(line)),
            None,
        )
        if header is None:
            return None
        digest = hashlib.sha256(header.encode("utf-8")).hexdigest()[:16]
        labels = TABLE_CELL_MARKER_PATTERN.sub("", header).strip(" |")
        labels = self._truncate_to_tokens(
            labels,
            max(8, min(96, self.max_tokens // 4)),
        )
        return f"[TABLE_HEADER_CONTEXT source_row=1 sha256={digest}] {labels}".strip()

    def _split_table_line(self, line: str, limit: int) -> list[str]:
        if self._count(line) <= limit:
            return [line]
        matches = list(TABLE_CELL_MARKER_PATTERN.finditer(line))
        if not matches:
            return self._split_long_unit_with_limit(line, limit)
        cell_units = [
            line[
                match.start() : (
                    matches[index + 1].start()
                    if index + 1 < len(matches)
                    else None
                )
            ].strip(" |")
            for index, match in enumerate(matches)
        ]
        preamble = line[: matches[0].start()].strip()
        if preamble:
            cell_units.insert(0, preamble)
        split_cells: list[str] = []
        for cell in cell_units:
            if self._count(cell) <= limit:
                split_cells.append(cell)
            else:
                split_cells.extend(self._split_table_cell(cell, limit))

        pieces: list[str] = []
        current: list[str] = []
        for cell in split_cells:
            candidate = " | ".join((*current, cell))
            if current and self._count(candidate) > limit:
                pieces.append(" | ".join(current))
                current = [cell]
            else:
                current.append(cell)
        if current:
            pieces.append(" | ".join(current))
        return pieces

    def _split_table_cell(self, cell: str, limit: int) -> list[str]:
        marker = TABLE_CELL_MARKER_PATTERN.match(cell)
        if marker is None:
            return self._split_long_unit_with_limit(cell, limit)
        source_cell = marker.group(1)
        marker_text = marker.group(0).strip()
        remaining = cell[marker.end() :].strip()
        pieces: list[str] = []
        segment_index = 1
        while remaining:
            prefix = (
                marker_text
                if segment_index == 1
                else f"[CELL_CONTINUATION source={source_cell} segment={segment_index}]"
            )
            available = limit - self._count(prefix)
            if available < 1:
                raise ValueError("Chunk token limit is too small for table cell metadata")
            content = self._truncate_to_tokens(remaining, available)
            if not content:
                raise ValueError("Unable to split an oversized structured table cell")
            pieces.append(f"{prefix} {content}".strip())
            remaining = remaining[len(content) :].lstrip()
            segment_index += 1
        return pieces or [marker_text]

    @staticmethod
    def _wrap_table_segment(
        table_identity: str,
        segment_index: int,
        payload: list[str],
        header_context: str | None,
    ) -> str:
        lines = [table_identity, f"[TABLE_SEGMENT index={segment_index}]"]
        if header_context:
            lines.append(header_context)
        lines.extend(payload)
        lines.extend(("[/TABLE_SEGMENT]", "[/TABLE]"))
        return "\n".join(lines)

    def _truncate_to_tokens(self, text: str, limit: int) -> str:
        if self._count(text) <= limit:
            return text
        low = 0
        high = len(text)
        while low < high:
            middle = (low + high + 1) // 2
            if self._count(text[:middle]) <= limit:
                low = middle
            else:
                high = middle - 1
        return text[:low].rstrip()

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
                if current and current_count + unit_count > self.max_tokens:
                    current, current_count = [], 0
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
        return self._split_long_unit_with_limit(text, self.max_tokens)

    def _split_long_unit_with_limit(self, text: str, limit: int) -> list[str]:
        pieces: list[str] = []
        remaining = text.strip()
        while remaining:
            if self._count(remaining) <= limit:
                pieces.append(remaining)
                break
            candidate = self._truncate_to_tokens(remaining, limit)
            if not candidate:
                raise ValueError("Unable to split content within the chunk token limit")
            whitespace = max(
                candidate.rfind(" "),
                candidate.rfind("\t"),
                candidate.rfind("\n"),
            )
            if whitespace > 0:
                piece = candidate[:whitespace].rstrip()
                consumed = whitespace + 1
            else:
                piece = candidate
                consumed = len(candidate)
            pieces.append(piece)
            remaining = remaining[consumed:].lstrip()
        return pieces or [text]

    @staticmethod
    def _count(text: str) -> int:
        return len(TOKEN_PATTERN.findall(text))

    @staticmethod
    def _add_chunk(
        chunks: list[PdfChunk],
        manual_id: str,
        page_number: int,
        section_title: str,
        text: str,
        token_count: int,
        *,
        chunk_index: int | None = None,
    ) -> None:
        resolved_index = len(chunks) if chunk_index is None else chunk_index
        if type(resolved_index) is not int or resolved_index < 0:
            raise ValueError("Chunk index must be a non-negative integer")
        checksum = hashlib.sha256(text.encode("utf-8")).hexdigest()
        chunk_id = hashlib.sha256(
            f"{manual_id}|{page_number}|{resolved_index}|{checksum}".encode("utf-8")
        ).hexdigest()[:32]
        chunks.append(PdfChunk(
            chunk_id=chunk_id,
            manual_id=manual_id,
            page_start=page_number,
            page_end=page_number,
            section_title=section_title,
            content=text,
            checksum=checksum,
            token_count=token_count,
            chunk_index=resolved_index,
        ))
