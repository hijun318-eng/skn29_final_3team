"""RAG는 전체 운영 역할에 공개하고 ML은 승인 역할로 제한한다.

Revision ID: 20260826_47
Revises: 20260826_46
"""

from __future__ import annotations

from alembic import op


revision = "20260826_47"
down_revision = "20260826_46"
branch_labels = None
depends_on = None


ALL_ROLES = '["analyst","report_admin","data_admin","platform_admin"]'
ML_ALLOWED_ROLES = '["analyst","platform_admin"]'
PREVIOUS_ROLES = '["analyst","platform_admin"]'


def upgrade() -> None:
    """RAG와 ML Tool의 역할 목록을 각 공개 정책에 맞게 갱신한다."""

    op.execute(
        "UPDATE tooling.tool_registry "
        f"SET required_roles_json = '{ALL_ROLES}'::jsonb "
        "WHERE tool_code = 'rag.answer'"
    )
    op.execute(
        "UPDATE tooling.tool_registry "
        f"SET required_roles_json = '{ML_ALLOWED_ROLES}'::jsonb "
        "WHERE tool_code = 'ml.predict'"
    )


def downgrade() -> None:
    """두 Tool의 역할 목록을 이전 analyst·platform_admin 정책으로 복원한다."""

    op.execute(
        "UPDATE tooling.tool_registry "
        f"SET required_roles_json = '{PREVIOUS_ROLES}'::jsonb "
        "WHERE tool_code IN ('rag.answer', 'ml.predict')"
    )
