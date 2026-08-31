"""Report Assistant 원지시와 정확 페이지 renderer 검증 receipt를 보존한다."""

from alembic import op


revision = "20260831_67"
down_revision = "20260831_66"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """원지시와 renderer 검증값을 phase별 불변식과 함께 저장한다."""

    op.execute(
        """
        ALTER TABLE report_v1.report_assistant_requests
            ADD COLUMN source_instruction varchar(500),
            ADD COLUMN exact_page_count smallint,
            ADD COLUMN verified_page_count integer,
            ADD COLUMN page_renderer_fingerprint varchar(64),
            ADD CONSTRAINT report_assistant_source_instruction_check CHECK (
                source_instruction IS NULL
                OR (
                    length(btrim(source_instruction)) BETWEEN 1 AND 500
                    AND source_instruction = btrim(source_instruction)
                )
            ),
            ADD CONSTRAINT report_assistant_exact_page_count_check CHECK (
                exact_page_count IS NULL OR exact_page_count BETWEEN 1 AND 20
            ),
            ADD CONSTRAINT report_assistant_verified_page_count_check CHECK (
                verified_page_count IS NULL OR verified_page_count >= 1
            ),
            ADD CONSTRAINT report_assistant_page_renderer_fingerprint_check CHECK (
                page_renderer_fingerprint IS NULL
                OR (
                    length(page_renderer_fingerprint) = 64
                    AND page_renderer_fingerprint = lower(page_renderer_fingerprint)
                    AND translate(
                        page_renderer_fingerprint, '0123456789abcdef', ''
                    ) = ''
                )
            ),
            ADD CONSTRAINT report_assistant_page_renderer_receipt_check CHECK (
                (verified_page_count IS NULL) = (page_renderer_fingerprint IS NULL)
            ),
            ADD CONSTRAINT report_assistant_page_constraint_source_check CHECK (
                exact_page_count IS NULL OR source_instruction IS NOT NULL
            ),
            ADD CONSTRAINT report_assistant_page_verification_phase_check CHECK (
                verified_page_count IS NULL
                OR (
                    report_patch_json IS NOT NULL
                    AND phase IN (
                        'waiting_patch_approval', 'saving_revision',
                        'completed', 'failed', 'cancelled'
                    )
                )
            ),
            ADD CONSTRAINT report_assistant_approved_page_constraint_check CHECK (
                exact_page_count IS NULL
                OR phase NOT IN ('saving_revision', 'completed')
                OR verified_page_count = exact_page_count
            );
        """
    )
    op.execute(
        """
        WITH active_chain_anchor AS (
            SELECT request.assistant_request_id,
                   CASE
                       WHEN request.phase = 'ready' THEN latest.turn_number
                       ELSE latest_new_data.turn_number
                   END AS anchor_turn_number
            FROM report_v1.report_assistant_requests request
            LEFT JOIN LATERAL (
                SELECT turn.turn_number, turn.change_kind
                FROM report_v1.report_assistant_turns turn
                WHERE turn.assistant_request_id = request.assistant_request_id
                ORDER BY turn.turn_number DESC
                LIMIT 1
            ) latest ON TRUE
            LEFT JOIN LATERAL (
                SELECT turn.turn_number
                FROM report_v1.report_assistant_turns turn
                WHERE turn.assistant_request_id = request.assistant_request_id
                  AND turn.change_kind = 'new_data'
                ORDER BY turn.turn_number DESC
                LIMIT 1
            ) latest_new_data ON TRUE
            WHERE request.source_instruction IS NULL
              AND (
                  (request.phase = 'ready' AND latest.change_kind = 'clarification')
                  OR (
                      request.phase IN (
                          'waiting_patch_approval', 'waiting_approval',
                          'running_data_agent', 'waiting_artifact', 'saving_revision'
                      )
                      AND request.analysis_plan_json IS NOT NULL
                  )
              )
        ), chain_bounds AS (
            SELECT anchor.*,
                   (
                       SELECT max(boundary.turn_number)
                       FROM report_v1.report_assistant_turns boundary
                       WHERE boundary.assistant_request_id = anchor.assistant_request_id
                         AND boundary.turn_number < anchor.anchor_turn_number
                         AND boundary.change_kind <> 'clarification'
                   ) AS boundary_turn_number,
                   (
                       SELECT min(retained.turn_number)
                       FROM report_v1.report_assistant_turns retained
                       WHERE retained.assistant_request_id = anchor.assistant_request_id
                   ) AS first_retained_turn_number
            FROM active_chain_anchor anchor
        ), chain_source AS (
            SELECT bounds.assistant_request_id,
                   CASE
                       WHEN bounds.boundary_turn_number IS NOT NULL
                            OR bounds.first_retained_turn_number = 1
                       THEN (
                           SELECT btrim(turn.user_instruction)
                           FROM report_v1.report_assistant_turns turn
                           WHERE turn.assistant_request_id = bounds.assistant_request_id
                             AND turn.turn_number <= bounds.anchor_turn_number
                             AND turn.turn_number > COALESCE(bounds.boundary_turn_number, 0)
                           ORDER BY turn.turn_number ASC
                           LIMIT 1
                       )
                       ELSE NULL
                   END AS source_instruction
            FROM chain_bounds bounds
            WHERE bounds.anchor_turn_number IS NOT NULL
        )
        UPDATE report_v1.report_assistant_requests request
        SET source_instruction = chain.source_instruction
        FROM chain_source chain
        WHERE request.assistant_request_id = chain.assistant_request_id
          AND chain.source_instruction IS NOT NULL;

        UPDATE report_v1.report_assistant_requests request
        SET phase = 'failed', status = 'failed',
            error_code = 'ASSISTANT_EXECUTION_INTERRUPTED', completed_at = now()
        WHERE request.source_instruction IS NULL
          AND (
              (
                  request.phase IN (
                      'waiting_approval', 'running_data_agent', 'waiting_artifact'
                  )
                  AND request.analysis_plan_json IS NOT NULL
              )
              OR (
                  request.phase = 'ready'
                  AND (
                      SELECT retained.change_kind
                      FROM report_v1.report_assistant_turns retained
                      WHERE retained.assistant_request_id = request.assistant_request_id
                      ORDER BY retained.turn_number DESC
                      LIMIT 1
                  ) = 'clarification'
              )
          );

        UPDATE report_v1.report_assistant_requests
        SET phase = 'failed', status = 'failed',
            error_code = 'ASSISTANT_EXECUTION_INTERRUPTED', completed_at = now()
        WHERE status = 'running'
          AND phase IN ('waiting_patch_approval', 'saving_revision');
        """
    )
    op.execute(
        """
        ALTER TABLE report_v1.report_assistant_requests
            ADD CONSTRAINT report_assistant_waiting_patch_page_receipt_check CHECK (
                phase <> 'waiting_patch_approval' OR verified_page_count IS NOT NULL
            );
        """
    )


