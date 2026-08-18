from __future__ import annotations

import math

import pytest
from sqlglot import exp, parse_one

from src.ai.sql_binding import (
    SqlBindingError,
    SqlBindingErrorCode,
    TypedSqlParameter,
    bind_sql_parameters,
)


def test_binds_typed_values_without_mutating_the_validated_tree() -> None:
    tree = parse_one(
        """
        SELECT :label AS label, :active AS active, :amount AS amount
        FROM analytics.events
        WHERE event_date >= CAST(:start AS DATE)
          AND occurred_at < from_iso8601_timestamp(:end)
        """,
        read="trino",
    )
    original = tree.sql(dialect="trino")

    bound = bind_sql_parameters(
        tree,
        {
            "label": {"value_type": "string", "value": "O'Brien"},
            "active": TypedSqlParameter("boolean", True),
            "amount": {"value_type": "number", "value": 12.5},
            "start": {"value_type": "date", "value": "2026-08-01"},
            "end": {
                "value_type": "timestamp",
                "value": "2026-09-01T00:00:00+09:00",
            },
        },
    )

    assert tree.sql(dialect="trino") == original
    assert "'O''Brien'" in bound
    assert "TRUE" in bound
    assert "12.5" in bound
    assert "CAST('2026-08-01' AS DATE)" in bound
    assert "FROM_ISO8601_TIMESTAMP('2026-09-01T00:00:00+09:00')" in bound
    assert list(parse_one(bound, read="trino").find_all(exp.Placeholder)) == []


@pytest.mark.parametrize(
    ("parameters", "missing", "extra"),
    [
        ({}, "['value']", "[]"),
        (
            {
                "value": {"value_type": "number", "value": 1},
                "other": {"value_type": "number", "value": 2},
            },
            "[]",
            "['other']",
        ),
    ],
)
def test_requires_an_exact_parameter_set(parameters, missing, extra) -> None:
    tree = parse_one("SELECT :value", read="trino")

    with pytest.raises(SqlBindingError) as raised:
        bind_sql_parameters(tree, parameters)

    assert raised.value.code is SqlBindingErrorCode.PARAMETER_SET_MISMATCH
    assert f"missing={missing}" in str(raised.value)
    assert f"extra={extra}" in str(raised.value)


def test_string_value_cannot_become_sql_syntax() -> None:
    tree = parse_one("SELECT :value AS value", read="trino")

    bound = bind_sql_parameters(
        tree,
        {
            "value": {
                "value_type": "string",
                "value": "x' FROM secret.admin --",
            }
        },
    )

    reparsed = parse_one(bound, read="trino")
    assert list(reparsed.find_all(exp.Table)) == []
    assert "'x'' FROM secret.admin --'" in bound


@pytest.mark.parametrize(
    ("sql", "parameter"),
    [
        ("SELECT :value", {"value_type": "number", "value": True}),
        ("SELECT :value", {"value_type": "number", "value": math.inf}),
        ("SELECT CAST(:value AS DATE)", {"value_type": "date", "value": "08/01/2026"}),
        (
            "SELECT from_iso8601_timestamp(:value)",
            {"value_type": "timestamp", "value": "2026-08-01T00:00:00"},
        ),
        ("SELECT :value", {"value_type": "uuid", "value": "abc"}),
    ],
)
def test_rejects_invalid_typed_values(sql, parameter) -> None:
    with pytest.raises(SqlBindingError) as raised:
        bind_sql_parameters(parse_one(sql, read="trino"), {"value": parameter})

    assert raised.value.code is SqlBindingErrorCode.INVALID_VALUE


@pytest.mark.parametrize(
    ("sql", "parameter"),
    [
        ("SELECT :value", {"value_type": "date", "value": "2026-08-01"}),
        (
            "SELECT :value",
            {
                "value_type": "timestamp",
                "value": "2026-08-01T00:00:00+09:00",
            },
        ),
    ],
)
def test_date_and_timestamp_require_explicit_type_context(sql, parameter) -> None:
    with pytest.raises(SqlBindingError) as raised:
        bind_sql_parameters(parse_one(sql, read="trino"), {"value": parameter})

    assert raised.value.code is SqlBindingErrorCode.INVALID_TYPE_CONTEXT


def test_text_that_looks_like_a_placeholder_is_not_bindable() -> None:
    tree = parse_one("SELECT ':value' AS text", read="trino")

    with pytest.raises(SqlBindingError) as raised:
        bind_sql_parameters(
            tree,
            {"value": {"value_type": "string", "value": "safe"}},
        )

    assert raised.value.code is SqlBindingErrorCode.PARAMETER_SET_MISMATCH


def test_binding_shape_must_be_typed() -> None:
    tree = parse_one("SELECT :value", read="trino")

    with pytest.raises(SqlBindingError) as raised:
        bind_sql_parameters(tree, {"value": {"value": "untyped"}})

    assert raised.value.code is SqlBindingErrorCode.INVALID_BINDING


def test_positional_placeholders_cannot_be_bound() -> None:
    tree = parse_one("SELECT ?", read="trino")

    with pytest.raises(SqlBindingError) as raised:
        bind_sql_parameters(
            tree,
            {"?": {"value_type": "string", "value": "safe"}},
        )

    assert raised.value.code is SqlBindingErrorCode.INVALID_BINDING


def test_parameter_names_must_be_strings() -> None:
    tree = parse_one("SELECT :value", read="trino")

    with pytest.raises(SqlBindingError) as raised:
        bind_sql_parameters(
            tree,
            {1: {"value_type": "number", "value": 1}},  # type: ignore[dict-item]
        )

    assert raised.value.code is SqlBindingErrorCode.INVALID_BINDING
