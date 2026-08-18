"""Template 역할 권한을 외부 고정 policy 파일에서 App DB 계약으로 이전한다.

외부 파일에 있던 과거 역할과 DB row를 안전하게 연결할 신뢰 가능한 key가 없으므로
upgrade는 기존 승인을 DRAFT로 되돌린다. 같은 이유로 downgrade도 과거 승인 상태를
추정 복원하지 않으며, 권한 확대는 반드시 정상 승인 절차를 다시 거쳐야 한다.
"""

from alembic import op


revision = "20260816_25"
down_revision = "20260816_24"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """역할 배열을 추가하고 승인 Template은 비어 있지 않은 배열만 허용한다.

    기존 승인 row의 역할은 삭제된 파일에서 추론하거나 복원하지 않는다. 역할 근거가
    없는 승인을 그대로 유지하면 권한이 우연히 넓어질 수 있으므로 DRAFT로 되돌려
    운영자가 DB의 정상 승인 절차에서 역할을 명시하도록 한다.
    """

    # PostgreSQL CHECK는 subquery를 직접 허용하지 않는다. 배열 원소를 검사하는
    # immutable helper를 schema에 두어 DB와 typed runtime이 같은 accepted domain
    # (string, nonblank, unique)을 사용하게 한다.
    op.execute(
        """
        CREATE FUNCTION context.valid_analysis_template_roles(value jsonb)
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
                -- Role 값은 application Role enum 및 auth_sessions constraint와 같은
                -- versioned 보안 계약이다. 새 역할은 code와 migration을 함께 바꾼다.
                ELSE NOT EXISTS (
                    SELECT 1
                    FROM jsonb_array_elements_text(value) AS item(name)
                    WHERE btrim(item.name) = ''
                       OR item.name NOT IN (
                           'hotel_analyst', 'report_admin', 'data_admin'
                       )
                )
                AND jsonb_array_length(value) = (
                    SELECT count(DISTINCT item.name)
                    FROM jsonb_array_elements_text(value) AS item(name)
                )
            END
        $$
        """
    )
    op.execute(
        "ALTER TABLE context.analysis_templates "
        "ADD COLUMN allowed_roles_json jsonb NOT NULL DEFAULT '[]'::jsonb"
    )
    # 역할 근거가 없는 승인 상태를 보존하는 것보다 재승인을 요구하는 것이 안전하다.
    op.execute(
        "UPDATE context.analysis_templates "
        "SET status = 'DRAFT', approved_by = NULL, approved_at = NULL "
        "WHERE status = 'APPROVED'"
    )
    op.execute(
        "ALTER TABLE context.analysis_templates "
        "ADD CONSTRAINT ck_analysis_templates_allowed_roles "
        "CHECK ("
        "context.valid_analysis_template_roles(allowed_roles_json) "
        "AND (status <> 'APPROVED' OR jsonb_array_length(allowed_roles_json) > 0)"
        ")"
    )


def downgrade() -> None:
    """DB 역할 계약을 제거하되 근거 없이 이전 승인 상태를 복원하지 않는다."""

    op.execute(
        "ALTER TABLE context.analysis_templates "
        "DROP CONSTRAINT ck_analysis_templates_allowed_roles, "
        "DROP COLUMN allowed_roles_json"
    )
    op.execute("DROP FUNCTION context.valid_analysis_template_roles(jsonb)")
