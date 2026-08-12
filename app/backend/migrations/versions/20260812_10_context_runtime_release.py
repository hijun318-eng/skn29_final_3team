"""Register the initial approved time policy and published P0 release."""

from alembic import op


revision = "20260812_10"
down_revision = "20260812_09"
branch_labels = None
depends_on = None

RECORD_ID = "00000000-0000-0000-0000-000000000101"
RELEASE_ID = "00000000-0000-0000-0000-000000000201"
ACTOR_ID = "00000000-0000-0000-0000-000000000301"
CHECKSUM = "8028b1ddd9111aa9f0270f937df327cccfb625fdcba3bbd8a1c7234543b375d4"
RELEASE_HASH = "f97f63a40740c15c6b7e3b1f05679fa6a2d8863b8b39cdc9c97f293ea5e9ddc3"


def upgrade() -> None:
    op.execute(
        f"""
        INSERT INTO context.context_records
            (context_record_id, record_type, record_key, version_no,
             payload_json, status, owner_role, approved_by, approved_at,
             valid_from, checksum, idempotency_key)
        VALUES
            ('{RECORD_ID}', 'TIME_POLICY', 'kr-business-calendar', 1,
             '{{"timezone":"Asia/Seoul","calendar_id":"gregorian-kr","period_boundary":"[start,end)","relative_period_as_of":"request_start"}}'::jsonb,
             'APPROVED', 'data_admin', '{ACTOR_ID}', now(),
             '2020-01-01T00:00:00+09:00', '{CHECKSUM}',
             'seed:time-policy:kr-business-calendar:v1')
        ON CONFLICT (context_record_id) DO NOTHING
        """
    )
    op.execute(
        f"""
        INSERT INTO context.context_releases
            (context_release_id, release_key, version_no,
             included_record_refs_json, status, release_hash,
             published_by, published_at, idempotency_key)
        VALUES
            ('{RELEASE_ID}', 'answervice-p0', 1,
             '[{{"context_record_id":"{RECORD_ID}","checksum":"{CHECKSUM}"}}]'::jsonb,
             'PUBLISHED', '{RELEASE_HASH}', '{ACTOR_ID}', now(),
             'seed:context-release:answervice-p0:v1')
        ON CONFLICT (context_release_id) DO NOTHING
        """
    )


def downgrade() -> None:
    for table in ("context_releases", "context_records"):
        op.execute(f"ALTER TABLE context.{table} DISABLE TRIGGER USER")
    op.execute(
        f"DELETE FROM context.context_releases WHERE context_release_id = '{RELEASE_ID}'"
    )
    op.execute(
        f"DELETE FROM context.context_records WHERE context_record_id = '{RECORD_ID}'"
    )
    for table in ("context_records", "context_releases"):
        op.execute(f"ALTER TABLE context.{table} ENABLE TRIGGER USER")
