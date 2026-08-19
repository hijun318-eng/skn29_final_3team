import unittest

from sqlglot import exp, parse_one

from src.ai.schema import validate_payload
from src.ai.sql_policy import validate_sql
from tests.ai.test_contracts import arbitrary_node2_request, qualified_field
from tests.support.fakes import ContractFakeModelAdapter


def independent_candidate(namespace):
    fact = f"{namespace}_catalog.semantic.fact_observations"
    dimension = f"{namespace}_catalog.semantic.dim_entities"
    sql = f"""
        SELECT d.category_code AS category,
               SUM(f.amount) AS resolved_measure
        FROM {fact} AS f
        LEFT JOIN {dimension} AS d
          ON f.entity_id = d.entity_id
         AND d.valid_from <= f.observed_at
         AND (d.valid_to IS NULL OR f.observed_at < d.valid_to)
        WHERE f.observed_at >= CAST(:{namespace}_window_start AS TIMESTAMP WITH TIME ZONE)
          AND f.observed_at < CAST(:{namespace}_window_end AS TIMESTAMP WITH TIME ZONE)
          AND f.status_code = :{namespace}_status
        GROUP BY d.category_code
        ORDER BY resolved_measure DESC
        LIMIT 500
    """
    return {
        "sql": sql,
        "used_assets": [fact, dimension],
        "used_columns": [
            qualified_field(fact, "entity_id"),
            qualified_field(fact, "observed_at"),
            qualified_field(fact, "amount"),
            qualified_field(fact, "status_code"),
            qualified_field(dimension, "entity_id"),
            qualified_field(dimension, "category_code"),
            qualified_field(dimension, "valid_from"),
            qualified_field(dimension, "valid_to"),
        ],
        "used_joins": [f"{namespace}_fact_to_dimension"],
        "used_metrics": [f"{namespace}_measure"],
    }


class Node2CandidateTests(unittest.TestCase):
    def test_independent_isomorphic_candidates_have_the_same_policy_shape(self):
        signatures = []
        for namespace in ("quartz", "ember"):
            with self.subTest(namespace=namespace):
                request = arbitrary_node2_request(namespace)
                response = independent_candidate(namespace)
                validate_payload("node2_request", request)
                validate_payload("node2_response", response)

                checked = validate_sql(
                    response["sql"],
                    max_limit=request["query_policy"]["max_limit"],
                )

                self.assertTrue(checked.ok, checked.violations)
                self.assertEqual(tuple(response["used_assets"]), checked.physical_tables)
                self.assertCountEqual(
                    [item["name"] for item in request["parameter_contract"]["parameters"]],
                    checked.placeholders,
                )
                self.assertEqual("LEFT", checked.joins[0].kind)
                self.assertEqual(3, len(checked.joins[0].on_conjuncts))
                signatures.append(
                    (
                        len(checked.physical_tables),
                        len(checked.columns),
                        len(checked.joins),
                        len(checked.placeholders),
                        checked.functions,
                    )
                )
        self.assertEqual(signatures[0], signatures[1])

    def test_candidate_ast_mutation_is_rejected_independently_of_the_stub(self):
        candidate = independent_candidate("quartz")
        tree = parse_one(candidate["sql"], read="trino")
        tree.set("expressions", [exp.Star()])

        checked = validate_sql(tree.sql(dialect="trino"), max_limit=500)

        self.assertFalse(checked.ok)
        self.assertIn("STAR_FORBIDDEN", {item.code for item in checked.violations})

    def test_programmed_response_is_not_derived_from_the_request_context(self):
        injected = independent_candidate("quartz")
        unrelated_request = arbitrary_node2_request("ember")
        adapter = ContractFakeModelAdapter(injected)

        response = adapter.generate("node2", unrelated_request)

        self.assertEqual(injected, response)
        self.assertEqual(0, adapter.remaining)
        self.assertEqual("node2", adapter.calls[0]["node"])


if __name__ == "__main__":
    unittest.main()
