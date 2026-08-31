"""manifest 문서를 PDF 또는 DOCX parser로 안전하게 dispatch한다."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .corpus_manifest import CorpusManifest, CorpusManifestDocument
from .docx_ingestion import DOCX_PARSER_CONTRACT_VERSION, DocxReportParser
from .pdf_ingestion import PDF_PARSER_CONTRACT_VERSION, PdfManualParser
from .vector_models import PdfChunk, PdfDocument

if TYPE_CHECKING:
    from .token_chunker import TokenChunker


class CorpusDocumentParser:
    """manifest에 봉인된 immutable source를 승인된 형식 parser로 전달한다."""

    def __init__(self, chunker: "TokenChunker") -> None:
        self._pdf = PdfManualParser(chunker=chunker)
        self._docx = DocxReportParser(chunker=chunker)

    def parse(
        self,
        path: Path,
        entry: CorpusManifestDocument,
    ) -> tuple[PdfDocument, list[PdfChunk], list[str], dict[str, Any]]:
        """원본 형식별 구조를 추출하고 provenance·receipt가 불일치하면 실패한다."""

        suffix = path.suffix.lower()
        if suffix == ".pdf":
            document, chunks, warnings, receipt = self._pdf.parse(path)
            CorpusManifest.validate_parsed_document(
                entry,
                document.manual_id,
                document.checksum,
            )
            if entry.source_version is not None:
                document = replace(
                    document,
                    version=entry.source_version,
                    role_scope=entry.role_scope or (),
                    document_type=entry.document_kind,
                    owner_team=entry.owner_team or "UNASSIGNED",
                    approval_status="APPROVED",
                    validity_status="VALID",
                )
            else:
                document = replace(
                    document,
                    approval_status="APPROVED",
                    validity_status="VALID",
                )
            receipt = {
                **receipt,
                "source_format": "pdf",
                "source_version": document.version,
                "document_kind": document.document_type,
                "owner_team": document.owner_team,
                "metadata": {
                    "period": entry.period,
                    "department": entry.department,
                },
            }
            self._validate_internal_report_receipt(entry, receipt)
            return document, chunks, warnings, receipt
        if suffix == ".docx":
            if (
                entry.source_version is None
                or entry.role_scope is None
                or entry.owner_team is None
            ):
                raise ValueError("DOCX sources require the v2 corpus manifest contract")
            document, chunks, warnings, receipt = self._docx.parse(
                path,
                manual_id=entry.manual_id,
                source_version=entry.source_version,
                role_scope=entry.role_scope,
                document_type=entry.document_kind,
                owner_team=entry.owner_team,
            )
            CorpusManifest.validate_parsed_document(
                entry,
                document.manual_id,
                document.checksum,
            )
            document = replace(
                document,
                approval_status="APPROVED",
                validity_status="VALID",
            )
            receipt = {
                **receipt,
                "document_kind": document.document_type,
                "owner_team": document.owner_team,
                "metadata": {
                    "period": entry.period,
                    "department": entry.department,
                },
            }
            self._validate_internal_report_receipt(entry, receipt)
            return document, chunks, warnings, receipt
        raise ValueError(f"Unsupported RAG corpus source format: {suffix or 'none'}")

    @staticmethod
    def _validate_internal_report_receipt(
        entry: CorpusManifestDocument,
        receipt: dict[str, Any],
    ) -> None:
        """특정 보고서 layout을 강제하지 않고 provenance·구조 receipt 누락을 거부한다."""

        if entry.document_kind != "INTERNAL_REPORT":
            return
        expected_parser_contract = {
            "docx": DOCX_PARSER_CONTRACT_VERSION,
            "pdf": PDF_PARSER_CONTRACT_VERSION,
        }.get(entry.source_format)
        if (
            receipt.get("source_checksum") != entry.source_sha256
            or receipt.get("parser_contract_version") != expected_parser_contract
        ):
            raise ValueError("RAG internal report provenance receipt is invalid")
        required_counts = {
            "content_unit_count": receipt.get("content_unit_count"),
            "chunk_count": receipt.get("chunk_count"),
        }
        if any(
            type(value) is not int or value < 1
            for value in required_counts.values()
        ):
            raise ValueError("RAG internal report extraction receipt is incomplete")

        structure = receipt.get("structure")
        if entry.source_format == "docx" and not isinstance(structure, dict):
            raise ValueError("RAG internal report extraction receipt is missing")
        if structure is not None and (
            not isinstance(structure, dict)
            or not structure
            or any(type(value) is not int or value < 0 for value in structure.values())
        ):
            raise ValueError("RAG internal report structure receipt is invalid")
