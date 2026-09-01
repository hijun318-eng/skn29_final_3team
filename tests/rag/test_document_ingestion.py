from __future__ import annotations

import hashlib
import io
import json
import os
import re
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from src.rag.corpus_manifest import (
    CORPUS_MANIFEST_VERSION_V2,
    CorpusManifest,
    CorpusManifestDocument,
)
from src.rag.api import create_app
from src.rag.document_ingestion import CorpusDocumentParser
from src.rag.embedding_input import EmbeddingInputBuilder
from src.rag.docx_ingestion import (
    DOCX_PARSER_CONTRACT_VERSION,
    DocxReportParser,
    _DocxExtractor,
)
from src.rag.source_bytes import (
    SOURCE_MAX_BYTES_BY_SUFFIX,
    read_bounded_source_bytes,
)
from src.rag.token_chunker import TokenChunker
from src.rag.vector_application import VectorRagApplication
from src.rag.vector_models import PdfChunk, PdfDocument


CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Default Extension="png" ContentType="image/png"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>"""
ROOT_RELS = """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""
DOCUMENT_RELS = """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rIdLink" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" Target="https://intranet.example/policy" TargetMode="External"/>
  <Relationship Id="rIdImage" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/chart.png"/>
  <Relationship Id="rIdHeader" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/header" Target="header1.xml"/>
  <Relationship Id="rIdFooter" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer" Target="footer1.xml"/>
</Relationships>"""
DOCUMENT_XML = """<?xml version="1.0" encoding="UTF-8"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
 xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
 xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing">
 <w:body>
  <w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Overview</w:t></w:r></w:p>
  <w:p><w:pPr><w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr></w:pPr>
   <w:r><w:t>First item</w:t></w:r><w:hyperlink r:id="rIdLink"><w:r><w:t>Policy link</w:t></w:r></w:hyperlink>
   <w:r><w:br w:type="page"/><w:t>After explicit break</w:t><w:lastRenderedPageBreak/><w:t>After rendered break</w:t></w:r>
  </w:p>
  <w:tbl><w:tblPr><w:tblStyle w:val="ReportTable"/></w:tblPr>
   <w:tr><w:tc><w:tcPr><w:gridSpan w:val="2"/><w:vMerge w:val="restart"/></w:tcPr><w:p><w:r><w:t>Merged value</w:t></w:r></w:p></w:tc>
   <w:tc><w:p><w:r><w:t>Third column</w:t></w:r></w:p></w:tc></w:tr>
   <w:tr><w:tc><w:tcPr><w:gridSpan w:val="2"/><w:vMerge/></w:tcPr><w:p/></w:tc><w:tc><w:p><w:r><w:t>Detail</w:t></w:r></w:p></w:tc></w:tr>
  </w:tbl>
  <w:p><w:pPr><w:pStyle w:val="Caption"/></w:pPr><w:r><w:t>Figure 1</w:t></w:r>
   <w:r><w:drawing><wp:inline><wp:docPr id="1" name="Chart" descr="Revenue chart"/><a:graphic><a:graphicData><a:blip r:embed="rIdImage"/></a:graphicData></a:graphic></wp:inline></w:drawing></w:r>
  </w:p>
  <w:p><w:r><w:footnoteReference w:id="2"/><w:endnoteReference w:id="3"/></w:r></w:p>
  <w:sectPr><w:headerReference w:type="default" r:id="rIdHeader"/><w:footerReference w:type="default" r:id="rIdFooter"/><w:type w:val="nextPage"/></w:sectPr>
 </w:body>
</w:document>"""
STYLES_XML = """<?xml version="1.0" encoding="UTF-8"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
 <w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="Heading 1"/><w:pPr><w:outlineLvl w:val="0"/></w:pPr></w:style>
 <w:style w:type="paragraph" w:styleId="Caption"><w:name w:val="Caption"/></w:style>
</w:styles>"""
NUMBERING_XML = """<?xml version="1.0" encoding="UTF-8"?>
<w:numbering xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
 <w:abstractNum w:abstractNumId="1"><w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="decimal"/><w:lvlText w:val="%1."/></w:lvl></w:abstractNum>
 <w:num w:numId="1"><w:abstractNumId w:val="1"/></w:num>
</w:numbering>"""
HEADER_XML = """<w:hdr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:p><w:r><w:t>Approved header</w:t></w:r></w:p></w:hdr>"""
FOOTER_XML = """<w:ftr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:p><w:r><w:t>Approved footer</w:t></w:r></w:p></w:ftr>"""
FOOTNOTES_XML = """<w:footnotes xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:footnote w:id="2"><w:p><w:r><w:t>Footnote content</w:t></w:r></w:p></w:footnote></w:footnotes>"""
ENDNOTES_XML = """<w:endnotes xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:endnote w:id="3"><w:p><w:r><w:t>Endnote content</w:t></w:r></w:p></w:endnote></w:endnotes>"""
CORE_XML = """<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>Monthly report</dc:title><cp:revision>7</cp:revision></cp:coreProperties>"""
COMMENTS_XML = """<w:comments xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:comment w:id="5" w:author="Finance reviewer" w:date="2026-08-30T01:02:03Z"><w:p><w:r><w:t>Review this reported amount.</w:t></w:r></w:p></w:comment></w:comments>"""
IMAGE_BYTES = b"deterministic-image"
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _docx_bytes(
    *,
    document_xml: str = DOCUMENT_XML,
    document_rels: str = DOCUMENT_RELS,
    extras: dict[str, bytes | str] | None = None,
) -> bytes:
    parts: dict[str, bytes | str] = {
        "[Content_Types].xml": CONTENT_TYPES,
        "_rels/.rels": ROOT_RELS,
        "word/document.xml": document_xml,
        "word/_rels/document.xml.rels": document_rels,
        "word/styles.xml": STYLES_XML,
        "word/numbering.xml": NUMBERING_XML,
        "word/header1.xml": HEADER_XML,
        "word/footer1.xml": FOOTER_XML,
        "word/footnotes.xml": FOOTNOTES_XML,
        "word/endnotes.xml": ENDNOTES_XML,
        "word/media/chart.png": IMAGE_BYTES,
        "docProps/core.xml": CORE_XML,
    }
    parts.update(extras or {})
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(parts):
            value = parts[name]
            archive.writestr(name, value.encode("utf-8") if isinstance(value, str) else value)
    return output.getvalue()


