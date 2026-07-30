"""Create the single Alembic chain without duplicating Compose-owned application DDL."""

from alembic import op


revision = "20260729_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Alembic creates alembic_version. Domain tables remain Compose-owned until their ownership transfer is approved.
    op.execute("SELECT 1")


def downgrade() -> None:
    pass
