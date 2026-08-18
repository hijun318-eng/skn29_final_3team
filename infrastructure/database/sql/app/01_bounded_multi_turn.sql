-- Bounded Governed Multi-turn DDL Migration (Milestone 1)
-- Target: app_db (PostgreSQL)

BEGIN;

-- 1. artifact.view_specs (Presentation View 명세)
CREATE TABLE IF NOT EXISTS artifact.view_specs (
    view_spec_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    artifact_id uuid NOT NULL REFERENCES artifact.analysis_artifacts(artifact_id),
    view_type varchar(32) NOT NULL CHECK (view_type IN ('TABLE', 'BAR', 'LINE', 'PIE', 'AREA', 'SCATTER', 'KPI')),
    spec_json jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

-- 2. chat.turns (불변 대화 턴)
CREATE TABLE IF NOT EXISTS chat.turns (
    turn_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id uuid NOT NULL REFERENCES chat.conversations(conversation_id),
    turn_index integer NOT NULL CHECK (turn_index >= 0),
    user_message text NOT NULL,
    route varchar(32) NOT NULL CHECK (route IN ('ANALYSIS', 'PRESENTATION', 'REPORT_ACTION')),
    source_turn_ids jsonb NOT NULL DEFAULT '[]',
    request_id uuid REFERENCES chat.analysis_requests(request_id),
    artifact_id uuid REFERENCES artifact.analysis_artifacts(artifact_id),
    view_spec_id uuid REFERENCES artifact.view_specs(view_spec_id),
    report_definition_id uuid REFERENCES report.report_definitions(report_definition_id),
    resolved_slots jsonb NOT NULL DEFAULT '{}',
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (conversation_id, turn_index)
);

-- 3. chat.turn_commands (멱등성 및 Lease 관리)
CREATE TABLE IF NOT EXISTS chat.turn_commands (
    command_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id uuid NOT NULL REFERENCES chat.conversations(conversation_id),
    idempotency_key varchar(128) NOT NULL,
    canonical_input_hash char(64) NOT NULL,
    status varchar(32) NOT NULL CHECK (status IN ('RUNNING', 'COMPLETED', 'FAILED')),
    turn_id uuid REFERENCES chat.turns(turn_id),
    error_response jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (conversation_id, idempotency_key)
);

-- 4. chat.conversations 확장
ALTER TABLE chat.conversations ADD COLUMN IF NOT EXISTS head_turn_id uuid REFERENCES chat.turns(turn_id);
ALTER TABLE chat.conversations ADD COLUMN IF NOT EXISTS turn_count integer NOT NULL DEFAULT 0;
ALTER TABLE chat.conversations ADD COLUMN IF NOT EXISTS active_command_id uuid REFERENCES chat.turn_commands(command_id);
ALTER TABLE chat.conversations ADD COLUMN IF NOT EXISTS lease_expires_at timestamptz;

-- 5. 인덱스 생성
CREATE INDEX IF NOT EXISTS idx_chat_turns_conv ON chat.turns(conversation_id, turn_index);
CREATE INDEX IF NOT EXISTS idx_chat_commands_lookup ON chat.turn_commands(conversation_id, idempotency_key);
CREATE INDEX IF NOT EXISTS idx_view_specs_artifact ON artifact.view_specs(artifact_id);

COMMIT;
