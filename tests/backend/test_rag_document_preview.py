from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "app" / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.services.rag_document_preview import render_docx_preview_html


def test_august_room_report_preview_preserves_sections_and_tables() -> None:
    source = (
        ROOT
        / "data"
        / "rag"
        / "manuals"
        / "monthly_reports"
        / "2026-08_03_객실팀_객실운영보고서.docx"
    ).read_bytes()

    html = render_docx_preview_html(source, "2026년 8월 객실 운영보고서 <script>")

    assert "객실 운영보고서" in html
    assert "호텔별 객실 실적" in html
    assert "객실 관련 고객 불편" in html
    assert "그랜드호텔" in html
    assert "15,532실" in html
    assert "<table>" in html
    assert "[PARAGRAPH" not in html
    assert "<script" not in html
    assert "&lt;script&gt;" in html
