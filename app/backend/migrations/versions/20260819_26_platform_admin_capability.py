"""사용자명과 무관한 전 서비스 관리 Role을 revocable session 계약에 추가한다."""

from alembic import op


revision = "20260819_26"
down_revision = "20260816_25"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """인증 session이 명시적인 ``platform_admin`` Role을 보존할 수 있게 확장한다."""

    op.execute(
        "ALTER TABLE security.auth_sessions "
        "DROP CONSTRAINT auth_sessions_role_check, "
        "ADD CONSTRAINT ck_auth_sessions_role CHECK (role IN ("
        "'hotel_analyst', 'report_admin', 'data_admin', 'platform_admin'"
        "))"
    )


def downgrade() -> None:
    """관리자 session을 폐기한 뒤 이전 세 역할 계약으로 안전하게 되돌린다."""

    # 이전 schema는 platform_admin 문자열을 저장할 수 없다. 원문 token은 어디에도
    # 저장되지 않으므로 해당 digest 행을 제거하면 이미 발급된 cookie도 즉시 무효화된다.
    op.execute("DELETE FROM security.auth_sessions WHERE role = 'platform_admin'")
    op.execute(
        "ALTER TABLE security.auth_sessions "
        "DROP CONSTRAINT ck_auth_sessions_role, "
        "ADD CONSTRAINT auth_sessions_role_check CHECK (role IN ("
        "'hotel_analyst', 'report_admin', 'data_admin'"
        "))"
    )