def _parser() -> DocxReportParser:
    chunker = TokenChunker(
        SimpleNamespace(model_id="fixture-no-embedding"),
        max_tokens=384,
        overlap_tokens=64,
    )
    return DocxReportParser(chunker)


def _parse(tmp_path: Path, source_bytes: bytes | None = None):
    source = tmp_path / "report.docx"
    source.write_bytes(source_bytes or _docx_bytes())
    return _parser().parse(
        source,
        manual_id="REPORT-FIXTURE-001",
        source_version="2026-08",
        role_scope=("STAFF", "SYSTEM_ADMIN"),
        document_type="INTERNAL_REPORT",
        owner_team="ACCOUNTING",
    )


def test_docx_parser_preserves_structure_and_explicit_locators(tmp_path: Path) -> None:
    document, chunks, warnings, receipt = _parse(tmp_path)
    content = "\n".join(chunk.content for chunk in chunks)
    structure = receipt["structure"]

    assert document.title == "Monthly report"
    assert document.version == "2026-08"
    assert document.document_type == "INTERNAL_REPORT"
    assert document.role_scope == ("STAFF", "SYSTEM_ADMIN")
    assert document.checksum == hashlib.sha256((tmp_path / "report.docx").read_bytes()).hexdigest()
    assert content.index("Overview") < content.index("First item") < content.index("Merged value")
    assert "[HEADING level=1 style=Heading 1]" in content
    assert "[LIST num_id=1 level=0 ordinal=1 format=decimal pattern=%1.]" in content
    assert "[HYPERLINK target=https://intranet.example/policy]" in content
    assert "[r1c1 span=2 vmerge=restart] Merged value" in content
    assert "[r2c1 span=2 vmerge=continue] [EMPTY_CELL]" in content
    assert f"[IMAGE name=Chart alt=Revenue chart sha256={hashlib.sha256(IMAGE_BYTES).hexdigest()}]" in content
    assert "Approved header" in content
    assert "Approved footer" in content
    assert "Footnote content" in content
    assert "Endnote content" in content
    assert structure["explicit_page_break_count"] == 1
    assert structure["last_rendered_page_break_count"] == 1
    assert structure["section_boundary_count"] == 1
    assert structure["header_part_count"] == 1
    assert structure["footer_part_count"] == 1
    assert structure["footnote_count"] == 1
    assert structure["endnote_count"] == 1
    assert structure["grid_span_count"] == 2
    assert structure["vertical_merge_count"] == 2
    assert structure["image_count"] == structure["media_digest_count"] == 1
    assert "EXTERNAL_HYPERLINK_NOT_FETCHED" in warnings
    assert "IMAGE_BINARY_NOT_OCR_EXTRACTED" in warnings
    assert all(" p." not in chunk.section_title for chunk in chunks)


def test_docx_parser_preserves_comments_cr_and_symbol(tmp_path: Path) -> None:
    commented_document = DOCUMENT_XML.replace(
        "<w:r><w:t>Overview</w:t></w:r>",
        (
            '<w:commentRangeStart w:id="5"/>'
            "<w:r><w:t>Overview</w:t><w:cr/>"
            '<w:sym w:font="Wingdings" w:char="F0B7"/>'
            '<w:br w:type="column"/></w:r>'
            '<w:commentRangeEnd w:id="5"/>'
            '<w:r><w:commentReference w:id="5"/></w:r>'
        ),
        1,
    )
    comments_relationship = (
        '  <Relationship Id="rIdComments" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments" '
        'Target="comments.xml"/>\n'
    )
    relationships = DOCUMENT_RELS.replace(
        "</Relationships>",
        comments_relationship + "</Relationships>",
    )

    _document, chunks, _warnings, receipt = _parse(
        tmp_path,
        _docx_bytes(
            document_xml=commented_document,
            document_rels=relationships,
            extras={"word/comments.xml": COMMENTS_XML},
        ),
    )

    content = "\n".join(chunk.content for chunk in chunks)
    assert "[COMMENT_RANGE_START id=5]" in content
    assert "[COMMENT_RANGE_END id=5]" in content
    assert "[COMMENT_REF id=5]" in content
    assert "[SYMBOL font=Wingdings char=F0B7]" in content
    assert "[BREAK type=column]" in content
    assert "Review this reported amount." in content
    assert receipt["structure"]["comment_count"] == 1
    assert receipt["structure"]["comment_reference_count"] == 1
    assert receipt["structure"]["comment_range_count"] == 1


