"""WordprocessingML 구조와 손실 진단을 보존하는 fail-closed DOCX parser다."""

from __future__ import annotations

import hashlib
import io
import posixpath
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any
from xml.etree import ElementTree

from .source_bytes import DEFAULT_MAX_SOURCE_BYTES, read_bounded_source_bytes
from .text_processing import SecurityScanner
from .vector_models import PdfChunk, PdfDocument

if TYPE_CHECKING:
    from .token_chunker import TokenChunker


DOCX_PARSER_CONTRACT_VERSION = "opc-wordprocessingml-v1.4"
_MAX_SOURCE_BYTES = DEFAULT_MAX_SOURCE_BYTES
_MAX_ZIP_ENTRIES = 4096
_MAX_UNCOMPRESSED_BYTES = 128 * 1024 * 1024
_MAX_PART_BYTES = 32 * 1024 * 1024
_MAX_COMPRESSION_RATIO = 200
_BREAK_EXPLICIT = "[[[DOCX_EXPLICIT_PAGE_BREAK]]]"
_BREAK_RENDERED = "[[[DOCX_LAST_RENDERED_PAGE_BREAK]]]"

_NS = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "cp": "http://schemas.openxmlformats.org/package/2006/metadata/core-properties",
    "dc": "http://purl.org/dc/elements/1.1/",
    "m": "http://schemas.openxmlformats.org/officeDocument/2006/math",
    "pr": "http://schemas.openxmlformats.org/package/2006/relationships",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "v": "urn:schemas-microsoft-com:vml",
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
}
_W = "{" + _NS["w"] + "}"
_R = "{" + _NS["r"] + "}"
_REL = "{" + _NS["pr"] + "}"
_HEADING_NAME = re.compile(r"^(?:heading|제목)\s*([1-9])$", re.IGNORECASE)
_SAFE_EXTERNAL_HYPERLINK = re.compile(r"^(?:https?://|mailto:)", re.IGNORECASE)


@dataclass(frozen=True)
class _Relationship:
    relationship_type: str
    target: str
    external: bool


@dataclass
class _ContentGroup:
    location_index: int
    locator_kind: str
    section_title: str
    blocks: list[str]


class DocxReportParser:
    """WordprocessingML을 source order로 추출하고 구조 손실 diagnostic을 발행한다."""

    def __init__(self, chunker: "TokenChunker") -> None:
        self._chunker = chunker
        self._scanner = SecurityScanner()

    def parse(
        self,
        path: Path,
        *,
        manual_id: str,
        source_version: str,
        role_scope: tuple[str, ...],
        document_type: str,
        owner_team: str,
    ) -> tuple[PdfDocument, list[PdfChunk], list[str], dict[str, Any]]:
        """DOCX bytes를 검증·추출·chunking하고 checksum 기반 receipt를 반환한다."""

        source_bytes = read_bounded_source_bytes(
            path,
            expected_suffix=".docx",
            maximum_bytes=_MAX_SOURCE_BYTES,
        )
        source_checksum = hashlib.sha256(source_bytes).hexdigest()
        extractor = _DocxExtractor(source_bytes)
        groups, metadata, diagnostics = extractor.extract()

        warnings = list(diagnostics)
        safe_groups: list[_ContentGroup] = []
        rejected_secret_units = 0
        masked_pii_units = 0
        masked_pii_section_titles = 0
        for group in groups:
            section_status, safe_section_title = self._scanner.inspect(
                group.section_title
            )
            if section_status == "REJECTED_SECRET":
                raise ValueError("DOCX section title was rejected by the secret scanner")
            if section_status == "MASKED_PII":
                masked_pii_section_titles += 1
            safe_blocks: list[str] = []
            for block in group.blocks:
                status, safe_text = self._scanner.inspect(block)
                if status == "REJECTED_SECRET":
                    rejected_secret_units += 1
                    continue
                if status == "MASKED_PII":
                    masked_pii_units += 1
                if safe_text.strip():
                    safe_blocks.append(safe_text)
            if safe_blocks:
                safe_groups.append(
                    _ContentGroup(
                        group.location_index,
                        group.locator_kind,
                        safe_section_title,
                        safe_blocks,
                    )
                )
        if rejected_secret_units:
            raise ValueError("DOCX contains content rejected by the secret scanner")
        if masked_pii_units:
            warnings.append(f"MASKED_PII_CONTENT_UNIT:{masked_pii_units}")
        if masked_pii_section_titles:
            warnings.append(
                f"MASKED_PII_SECTION_TITLE:{masked_pii_section_titles}"
            )
        if not safe_groups:
            raise ValueError("DOCX contains no safe extractable content")

        chunks: list[PdfChunk] = []
        for group in safe_groups:
            section_title = (
                f"[DOCX {group.locator_kind} {group.location_index}] "
                f"{group.section_title}"
            )[:500]
            group_chunks = self._chunker.chunk_structured_blocks(
                manual_id,
                group.location_index,
                section_title,
                group.blocks,
                chunk_index_offset=len(chunks),
            )
            chunks.extend(group_chunks)
        if not chunks:
            raise ValueError("DOCX extraction produced no chunks")

        raw_title = str(metadata.get("title") or path.stem.replace("_", " ")).strip()[:200]
        title_status, title = self._scanner.inspect(raw_title)
        if title_status == "REJECTED_SECRET":
            raise ValueError("DOCX title was rejected by the secret scanner")
        if title_status == "MASKED_PII":
            warnings.append("MASKED_PII_TITLE")
        document = PdfDocument(
            manual_id=manual_id,
            title=title or manual_id,
            version=source_version,
            source_path=str(path.resolve()),
            checksum=source_checksum,
            role_scope=role_scope,
            document_type=document_type,
            owner_team=owner_team,
        )
        token_counts = [chunk.token_count for chunk in chunks]
        receipt = {
            "manual_id": manual_id,
            "source_format": "docx",
            "source_checksum": source_checksum,
            "source_version": source_version,
            "parser_contract_version": DOCX_PARSER_CONTRACT_VERSION,
            "content_unit_count": sum(len(group.blocks) for group in safe_groups),
            "content_group_count": len(safe_groups),
            "chunk_count": len(chunks),
            "minimum_chunk_tokens": min(token_counts),
            "maximum_chunk_tokens": max(token_counts),
            "mean_chunk_tokens": sum(token_counts) / len(token_counts),
            "chunking_schema_version": self._chunker.schema_version,
            "embedding_profile_id": self._chunker.provider.model_id,
            "structure": metadata["structure"],
            "diagnostics": sorted(set(warnings)),
        }
        return document, chunks, warnings, receipt


