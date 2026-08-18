"""owner 범위의 Analysis Definition과 request 실행 연결을 영속화한다."""

import os
import re

from alembic import op


revision = "20260810_06"
down_revision = "20260804_05"
branch_labels = None
depends_on = None


def _runtime_role() -> str:
    role = os.getenv("APP_DB_USER", "")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", role):
        raise RuntimeError("APP_DB_USER is missing or invalid")
    return f'"{role}"'


def upgrade() -> None:
    """Analysis version·run link schema를 생성하고 runtime 최소권한을 부여한다."""

    op.execute("CREATE SCHEMA analysis_v1")
    op.execute(
        """
        CREATE TABLE analysis_v1.analysis_definitions (
            definition_id uuid NOT NULL,
            version integer NOT NULL CHECK (version >= 1),
            owner_id uuid NOT NULL,
            title varchar(255) NOT NULL CHECK (btrim(title) <> ''),
            question_text_redacted text NOT NULL CHECK (btrim(question_text_redacted) <> ''),
            parameters_json jsonb NOT NULL,
            parameter_hash varchar(64) NOT NULL,
            status varchar(16) NOT NULL DEFAULT 'approved' CHECK (status = 'approved'),
            created_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (definition_id, version)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE analysis_v1.analysis_run_links (
            definition_id uuid NOT NULL,
            definition_version integer NOT NULL,
            request_id uuid NOT NULL UNIQUE REFERENCES chat.analysis_requests(request_id),
            idempotency_key varchar(128) NOT NULL CHECK (btrim(idempotency_key) <> ''),
            as_of date NOT NULL,
            timezone_name varchar(64) NOT NULL CHECK (timezone_name = 'Asia/Seoul'),
            created_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (definition_id, definition_version, request_id),
            UNIQUE (definition_id, definition_version, idempotency_key),
            FOREIGN KEY (definition_id, definition_version)
                REFERENCES analysis_v1.analysis_definitions(definition_id, version)
        )
        """
    )
    op.execute(
        """
        CREATE FUNCTION analysis_v1.reject_immutable_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'Analysis Definition and Run history are immutable';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    for table in ("analysis_definitions", "analysis_run_links"):
        op.execute(
            f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE "
            f"ON analysis_v1.{table} FOR EACH ROW "
            "EXECUTE FUNCTION analysis_v1.reject_immutable_mutation()"
        )
    role = _runtime_role()
    op.execute(f"GRANT USAGE ON SCHEMA analysis_v1, chat, query, artifact TO {role}")
    op.execute(f"GRANT SELECT, INSERT ON ALL TABLES IN SCHEMA analysis_v1 TO {role}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON chat.analysis_requests TO {role}")
    op.execute(f"GRANT SELECT, INSERT ON chat.analysis_state_transitions TO {role}")
    op.execute(f"GRANT SELECT, INSERT ON query.query_executions TO {role}")
    op.execute(f"GRANT SELECT, INSERT ON artifact.analysis_artifacts TO {role}")


def downgrade() -> None:
    """Analysis persistence 권한을 회수하고 전용 schema를 제거한다."""

    role = _runtime_role()
    op.execute(f"REVOKE SELECT, INSERT ON artifact.analysis_artifacts FROM {role}")
    op.execute(f"REVOKE SELECT, INSERT ON query.query_executions FROM {role}")
    op.execute(f"REVOKE SELECT, INSERT ON chat.analysis_state_transitions FROM {role}")
    op.execute(f"REVOKE SELECT, INSERT, UPDATE ON chat.analysis_requests FROM {role}")
    op.execute(f"REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA analysis_v1 FROM {role}")
    op.execute(f"REVOKE USAGE ON SCHEMA analysis_v1 FROM {role}")
    op.execute("DROP SCHEMA analysis_v1 CASCADE")
