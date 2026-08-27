"""사람 계정을 App DB로 이전하고 Role 계약을 ``analyst``·``admin`` 둘로 축소한다.

기존 session은 새 계정 원본과 결속되지 않았으므로 모두 폐기한다. 과거 audit·request·tool
run의 Role 문자열은 당시 증거이며 수정하지 않고 현재 Template·Tool entitlement만 전환한다.
"""

import os
import re

from alembic import op


revision = "20260827_31"
down_revision = "20260821_29"
branch_labels = None
depends_on = None


def _runtime_role() -> str:
    """환경의 App runtime DB role을 검증해 인용된 PostgreSQL 식별자로 반환한다."""

    role = os.getenv("APP_DB_USER", "")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", role):
        raise RuntimeError("APP_DB_USER is missing or invalid")
    return f'"{role}"'


def _template_role_function(roles: tuple[str, ...]) -> str:
    """Template JSON 배열에 허용할 정확한 사람 Role 집합으로 immutable validator를 만든다."""

    accepted = ", ".join(f"'{role}'" for role in roles)
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
                       OR item.name NOT IN ({accepted})
                )
                AND jsonb_array_length(value) = (
                    SELECT count(DISTINCT item.name)
                    FROM jsonb_array_elements_text(value) AS item(name)
                )
            END
        $$
    """


def _rewrite_legacy_role_arrays(table: str, column: str) -> None:
    """legacy 관리 Role을 ``admin`` 하나로 바꾸고 원래 순서 기준으로 중복 제거한다."""

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
                    CASE
                        WHEN item.value IN (
                            'report_admin', 'data_admin', 'platform_admin'
                        ) THEN 'admin'
                        ELSE item.value
                    END AS role,
                    min(item.position) AS first_position
                FROM jsonb_array_elements_text(target_row.{column})
                    WITH ORDINALITY AS item(value, position)
                GROUP BY CASE
                    WHEN item.value IN (
                        'report_admin', 'data_admin', 'platform_admin'
                    ) THEN 'admin'
                    ELSE item.value
                END
            ) AS deduplicated
        )
        WHERE target_row.{column} ?| ARRAY[
            'report_admin', 'data_admin', 'platform_admin'
        ]
        """
    )


def _rewrite_admin_array_for_downgrade(table: str, column: str) -> None:
    """provenance가 사라진 ``admin`` entitlement를 보수적인 ``report_admin``으로 되돌린다."""

    op.execute(
        f"""
        UPDATE {table} AS target_row
        SET {column} = (
            SELECT jsonb_agg(
                to_jsonb(
                    CASE WHEN item.value = 'admin' THEN 'report_admin' ELSE item.value END
                ) ORDER BY item.position
            )
            FROM jsonb_array_elements_text(target_row.{column})
                WITH ORDINALITY AS item(value, position)
        )
        WHERE target_row.{column} ? 'admin'
        """
    )


