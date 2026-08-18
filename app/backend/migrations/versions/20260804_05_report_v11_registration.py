"""REPORT-v1.1 layout 계약과 server 소유 manual command를 등록한다."""

import os
import re

from alembic import op


revision = "20260804_05"
down_revision = "20260804_04"
branch_labels = None
depends_on = None


def _runtime_role() -> str:
    role = os.getenv("APP_DB_USER", "")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", role):
        raise RuntimeError("APP_DB_USER is missing or invalid")
    return f'"{role}"'


def upgrade() -> None:
    """Report block layout constraint와 수동 실행 command persistence를 추가한다."""

    op.execute("ALTER TABLE report_v1.report_blocks ADD COLUMN block_type varchar(16)")
    op.execute("ALTER TABLE report_v1.report_blocks ADD COLUMN x smallint")
    op.execute("ALTER TABLE report_v1.report_blocks ADD COLUMN y smallint")
    op.execute("ALTER TABLE report_v1.report_blocks ADD COLUMN w smallint")
    op.execute("ALTER TABLE report_v1.report_blocks ADD COLUMN h smallint")
    op.execute("ALTER TABLE report_v1.report_blocks ADD COLUMN content text NOT NULL DEFAULT ''")
    op.execute(
        "UPDATE report_v1.report_blocks "
        "SET block_type = 'table', x = 0, y = 0, w = columns, h = 1"
    )
    for column in ("block_type", "x", "y", "w", "h"):
        op.execute(f"ALTER TABLE report_v1.report_blocks ALTER COLUMN {column} SET NOT NULL")
    op.execute("ALTER TABLE report_v1.report_blocks ALTER COLUMN artifact_id DROP NOT NULL")
    op.execute(
        "ALTER TABLE report_v1.report_blocks ADD CONSTRAINT report_block_type_check "
        "CHECK (block_type IN ('table', 'chart', 'text'))"
    )
    op.execute(
        "ALTER TABLE report_v1.report_blocks ADD CONSTRAINT report_block_layout_check "
        "CHECK (columns = w AND x >= 0 AND y >= 0 AND w BETWEEN 1 AND 12 "
        "AND h > 0 AND x + w <= 12)"
    )
    op.execute(
        "ALTER TABLE report_v1.report_blocks ADD CONSTRAINT report_block_artifact_check "
        "CHECK ((block_type IN ('table', 'chart') AND artifact_id IS NOT NULL) "
        "OR (block_type = 'text' AND btrim(content) <> ''))"
    )
    op.execute(
        """
        CREATE TABLE report_v1.report_manual_run_commands (
            command_id uuid PRIMARY KEY,
            definition_id uuid NOT NULL,
            definition_version integer NOT NULL,
            as_of timestamptz NOT NULL,
            idempotency_key text NOT NULL CHECK (btrim(idempotency_key) <> ''),
            status varchar(16) NOT NULL DEFAULT 'queued' CHECK (status = 'queued'),
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (definition_id, definition_version, idempotency_key),
            FOREIGN KEY (definition_id, definition_version)
                REFERENCES report_v1.report_definition_versions(definition_id, version)
        )
        """
    )
    op.execute(
        """
        CREATE TRIGGER report_manual_command_requires_approved_definition
        BEFORE INSERT ON report_v1.report_manual_run_commands
        FOR EACH ROW EXECUTE FUNCTION report_v1.require_approved_definition()
        """
    )
    role = _runtime_role()
    op.execute(
        f"GRANT SELECT, INSERT, UPDATE ON report_v1.report_manual_run_commands TO {role}"
    )
    op.execute(f"GRANT DELETE ON report_v1.report_blocks TO {role}")


def downgrade() -> None:
    """추가 권한·command table·layout column을 의존성 역순으로 제거한다."""

    role = _runtime_role()
    op.execute(f"REVOKE DELETE ON report_v1.report_blocks FROM {role}")
    op.execute(
        f"REVOKE SELECT, INSERT, UPDATE ON report_v1.report_manual_run_commands FROM {role}"
    )
    op.execute("DROP TABLE report_v1.report_manual_run_commands")
    op.execute("ALTER TABLE report_v1.report_blocks DROP CONSTRAINT report_block_artifact_check")
    op.execute("ALTER TABLE report_v1.report_blocks DROP CONSTRAINT report_block_layout_check")
    op.execute("ALTER TABLE report_v1.report_blocks DROP CONSTRAINT report_block_type_check")
    op.execute(
        "UPDATE report_v1.report_blocks SET artifact_id = block_id WHERE artifact_id IS NULL"
    )
    op.execute("ALTER TABLE report_v1.report_blocks ALTER COLUMN artifact_id SET NOT NULL")
    for column in ("content", "h", "w", "y", "x", "block_type"):
        op.execute(f"ALTER TABLE report_v1.report_blocks DROP COLUMN {column}")
