from __future__ import annotations

import unittest

from sqlglot import exp, parse_one

from src.ai.sql_policy import (
    SqlPolicyError,
    canonicalize_table_fqn,
    validate_sql,
)


class SqlPolicyTests(unittest.TestCase):
    def test_isomorphic_schemas_produce_equivalent_ast_evidence(self) -> None:
        schemas = (
            ("orbit.ops.event_fact", "quartz.mart.value_dim"),
            ("cobalt.raw.signal_log", "ember.curated.factor_map"),
        )
        for fact, dimension in schemas:
            with self.subTest(fact=fact):
                sql = f"""
                    WITH scoped AS (
                        SELECT f.entity_key, f.occurred_on
                        FROM {fact} AS f
                        WHERE f.occurred_on >= CAST(:period_start AS DATE)
                    )
                    SELECT s.entity_key AS bucket, SUM(d.measure) AS total
                    FROM scoped AS s
                    JOIN {dimension} AS d
                      ON s.entity_key = d.entity_key AND d.active = :active
                    WHERE d.category = :category
                    GROUP BY s.entity_key
                    ORDER BY total DESC
                    LIMIT 250
                """

                result = validate_sql(sql)

                self.assertTrue(result.ok, result.violations)
                self.assertEqual((fact, dimension), result.physical_tables)
                self.assertNotIn("scoped", result.physical_tables)
                self.assertEqual(("bucket", "total"), result.projection_aliases)
                self.assertCountEqual(("SUM", "CAST"), result.functions)
                self.assertCountEqual(
                    ("period_start", "active", "category"), result.placeholders
                )
                self.assertEqual(250, result.limit)
                self.assertEqual(1, len(result.joins))
                self.assertEqual(2, len(result.joins[0].on_conjuncts))
                self.assertTrue(any(item.source_table == fact for item in result.columns))
                self.assertTrue(
                    any(item.source_table == dimension for item in result.columns)
                )

    def test_ast_mutations_are_rejected_without_sql_pattern_matching(self) -> None:
        base = parse_one(
            "SELECT a.entity_key FROM orbit.ops.event_fact AS a LIMIT 10",
            read="trino",
        )
        mutations = {}

        star = base.copy()
        star.set("expressions", [exp.Star()])
        mutations["STAR_FORBIDDEN"] = star.sql(dialect="trino")

        computed_limit = base.copy()
        computed_limit.set(
            "limit", exp.Limit(expression=exp.Placeholder(this="row_count"))
        )
        mutations["LITERAL_LIMIT_REQUIRED"] = computed_limit.sql(dialect="trino")

        oversized = base.copy()
        oversized.args["limit"].set("expression", exp.Literal.number(1001))
        mutations["LIMIT_OUT_OF_RANGE"] = oversized.sql(dialect="trino")

        commented = base.copy()
        commented.add_comments(["policy bypass"])
        mutations["COMMENTS_FORBIDDEN"] = commented.sql(dialect="trino")

        union = base.copy().union(base.copy())
        mutations["FORBIDDEN_STATEMENT"] = union.sql(dialect="trino")

        for expected_code, sql in mutations.items():
            with self.subTest(expected_code=expected_code):
                result = validate_sql(sql)
                self.assertFalse(result.ok)
                self.assertIn(expected_code, {item.code for item in result.violations})

    def test_only_one_read_only_query_is_accepted(self) -> None:
        cases = {
            "DELETE FROM orbit.ops.event_fact": "READ_ONLY_QUERY_REQUIRED",
            "CREATE TABLE x AS SELECT 1": "READ_ONLY_QUERY_REQUIRED",
            "SHOW TABLES": "READ_ONLY_QUERY_REQUIRED",
            "SELECT 1 LIMIT 1; SELECT 2 LIMIT 1": "SINGLE_STATEMENT_REQUIRED",
        }
        for sql, expected_code in cases.items():
            with self.subTest(sql=sql):
                result = validate_sql(sql)
                codes = {item.code for item in result.violations}
                self.assertIn(expected_code, codes)
                self.assertFalse(result.ok)

    def test_top_level_limit_must_be_present_positive_and_literal(self) -> None:
        cases = {
            "SELECT 1": "LIMIT_REQUIRED",
            "SELECT 1 LIMIT :row_count": "LITERAL_LIMIT_REQUIRED",
            "SELECT 1 LIMIT 0": "LIMIT_OUT_OF_RANGE",
            "SELECT 1 LIMIT 1001": "LIMIT_OUT_OF_RANGE",
        }
        for sql, expected_code in cases.items():
            with self.subTest(sql=sql):
                result = validate_sql(sql)
                self.assertIn(expected_code, {item.code for item in result.violations})

    def test_positional_placeholders_are_rejected(self) -> None:
        result = validate_sql("SELECT ? AS value LIMIT 1")

        self.assertIn(
            "NAMED_PLACEHOLDER_REQUIRED",
            {item.code for item in result.violations},
        )

    def test_parse_errors_are_structured_and_raise_on_demand(self) -> None:
        result = validate_sql("SELECT (")

        self.assertFalse(result.ok)
        self.assertEqual("SQL_PARSE_ERROR", result.violations[0].code)
        with self.assertRaises(SqlPolicyError) as raised:
            result.raise_for_violations()
        self.assertEqual(result.violations, raised.exception.violations)

    def test_quoted_identifiers_preserve_case_sensitive_identity(self) -> None:
        result = validate_sql(
            'SELECT "E"."Value" FROM "Catalog"."Schema"."Events" AS "E" LIMIT 1'
        )

        self.assertTrue(result.ok, result.violations)
        self.assertEqual(
            ('"Catalog"."Schema"."Events"',),
            result.physical_tables,
        )
        self.assertEqual('"Value"', result.columns[0].name)
        self.assertEqual('"E"', result.columns[0].qualifier)
        self.assertEqual(result.physical_tables[0], result.columns[0].source_table)
        self.assertEqual(
            '"Catalog"."Schema"."Events"',
            canonicalize_table_fqn('"Catalog"."Schema"."Events"'),
        )
        self.assertEqual(
            "catalog.schema.events",
            canonicalize_table_fqn("Catalog.Schema.Events"),
        )


if __name__ == "__main__":
    unittest.main()
