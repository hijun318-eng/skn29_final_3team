from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from .text_processing import SecurityScanner
from .vector_models import PdfChunk, PdfDocument


MANUAL_ID_PATTERN = re.compile(
    r"(?<![A-Z0-9-])(INDEX-\d{3}|POL-[A-Z]+-\d{3}|POLICY-[A-Z]+-\d{3}|"
    r"REPORT-RULE-\d{3}|SOP-[A-Z]+-\d{3})(?![A-Z0-9-])"
)
VERSION_PATTERN = re.compile(r"\bv(\d+(?:\.\d+)*)\b", re.IGNORECASE)
SECTION_PATTERN = re.compile(r"(?m)^\s*(\d+(?:\.\d+)*)[.)]\s+([^\n]{2,100})")


class PdfManualParser:
    def __init__(self, chunker: "TokenChunker", maximum_empty_page_ratio: float = 0.05) -> None:
        self._chunker = chunker
        self._maximum_empty_page_ratio = maximum_empty_page_ratio
        self._scanner = SecurityScanner()

    def parse(self, path: Path) -> tuple[PdfDocument, list[PdfChunk], list[str], dict[str, Any]]:
        source_bytes = path.read_bytes()
        source_checksum = hashlib.sha256(source_bytes).hexdigest()
        pages = self._extract_pages(path)

        page_count = len(pages)
        empty_page_count = sum(1 for _, blocks in pages if not blocks)
        empty_page_ratio = empty_page_count / page_count if page_count > 0 else 0

        warnings: list[str] = []
        if empty_page_count > 0:
            warnings.append(f"{path.name}: EMPTY_TEXT_PAGE ({empty_page_count} pages)")

        if empty_page_ratio > self._maximum_empty_page_ratio:
            raise ValueError(f"OCR_REQUIRED: Empty page ratio {empty_page_ratio:.2f} exceeds {self._maximum_empty_page_ratio:.2f}")

        valid_pages = [(num, blocks) for num, blocks in pages if blocks]
        if not valid_pages:
            raise ValueError(f"No valid text pages found in {path.name}")

        first_page_text = " ".join(valid_pages[0][1])
        manual_id = self._extract_manual_id(path, first_page_text)
        version = self._extract_version(path.name, first_page_text)
        title = self._extract_title(path, first_page_text, manual_id)

        chunks: list[PdfChunk] = []
        for page_number, blocks in valid_pages:
            # Check security per block and combine safe text
            safe_blocks = []
            for block in blocks:
                status, safe_text = self._scanner.inspect(block)
                if status == "REJECTED_SECRET":
                    warnings.append(f"{path.name}: page {page_number} rejected by secret scanner")
                    continue
                if status == "MASKED_PII":
                    warnings.append(f"{path.name}: page {page_number} contains masked PII")
                if safe_text.strip():
                    safe_blocks.append(safe_text)

            page_chunks = self._chunker.chunk_blocks(manual_id, page_number, safe_blocks)
            chunks.extend(page_chunks)

        document = PdfDocument(
            manual_id=manual_id,
            title=title,
            version=version,
            source_path=str(path.resolve()),
            checksum=source_checksum,
            role_scope=(
                "ANALYST",
                "PLATFORM_ADMIN",
                "STAFF",
                "MANAGER",
                "SYSTEM_ADMIN",
            ),
        )

        chunk_tokens = [c.token_count for c in chunks]
        manifest = {
            "manual_id": manual_id,
            "source_checksum": source_checksum,
            "page_count": page_count,
            "parsed_page_count": len(valid_pages),
            "empty_page_count": empty_page_count,
            "empty_page_ratio": empty_page_ratio,
            "section_count": len(set(c.section_title for c in chunks)),
            "chunk_count": len(chunks),
            "minimum_chunk_tokens": min(chunk_tokens) if chunk_tokens else 0,
            "maximum_chunk_tokens": max(chunk_tokens) if chunk_tokens else 0,
            "mean_chunk_tokens": sum(chunk_tokens) / len(chunk_tokens) if chunk_tokens else 0,
            "parser_warnings": warnings,
            "chunking_schema_version": self._chunker.schema_version,
            "embedding_profile_id": self._chunker.provider.model_id
        }

        return document, chunks, warnings, manifest

    def _extract_pages(self, path: Path) -> list[tuple[int, list[str]]]:
        try:
            import fitz
        except ModuleNotFoundError as error:
            raise RuntimeError("PyMuPDF is required to parse PDF manuals") from error
        pages = []
        with fitz.open(path) as document:
            for index, page in enumerate(document):
                # get_text("blocks") returns tuple: (x0, y0, x1, y1, text, block_no, block_type)
                # We need to sort and keep block_type 0 (text)
                blocks = page.get_text("blocks", sort=True)
                text_blocks = [b[4].strip() for b in blocks if b[6] == 0 and b[4].strip()]
                pages.append((index + 1, text_blocks))
        return pages

    def _extract_manual_id(self, path: Path, text: str) -> str:
        if "내부업무매뉴얼_통합본" in path.name:
            return "MANUAL-COMBINED-001"
        match = MANUAL_ID_PATTERN.search(text) or MANUAL_ID_PATTERN.search(path.name)
        if match:
            return match.group(1)
        return f"MANUAL-{hashlib.sha256(path.name.encode('utf-8')).hexdigest()[:12].upper()}"

    def _extract_version(self, filename: str, text: str) -> str:
        match = VERSION_PATTERN.search(filename) or VERSION_PATTERN.search(text)
        return match.group(1) if match else "UNRESOLVED"

    def _extract_title(self, path: Path, text: str, manual_id: str) -> str:
        stem = re.sub(r"^\d{6}_", "", path.stem)
        stem = re.sub(r"^00_", "", stem)
        stem = re.sub(r"_업무숙지본_v\d+(?:\.\d+)*$", "", stem)
        if manual_id in stem:
            filename_title = stem.split(manual_id, maxsplit=1)[1].strip(" _-")
            if filename_title:
                return filename_title[:200]
        if stem:
            return stem.replace("_", " ")[:200]
        compact = " ".join(text.split())
        position = compact.find(manual_id)
        tail = compact[position + len(manual_id) :] if position >= 0 else compact
        title = re.split(r"내부 업무 매뉴얼|문서 ID", tail, maxsplit=1)[0].strip()
        return title[:200] or manual_id
