"""Runtime과 분리된 catalog candidate publisher 최소 권한을 부여한다."""

import os
import re

from alembic import op


revision = "20260825_36"
down_revision = "20260823_35"
branch_labels = None
depends_on = None


def _role(environment_name: str) -> str:
    role = os.getenv(environment_name, "")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", role):
        raise RuntimeError(f"{environment_name} is missing or invalid")
    return f'"{role}"'


def upgrade() -> None:
    """Runtime manifest write를 회수하고 publisher의 append-only 후보 게시만 허용한다."""

    runtime = _role("APP_DB_USER")
    publisher = _role("APP_CATALOG_PUBLISHER_USER")
    op.execute(
        f"REVOKE INSERT ON governance.product_release_manifests FROM {runtime}"
    )
    op.execute(f"GRANT USAGE ON SCHEMA governance TO {publisher}")
    op.execute(
        f"GRANT SELECT ON governance.alembic_version TO {publisher}"
    )
    op.execute(
        f"GRANT SELECT, INSERT ON governance.runtime_catalog_projections, "
        f"governance.product_release_manifests TO {publisher}"
    )


def downgrade() -> None:
    """Publisher 후보 권한을 회수하고 이전 runtime manifest write 계약을 복원한다."""

    runtime = _role("APP_DB_USER")
    publisher = _role("APP_CATALOG_PUBLISHER_USER")
    op.execute(
        f"REVOKE SELECT, INSERT ON governance.runtime_catalog_projections, "
        f"governance.product_release_manifests FROM {publisher}"
    )
    op.execute(
        f"REVOKE SELECT ON governance.alembic_version FROM {publisher}"
    )
    op.execute(f"REVOKE USAGE ON SCHEMA governance FROM {publisher}")
    op.execute(
        f"GRANT INSERT ON governance.product_release_manifests TO {runtime}"
    )
