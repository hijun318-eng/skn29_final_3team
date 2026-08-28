"""대화형 로그인 계정을 APP DB의 단일 정본으로 저장한다."""

import os
import re

from alembic import op


revision = "20260826_46"
down_revision = "20260826_45"
branch_labels = None
depends_on = None


def _runtime_role() -> str:
    role = os.getenv("APP_DB_USER", "")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", role):
        raise RuntimeError("APP_DB_USER is missing or invalid")
    return f'"{role}"'


def upgrade() -> None:
    """PBKDF2 verifier와 현재 Role만 저장하고 runtime에는 읽기 권한만 부여한다."""

    op.execute(
        """
        CREATE TABLE security.auth_accounts (
            username varchar(64) PRIMARY KEY,
            password_salt varchar(128) NOT NULL,
            password_hash char(64) NOT NULL,
            password_iterations integer NOT NULL,
            subject uuid NOT NULL UNIQUE,
            role varchar(32) NOT NULL,
            active boolean NOT NULL DEFAULT true,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_auth_accounts_username CHECK (
                username = lower(btrim(username))
                AND username ~ '^[a-z0-9._-]{3,64}$'
            ),
            CONSTRAINT ck_auth_accounts_password_salt CHECK (
                password_salt ~ '^[A-Za-z0-9_-]{22,128}$'
            ),
            CONSTRAINT ck_auth_accounts_password_hash CHECK (
                password_hash ~ '^[0-9a-f]{64}$'
            ),
            CONSTRAINT ck_auth_accounts_password_iterations CHECK (
                password_iterations >= 200000
            ),
            CONSTRAINT ck_auth_accounts_role CHECK (
                role IN ('analyst', 'report_admin', 'data_admin', 'platform_admin')
            ),
            CONSTRAINT ck_auth_accounts_updated_at CHECK (updated_at >= created_at)
        )
        """
    )
    role = _runtime_role()
    op.execute(f"GRANT SELECT ON security.auth_accounts TO {role}")


def downgrade() -> None:
    """runtime 읽기 권한과 DB 계정 정본을 제거하되 세션 이력은 보존한다."""

    role = _runtime_role()
    op.execute(f"REVOKE SELECT ON security.auth_accounts FROM {role}")
    op.execute("DROP TABLE security.auth_accounts")
