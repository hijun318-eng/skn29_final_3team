"""승인 시 렌더링한 HTML·PDF snapshot과 source/artifact checksum을 불변 문서로 저장한다."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from uuid import UUID

from sqlalchemy import text

from app.services.report.document import canonical_source_checksum
from src.report.domain import CURRENCY_DISPLAY_UNITS, DefinitionStatus


class PostgresReportDocumentRepositoryMixin:
    """보고서 승인 source와 불변 HTML·PDF 문서를 PostgreSQL version에 연결한다.

    소유자 또는 ``manage_all`` 범위의 draft만 렌더링 대상으로 노출하며 모든 data block에
    승인 artifact checksum을 요구한다. 승인 시 source 재검증과 문서 삽입, definition 상태
    변경을 한 transaction으로 묶는다.
    """
    async def _document_source(self, session, definition_id, version: int) -> dict[str, object]:
        row = (await session.execute(
            text(
                """
                SELECT v.definition_id, v.version, v.status, v.title,
                       v.orientation, v.currency_display_unit
                FROM report_v1.report_definition_versions v
                JOIN report_v1.report_definitions d USING (definition_id)
                WHERE v.definition_id = :definition_id AND v.version = :version
                  AND (:manage_all OR d.owner_id = :owner_id)
                """
            ),
            {**self._scope_params(), "definition_id": definition_id, "version": version},
        )).mappings().one_or_none()
        if row is None:
            raise KeyError("Report definition version not found")
        if row["status"] != DefinitionStatus.DRAFT.value:
            raise ValueError("Only a draft Report version can be finalized")

        block_rows = (await session.execute(
            text(
                """
                SELECT b.block_id, b.title, b.block_type, b.x, b.y, b.w, b.h,
                       b.content, b.artifact_id, b.query_id,
                       a.artifact_checksum, a.data_snapshot_json,
                       a.chart_spec_json, a.evidence_json, a.narrative_markdown,
                       a.status AS artifact_status
                FROM report_v1.report_blocks b
                LEFT JOIN artifact.analysis_artifacts a ON a.artifact_id = b.artifact_id
                WHERE b.definition_id = :definition_id
                  AND b.definition_version = :version
                ORDER BY b.y, b.x, b.block_id
                """
            ),
            {"definition_id": definition_id, "version": version},
        )).mappings().all()
        blocks: list[dict[str, object]] = []
        artifact_versions: dict[str, dict[str, str]] = {}
        for block in block_rows:
            artifact = None
            if block["block_type"] in {"table", "chart", "artifact"}:
                if block["artifact_status"] != "APPROVED" or not block["artifact_checksum"]:
                    raise ValueError("Every data block needs an approved immutable Artifact")
                artifact_id = str(block["artifact_id"])
                artifact = {
                    "artifact_id": artifact_id,
                    "artifact_checksum": block["artifact_checksum"],
                    "query_id": block["query_id"],
                    "table": block["data_snapshot_json"],
                    "chart_spec": block["chart_spec_json"],
                    "evidence": block["evidence_json"],
                    "narrative": block["narrative_markdown"],
                }
                artifact_versions[artifact_id] = {
                    "artifact_id": artifact_id,
                    "artifact_checksum": str(block["artifact_checksum"]),
                    "query_id": str(block["query_id"]),
                }
            blocks.append(
                {
                    "block_id": str(block["block_id"]),
                    "title": block["title"],
                    "type": block["block_type"],
                    "x": block["x"],
                    "y": block["y"],
                    "w": block["w"],
                    "h": block["h"],
                    "content": block["content"],
                    "artifact": artifact,
                }
            )
        return {
            "definition_id": str(row["definition_id"]),
            "version": int(row["version"]),
            "title": row["title"],
            "orientation": row["orientation"],
            "currency_display_unit": row["currency_display_unit"],
            "blocks": blocks,
            "artifact_versions": [artifact_versions[key] for key in sorted(artifact_versions)],
        }

    async def get_document_source(self, definition_id: str, version: int) -> dict[str, object]:
        """접근 가능한 draft version을 checksum 계산용 문서 source dict로 복원한다.

        block을 배치 순서로 반환하며 data block마다 승인 artifact와 checksum을 포함한다.
        UUID 오류는 ``ValueError``, 누락·비소유 version은 ``KeyError``, 비draft 또는 유효하지
        않은 data block은 ``ValueError``다.
        """
        definition_uuid = self._document_uuid(definition_id)
        async with self._sessionmaker() as session:
            return await self._document_source(session, definition_uuid, version)

    @staticmethod
    def _document_uuid(value: str):
        try:
            return UUID(str(value))
        except (TypeError, ValueError, AttributeError) as error:
            raise ValueError("definition_id must be a valid UUID") from error

    async def approve_with_document(
        self,
        definition_id: str,
        version: int,
        approved_at: datetime,
        orientation: str,
        currency_display_unit: str,
        expected_source_checksum: str,
        html_snapshot: str,
        pdf_bytes: bytes,
    ):
        """렌더링 source를 재검증해 draft와 HTML·PDF snapshot을 원자적으로 승인한다.

        소유 범위의 version을 잠근 뒤 orientation·통화 단위·source checksum이 렌더링 전과
        같은지 확인한다. 일치하면 문서와 세 checksum을 삽입하고 draft를 approved로 바꾼다.
        누락·비소유는 ``KeyError``, 형식·상태·동시 변경은 ``ValueError``로 거부하며, 성공 시
        승인된 :class:`ReportDefinitionVersion`을 반환한다.
        """
        if orientation not in {"portrait", "landscape"}:
            raise ValueError("orientation must be portrait or landscape")
        if currency_display_unit not in CURRENCY_DISPLAY_UNITS:
            raise ValueError("currency_display_unit is invalid")
        if not html_snapshot.strip() or not pdf_bytes.startswith(b"%PDF-"):
            raise ValueError("A valid HTML and PDF snapshot is required")
        definition_uuid = self._document_uuid(definition_id)
        async with self._sessionmaker.begin() as session:
            locked = (await session.execute(
                text(
                    """
                    SELECT v.status, v.orientation, v.currency_display_unit
                    FROM report_v1.report_definition_versions v
                    JOIN report_v1.report_definitions d USING (definition_id)
                    WHERE v.definition_id = :definition_id AND v.version = :version
                      AND (:manage_all OR d.owner_id = :owner_id)
                    FOR UPDATE OF v
                    """
                ),
                {**self._scope_params(), "definition_id": definition_uuid, "version": version},
            )).mappings().one_or_none()
            if locked is None:
                raise KeyError("Report definition version not found")
            if locked["status"] != DefinitionStatus.DRAFT.value:
                raise ValueError("Only a draft Report version can be finalized")
            if locked["orientation"] != orientation:
                raise ValueError("Report orientation changed while the PDF was rendering")
            if locked["currency_display_unit"] != currency_display_unit:
                raise ValueError("Report currency display unit changed while the PDF was rendering")
            source = await self._document_source(session, definition_uuid, version)
            actual_checksum = canonical_source_checksum(source, orientation)
            if actual_checksum != expected_source_checksum:
                raise ValueError("Report content changed while the PDF was rendering")
            artifact_versions = json.dumps(
                source["artifact_versions"], ensure_ascii=False, separators=(",", ":"), sort_keys=True
            )
            await session.execute(
                text(
                    """
                    INSERT INTO report_v1.report_documents
                        (definition_id, definition_version, orientation,
                         currency_display_unit, renderer_version,
                         source_checksum, html_checksum, pdf_checksum, html_snapshot,
                         pdf_bytes, artifact_versions, confirmed_at)
                    VALUES (:definition_id, :version, :orientation,
                            :currency_display_unit, 'weasyprint-69',
                            :source_checksum, :html_checksum, :pdf_checksum, :html_snapshot,
                            :pdf_bytes, CAST(:artifact_versions AS jsonb), :confirmed_at)
                    """
                ),
                {
                    "definition_id": definition_uuid,
                    "version": version,
                    "orientation": orientation,
                    "currency_display_unit": currency_display_unit,
                    "source_checksum": actual_checksum,
                    "html_checksum": hashlib.sha256(html_snapshot.encode("utf-8")).hexdigest(),
                    "pdf_checksum": hashlib.sha256(pdf_bytes).hexdigest(),
                    "html_snapshot": html_snapshot,
                    "pdf_bytes": pdf_bytes,
                    "artifact_versions": artifact_versions,
                    "confirmed_at": approved_at,
                },
            )
            updated = await session.execute(
                text(
                    """
                    UPDATE report_v1.report_definition_versions
                    SET status = 'approved', approved_at = :approved_at
                    WHERE definition_id = :definition_id AND version = :version
                      AND status = 'draft'
                    """
                ),
                {"definition_id": definition_uuid, "version": version, "approved_at": approved_at},
            )
            if updated.rowcount != 1:
                raise ValueError("Report finalization lost its draft lock")
        return await self.get_version(definition_id, version)

    async def get_document(self, definition_id: str, version: int) -> dict[str, object]:
        """접근 가능한 definition version의 확정 문서 bytes와 무결성 metadata를 반환한다.

        반환 dict에는 HTML·PDF snapshot, renderer version, source·HTML·PDF checksum과 artifact
        version 목록이 포함된다. UUID 오류는 ``ValueError``이고 문서 누락 또는 비소유는
        동일한 ``KeyError``다.
        """
        definition_uuid = self._document_uuid(definition_id)
        async with self._sessionmaker() as session:
            row = (await session.execute(
                text(
                    """
                    SELECT doc.definition_id, doc.definition_version, doc.orientation,
                           doc.currency_display_unit,
                           doc.renderer_version, doc.source_checksum, doc.html_checksum,
                           doc.pdf_checksum, doc.html_snapshot, doc.pdf_bytes,
                           doc.artifact_versions, doc.confirmed_at
                    FROM report_v1.report_documents doc
                    JOIN report_v1.report_definitions d USING (definition_id)
                    WHERE doc.definition_id = :definition_id
                      AND doc.definition_version = :version
                      AND (:manage_all OR d.owner_id = :owner_id)
                    """
                ),
                {**self._scope_params(), "definition_id": definition_uuid, "version": version},
            )).mappings().one_or_none()
        if row is None:
            raise KeyError("Final Report document not found")
        return dict(row)
