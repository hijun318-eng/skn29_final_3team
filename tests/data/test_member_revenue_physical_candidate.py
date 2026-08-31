"""회원 매출 물리화 후보가 기존 계약을 보존하며 원천 스캔을 분리하는지 검증한다."""

from __future__ import annotations

import sys
from pathlib import Path

import sqlglot
from sqlglot import exp


ROOT = Path(__file__).resolve().parents[2]
DATAHUB = ROOT / "infrastructure" / "database" / "datahub"
if str(DATAHUB) not in sys.path:
    sys.path.insert(0, str(DATAHUB))

from runtime_governance_draft import build_draft  # noqa: E402


SQL_DIRECTORY = (
    ROOT
    / "infrastructure"
    / "database"
    / "serving_candidates"
    / "walkerhill_member_revenue_physical_v1"
)
RELEASE_ID = "walkerhill-member-revenue-physical-v1.20260830.1"
TARGET_SCHEMA = "serving.analytics_v4_3"
ROOM_ASSET = f"{TARGET_SCHEMA}.member_room_revenue_daily"
FNB_ASSET = f"{TARGET_SCHEMA}.member_fnb_revenue_daily"
COMBINED_ASSET = f"{TARGET_SCHEMA}.member_revenue_daily"


def _statements(filename: str) -> list[exp.Expression]:
    return sqlglot.parse(
        (SQL_DIRECTORY / filename).read_text(encoding="utf-8"),
        read="trino",
    )


def _creates() -> dict[str, exp.Create]:
    return {
        statement.this.sql(dialect="trino"): statement
        for statement in _statements("10_member_revenue_materialized_views.sql")
        if isinstance(statement, exp.Create)
    }


def _is_materialized(statement: exp.Create) -> bool:
    properties = statement.args.get("properties")
    return isinstance(properties, exp.Properties) and any(
        isinstance(item, exp.MaterializedProperty)
        for item in properties.expressions
    )


def test_candidate_is_inactive_and_preserves_the_public_view_contract() -> None:
    for path in SQL_DIRECTORY.glob("*.sql"):
        assert "execution_default=NOT_RUN" in path.read_text(encoding="utf-8")

    evidence = build_draft(SQL_DIRECTORY, TARGET_SCHEMA, RELEASE_ID)
    views = {view.fqn: view for view in evidence.views}

    assert set(views) == {ROOM_ASSET, FNB_ASSET, COMBINED_ASSET}
    assert {field.name for field in views[COMBINED_ASSET].fields} == {
        "business_date",
        "hotel_code",
        "tier_code",
        "tier_name",
        "room_revenue_krw",
        "fnb_revenue_krw",
    }
    assert not {
        "guest_id",
        "member_no",
        "pos_customer_ref",
    } & {field.name for field in views[COMBINED_ASSET].fields}

    active_capability = (
        ROOT / "app" / "backend" / "contracts" / "analysis_capability.product.v1.json"
    ).read_text(encoding="utf-8")
    assert COMBINED_ASSET in active_capability
    assert ROOM_ASSET not in active_capability
    assert FNB_ASSET not in active_capability


def test_expensive_source_domains_are_isolated_behind_materialized_views() -> None:
    evidence = build_draft(SQL_DIRECTORY, TARGET_SCHEMA, RELEASE_ID)
    views = {view.fqn: view for view in evidence.views}

    assert set(views[ROOM_ASSET].source_relations) == {
        "pms.walkerhill_v4_3.pms_stay_nights",
        "pms.walkerhill_v4_3.pms_stays",
        "crm.walkerhill_v4_3.crm_customer_map",
        "crm.walkerhill_v4_3.crm_member_grade_history",
        "crm.walkerhill_v4_3.crm_membership_tiers",
    }
    assert set(views[FNB_ASSET].source_relations) == {
        "pos.walkerhill_v4_3.pos_orders",
        "pos.walkerhill_v4_3.pos_outlets",
        "crm.walkerhill_v4_3.crm_customer_map",
        "crm.walkerhill_v4_3.crm_member_grade_history",
        "crm.walkerhill_v4_3.crm_membership_tiers",
    }
    assert set(views[COMBINED_ASSET].source_relations) == {ROOM_ASSET, FNB_ASSET}


def test_only_the_compact_public_view_keeps_the_full_outer_join() -> None:
    creates = _creates()
    assert set(creates) == {ROOM_ASSET, FNB_ASSET, COMBINED_ASSET}
    assert _is_materialized(creates[ROOM_ASSET])
    assert _is_materialized(creates[FNB_ASSET])
    assert not _is_materialized(creates[COMBINED_ASSET])

    room_full = [
        join
        for join in creates[ROOM_ASSET].expression.find_all(exp.Join)
        if join.args.get("side") == "FULL"
    ]
    fnb_full = [
        join
        for join in creates[FNB_ASSET].expression.find_all(exp.Join)
        if join.args.get("side") == "FULL"
    ]
    combined_full = [
        join
        for join in creates[COMBINED_ASSET].expression.find_all(exp.Join)
        if join.args.get("side") == "FULL" and join.args.get("kind") == "OUTER"
    ]
    assert room_full == []
    assert fnb_full == []
    assert len(combined_full) == 1


def test_refreshes_are_independent_and_validation_is_read_only() -> None:
    refreshes = [
        statement
        for statement in _statements("20_refresh_member_revenue_materialized_views.sql")
        if isinstance(statement, exp.Refresh)
    ]
    assert [statement.this.sql(dialect="trino") for statement in refreshes] == [
        ROOM_ASSET,
        FNB_ASSET,
    ]
    assert all(statement.args.get("kind") == "MATERIALIZED VIEW" for statement in refreshes)

    validation = _statements("30_member_revenue_validation.sql")
    assert validation
    assert all(isinstance(statement, (exp.Select, exp.Command)) for statement in validation)
    validation_sql = "\n".join(statement.sql(dialect="trino") for statement in validation)
    assert "member_room_revenue_daily_not_empty" in validation_sql
    assert "member_fnb_revenue_daily_not_empty" in validation_sql
    commands = [statement for statement in validation if isinstance(statement, exp.Command)]
    assert len(commands) == 2
    assert all(statement.sql(dialect="trino").startswith("EXPLAIN") for statement in commands)
