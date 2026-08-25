-- 멀티턴 대화의 head·명령 lease·Turn 불변성을 DB 제약으로 보장하고 충돌 시 닫힌다.

BEGIN;

ALTER TABLE chat.conversations
    ADD COLUMN IF NOT EXISTS head_turn_id uuid,
    ADD COLUMN IF NOT EXISTS turn_count integer NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS active_command_id uuid,
    ADD COLUMN IF NOT EXISTS lease_expires_at timestamptz;

CREATE TABLE IF NOT EXISTS chat.turns (
    turn_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id uuid NOT NULL REFERENCES chat.conversations(conversation_id) ON DELETE CASCADE,
    turn_index integer NOT NULL CHECK (turn_index >= 0),
    user_message text NOT NULL,
    route varchar(24) NOT NULL CHECK (route IN ('ANALYSIS','PRESENTATION','REPORT_ACTION')),
    source_turn_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
    request_id uuid,
    artifact_id uuid,
    view_spec_id uuid,
    report_definition_id uuid,
    resolved_slots jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (conversation_id, turn_index)
);

CREATE TABLE IF NOT EXISTS chat.turn_commands (
    command_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id uuid NOT NULL REFERENCES chat.conversations(conversation_id) ON DELETE CASCADE,
    idempotency_key varchar(255) NOT NULL,
    canonical_input_hash varchar(64) NOT NULL,
    status varchar(16) NOT NULL CHECK (status IN ('RUNNING','COMPLETED','FAILED')),
    turn_id uuid REFERENCES chat.turns(turn_id) ON DELETE SET NULL,
    error_response jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (conversation_id, idempotency_key)
);

CREATE TABLE IF NOT EXISTS artifact.view_specs (
    view_spec_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    artifact_id uuid NOT NULL,
    view_type varchar(24) NOT NULL,
    spec_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_chat_turns_conversation
    ON chat.turns (conversation_id, turn_index);

CREATE INDEX IF NOT EXISTS idx_chat_turn_commands_conversation
    ON chat.turn_commands (conversation_id, created_at DESC);

GRANT SELECT, INSERT, UPDATE, DELETE ON chat.turns, chat.turn_commands TO app_user;
GRANT SELECT, INSERT, UPDATE, DELETE ON artifact.view_specs TO app_user;
GRANT SELECT, INSERT, UPDATE, DELETE ON chat.turns, chat.turn_commands TO app_migration;
GRANT SELECT, INSERT, UPDATE, DELETE ON artifact.view_specs TO app_migration;

COMMIT;