def test_docx_parser_diagnoses_unknown_related_and_table_content(
    tmp_path: Path,
) -> None:
    extended_document = DOCUMENT_XML.replace(
        "<w:p><w:r><w:t>Detail</w:t></w:r></w:p>",
        (
            "<w:customXml><w:r><w:t>Preserved table extension</w:t></w:r>"
            "</w:customXml>"
        ),
        1,
    )
    extended_header = HEADER_XML.replace(
        "</w:hdr>",
        (
            "<w:customXml><w:r><w:t>Preserved header extension</w:t></w:r>"
            "</w:customXml></w:hdr>"
        ),
    )

    _document, chunks, warnings, _receipt = _parse(
        tmp_path,
        _docx_bytes(
            document_xml=extended_document,
            extras={"word/header1.xml": extended_header},
        ),
    )

    content = "\n".join(chunk.content for chunk in chunks)
    assert "Preserved table extension" in content
    assert "Preserved header extension" in content
    assert "UNSUPPORTED_TABLE_CELL_ELEMENT:customXml" in warnings
    assert "UNSUPPORTED_RELATED_ELEMENT:customXml" in warnings


def test_docx_parser_preserves_wrapped_table_rows_and_cells_in_reading_order(
    tmp_path: Path,
) -> None:
    wrapped_table = (
        '<w:tbl><w:tblPr><w:tblStyle w:val="WrappedTable"/></w:tblPr>'
        '<w:sdt><w:sdtPr/><w:sdtContent>'
        '<w:customXml><w:customXmlPr/><w:tr><w:trPr/>'
        '<w:sdt><w:sdtPr/><w:sdtContent><w:ins><w:tc><w:tcPr/>'
        '<w:p><w:r><w:t>Wrapped first</w:t></w:r></w:p>'
        '</w:tc></w:ins></w:sdtContent></w:sdt>'
        '<w:moveTo><w:tc><w:p><w:r><w:t>Wrapped second</w:t></w:r></w:p>'
        '</w:tc></w:moveTo>'
        '</w:tr></w:customXml>'
        '<w:del><w:tr><w:tc><w:p><w:r><w:delText>Wrapped third</w:delText>'
        '</w:r></w:p></w:tc></w:tr></w:del>'
        '</w:sdtContent></w:sdt></w:tbl>'
    )
    document_xml = re.sub(
        r"<w:tbl>.*?</w:tbl>",
        wrapped_table,
        DOCUMENT_XML,
        count=1,
        flags=re.DOTALL,
    )

    _document, chunks, warnings, receipt = _parse(
        tmp_path,
        _docx_bytes(document_xml=document_xml),
    )

    content = "\n".join(chunk.content for chunk in chunks)
    assert content.index("Wrapped first") < content.index("Wrapped second") < content.index("Wrapped third")
    assert receipt["structure"]["table_row_count"] == 2
    assert receipt["structure"]["table_cell_count"] == 3
    assert "TABLE_TR_WRAPPER_PRESERVED:customXml" in warnings
    assert "TABLE_TC_WRAPPER_PRESERVED:ins" in warnings
    assert "TABLE_TC_WRAPPER_PRESERVED:moveTo" in warnings
    assert "TABLE_TR_WRAPPER_PRESERVED:del" in warnings


def test_docx_parser_rejects_comment_anchor_body_mismatch(tmp_path: Path) -> None:
    referenced_document = DOCUMENT_XML.replace(
        "<w:r><w:t>Overview</w:t></w:r>",
        '<w:r><w:t>Overview</w:t><w:commentReference w:id="5"/></w:r>',
        1,
    )

    with pytest.raises(ValueError, match="references and bodies do not match"):
        _parse(tmp_path, _docx_bytes(document_xml=referenced_document))


def test_docx_parser_rejects_comment_range_mismatch(tmp_path: Path) -> None:
    commented_document = DOCUMENT_XML.replace(
        "<w:r><w:t>Overview</w:t></w:r>",
        (
            '<w:commentRangeStart w:id="5"/>'
            '<w:r><w:t>Overview</w:t><w:commentReference w:id="5"/></w:r>'
        ),
        1,
    )
    relationships = DOCUMENT_RELS.replace(
        "</Relationships>",
        (
            '<Relationship Id="rIdComments" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments" '
            'Target="comments.xml"/></Relationships>'
        ),
    )

    with pytest.raises(ValueError, match="range anchors do not match"):
        _parse(
            tmp_path,
            _docx_bytes(
                document_xml=commented_document,
                document_rels=relationships,
                extras={"word/comments.xml": COMMENTS_XML},
            ),
        )