def upgrade() -> None:
    """DB 계정 원본·두 Role·session FK·관리 entitlement·append-only 감사를 적용한다."""

    op.execute(
        """
        CREATE TABLE security.accounts (
            subject uuid PRIMARY KEY,
            username varchar(64) NOT NULL UNIQUE,
            password_salt varchar(128) NOT NULL,
            password_hash char(64) NOT NULL,
            password_iterations integer NOT NULL CHECK (password_iterations >= 200000),
            role varchar(32) NOT NULL CHECK (role IN ('analyst', 'admin')),
            active boolean NOT NULL DEFAULT true,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            deactivated_at timestamptz,
            deleted_at timestamptz,
            CONSTRAINT ck_accounts_username CHECK (
                username = lower(btrim(username))
                AND username ~ '^[a-z0-9._-]{3,64}$'
            ),
            CONSTRAINT ck_accounts_password_salt CHECK (
                password_salt ~ '^[A-Za-z0-9_-]{22,128}$'
            ),
            CONSTRAINT ck_accounts_password_hash CHECK (
                password_hash ~ '^[0-9a-f]{64}$'
            ),
            CONSTRAINT ck_accounts_deleted_inactive CHECK (
                deleted_at IS NULL OR active = false
            ),
            CONSTRAINT ck_accounts_deactivated_state CHECK (
                (active AND deactivated_at IS NULL)
                OR (NOT active AND deactivated_at IS NOT NULL)
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_accounts_active_role "
        "ON security.accounts (role, username) WHERE active AND deleted_at IS NULL"
    )

    # 이전 파일 계정과 결속되지 않은 token digest를 보존하면 Role 전환 뒤에도 인증될 수
    # 있으므로 모든 session을 폐기하고 새 DB 계정 로그인으로만 다시 발급한다.
    op.execute("DELETE FROM security.auth_sessions")
    op.execute(
        "ALTER TABLE security.auth_sessions "
        "DROP CONSTRAINT ck_auth_sessions_role, "
        "ADD CONSTRAINT ck_auth_sessions_role "
        "CHECK (role IN ('analyst', 'admin')), "
        "ADD CONSTRAINT fk_auth_sessions_account "
        "FOREIGN KEY (subject) REFERENCES security.accounts(subject)"
    )

    op.execute(
        "ALTER TABLE context.analysis_templates "
        "DROP CONSTRAINT ck_analysis_templates_allowed_roles"
    )
    _rewrite_legacy_role_arrays(
        "context.analysis_templates", "allowed_roles_json"
    )
    op.execute(_template_role_function(("analyst", "admin")))
    op.execute(
        "ALTER TABLE context.analysis_templates "
        "ADD CONSTRAINT ck_analysis_templates_allowed_roles CHECK ("
        "context.valid_analysis_template_roles(allowed_roles_json) "
        "AND (status <> 'APPROVED' OR jsonb_array_length(allowed_roles_json) > 0)"
        ")"
    )
    _rewrite_legacy_role_arrays("tooling.tool_registry", "required_roles_json")
    op.execute(
        "ALTER TABLE tooling.tool_registry "
        "ADD CONSTRAINT ck_tool_registry_required_roles CHECK ("
        "context.valid_analysis_template_roles(required_roles_json) "
        "AND (NOT is_enabled OR jsonb_array_length(required_roles_json) > 0)"
        ")"
    )

    op.execute(
        """
        CREATE FUNCTION governance.reject_audit_event_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION 'governance.audit_events is append-only';
        END;
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER audit_events_append_only "
        "BEFORE UPDATE OR DELETE ON governance.audit_events "
        "FOR EACH ROW EXECUTE FUNCTION governance.reject_audit_event_mutation()"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_audit_events_created "
        "ON governance.audit_events (created_at DESC, audit_event_id DESC)"
    )

    role = _runtime_role()
    op.execute(f"GRANT USAGE ON SCHEMA security, governance TO {role}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON security.accounts TO {role}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON security.auth_sessions TO {role}")
    op.execute(f"GRANT SELECT, INSERT ON governance.audit_events TO {role}")


def downgrade() -> None:
    """신규 session·계정을 제거하고 과거 Role 제약을 보수적인 관리 계약으로 복원한다."""

    role = _runtime_role()
    op.execute(f"REVOKE SELECT, INSERT, UPDATE ON security.accounts FROM {role}")
    op.execute("DROP TRIGGER audit_events_append_only ON governance.audit_events")
    op.execute("DROP FUNCTION governance.reject_audit_event_mutation()")
    op.execute("DROP INDEX IF EXISTS governance.ix_audit_events_created")

    op.execute(
        "ALTER TABLE context.analysis_templates "
        "DROP CONSTRAINT ck_analysis_templates_allowed_roles"
    )
    op.execute(
        "ALTER TABLE tooling.tool_registry "
        "DROP CONSTRAINT ck_tool_registry_required_roles"
    )
    _rewrite_admin_array_for_downgrade(
        "context.analysis_templates", "allowed_roles_json"
    )
    op.execute(
        _template_role_function(
            ("analyst", "report_admin", "data_admin", "platform_admin")
        )
    )
    op.execute(
        "ALTER TABLE context.analysis_templates "
        "ADD CONSTRAINT ck_analysis_templates_allowed_roles CHECK ("
        "context.valid_analysis_template_roles(allowed_roles_json) "
        "AND (status <> 'APPROVED' OR jsonb_array_length(allowed_roles_json) > 0)"
        ")"
    )
    _rewrite_admin_array_for_downgrade(
        "tooling.tool_registry", "required_roles_json"
    )

    op.execute("DELETE FROM security.auth_sessions")
    op.execute(
        "ALTER TABLE security.auth_sessions "
        "DROP CONSTRAINT fk_auth_sessions_account, "
        "DROP CONSTRAINT ck_auth_sessions_role, "
        "ADD CONSTRAINT ck_auth_sessions_role CHECK (role IN ("
        "'analyst', 'report_admin', 'data_admin', 'platform_admin'"
        "))"
    )
    op.execute("DROP TABLE security.accounts")
