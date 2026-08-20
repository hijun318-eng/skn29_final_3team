"""분석 Role을 ``analyst`` 하나로 통일하고 기존 저장값을 원자적으로 이전한다."""

from alembic import op


revision = "20260820_27"
down_revision = "20260819_26"
branch_labels = None
depends_on = None


def _template_role_function(analyst_role: str) -> str:
    """Template JSON Role 제약을 지정한 분석 Role 이름으로 렌더링한다."""

    return f"""
        CREATE OR REPLACE FUNCTION context.valid_analysis_template_roles(value jsonb)
        RETURNS boolean
        LANGUAGE sql
        IMMUTABLE
        STRICT
        PARALLEL SAFE
        AS $$
            SELECT CASE
                WHEN jsonb_typeof(value) <> 'array' THEN false
                WHEN jsonb_path_exists(
                    value, '$[*] ? (@.type() != "string")'
                ) THEN false
                ELSE NOT EXISTS (
                    SELECT 1
                    FROM jsonb_array_elements_text(value) AS item(name)
                    WHERE btrim(item.name) = ''
                       OR item.name NOT IN (
                           '{analyst_role}', 'report_admin', 'data_admin',
                           'platform_admin'
                       )
                )
                AND jsonb_array_length(value) = (
                    SELECT count(DISTINCT item.name)
                    FROM jsonb_array_elements_text(value) AS item(name)
                )
            END
        $$
    """


def _rewrite_jsonb_role_array(
    table: str,
    column: str,
    source: str,
    target: str,
) -> None:
    """JSON 배열 순서를 보존하면서 Role 이름을 바꾸고 중복을 제거한다."""

    op.execute(
        f"""
        UPDATE {table} AS target_row
        SET {column} = (
            SELECT COALESCE(
                jsonb_agg(to_jsonb(deduplicated.role) ORDER BY deduplicated.first_position),
                '[]'::jsonb
            )
            FROM (
                SELECT
                    CASE WHEN item.value = '{source}' THEN '{target}' ELSE item.value END AS role,
                    min(item.position) AS first_position
                FROM jsonb_array_elements_text(target_row.{column})
                    WITH ORDINALITY AS item(value, position)
                GROUP BY CASE
                    WHEN item.value = '{source}' THEN '{target}' ELSE item.value
                END
            ) AS deduplicated
        )
        WHERE target_row.{column} ? '{source}'
        """
    )


def _rewrite_role_columns(source: str, target: str) -> None:
    """현재 저장소의 역할 식별자와 MCP 허용 목록을 동일 이름으로 이전한다."""

    for table, column in (
        ("chat.analysis_requests", "user_role"),
        ("context.context_records", "owner_role"),
        ("governance.audit_events", "actor_role"),
        ("tooling.tool_runs", "caller_role"),
    ):
        op.execute(
            f"UPDATE {table} SET {column} = '{target}' WHERE {column} = '{source}'"
        )
    _rewrite_jsonb_role_array(
        "tooling.tool_registry",
        "required_roles_json",
        source,
        target,
    )


def _replace_session_role(source: str, target: str) -> None:
    """Session CHECK를 잠시 해제하고 저장 Role을 canonical 값으로 이전한다."""

    op.execute(
        "ALTER TABLE security.auth_sessions DROP CONSTRAINT ck_auth_sessions_role"
    )
    op.execute(
        f"UPDATE security.auth_sessions SET role = '{target}' WHERE role = '{source}'"
    )
    op.execute(
        "ALTER TABLE security.auth_sessions "
        "ADD CONSTRAINT ck_auth_sessions_role CHECK (role IN ("
        f"'{target}', 'report_admin', 'data_admin', 'platform_admin'"
        "))"
    )


def upgrade() -> None:
    """모든 신규·기존 분석 Role 표현을 ``analyst``로 통일한다."""

    op.execute(
        "ALTER TABLE context.analysis_templates "
        "DROP CONSTRAINT ck_analysis_templates_allowed_roles"
    )
    _rewrite_jsonb_role_array(
        "context.analysis_templates",
        "allowed_roles_json",
        "hotel_analyst",
        "analyst",
    )
    op.execute(_template_role_function("analyst"))
    op.execute(
        "ALTER TABLE context.analysis_templates "
        "ADD CONSTRAINT ck_analysis_templates_allowed_roles CHECK ("
        "context.valid_analysis_template_roles(allowed_roles_json) "
        "AND (status <> 'APPROVED' OR jsonb_array_length(allowed_roles_json) > 0)"
        ")"
    )
    _replace_session_role("hotel_analyst", "analyst")
    _rewrite_role_columns("hotel_analyst", "analyst")


def downgrade() -> None:
    """이전 릴리스가 이해하는 ``hotel_analyst`` 표현으로 되돌린다."""

    op.execute(
        "ALTER TABLE context.analysis_templates "
        "DROP CONSTRAINT ck_analysis_templates_allowed_roles"
    )
    _rewrite_jsonb_role_array(
        "context.analysis_templates",
        "allowed_roles_json",
        "analyst",
        "hotel_analyst",
    )
    op.execute(_template_role_function("hotel_analyst"))
    op.execute(
        "ALTER TABLE context.analysis_templates "
        "ADD CONSTRAINT ck_analysis_templates_allowed_roles CHECK ("
        "context.valid_analysis_template_roles(allowed_roles_json) "
        "AND (status <> 'APPROVED' OR jsonb_array_length(allowed_roles_json) > 0)"
        ")"
    )
    _replace_session_role("analyst", "hotel_analyst")
    _rewrite_role_columns("analyst", "hotel_analyst")