def test_docx_xml_security_scan_covers_declarations_after_first_megabyte() -> None:
    raw = b"x" * (1024 * 1024 + 1) + b"<!DOCTYPE x [<!ENTITY e 'boom'>]>"

    with pytest.raises(ValueError, match="entities"):
        _DocxExtractor._assert_safe_xml(raw)


@pytest.mark.parametrize(
    ("part_name", "payload"),
    [
        ("word/charts/chart1.xml", b"<chart/>"),
        ("word/diagrams/data1.xml", b"<diagram/>"),
        ("word/embeddings/object1.bin", b"ole-object"),
    ],
)
def test_docx_parser_rejects_unsupported_embedded_package_part(
    tmp_path: Path,
    part_name: str,
    payload: bytes,
) -> None:
    with pytest.raises(ValueError, match="Unsupported embedded"):
        _parse(
            tmp_path,
            _docx_bytes(extras={part_name: payload}),
        )


def test_docx_parser_rejects_inline_object_without_silent_loss(tmp_path: Path) -> None:
    object_document = DOCUMENT_XML.replace(
        "<w:r><w:t>Overview</w:t></w:r>",
        "<w:r><w:object/></w:r>",
        1,
    )

    with pytest.raises(ValueError, match="Unsupported embedded DOCX element: object"):
        _parse(tmp_path, _docx_bytes(document_xml=object_document))


def test_docx_parser_receipts_unreferenced_media_instead_of_dropping_it(
    tmp_path: Path,
) -> None:
    _document, _chunks, warnings, receipt = _parse(
        tmp_path,
        _docx_bytes(extras={"word/media/orphan.png": b"orphan-media"}),
    )

    assert "UNREFERENCED_MEDIA_PART_NOT_INDEXED:1" in warnings
    assert receipt["structure"]["unreferenced_media_part_count"] == 1


def test_structured_table_chunking_repeats_context_without_cell_duplication() -> None:
    chunker = TokenChunker(
        SimpleNamespace(model_id="fixture"),
        max_tokens=72,
        overlap_tokens=12,
    )
    rows = [
        f"[r{row}c1 span=1] period-{row} | [r{row}c2 span=1] "
        + " ".join(f"amount-{row}-{index}" for index in range(12))
        for row in range(1, 9)
    ]
    table = "\n".join(("[TABLE index=1 style=Grid]", *rows, "[/TABLE]"))

    chunks = chunker.chunk_structured_blocks(
        "REPORT-TABLE",
        1,
        "Table",
        [table],
    )
    content = "\n".join(chunk.content for chunk in chunks)
    primary_cells = re.findall(r"\[r\d+c\d+\b", content)

    assert len(chunks) > 1
    assert len(primary_cells) == 16
    assert len(set(primary_cells)) == 16
    assert all(chunk.token_count <= 72 for chunk in chunks)
    assert all(
        "[TABLE" in chunk.content
        for chunk in chunks
        if re.search(r"\[r\d+c\d+\b", chunk.content)
    )
    assert all(
        "[TABLE_HEADER_CONTEXT source_row=1" in chunk.content
        for chunk in chunks[1:]
    )


def test_structured_chunk_identity_uses_document_global_offset() -> None:
    chunker = TokenChunker(
        SimpleNamespace(model_id="fixture"),
        max_tokens=72,
        overlap_tokens=12,
        min_tokens=1,
    )
    first = chunker.chunk_structured_blocks(
        "REPORT-REPEATED",
        1,
        "First heading",
        ["동일한 반복 본문"],
        chunk_index_offset=0,
    )
    second = chunker.chunk_structured_blocks(
        "REPORT-REPEATED",
        1,
        "Second heading",
        ["동일한 반복 본문"],
        chunk_index_offset=len(first),
    )

    combined = [*first, *second]
    assert [chunk.chunk_index for chunk in combined] == [0, 1]
    assert len({chunk.chunk_id for chunk in combined}) == 2
    assert [chunk.content for chunk in combined] == ["동일한 반복 본문"] * 2


def test_sentence_overlap_never_emits_a_chunk_over_the_token_limit() -> None:
    chunker = TokenChunker(
        SimpleNamespace(model_id="fixture"),
        max_tokens=100,
        overlap_tokens=70,
        min_tokens=1,
    )
    first = " ".join(f"first{index}" for index in range(60)) + "."
    second = " ".join(f"second{index}" for index in range(60)) + "."

    chunks = chunker.chunk_structured_blocks(
        "REPORT-OVERLAP",
        1,
        "Long sentences",
        [f"{first} {second}"],
    )

    assert len(chunks) == 2
    assert all(chunk.token_count <= 100 for chunk in chunks)
    assert "first0" in chunks[0].content
    assert "second0" in chunks[1].content


