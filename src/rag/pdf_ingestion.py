"""PDF 매뉴얼을 페이지별 안전 text block과 checksum receipt로 변환한다."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from .source_bytes import DEFAULT_MAX_SOURCE_BYTES, read_bounded_source_bytes
from .text_processing import SecurityScanner
from .vector_models import PdfChunk, PdfDocument


MANUAL_ID_PATTERN = re.compile(
    r"(?<![A-Z0-9-])(INDEX-\d{3}|POL-[A-Z]+-\d{3}|POLICY-[A-Z]+-\d{3}|"
    r"REPORT-RULE-\d{3}|SOP-[A-Z]+-\d{3})(?![A-Z0-9-])"
)
VERSION_PATTERN = re.compile(r"\bv(\d+(?:\.\d+)*)\b", re.IGNORECASE)
SECTION_PATTERN = re.compile(r"(?m)^\s*(\d+(?:\.\d+)*)[.)]\s+([^\n]{2,100})")
PDF_PARSER_CONTRACT_VERSION = "fitz-blocks-v1.1"
PDF_MAX_SOURCE_BYTES = DEFAULT_MAX_SOURCE_BYTES


def read_bounded_pdf_bytes(path: Path) -> bytes:
    """PDF 원본을 고정 상한까지만 읽어 parser와 source 응답의 메모리 경계를 통일한다."""

    return read_bounded_source_bytes(
        path,
        expected_suffix=".pdf",
        maximum_bytes=PDF_MAX_SOURCE_BYTES,
    )


class PdfManualParser:
    """PyMuPDF text block을 보안 검사한 뒤 페이지 locator chunk로 생성한다."""

    def __init__(self, chunker: "TokenChunker", maximum_empty_page_ratio: float = 0.05) -> None:
        self._chunker = chunker
        self._maximum_empty_page_ratio = maximum_empty_page_ratio
        self._scanner = SecurityScanner()

    def parse(self, path: Path) -> tuple[PdfDocument, list[PdfChunk], list[str], dict[str, Any]]:
        """PDF bytes·페이지를 검증하고 문서·chunk·경고·구조 receipt를 반환한다."""

        source_bytes = read_bounded_pdf_bytes(path)
        source_checksum = hashlib.sha256(source_bytes).hexdigest()
        pages, image_receipts = self._extract_pages(source_bytes)

        page_count = len(pages)
        empty_page_count = sum(1 for _, blocks in pages if not blocks)
        empty_page_ratio = empty_page_count / page_count if page_count > 0 else 0

        warnings: list[str] = []
        if empty_page_count > 0:
            warnings.append(f"{path.name}: EMPTY_TEXT_PAGE ({empty_page_count} pages)")
        if image_receipts:
            warnings.append("IMAGE_BINARY_NOT_OCR_EXTRACTED")

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
        content_unit_count = 0
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

            content_unit_count += len(safe_blocks)
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
            "parser_contract_version": PDF_PARSER_CONTRACT_VERSION,
            "content_unit_count": content_unit_count,
            "page_count": page_count,
            "parsed_page_count": len(valid_pages),
            "empty_page_count": empty_page_count,
            "empty_page_ratio": empty_page_ratio,
            "image_count": len(image_receipts),
            "image_receipts": image_receipts,
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

    def _extract_pages(
        self,
        source_bytes: bytes,
    ) -> tuple[list[tuple[int, list[str]]], list[dict[str, object]]]:
        try:
            import fitz
        except ModuleNotFoundError as error:
            raise RuntimeError("PyMuPDF is required to parse PDF manuals") from error
        pages: list[tuple[int, list[str]]] = []
        image_receipts: list[dict[str, object]] = []
        with fitz.open(stream=source_bytes, filetype="pdf") as document:
            for index, page in enumerate(document):
                # get_text("blocks") returns tuple: (x0, y0, x1, y1, text, block_no, block_type)
                # We need to sort and keep block_type 0 (text)
                blocks = page.get_text("blocks", sort=True)
                text_blocks = [b[4].strip() for b in blocks if b[6] == 0 and b[4].strip()]
                pages.append((index + 1, text_blocks))
                structured = page.get_text("dict", sort=True)
                structured_blocks = (
                    structured.get("blocks", [])
                    if isinstance(structured, dict)
                    else []
                )
                page_image_index = 0
                for block in structured_blocks:
                    if not isinstance(block, dict) or block.get("type") != 1:
                        continue
                    image = block.get("image")
                    if not isinstance(image, bytes) or not image:
                        raise ValueError("PDF image block has no immutable source bytes")
                    page_image_index += 1
                    image_receipts.append(
                        {
                            "page": index + 1,
                            "image_index": page_image_index,
                            "sha256": hashlib.sha256(image).hexdigest(),
                            "size_bytes": len(image),
                        }
                    )
        return pages, image_receipts

    def _extract_manual_id(self, path: Path, text: str) -> str:
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
