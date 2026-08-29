"""이미 배포된 Seung Report Assistant head를 통합 chain에서 인식한다.

이 revision의 DDL은 Seung DB에 이미 적용되어 있다. 현행 Daesung chain에도
동등한 DDL이 20260826_37~44, 20260828_50~54로 존재하므로 여기서 다시
실행하지 않는다. 다음 reconciliation revision이 실제 schema fingerprint를
검증하고 Daesung 전용 변경만 보충한다.
"""


revision = "20260827_41"
down_revision = "20260828_55"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """동등한 Report Assistant DDL을 재실행하지 않는다."""


def downgrade() -> None:
    """호환 표식에는 되돌릴 DDL이 없다."""