def test_docx_heading_context_keeps_at_most_current_and_two_ancestors(
    tmp_path: Path,
) -> None:
    nested_headings = "".join(
        (
            '<w:p><w:pPr><w:pStyle w:val="Heading2"/></w:pPr>'
            '<w:r><w:t>Operations</w:t></w:r></w:p>',
            '<w:p><w:pPr><w:pStyle w:val="Heading3"/></w:pPr>'
            '<w:r><w:t>Revenue</w:t></w:r></w:p>',
            '<w:p><w:pPr><w:pStyle w:val="Heading4"/></w:pPr>'
            '<w:r><w:t>Detail</w:t></w:r></w:p>',
        )
    )
    document_xml = DOCUMENT_XML.replace(
        "  <w:p><w:pPr><w:numPr>",
        nested_headings + "\n  <w:p><w:pPr><w:numPr>",
        1,
    )
    heading_styles = "".join(
        f'<w:style w:type="paragraph" w:styleId="Heading{level}">'
        f'<w:name w:val="Heading {level}"/><w:pPr><w:outlineLvl w:val="{level - 1}"/>'
        "</w:pPr></w:style>"
        for level in (2, 3, 4)
    )
    styles_xml = STYLES_XML.replace(
        "</w:styles>",
        heading_styles + "</w:styles>",
    )

    _document, chunks, _warnings, _receipt = _parse(
        tmp_path,
        _docx_bytes(
            document_xml=document_xml,
            extras={"word/styles.xml": styles_xml},
        ),
    )

    titles = [chunk.section_title for chunk in chunks]
    assert any("Overview > Operations > Revenue" in title for title in titles)
    detail_title = next(title for title in titles if title.endswith("Operations > Revenue > Detail"))
    assert "Overview > Operations > Revenue > Detail" not in detail_title
    assert all("Monthly report" not in chunk.content for chunk in chunks)
    assert all("ACCOUNTING" not in chunk.content for chunk in chunks)


def test_embedding_input_adds_dense_context_without_mutating_evidence_or_role() -> None:
    document = PdfDocument(
        manual_id="REPORT-ONE",
        title="Monthly Revenue Review",
        version="2026-08",
        source_path="/corpus/report.docx",
        checksum="a" * 64,
        role_scope=("ROLE_MUST_REMAIN_A_FILTER",),
        document_type="INTERNAL_REPORT",
        owner_team="ACCOUNTING",
    )
    chunk = PdfChunk(
        chunk_id="chunk-1",
        manual_id="REPORT-ONE",
        page_start=1,
        page_end=1,
        section_title="Operations > Revenue > Detail",
        content="Stored evidence remains byte-identical.",
        checksum="b" * 64,
    )
    builder = EmbeddingInputBuilder(2048)

    first = builder.build(document, chunk)
    second = builder.build(document, chunk)

    assert first == second
    assert "title: Monthly Revenue Review" in first
    assert "version: 2026-08" in first
    assert "document_type: INTERNAL_REPORT" in first
    assert "owner_team: ACCOUNTING" in first
    assert "section: Operations > Revenue > Detail" in first
    assert first.endswith(chunk.content)
    assert chunk.content == "Stored evidence remains byte-identical."
    assert "ROLE_MUST_REMAIN_A_FILTER" not in first
    assert builder.token_count(first) <= 2048


def test_embedding_input_fails_closed_when_context_bound_is_exceeded() -> None:
    document = PdfDocument(
        manual_id="REPORT-ONE",
        title="Monthly report",
        version="2026-08",
        source_path="/corpus/report.docx",
        checksum="a" * 64,
        role_scope=("STAFF",),
        document_type="INTERNAL_REPORT",
        owner_team="ACCOUNTING",
    )
    chunk = PdfChunk(
        chunk_id="chunk-1",
        manual_id="REPORT-ONE",
        page_start=1,
        page_end=1,
        section_title="Detail",
        content="가" * 300,
        checksum="b" * 64,
    )

    with pytest.raises(ValueError, match="context limit"):
        EmbeddingInputBuilder(256).build(document, chunk)

    counter_calls: list[str] = []

    def over_limit(value: str) -> int:
        counter_calls.append(value)
        return 257

    with pytest.raises(ValueError, match="context limit"):
        EmbeddingInputBuilder(256, over_limit).build(
            document,
            PdfChunk(
                chunk_id="chunk-2",
                manual_id="REPORT-ONE",
                page_start=1,
                page_end=1,
                section_title="Detail",
                content="short content",
                checksum="c" * 64,
            ),
        )
    assert counter_calls


