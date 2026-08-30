"""공개 MCP Tool output schema를 추가 필드 거부 계약으로 닫는다."""

from alembic import op


revision = "20260831_61"
down_revision = "20260831_60"
branch_labels = None
depends_on = None

TOOL_ID = "c4454392-2f92-54a4-ad13-b8cdaba45732"


def upgrade() -> None:
    """기존 analysis.get_run registry row 한 건의 output schema만 엄격화한다."""

    op.execute(
        f"""
        DO $$
        DECLARE
            affected integer;
        BEGIN
            UPDATE tooling.tool_registry
            SET output_schema_json = output_schema_json
                || '{{"additionalProperties": false}}'::jsonb
            WHERE tool_id = '{TOOL_ID}'
              AND tool_code = 'analysis.get_run'
              AND semantic_version = '1.0.0'
              AND NOT (output_schema_json ? 'additionalProperties');
            GET DIAGNOSTICS affected = ROW_COUNT;
            IF affected <> 1 THEN
                RAISE EXCEPTION 'analysis.get_run output schema receipt is not the expected predecessor';
            END IF;
        END $$
        """
    )


def downgrade() -> None:
    """추가 필드 거부 표식만 제거해 직전 registry 계약으로 되돌린다."""

    op.execute(
        f"""
        DO $$
        DECLARE
            affected integer;
        BEGIN
            UPDATE tooling.tool_registry
            SET output_schema_json = output_schema_json - 'additionalProperties'
            WHERE tool_id = '{TOOL_ID}'
              AND tool_code = 'analysis.get_run'
              AND semantic_version = '1.0.0'
              AND output_schema_json->'additionalProperties' = 'false'::jsonb;
            GET DIAGNOSTICS affected = ROW_COUNT;
            IF affected <> 1 THEN
                RAISE EXCEPTION 'analysis.get_run output schema receipt cannot be downgraded safely';
            END IF;
        END $$
        """
    )
