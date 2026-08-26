"""검증된 Report Assistant 텍스트 근거 별칭을 Report block revision에 보존한다."""

from alembic import op


revision = "20260826_39"
down_revision = "20260826_38"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """기존 block은 빈 근거로 유지하고 이후 revision에 bounded 별칭 배열을 저장한다."""

    op.execute(
        "ALTER TABLE report_v1.report_blocks "
        "ADD COLUMN evidence_refs text[] NOT NULL DEFAULT '{}'::text[]"
    )
    op.execute(
        "ALTER TABLE report_v1.report_blocks "
        "ADD CONSTRAINT report_block_evidence_refs_check CHECK ("
        "cardinality(evidence_refs) <= 16 "
        "AND NOT ('' = ANY(evidence_refs))"
        ")"
    )


def downgrade() -> None:
    """보고서 본문과 Artifact lineage는 유지하고 표시용 근거 별칭만 제거한다."""

    op.execute(
        "ALTER TABLE report_v1.report_blocks "
        "DROP CONSTRAINT report_block_evidence_refs_check"
    )
    op.execute("ALTER TABLE report_v1.report_blocks DROP COLUMN evidence_refs")