@pytest.mark.parametrize(
    ("source_bytes", "message"),
    [
        (
            _docx_bytes(document_xml="<!DOCTYPE x [<!ENTITY e 'boom'>]><x>&e;</x>"),
            "entities",
        ),
        (
            _docx_bytes(extras={"word/vbaProject.bin": b"macro"}),
            "Macro-enabled",
        ),
        (
            _docx_bytes(
                document_rels=DOCUMENT_RELS.replace(
                    "Target=\"media/chart.png\"",
                    "Target=\"https://example.invalid/chart.png\" TargetMode=\"External\"",
                )
            ),
            "external",
        ),
        (
            _docx_bytes(document_rels=DOCUMENT_RELS.replace("rIdImage", "rIdOther")),
            "relationship is missing",
        ),
    ],
)
def test_docx_parser_fails_closed_for_unsafe_or_incomplete_packages(
    tmp_path: Path,
    source_bytes: bytes,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        _parse(tmp_path, source_bytes)


def test_docx_parser_rejects_zip_bomb_ratio(tmp_path: Path) -> None:
    source = tmp_path / "bomb.docx"
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", b"0" * (2 * 1024 * 1024))
        archive.writestr("[Content_Types].xml", CONTENT_TYPES)
        archive.writestr("_rels/.rels", ROOT_RELS)
    source.write_bytes(output.getvalue())
    with pytest.raises(ValueError, match="compression ratio"):
        _parser().parse(
            source,
            manual_id="REPORT-FIXTURE-001",
            source_version="1",
            role_scope=("STAFF",),
            document_type="INTERNAL_REPORT",
            owner_team="ACCOUNTING",
        )


def test_v2_manifest_recursively_exact_matches_formats_and_access_metadata(
    tmp_path: Path,
) -> None:
    manuals = tmp_path / "manuals"
    (manuals / "monthly").mkdir(parents=True)
    pdf = manuals / "manual.pdf"
    docx = manuals / "monthly" / "report.docx"
    pdf.write_bytes(b"pdf")
    docx.write_bytes(_docx_bytes())
    documents = [
        {
            "source_file": "manual.pdf",
            "document_kind": "MANUAL",
            "manual_id": "MANUAL-ONE",
            "source_sha256": hashlib.sha256(pdf.read_bytes()).hexdigest(),
            "source_version": "UNRESOLVED",
            "role_scope": ["STAFF"],
            "owner_team": "OPERATIONS",
            "metadata": {"period": None, "department": None},
        },
        {
            "source_file": "monthly/report.docx",
            "document_kind": "INTERNAL_REPORT",
            "manual_id": "REPORT-ONE",
            "source_sha256": hashlib.sha256(docx.read_bytes()).hexdigest(),
            "source_version": "2026-08",
            "role_scope": ["STAFF", "SYSTEM_ADMIN"],
            "owner_team": "ACCOUNTING",
            "metadata": {"period": "2026-08", "department": "ACCOUNTING"},
        },
    ]
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {"schema_version": CORPUS_MANIFEST_VERSION_V2, "documents": documents},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    manifest = CorpusManifest.load(manifest_path, manuals)
    manifest.validate_access_policy(frozenset({"STAFF", "SYSTEM_ADMIN"}))
    assert [item.source_format for item in manifest.included_documents] == ["pdf", "docx"]
    assert manifest.documents[1].period == "2026-08"
    with pytest.raises(ValueError, match="access policy"):
        manifest.validate_access_policy(frozenset({"STAFF"}))

    docx.write_bytes(b"changed")
    with pytest.raises(ValueError, match="checksum"):
        CorpusManifest.load(manifest_path, manuals)


def test_manifest_rejects_source_above_the_shared_pdf_docx_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manuals = tmp_path / "manuals"
    manuals.mkdir()
    source = manuals / "manual.pdf"
    content = b"nine-byte"
    source.write_bytes(content)
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": CORPUS_MANIFEST_VERSION_V2,
                "documents": [
                    {
                        "source_file": "manual.pdf",
                        "document_kind": "MANUAL",
                        "manual_id": "MANUAL-ONE",
                        "source_sha256": hashlib.sha256(content).hexdigest(),
                        "source_version": "UNRESOLVED",
                        "role_scope": ["STAFF"],
                        "owner_team": "OPERATIONS",
                        "metadata": {"period": None, "department": None},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setitem(SOURCE_MAX_BYTES_BY_SUFFIX, ".pdf", 8)

    with pytest.raises(ValueError, match="source size is invalid"):
        CorpusManifest.load(manifest_path, manuals)


def test_bounded_source_read_rejects_descriptor_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "report.docx"
    source.write_bytes(b"immutable")
    actual_fstat = os.fstat
    call_count = 0

    def drifting_fstat(file_descriptor: int) -> object:
        nonlocal call_count
        call_count += 1
        current = actual_fstat(file_descriptor)
        if call_count == 1:
            return current
        return SimpleNamespace(
            st_mode=current.st_mode,
            st_dev=current.st_dev,
            st_ino=current.st_ino,
            st_size=current.st_size,
            st_mtime_ns=current.st_mtime_ns + 1,
            st_ctime_ns=current.st_ctime_ns,
        )

    monkeypatch.setattr("src.rag.source_bytes.os.fstat", drifting_fstat)

    with pytest.raises(ValueError, match="changed during bounded read"):
        read_bounded_source_bytes(source)


def test_tracked_mixed_corpus_exact_matches_and_reports_keep_structure_receipts() -> None:
    manuals = PROJECT_ROOT / "data" / "rag" / "manuals"
    manifest = CorpusManifest.load(
        PROJECT_ROOT / "config" / "rag" / "corpus_manifest.json",
        manuals,
    )
    assert (
        manifest.manifest_sha256
        == "315ec787140502674ee5301eb2c066ddc34d94a485c58c82b0bf8366893e0062"
    )
    reports = [
        entry
        for entry in manifest.included_documents
        if entry.document_kind == "INTERNAL_REPORT"
    ]
    parser = CorpusDocumentParser(
        TokenChunker(SimpleNamespace(model_id="fixture"), 384, 64)
    )
    embedding_input_builder = EmbeddingInputBuilder(2048)
    totals = {
        "documents": 0,
        "chunks": 0,
        "embedding_inputs": 0,
        "content_units": 0,
        "headings": 0,
        "tables": 0,
        "rows": 0,
        "cells": 0,
        "explicit_breaks": 0,
        "sections": 0,
        "headers": 0,
        "footers": 0,
    }
    primary_cell_identities: list[str] = []
    maximum_embedding_input_tokens = 0
    for entry in reports:
        source = CorpusManifest.source_path(manuals, entry)
        _document, chunks, warnings, receipt = parser.parse(source, entry)
        structure = receipt["structure"]
        assert entry.source_sha256 == hashlib.sha256(source.read_bytes()).hexdigest()
        assert warnings == []
        assert receipt["content_unit_count"] > 0
        assert structure["table_count"] > 0
        assert structure["header_part_count"] > 0
        assert structure["footer_part_count"] > 0
        assert structure["comment_count"] == 0
        assert all(chunk.token_count <= 384 for chunk in chunks)
        totals["documents"] += 1
        totals["chunks"] += len(chunks)
        totals["content_units"] += receipt["content_unit_count"]
        totals["headings"] += structure["heading_count"]
        totals["tables"] += structure["table_count"]
        totals["rows"] += structure["table_row_count"]
        totals["cells"] += structure["table_cell_count"]
        totals["explicit_breaks"] += structure["explicit_page_break_count"]
        totals["sections"] += structure["section_boundary_count"]
        totals["headers"] += structure["header_part_count"]
        totals["footers"] += structure["footer_part_count"]
        for chunk in chunks:
            original_content = chunk.content
            dense_input = embedding_input_builder.build(_document, chunk)
            assert chunk.content == original_content
            totals["embedding_inputs"] += 1
            maximum_embedding_input_tokens = max(
                maximum_embedding_input_tokens,
                embedding_input_builder.token_count(dense_input),
            )
            table_index: str | None = None
            markers: list[str] = []
            for marker in re.finditer(
                r"\[TABLE index=(\d+)\b|\[(r\d+c\d+)\b",
                chunk.content,
            ):
                if marker.group(1) is not None:
                    table_index = marker.group(1)
                elif marker.group(2) is not None:
                    assert table_index is not None
                    markers.append(marker.group(2))
                    primary_cell_identities.append(
                        f"{entry.manual_id}:table-{table_index}:{marker.group(2)}"
                    )
            if markers:
                assert "[TABLE" in chunk.content

    assert len(manifest.documents) == 41
    assert sum(entry.source_format == "pdf" for entry in manifest.documents) == 17
    assert totals == {
        "documents": 24,
        "chunks": 356,
        "embedding_inputs": 356,
        "content_units": 658,
        "headings": 141,
        "tables": 144,
        "rows": 659,
        "cells": 3155,
        "explicit_breaks": 32,
        "sections": 24,
        "headers": 24,
        "footers": 24,
    }
    assert len(primary_cell_identities) == 3155
    assert len(set(primary_cell_identities)) == 3155
    assert 0 < maximum_embedding_input_tokens <= 2048


def test_v2_manifest_rejects_path_traversal_and_unlisted_recursive_source(
    tmp_path: Path,
) -> None:
    manuals = tmp_path / "manuals"
    manuals.mkdir()
    source = manuals / "report.docx"
    source.write_bytes(_docx_bytes())
    base = {
        "source_file": "../report.docx",
        "document_kind": "INTERNAL_REPORT",
        "manual_id": "REPORT-ONE",
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "source_version": "2026-08",
        "role_scope": ["STAFF"],
        "owner_team": "ACCOUNTING",
        "metadata": {"period": "2026-08", "department": "ACCOUNTING"},
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {"schema_version": CORPUS_MANIFEST_VERSION_V2, "documents": [base]}
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="document is invalid"):
        CorpusManifest.load(manifest_path, manuals)

    base["source_file"] = "report.docx"
    (manuals / "unlisted.pdf").write_bytes(b"pdf")
    manifest_path.write_text(
        json.dumps(
            {"schema_version": CORPUS_MANIFEST_VERSION_V2, "documents": [base]}
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="does not match"):
        CorpusManifest.load(manifest_path, manuals)


@pytest.mark.parametrize("control", ["\n", "\r", "\x00", "\x1f", "\x7f"])
def test_v2_manifest_rejects_control_characters_in_source_file(
    tmp_path: Path,
    control: str,
) -> None:
    manuals = tmp_path / "manuals"
    manuals.mkdir()
    source = manuals / "report.docx"
    source.write_bytes(_docx_bytes())
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": CORPUS_MANIFEST_VERSION_V2,
                "documents": [
                    {
                        "source_file": f"report{control}.docx",
                        "document_kind": "INTERNAL_REPORT",
                        "manual_id": "REPORT-ONE",
                        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                        "source_version": "2026-08",
                        "role_scope": ["STAFF"],
                        "owner_team": "ACCOUNTING",
                        "metadata": {
                            "period": "2026-08",
                            "department": "ACCOUNTING",
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="document is invalid"):
        CorpusManifest.load(manifest_path, manuals)


def test_dispatcher_applies_manifest_identity_and_provenance(tmp_path: Path) -> None:
    source = tmp_path / "report.docx"
    source.write_bytes(_docx_bytes())
    entry = CorpusManifestDocument(
        "report.docx",
        "INTERNAL_REPORT",
        "REPORT-ONE",
        hashlib.sha256(source.read_bytes()).hexdigest(),
        "2026-08",
        ("STAFF", "SYSTEM_ADMIN"),
        "ACCOUNTING",
        "2026-08",
        "ACCOUNTING",
    )
    parser = CorpusDocumentParser(
        TokenChunker(SimpleNamespace(model_id="fixture"), 384, 64)
    )

    document, chunks, _warnings, receipt = parser.parse(source, entry)

    assert document.manual_id == "REPORT-ONE"
    assert document.version == "2026-08"
    assert document.owner_team == "ACCOUNTING"
    assert document.role_scope == ("STAFF", "SYSTEM_ADMIN")
    assert document.approval_status == "APPROVED"
    assert document.validity_status == "VALID"
    assert chunks
    assert receipt["metadata"] == {
        "period": "2026-08",
        "department": "ACCOUNTING",
    }


def test_dispatcher_accepts_narrative_internal_report_without_table(tmp_path: Path) -> None:
    source = tmp_path / "report.docx"
    table_start = DOCUMENT_XML.index("  <w:tbl>")
    table_end = DOCUMENT_XML.index("  </w:tbl>") + len("  </w:tbl>\n")
    source.write_bytes(
        _docx_bytes(document_xml=DOCUMENT_XML[:table_start] + DOCUMENT_XML[table_end:])
    )
    entry = CorpusManifestDocument(
        "report.docx",
        "INTERNAL_REPORT",
        "REPORT-ONE",
        hashlib.sha256(source.read_bytes()).hexdigest(),
        "2026-08",
        ("STAFF",),
        "ACCOUNTING",
        "2026-08",
        "ACCOUNTING",
    )
    parser = CorpusDocumentParser(
        TokenChunker(SimpleNamespace(model_id="fixture"), 384, 64)
    )

    _document, chunks, _warnings, receipt = parser.parse(source, entry)

    assert chunks
    assert receipt["content_unit_count"] > 0
    assert receipt["structure"]["table_count"] == 0


def test_dispatcher_rejects_invalid_internal_report_receipt() -> None:
    entry = CorpusManifestDocument(
        "report.docx",
        "INTERNAL_REPORT",
        "REPORT-ONE",
        "a" * 64,
        "2026-08",
        ("STAFF",),
        "ACCOUNTING",
        "2026-08",
        "ACCOUNTING",
    )
    receipt = {
        "source_checksum": "a" * 64,
        "parser_contract_version": DOCX_PARSER_CONTRACT_VERSION,
        "content_unit_count": 1,
        "chunk_count": 1,
        "structure": {"table_count": -1},
    }

    with pytest.raises(ValueError, match="structure receipt is invalid"):
        CorpusDocumentParser._validate_internal_report_receipt(entry, receipt)


def test_source_document_serves_checksum_bound_docx_without_pdf_mislabelling(
    tmp_path: Path,
) -> None:
    manuals = tmp_path / "manuals"
    source = manuals / "monthly" / "report.docx"
    source.parent.mkdir(parents=True)
    content = _docx_bytes()
    source.write_bytes(content)

    class Repository:
        @staticmethod
        def active_release_receipt(*_args: object) -> dict[str, object]:
            return {"release_id": "active"}

        @staticmethod
        def source_receipt(*_args: object) -> tuple[Path, str]:
            return source, hashlib.sha256(content).hexdigest()

    application = object.__new__(VectorRagApplication)
    application._settings = SimpleNamespace(  # type: ignore[attr-defined]
        embedding_provider="openai",
        model_id="text-embedding-3-large",
        dimension=1024,
        model_revision="text-embedding-3-large:d1024",
        manuals_dir=manuals,
    )
    application._corpus_manifest = SimpleNamespace(  # type: ignore[attr-defined]
        manifest_sha256="a" * 64
    )
    application._processing_profile_sha256 = "b" * 64  # type: ignore[attr-defined]
    application._repository = Repository()  # type: ignore[attr-defined]
    application._policy = SimpleNamespace(  # type: ignore[attr-defined]
        decide=lambda _role, _top_k: SimpleNamespace(
            allow_unresolved_validity=False
        )
    )

    served, filename, media_type = application.source_document(
        "REPORT-ONE",
        "STAFF",
    )

    assert served == content
    assert filename == "report.docx"
    assert media_type.endswith("wordprocessingml.document")
    with pytest.raises(FileNotFoundError):
        application.source_pdf("REPORT-ONE", "STAFF")


def test_rag_openapi_keeps_pdf_compatibility_and_exposes_generic_source() -> None:
    with patch.dict(
        os.environ,
        {"RAG_DATABASE_URL": "postgresql://rag_test@localhost/rag_test"},
    ):
        schema = create_app(PROJECT_ROOT).openapi()

    assert "/v1/documents/{manual_id}/source.pdf" in schema["paths"]
    assert "/v1/documents/{manual_id}/source" in schema["paths"]
