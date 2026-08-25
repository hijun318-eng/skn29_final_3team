"""점진적 SUMMARY·KPI·FULL 표현 타입을 ViewSpec 저장 계약에 추가한다."""

from alembic import op


revision = "20260826_37"
down_revision = "20260825_36"
branch_labels = None
depends_on = None


_CURRENT_TYPES = (
    "'SUMMARY','KPI','TABLE','BAR','LINE','PIE','AREA','SCATTER','FULL'"
)
_PREVIOUS_TYPES = "'TABLE','BAR','LINE','PIE','AREA','SCATTER','KPI'"


def _replace_view_type_constraint(allowed_types: str) -> None:
    """고정 이름의 CHECK constraint를 지정한 allowlist로 원자적으로 교체한다."""

    op.execute(
        "ALTER TABLE artifact.view_specs "
        "DROP CONSTRAINT IF EXISTS view_specs_view_type_check"
    )
    op.execute(
        "ALTER TABLE artifact.view_specs "
        "ADD CONSTRAINT view_specs_view_type_check "
        f"CHECK (view_type IN ({allowed_types}))"
    )


def upgrade() -> None:
    """새 표현 타입을 허용하고 downgrade 시 보존한 typed spec을 다시 복원한다."""

    _replace_view_type_constraint(_CURRENT_TYPES)
    op.execute(
        """
        UPDATE artifact.view_specs
        SET view_type = spec_json ->> 'presentation_type'
        WHERE view_type = 'TABLE'
          AND spec_json ->> 'presentation_type' IN ('SUMMARY', 'FULL')
        """
    )


def downgrade() -> None:
    """신규 타입을 TABLE 호환값으로 낮추되 원래 타입은 spec_json에 보존한다."""

    op.execute(
        """
        UPDATE artifact.view_specs
        SET spec_json = jsonb_set(
                spec_json,
                '{presentation_type}',
                to_jsonb(view_type),
                true
            ),
            view_type = 'TABLE'
        WHERE view_type IN ('SUMMARY', 'FULL')
        """
    )
    _replace_view_type_constraint(_PREVIOUS_TYPES)