def downgrade() -> None:
    """새 페이지 제약 receipt가 없을 때만 이전 계약으로 되돌린다."""

    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM report_v1.report_assistant_requests
                WHERE source_instruction IS NOT NULL
                   OR exact_page_count IS NOT NULL
                   OR verified_page_count IS NOT NULL
                   OR page_renderer_fingerprint IS NOT NULL
            ) THEN
                RAISE EXCEPTION 'Report Assistant page constraint receipts must be preserved';
            END IF;
        END $$;
        ALTER TABLE report_v1.report_assistant_requests
            DROP CONSTRAINT report_assistant_waiting_patch_page_receipt_check,
            DROP CONSTRAINT report_assistant_approved_page_constraint_check,
            DROP CONSTRAINT report_assistant_page_verification_phase_check,
            DROP CONSTRAINT report_assistant_page_constraint_source_check,
            DROP CONSTRAINT report_assistant_page_renderer_receipt_check,
            DROP CONSTRAINT report_assistant_page_renderer_fingerprint_check,
            DROP CONSTRAINT report_assistant_verified_page_count_check,
            DROP CONSTRAINT report_assistant_exact_page_count_check,
            DROP CONSTRAINT report_assistant_source_instruction_check,
            DROP COLUMN verified_page_count,
            DROP COLUMN page_renderer_fingerprint,
            DROP COLUMN exact_page_count,
            DROP COLUMN source_instruction;
        """
    )