class _DocxExtractor:
    def __init__(self, source_bytes: bytes) -> None:
        self._source_bytes = source_bytes
        self._diagnostics: list[str] = []
        self._parts: dict[str, bytes] = {}
        self._relationships: dict[str, dict[str, _Relationship]] = {}
        self._styles: dict[str, dict[str, object]] = {}
        self._numbering: dict[str, dict[int, dict[str, object]]] = {}
        self._list_counters: dict[tuple[str, int], int] = {}
        self._heading_path: list[tuple[int, str]] = []
        self._comment_range_starts: set[str] = set()
        self._comment_range_ends: set[str] = set()
        self._comment_references: set[str] = set()
        self._comment_ids: set[str] = set()
        self._consumed_media_parts: set[str] = set()
        self._structure = {
            "paragraph_count": 0,
            "heading_count": 0,
            "list_item_count": 0,
            "table_count": 0,
            "table_row_count": 0,
            "table_cell_count": 0,
            "grid_span_count": 0,
            "vertical_merge_count": 0,
            "explicit_page_break_count": 0,
            "last_rendered_page_break_count": 0,
            "section_boundary_count": 0,
            "header_part_count": 0,
            "footer_part_count": 0,
            "footnote_count": 0,
            "endnote_count": 0,
            "hyperlink_count": 0,
            "external_hyperlink_count": 0,
            "image_count": 0,
            "image_without_alt_count": 0,
            "media_digest_count": 0,
            "unreferenced_media_part_count": 0,
            "caption_count": 0,
            "comment_count": 0,
            "comment_reference_count": 0,
            "comment_range_count": 0,
        }

    def extract(self) -> tuple[list[_ContentGroup], dict[str, object], list[str]]:
        self._load_package()
        self._styles = self._load_styles()
        self._numbering = self._load_numbering()
        document = self._xml("word/document.xml", required=True)
        body = document.find("w:body", _NS)
        if body is None:
            raise ValueError("DOCX document body is missing")

        groups: list[_ContentGroup] = [
            _ContentGroup(1, "DOCUMENT_START", "문서 본문", [])
        ]
        self._walk_body(body, groups)
        self._append_related_parts(document, groups)
        self._append_notes("word/footnotes.xml", "FOOTNOTE", groups)
        self._append_notes("word/endnotes.xml", "ENDNOTE", groups)
        self._append_comments(groups)
        self._validate_comment_anchors()
        self._report_unreferenced_media()
        groups = [group for group in groups if any(block.strip() for block in group.blocks)]
        if not groups:
            raise ValueError("DOCX contains no extractable content units")

        metadata = self._core_properties()
        metadata["structure"] = dict(self._structure)
        if self._structure["image_count"] != self._structure["media_digest_count"]:
            raise ValueError("DOCX image relationship did not produce a media digest")
        return groups, metadata, self._diagnostics

    def _load_package(self) -> None:
        try:
            archive = zipfile.ZipFile(io.BytesIO(self._source_bytes))
        except zipfile.BadZipFile as error:
            raise ValueError("DOCX package is not a valid ZIP archive") from error
        with archive:
            infos = archive.infolist()
            if not infos or len(infos) > _MAX_ZIP_ENTRIES:
                raise ValueError("DOCX package entry count is invalid")
            names: set[str] = set()
            total_size = 0
            for info in infos:
                if info.is_dir():
                    directory = info.filename.rstrip("/")
                    self._normalized_part_name(directory)
                    continue
                normalized = self._normalized_part_name(info.filename)
                identity = normalized.casefold()
                if identity in names:
                    raise ValueError("DOCX package contains duplicate part identity")
                names.add(identity)
                if info.flag_bits & 0x1:
                    raise ValueError("Encrypted DOCX entries are not supported")
                if info.file_size > _MAX_PART_BYTES:
                    raise ValueError("DOCX package part exceeds the size limit")
                total_size += info.file_size
                if total_size > _MAX_UNCOMPRESSED_BYTES:
                    raise ValueError("DOCX package exceeds the uncompressed size limit")
                if (
                    info.file_size > 1024 * 1024
                    and info.compress_size > 0
                    and info.file_size / info.compress_size > _MAX_COMPRESSION_RATIO
                ):
                    raise ValueError("DOCX package compression ratio is unsafe")
                self._parts[normalized] = archive.read(info)

        required = {"[Content_Types].xml", "_rels/.rels", "word/document.xml"}
        if not required.issubset(self._parts):
            raise ValueError("DOCX package is missing a required OPC part")
        content_types = self._parts["[Content_Types].xml"].lower()
        if b"macroenabled" in content_types or any(
            "vbaproject" in name.casefold() for name in self._parts
        ):
            raise ValueError("Macro-enabled DOCX content is not supported")
        unsupported_embedded_prefixes = (
            "word/activex/",
            "word/charts/",
            "word/diagrams/",
            "word/embeddings/",
        )
        if any(
            name.casefold().startswith(unsupported_embedded_prefixes)
            or name.casefold().endswith(".bin")
            for name in self._parts
        ):
            raise ValueError("Unsupported embedded DOCX object is present")
        for part_name, diagnostic in (
            ("word/commentsextended.xml", "COMMENTS_EXTENDED_NOT_INDEXED"),
            ("word/commentsextensible.xml", "COMMENTS_EXTENSIBLE_NOT_INDEXED"),
            ("word/commentsids.xml", "COMMENT_IDENTIFIERS_NOT_INDEXED"),
            ("word/people.xml", "COMMENT_PEOPLE_METADATA_NOT_INDEXED"),
        ):
            if part_name in {name.casefold() for name in self._parts}:
                self._diagnostics.append(diagnostic)

        for name in sorted(self._parts):
            if name.endswith(".rels"):
                self._load_relationship_part(name)
            elif name.endswith(".xml"):
                self._assert_safe_xml(self._parts[name])

    @staticmethod
    def _normalized_part_name(value: str) -> str:
        if "\\" in value or not value:
            raise ValueError("DOCX package part path is invalid")
        path = PurePosixPath(value)
        if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
            raise ValueError("DOCX package part path is invalid")
        normalized = path.as_posix()
        if normalized != value:
            raise ValueError("DOCX package part path is not normalized")
        return normalized

    @staticmethod
    def _assert_safe_xml(raw: bytes) -> None:
        upper = raw.upper()
        if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
            raise ValueError("DOCX XML declarations with entities are not supported")

    def _xml(self, name: str, *, required: bool = False) -> ElementTree.Element | None:
        raw = self._parts.get(name)
        if raw is None:
            if required:
                raise ValueError(f"DOCX required part is missing: {name}")
            return None
        self._assert_safe_xml(raw)
        try:
            return ElementTree.fromstring(raw)
        except ElementTree.ParseError as error:
            raise ValueError(f"DOCX XML part is malformed: {name}") from error

    def _load_relationship_part(self, name: str) -> None:
        root = self._xml(name, required=True)
        assert root is not None
        source_part = self._source_part_for_relationships(name)
        relationships: dict[str, _Relationship] = {}
        for item in root.findall(f"{_REL}Relationship"):
            relationship_id = item.get("Id")
            relationship_type = item.get("Type")
            target = item.get("Target")
            external = item.get("TargetMode") == "External"
            if not relationship_id or not relationship_type or not target:
                raise ValueError("DOCX relationship is incomplete")
            if relationship_id in relationships:
                raise ValueError("DOCX relationship identity is duplicated")
            unsupported_relationships = (
                "/afchunk",
                "/chart",
                "/control",
                "/diagramcolors",
                "/diagramdata",
                "/diagramlayout",
                "/diagramquickstyle",
                "/oleobject",
                "/package",
            )
            if relationship_type.casefold().endswith(unsupported_relationships):
                raise ValueError("Unsupported embedded DOCX relationship is present")
            if external:
                if not relationship_type.endswith("/hyperlink") or not _SAFE_EXTERNAL_HYPERLINK.match(target):
                    raise ValueError("Unsupported external DOCX relationship")
                resolved_target = target
                if "EXTERNAL_HYPERLINK_NOT_FETCHED" not in self._diagnostics:
                    self._diagnostics.append("EXTERNAL_HYPERLINK_NOT_FETCHED")
            else:
                resolved_target = posixpath.normpath(
                    posixpath.join(posixpath.dirname(source_part), target)
                )
                if resolved_target.startswith("../") or resolved_target not in self._parts:
                    raise ValueError("DOCX relationship target is missing or escapes the package")
            relationships[relationship_id] = _Relationship(
                relationship_type,
                resolved_target,
                external,
            )
        self._relationships[source_part] = relationships

    @staticmethod
    def _source_part_for_relationships(name: str) -> str:
        if name == "_rels/.rels":
            return ""
        parent, rel_name = posixpath.split(name)
        if not parent.endswith("/_rels") or not rel_name.endswith(".rels"):
            raise ValueError("DOCX relationship part path is invalid")
        return posixpath.join(parent[: -len("/_rels")], rel_name[: -len(".rels")])

    def _relationship(self, source_part: str, relationship_id: str) -> _Relationship:
        relationship = self._relationships.get(source_part, {}).get(relationship_id)
        if relationship is None:
            raise ValueError("DOCX referenced relationship is missing")
        return relationship

    def _load_styles(self) -> dict[str, dict[str, object]]:
        root = self._xml("word/styles.xml")
        if root is None:
            self._diagnostics.append("STYLES_PART_MISSING")
            return {}
        styles: dict[str, dict[str, object]] = {}
        for style in root.findall("w:style", _NS):
            style_id = style.get(f"{_W}styleId")
            if not style_id:
                continue
            name_node = style.find("w:name", _NS)
            based_on = style.find("w:basedOn", _NS)
            outline = style.find("w:pPr/w:outlineLvl", _NS)
            num_id = style.find("w:pPr/w:numPr/w:numId", _NS)
            ilvl = style.find("w:pPr/w:numPr/w:ilvl", _NS)
            styles[style_id] = {
                "name": name_node.get(f"{_W}val") if name_node is not None else style_id,
                "based_on": based_on.get(f"{_W}val") if based_on is not None else None,
                "outline": self._integer_attr(outline, "val"),
                "num_id": num_id.get(f"{_W}val") if num_id is not None else None,
                "ilvl": self._integer_attr(ilvl, "val"),
            }
        return styles

    def _resolved_style(self, style_id: str | None) -> dict[str, object]:
        resolved: dict[str, object] = {}
        seen: set[str] = set()
        current = style_id
        chain: list[dict[str, object]] = []
        while current and current not in seen and current in self._styles:
            seen.add(current)
            style = self._styles[current]
            chain.append(style)
            based = style.get("based_on")
            current = str(based) if based else None
        for style in reversed(chain):
            resolved.update({key: value for key, value in style.items() if value is not None})
        if style_id:
            resolved["style_id"] = style_id
        return resolved

    def _load_numbering(self) -> dict[str, dict[int, dict[str, object]]]:
        root = self._xml("word/numbering.xml")
        if root is None:
            return {}
        abstracts: dict[str, dict[int, dict[str, object]]] = {}
        for abstract in root.findall("w:abstractNum", _NS):
            abstract_id = abstract.get(f"{_W}abstractNumId")
            if abstract_id is None:
                continue
            levels: dict[int, dict[str, object]] = {}
            for level in abstract.findall("w:lvl", _NS):
                ilvl = self._integer_attr(level, "ilvl")
                if ilvl is None:
                    continue
                levels[ilvl] = {
                    "start": self._integer_attr(level.find("w:start", _NS), "val") or 1,
                    "format": self._value(level.find("w:numFmt", _NS)) or "decimal",
                    "text": self._value(level.find("w:lvlText", _NS)) or f"%{ilvl + 1}.",
                }
            abstracts[abstract_id] = levels
        numbering: dict[str, dict[int, dict[str, object]]] = {}
        for number in root.findall("w:num", _NS):
            num_id = number.get(f"{_W}numId")
            abstract_id = self._value(number.find("w:abstractNumId", _NS))
            if num_id is None or abstract_id not in abstracts:
                continue
            levels = {level: dict(values) for level, values in abstracts[abstract_id].items()}
            for override in number.findall("w:lvlOverride", _NS):
                ilvl = self._integer_attr(override, "ilvl")
                start = self._integer_attr(override.find("w:startOverride", _NS), "val")
                if ilvl is not None and start is not None and ilvl in levels:
                    levels[ilvl]["start"] = start
            numbering[num_id] = levels
        return numbering

    def _walk_body(self, container: ElementTree.Element, groups: list[_ContentGroup]) -> None:
        for child in list(container):
            local = self._local_name(child.tag)
            if local == "p":
                self._append_paragraph(child, "word/document.xml", groups)
            elif local == "tbl":
                groups[-1].blocks.append(self._render_table(child, "word/document.xml"))
            elif local == "sdt":
                content = child.find("w:sdtContent", _NS)
                if content is None:
                    self._diagnostics.append("EMPTY_CONTENT_CONTROL")
                else:
                    self._walk_body(content, groups)
            elif local == "sectPr":
                self._append_section_boundary(child, groups[-1])
            elif local in {"altChunk", "object", "oleObject"}:
                raise ValueError(f"Unsupported embedded DOCX element: {local}")
            elif local in {"bookmarkStart", "bookmarkEnd", "proofErr", "permStart", "permEnd"}:
                continue
            else:
                text = self._plain_text(child)
                self._diagnostics.append(f"UNSUPPORTED_BODY_ELEMENT:{local}")
                if text:
                    groups[-1].blocks.append(f"[UNSUPPORTED {local}] {text}")

    def _append_paragraph(
        self,
        paragraph: ElementTree.Element,
        source_part: str,
        groups: list[_ContentGroup],
    ) -> None:
        self._structure["paragraph_count"] += 1
        ppr = paragraph.find("w:pPr", _NS)
        style_id = self._value(ppr.find("w:pStyle", _NS)) if ppr is not None else None
        style = self._resolved_style(style_id)
        heading_level = self._heading_level(style)
        list_metadata = self._list_metadata(ppr, style)
        rendered = self._render_inline(paragraph, source_part).strip()
        if not rendered and ppr is None:
            return
        parts = re.split(
            f"({re.escape(_BREAK_EXPLICIT)}|{re.escape(_BREAK_RENDERED)})",
            rendered,
        )
        first_content = True
        for part in parts:
            if part == _BREAK_EXPLICIT or part == _BREAK_RENDERED:
                if part == _BREAK_EXPLICIT:
                    self._structure["explicit_page_break_count"] += 1
                    kind = "EXPLICIT_PAGE_BREAK"
                else:
                    self._structure["last_rendered_page_break_count"] += 1
                    kind = "LAST_RENDERED_PAGE_BREAK"
                groups.append(
                    _ContentGroup(
                        groups[-1].location_index + 1,
                        kind,
                        groups[-1].section_title,
                        [f"[{kind} index={groups[-1].location_index + 1}]"],
                    )
                )
                first_content = True
                continue
            text = part.strip()
            if not text:
                continue
            prefix: list[str] = []
            style_name = str(style.get("name") or style_id or "UNSTYLED")
            if heading_level is not None:
                self._structure["heading_count"] += 1
                section_context = self._update_heading_path(heading_level, text)
                if groups[-1].blocks:
                    groups.append(
                        _ContentGroup(
                            groups[-1].location_index,
                            groups[-1].locator_kind,
                            section_context,
                            [],
                        )
                    )
                groups[-1].section_title = section_context
                prefix.append(f"[HEADING level={heading_level} style={style_name}]")
            else:
                prefix.append(f"[PARAGRAPH style={style_name}]")
            if list_metadata is not None and first_content:
                self._structure["list_item_count"] += 1
                prefix.append(list_metadata)
            if style_name.casefold() == "caption":
                self._structure["caption_count"] += 1
                prefix.append("[CAPTION]")
            groups[-1].blocks.append(" ".join((*prefix, text)))
            first_content = False
        if ppr is not None:
            section = ppr.find("w:sectPr", _NS)
            if section is not None:
                self._append_section_boundary(section, groups[-1])

    def _update_heading_path(self, level: int, title: str) -> str:
        self._heading_path = [
            (ancestor_level, ancestor_title)
            for ancestor_level, ancestor_title in self._heading_path
            if ancestor_level < level
        ]
        self._heading_path.append((level, title[:200]))
        return " > ".join(title for _level, title in self._heading_path[-3:])[:500]

    def _heading_level(self, style: dict[str, object]) -> int | None:
        outline = style.get("outline")
        if isinstance(outline, int) and 0 <= outline <= 8:
            return outline + 1
        match = _HEADING_NAME.fullmatch(str(style.get("name") or "").strip())
        return int(match.group(1)) if match else None

    def _list_metadata(
        self,
        ppr: ElementTree.Element | None,
        style: dict[str, object],
    ) -> str | None:
        num_id = None
        ilvl = None
        if ppr is not None:
            num_id = self._value(ppr.find("w:numPr/w:numId", _NS))
            ilvl = self._integer_attr(ppr.find("w:numPr/w:ilvl", _NS), "val")
        num_id = num_id or (str(style["num_id"]) if style.get("num_id") is not None else None)
        if ilvl is None and isinstance(style.get("ilvl"), int):
            ilvl = int(style["ilvl"])
        if num_id is None:
            return None
        level = ilvl or 0
        definition = self._numbering.get(num_id, {}).get(level)
        if definition is None:
            raise ValueError("DOCX numbered paragraph has no numbering definition")
        for key in tuple(self._list_counters):
            if key[0] == num_id and key[1] > level:
                del self._list_counters[key]
        counter_key = (num_id, level)
        current = self._list_counters.get(counter_key, int(definition["start"]) - 1) + 1
        self._list_counters[counter_key] = current
        return (
            f"[LIST num_id={num_id} level={level} ordinal={current} "
            f"format={definition['format']} pattern={definition['text']}]"
        )

    def _render_inline(self, node: ElementTree.Element, source_part: str) -> str:
        output: list[str] = []
        for child in list(node):
            local = self._local_name(child.tag)
            if local in {"pPr", "rPr"}:
                continue
            if local in {"t", "delText"}:
                output.append(child.text or "")
            elif local == "tab":
                output.append("\t")
            elif local == "cr":
                output.append("\n")
            elif local == "ptab":
                output.append("[POSITIONAL_TAB]")
            elif local == "sym":
                font = (child.get(f"{_W}font") or "UNSPECIFIED")[:100]
                character = (child.get(f"{_W}char") or "UNSPECIFIED")[:16]
                output.append(f"[SYMBOL font={font} char={character}]")
            elif local == "br":
                break_type = child.get(f"{_W}type") or "textWrapping"
                if break_type == "page":
                    output.append(_BREAK_EXPLICIT)
                elif break_type == "textWrapping":
                    output.append("\n")
                else:
                    output.append(f"[BREAK type={break_type}]")
            elif local == "lastRenderedPageBreak":
                output.append(_BREAK_RENDERED)
            elif local == "noBreakHyphen":
                output.append("‑")
            elif local == "softHyphen":
                output.append("\u00ad")
            elif local == "hyperlink":
                self._structure["hyperlink_count"] += 1
                label = self._render_inline(child, source_part).strip()
                relationship_id = child.get(f"{_R}id")
                anchor = child.get(f"{_W}anchor")
                if relationship_id:
                    relationship = self._relationship(source_part, relationship_id)
                    if not relationship.relationship_type.endswith("/hyperlink"):
                        raise ValueError("DOCX hyperlink uses an invalid relationship type")
                    target = relationship.target
                    if relationship.external:
                        self._structure["external_hyperlink_count"] += 1
                        if "EXTERNAL_HYPERLINK_NOT_FETCHED" not in self._diagnostics:
                            self._diagnostics.append("EXTERNAL_HYPERLINK_NOT_FETCHED")
                elif anchor:
                    target = f"#{anchor}"
                else:
                    raise ValueError("DOCX hyperlink target is missing")
                output.append(f"{label} [HYPERLINK target={target}]")
            elif local in {"drawing", "pict"}:
                output.append(self._render_drawing(child, source_part))
            elif local == "footnoteReference":
                output.append(f"[FOOTNOTE_REF id={child.get(f'{_W}id', '')}]")
            elif local == "endnoteReference":
                output.append(f"[ENDNOTE_REF id={child.get(f'{_W}id', '')}]")
            elif local == "commentRangeStart":
                comment_id = self._required_nonnegative_id(child, "comment range start")
                self._comment_range_starts.add(comment_id)
                output.append(f"[COMMENT_RANGE_START id={comment_id}]")
            elif local == "commentRangeEnd":
                comment_id = self._required_nonnegative_id(child, "comment range end")
                self._comment_range_ends.add(comment_id)
                output.append(f"[COMMENT_RANGE_END id={comment_id}]")
            elif local == "commentReference":
                comment_id = self._required_nonnegative_id(child, "comment reference")
                self._comment_references.add(comment_id)
                output.append(f"[COMMENT_REF id={comment_id}]")
            elif local == "instrText":
                instruction = " ".join((child.text or "").split())
                if instruction:
                    output.append(f"[FIELD {instruction}]")
            elif local == "fldSimple":
                instruction = " ".join((child.get(f"{_W}instr") or "").split())
                displayed = self._render_inline(child, source_part).strip()
                if not instruction:
                    raise ValueError("DOCX simple field instruction is missing")
                output.append(
                    f"[FIELD_SIMPLE instruction={instruction}] {displayed}".rstrip()
                )
            elif local == "del":
                self._diagnostics.append("TRACKED_DELETION_PRESERVED")
                output.append(f"[DELETED {self._render_inline(child, source_part)}]")
            elif local == "ins":
                self._diagnostics.append("TRACKED_INSERTION_PRESERVED")
                output.append(f"[INSERTED {self._render_inline(child, source_part)}]")
            elif local in {"altChunk", "object", "oleObject"}:
                raise ValueError(f"Unsupported embedded DOCX element: {local}")
            elif local in {"fldChar", "bookmarkStart", "bookmarkEnd", "proofErr"}:
                continue
            else:
                rendered = self._render_inline(child, source_part)
                if rendered:
                    output.append(rendered)
                elif child.text and child.text.strip():
                    self._diagnostics.append(f"UNSUPPORTED_INLINE_ELEMENT:{local}")
                    output.append(f"[UNSUPPORTED_INLINE {local}] {child.text}")
                elif not list(child):
                    self._diagnostics.append(f"UNSUPPORTED_INLINE_ELEMENT:{local}")
        return "".join(output)

    def _render_drawing(self, node: ElementTree.Element, source_part: str) -> str:
        self._structure["image_count"] += 1
        properties = node.find(".//wp:docPr", _NS)
        alt = ""
        name = ""
        if properties is not None:
            alt = (properties.get("descr") or properties.get("title") or "").strip()
            name = (properties.get("name") or "").strip()
        relationship_ids = [
            value
            for value in (
                *(item.get(f"{_R}embed") for item in node.findall(".//a:blip", _NS)),
                *(item.get(f"{_R}id") for item in node.findall(".//v:imagedata", _NS)),
            )
            if value
        ]
        if len(relationship_ids) != 1:
            raise ValueError("DOCX image must reference exactly one embedded media part")
        relationship = self._relationship(source_part, relationship_ids[0])
        if relationship.external or not relationship.relationship_type.endswith("/image"):
            raise ValueError("DOCX image relationship is invalid")
        media = self._parts.get(relationship.target)
        if media is None:
            raise ValueError("DOCX image media part is missing")
        digest = hashlib.sha256(media).hexdigest()
        self._consumed_media_parts.add(relationship.target)
        self._structure["media_digest_count"] += 1
        self._diagnostics.append("IMAGE_BINARY_NOT_OCR_EXTRACTED")
        if not alt:
            self._structure["image_without_alt_count"] += 1
            self._diagnostics.append("IMAGE_ALT_TEXT_MISSING")
        return f"[IMAGE name={name or 'UNNAMED'} alt={alt or 'UNAVAILABLE'} sha256={digest}]"

    def _render_table(self, table: ElementTree.Element, source_part: str) -> str:
        self._structure["table_count"] += 1
        style = self._value(table.find("w:tblPr/w:tblStyle", _NS)) or "UNSTYLED"
        lines = [f"[TABLE index={self._structure['table_count']} style={style}]"]
        rows = self._wrapped_table_elements(
            table,
            expected="tr",
            property_elements={"tblPr", "tblGrid"},
        )
        for row_index, row in enumerate(rows, start=1):
            self._structure["table_row_count"] += 1
            column = 1
            cells: list[str] = []
            for cell in self._wrapped_table_elements(
                row,
                expected="tc",
                property_elements={"trPr"},
            ):
                self._structure["table_cell_count"] += 1
                span = self._integer_attr(cell.find("w:tcPr/w:gridSpan", _NS), "val") or 1
                merge_node = cell.find("w:tcPr/w:vMerge", _NS)
                merge = None
                if merge_node is not None:
                    merge = merge_node.get(f"{_W}val") or "continue"
                    self._structure["vertical_merge_count"] += 1
                if span > 1:
                    self._structure["grid_span_count"] += 1
                content: list[str] = []
                for child in list(cell):
                    local = self._local_name(child.tag)
                    if local == "tcPr":
                        continue
                    if local == "p":
                        value = self._render_inline(child, source_part).strip()
                        if value:
                            content.append(value)
                    elif local == "tbl":
                        content.append(self._render_table(child, source_part))
                    elif local == "sdt":
                        structured = child.find("w:sdtContent", _NS)
                        if structured is None:
                            self._diagnostics.append("EMPTY_TABLE_CONTENT_CONTROL")
                        else:
                            content.extend(
                                self._render_part_blocks(structured, source_part)
                            )
                    elif local in {"altChunk", "object", "oleObject"}:
                        raise ValueError(
                            f"Unsupported embedded DOCX table element: {local}"
                        )
                    else:
                        preserved = self._plain_text(child)
                        self._diagnostics.append(
                            f"UNSUPPORTED_TABLE_CELL_ELEMENT:{local}"
                        )
                        if preserved:
                            content.append(f"[UNSUPPORTED {local}] {preserved}")
                normalized = " / ".join(content) or "[EMPTY_CELL]"
                metadata = f"r{row_index}c{column} span={span}"
                if merge is not None:
                    metadata += f" vmerge={merge}"
                cells.append(f"[{metadata}] {normalized}")
                column += span
            lines.append(" | ".join(cells))
        lines.append("[/TABLE]")
        return "\n".join(lines)

    def _wrapped_table_elements(
        self,
        container: ElementTree.Element,
        *,
        expected: str,
        property_elements: set[str],
    ) -> list[ElementTree.Element]:
        """표 행·셀 wrapper를 문서 순서대로 풀고 속성·미지원 요소를 명시한다."""

        elements: list[ElementTree.Element] = []
        for child in list(container):
            local = self._local_name(child.tag)
            if local == expected:
                elements.append(child)
            elif local in property_elements or local == "customXmlPr":
                continue
            elif local == "sdt":
                content = child.find("w:sdtContent", _NS)
                if content is None:
                    self._diagnostics.append("EMPTY_TABLE_CONTENT_CONTROL")
                else:
                    elements.extend(
                        self._wrapped_table_elements(
                            content,
                            expected=expected,
                            property_elements=property_elements,
                        )
                    )
            elif local in {"customXml", "ins", "del", "moveFrom", "moveTo"}:
                self._diagnostics.append(
                    f"TABLE_{expected.upper()}_WRAPPER_PRESERVED:{local}"
                )
                elements.extend(
                    self._wrapped_table_elements(
                        child,
                        expected=expected,
                        property_elements=property_elements,
                    )
                )
            elif local in {"altChunk", "object", "oleObject"}:
                raise ValueError(
                    f"Unsupported embedded DOCX table element: {local}"
                )
            elif local in {
                "bookmarkStart",
                "bookmarkEnd",
                "proofErr",
                "permStart",
                "permEnd",
            }:
                continue
            else:
                self._diagnostics.append(
                    f"UNSUPPORTED_TABLE_{expected.upper()}_ELEMENT:{local}"
                )
        return elements

    def _append_section_boundary(
        self,
        section: ElementTree.Element,
        group: _ContentGroup,
    ) -> None:
        self._structure["section_boundary_count"] += 1
        section_type = self._value(section.find("w:type", _NS)) or "nextPage"
        group.blocks.append(
            f"[SECTION_BOUNDARY index={self._structure['section_boundary_count']} type={section_type}]"
        )

    def _append_related_parts(
        self,
        document: ElementTree.Element,
        groups: list[_ContentGroup],
    ) -> None:
        referenced: list[tuple[str, str, str]] = []
        for kind, tag in (("HEADER", "headerReference"), ("FOOTER", "footerReference")):
            seen: set[str] = set()
            for reference in document.findall(f".//w:{tag}", _NS):
                relationship_id = reference.get(f"{_R}id")
                if not relationship_id or relationship_id in seen:
                    continue
                seen.add(relationship_id)
                relationship = self._relationship("word/document.xml", relationship_id)
                if relationship.external or not relationship.relationship_type.endswith(f"/{kind.lower()}"):
                    raise ValueError(f"DOCX {kind.lower()} relationship is invalid")
                referenced.append((kind, reference.get(f"{_W}type") or "default", relationship.target))
        for kind, reference_type, part_name in referenced:
            root = self._xml(part_name, required=True)
            assert root is not None
            blocks = self._render_part_blocks(root, part_name)
            if not blocks:
                self._diagnostics.append(f"EMPTY_{kind}_PART")
                continue
            key = "header_part_count" if kind == "HEADER" else "footer_part_count"
            self._structure[key] += 1
            groups.append(
                _ContentGroup(
                    groups[-1].location_index + 1,
                    f"{kind}_PART",
                    f"{kind.title()} {reference_type}",
                    [f"[{kind} type={reference_type} part={part_name}]", *blocks],
                )
            )

    def _append_notes(
        self,
        part_name: str,
        kind: str,
        groups: list[_ContentGroup],
    ) -> None:
        root = self._xml(part_name)
        if root is None:
            return
        tag = "footnote" if kind == "FOOTNOTE" else "endnote"
        count_key = "footnote_count" if kind == "FOOTNOTE" else "endnote_count"
        for note in root.findall(f"w:{tag}", _NS):
            note_id = note.get(f"{_W}id")
            if note_id is None or note_id.startswith("-"):
                continue
            blocks = self._render_part_blocks(note, part_name)
            if not blocks:
                self._diagnostics.append(f"EMPTY_{kind}:{note_id}")
                continue
            self._structure[count_key] += 1
            groups.append(
                _ContentGroup(
                    groups[-1].location_index + 1,
                    kind,
                    f"{kind.title()} {note_id}",
                    [f"[{kind} id={note_id}]", *blocks],
                )
            )

    def _append_comments(self, groups: list[_ContentGroup]) -> None:
        comment_relationships = [
            relationship
            for relationship in self._relationships.get("word/document.xml", {}).values()
            if relationship.relationship_type.endswith("/comments")
        ]
        comments_part_present = "word/comments.xml" in self._parts
        if len(comment_relationships) > 1:
            raise ValueError("DOCX comments relationship is duplicated")
        if comments_part_present != bool(comment_relationships):
            raise ValueError("DOCX comments part and relationship do not match")
        if not comments_part_present:
            return
        relationship = comment_relationships[0]
        if relationship.external or relationship.target != "word/comments.xml":
            raise ValueError("DOCX comments relationship is invalid")
        root = self._xml("word/comments.xml", required=True)
        assert root is not None
        for comment in root.findall("w:comment", _NS):
            comment_id = self._required_nonnegative_id(comment, "comment")
            if comment_id in self._comment_ids:
                raise ValueError("DOCX comment identity is duplicated")
            self._comment_ids.add(comment_id)
            blocks = self._render_part_blocks(comment, "word/comments.xml")
            if not blocks:
                raise ValueError("DOCX comment body is empty")
            author = (comment.get(f"{_W}author") or "UNSPECIFIED")[:200]
            created_at = (comment.get(f"{_W}date") or "UNSPECIFIED")[:100]
            self._structure["comment_count"] += 1
            groups.append(
                _ContentGroup(
                    groups[-1].location_index + 1,
                    "COMMENT",
                    f"Comment {comment_id}",
                    [
                        f"[COMMENT id={comment_id} author={author} date={created_at}]",
                        *blocks,
                    ],
                )
            )

    def _validate_comment_anchors(self) -> None:
        if self._comment_range_starts != self._comment_range_ends:
            raise ValueError("DOCX comment range anchors do not match")
        if self._comment_references != self._comment_ids:
            raise ValueError("DOCX comment references and bodies do not match")
        if not self._comment_range_starts.issubset(self._comment_references):
            raise ValueError("DOCX comment range has no matching reference")
        self._structure["comment_reference_count"] = len(self._comment_references)
        self._structure["comment_range_count"] = len(self._comment_range_starts)

    def _report_unreferenced_media(self) -> None:
        media_parts = {
            name
            for name in self._parts
            if name.casefold().startswith("word/media/")
        }
        unreferenced = media_parts - self._consumed_media_parts
        if unreferenced:
            self._structure["unreferenced_media_part_count"] = len(unreferenced)
            self._diagnostics.append(
                f"UNREFERENCED_MEDIA_PART_NOT_INDEXED:{len(unreferenced)}"
            )

    @staticmethod
    def _required_nonnegative_id(node: ElementTree.Element, label: str) -> str:
        value = node.get(f"{_W}id")
        if value is None or not value.isdigit():
            raise ValueError(f"DOCX {label} identity is invalid")
        return value

    def _render_part_blocks(
        self,
        root: ElementTree.Element,
        source_part: str,
    ) -> list[str]:
        blocks: list[str] = []
        for child in list(root):
            local = self._local_name(child.tag)
            if local == "p":
                text = self._render_inline(child, source_part).strip()
                if text:
                    blocks.append(text)
            elif local == "tbl":
                blocks.append(self._render_table(child, source_part))
            elif local == "sdt":
                content = child.find("w:sdtContent", _NS)
                if content is None:
                    self._diagnostics.append("EMPTY_RELATED_CONTENT_CONTROL")
                else:
                    blocks.extend(self._render_part_blocks(content, source_part))
            elif local in {"altChunk", "object", "oleObject"}:
                raise ValueError(f"Unsupported embedded DOCX related element: {local}")
            else:
                preserved = self._plain_text(child)
                self._diagnostics.append(f"UNSUPPORTED_RELATED_ELEMENT:{local}")
                if preserved:
                    blocks.append(f"[UNSUPPORTED {local}] {preserved}")
        return blocks

    def _core_properties(self) -> dict[str, object]:
        root = self._xml("docProps/core.xml")
        if root is None:
            self._diagnostics.append("CORE_PROPERTIES_MISSING")
            return {}
        values: dict[str, object] = {}
        for child in list(root):
            local = self._local_name(child.tag)
            if local in {"title", "subject", "revision"} and child.text:
                values[local] = child.text.strip()
        return values

    @staticmethod
    def _plain_text(node: ElementTree.Element) -> str:
        return " ".join(text.strip() for text in node.itertext() if text.strip())

    @staticmethod
    def _local_name(tag: str) -> str:
        return tag.rsplit("}", 1)[-1]

    @staticmethod
    def _value(node: ElementTree.Element | None) -> str | None:
        return node.get(f"{_W}val") if node is not None else None

    @staticmethod
    def _integer_attr(node: ElementTree.Element | None, name: str) -> int | None:
        if node is None:
            return None
        value = node.get(f"{_W}{name}")
        if value is None or not value.isdigit():
            return None
        return int(value)
