"""승인된 RAG DOCX 원문을 브라우저에서 읽을 수 있는 안전한 HTML로 변환한다."""

from __future__ import annotations

from html import escape
import re

from src.rag.docx_ingestion import _DocxExtractor


_BLOCK_PATTERN = re.compile(
    r"^\[(?P<kind>PARAGRAPH|HEADING|LIST|CAPTION)[^\]]*\]\s*(?P<text>.*)$",
    re.DOTALL,
)
_CELL_PATTERN = re.compile(
    r"\[r\d+c\d+\s+span=(?P<span>\d+)(?:\s+vmerge=\w+)?\]\s*"
    r"(?P<text>.*?)(?=\s+\|\s+\[r\d+c\d+\s+span=|$)"
)
_INLINE_MARKER_PATTERN = re.compile(
    r"\[(?:/?HYPERLINK(?:\s+target=[^\]]+)?|FIELD(?:_SIMPLE)?\s+[^\]]+|"
    r"FOOTNOTE_REFERENCE\s+[^\]]+|ENDNOTE_REFERENCE\s+[^\]]+)\]"
)


class RagDocumentPreviewError(ValueError):
    """DOCX 원문을 안전한 읽기 화면으로 변환할 수 없을 때 발생한다."""


def _clean_text(value: str) -> str:
    cleaned = _INLINE_MARKER_PATTERN.sub("", value).replace("[EMPTY_CELL]", "")
    return cleaned.strip()


def _render_table(block: str) -> str:
    rows: list[str] = []
    for row_index, line in enumerate(block.splitlines()[1:-1]):
        cells = list(_CELL_PATTERN.finditer(line))
        if not cells:
            continue
        tag = "th" if row_index == 0 else "td"
        rendered_cells = []
        for cell in cells:
            span = max(1, int(cell.group("span")))
            colspan = f' colspan="{span}"' if span > 1 else ""
            scope = ' scope="col"' if tag == "th" else ""
            rendered_cells.append(
                f"<{tag}{scope}{colspan}>{escape(_clean_text(cell.group('text')))}</{tag}>"
            )
        rows.append(f"<tr>{''.join(rendered_cells)}</tr>")
    if not rows:
        return ""
    return f'<div class="table-wrap"><table>{"".join(rows)}</table></div>'


def _render_block(block: str) -> str:
    if block.startswith("[TABLE "):
        return _render_table(block)
    if block.startswith(("[EXPLICIT_PAGE_BREAK", "[SECTION_BOUNDARY")):
        return '<hr class="page-break">'
    match = _BLOCK_PATTERN.match(block)
    if not match:
        return ""
    text = escape(_clean_text(match.group("text")))
    if not text:
        return ""
    kind = match.group("kind")
    if kind == "HEADING":
        return f"<h2>{text}</h2>"
    if kind == "CAPTION":
        return f'<p class="caption">{text}</p>'
    if kind == "LIST":
        return f'<p class="list-item">{text}</p>'
    style_match = re.match(r"^\[PARAGRAPH style=([^\]]+)\]", block)
    style = style_match.group(1).lower() if style_match else ""
    if style == "title":
        return f"<h1>{text}</h1>"
    if style == "subtitle":
        return f'<p class="subtitle">{text}</p>'
    return f"<p>{text}</p>"


def render_docx_preview_html(source: bytes, title: str) -> str:
    """검증된 DOCX bytes를 외부 리소스와 실행 코드가 없는 열람용 HTML로 만든다."""

    try:
        groups, _metadata, _diagnostics = _DocxExtractor(source).extract()
    except (KeyError, OSError, ValueError) as error:
        raise RagDocumentPreviewError("DOCX 미리보기를 만들 수 없습니다.") from error
    blocks = [
        rendered
        for group in groups
        if group.locator_kind not in {"HEADER_PART", "FOOTER_PART"}
        for block in group.blocks
        if (rendered := _render_block(block))
    ]
    if not blocks:
        raise RagDocumentPreviewError("DOCX 미리보기에 표시할 본문이 없습니다.")
    safe_title = escape(title.strip() or "근거 문서")
    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{safe_title}</title>
  <style>
    :root {{ color-scheme: light; font-family: "Noto Sans CJK KR", "Malgun Gothic", sans-serif; }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; padding: 32px; color: #10243e; background: #eef3f8; line-height: 1.65; }}
    main {{ width: min(940px, 100%); margin: 0 auto; padding: 48px 52px; background: #fff; box-shadow: 0 8px 28px rgba(15,35,58,.12); }}
    h1 {{ margin: 8px 0 6px; font-size: 28px; line-height: 1.3; }}
    h2 {{ margin: 32px 0 12px; padding-bottom: 8px; border-bottom: 2px solid #176fe5; font-size: 19px; line-height: 1.4; }}
    p {{ margin: 10px 0; }}
    .subtitle {{ margin-top: 0; color: #5b6f88; font-size: 15px; }}
    .caption {{ color: #5b6f88; font-size: 12px; }}
    .list-item {{ padding-left: 18px; }}
    .table-wrap {{ margin: 16px 0 22px; overflow-x: auto; border: 1px solid #cfdae8; border-radius: 8px; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 13px; font-variant-numeric: tabular-nums; }}
    th, td {{ padding: 10px 12px; border-bottom: 1px solid #dce5ef; text-align: left; white-space: nowrap; }}
    th {{ color: #405675; background: #f3f6fa; font-weight: 700; }}
    tr:last-child td {{ border-bottom: 0; }}
    .page-break {{ margin: 34px 0; border: 0; border-top: 1px dashed #b9c7d8; }}
    @media (max-width: 680px) {{ body {{ padding: 0; }} main {{ padding: 28px 20px; box-shadow: none; }} }}
  </style>
</head>
<body><main>{''.join(blocks)}</main></body>
</html>"""
