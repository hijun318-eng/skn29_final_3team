from pathlib import Path
from sys import path

import pytest


BACKEND = Path(__file__).resolve().parents[2] / "app" / "backend"
path.insert(0, str(BACKEND))

from app.adapters.i2_data_platform import I2DataPlatformAdapter
from app.services.context_builder import (
    ContextAsset,
    ContextBuildRequest,
    ContextPackageBuilder,
)
from app.services.pipeline_support import PipelineSupport


def _package():
    asset = ContextAsset(
        urn="urn:allowed",
        fqn="catalog.schema.allowed",
        columns=("id", "amount"),
    )
    return ContextPackageBuilder().build(
        ContextBuildRequest(
            context_release="context-v1",
            policy_version="policy-v1",
            time_version="2026-08-12",
            entitlement_hash="hash",
            assets=(asset,),
            token_count=10,
            model_context_tokens=24_000,
        ),
        frozenset({asset.urn}),
    )


def _plan(sql: str) -> dict[str, object]:
    return {
        "sql": sql,
        "parameters": {},
        "references": [
            {
                "urn": "urn:allowed",
                "fqn": "catalog.schema.allowed",
                "columns": ["id", "amount"],
            }
        ],
    }


def test_g2_ast_allows_one_select_or_cte_and_rejects_non_query_shapes():
    package = _package()
    assert (
        PipelineSupport.g2_violation(
            _plan(
                "WITH scoped AS (SELECT a.id FROM catalog.schema.allowed AS a) "
                "SELECT id FROM scoped LIMIT 100"
            ),
            package,
        )
        is None
    )

    unsafe = (
        "SELECT id FROM catalog.schema.allowed LIMIT 1; DELETE FROM x",
        "SELECT id FROM catalog.schema.allowed UNION SELECT id FROM x LIMIT 1",
        "INSERT INTO x SELECT id FROM catalog.schema.allowed",
        "CALL system.runtime.kill_query('x')",
        "EXECUTE IMMEDIATE 'SELECT 1'",
        "SELECT query_id FROM system.runtime.queries LIMIT 1",
        "SELECT table_name FROM catalog.information_schema.tables LIMIT 1",
        "SELECT * FROM TABLE(postgresql.query(query => 'SELECT 1')) LIMIT 1",
        "WITH changed AS (DELETE FROM x RETURNING *) SELECT * FROM changed LIMIT 1",
        "SELECT '",
    )
    for sql in unsafe:
        assert PipelineSupport.g2_violation(_plan(sql), package) == "UNSAFE_SQL"


def test_g2_ast_combines_context_source_and_column_policy():
    package = _package()
    assert (
        PipelineSupport.g2_violation(
            _plan("SELECT a.secret FROM catalog.schema.allowed AS a LIMIT 10"),
            package,
        )
        == "REFERENCE_OUTSIDE_CONTEXT"
    )
    assert (
        PipelineSupport.g2_violation(
            _plan("SELECT id FROM catalog.schema.other LIMIT 10"), package
        )
        == "SQL_REFERENCE_MISMATCH"
    )


def test_trino_validate_explain_finishes_before_bound_query_execution():
    adapter = I2DataPlatformAdapter("http://trino:8080", "runtime-user")
    calls: list[tuple[str, str, object]] = []

    def transport(method, url, body):
        calls.append((method, url, body))
        if len(calls) == 1:
            return {
                "id": "validate-1",
                "stats": {"state": "RUNNING"},
                "nextUri": "http://trino:8080/v1/statement/validate-1/1",
            }
        if len(calls) == 2:
            return {"id": "validate-1", "stats": {"state": "FINISHED"}}
        return {
            "id": "query-1",
            "stats": {"state": "FINISHED"},
            "columns": [{"name": "id"}],
            "data": [[1]],
        }

    adapter._trino.transport = transport
    result = adapter.execute_query(
        "SELECT id FROM catalog.schema.allowed WHERE id = :required_filter_1 LIMIT 1",
        {"required_filter_1": {"value_type": "number", "value": 1}},
        "g2-token",
    )

    bound = "SELECT id FROM catalog.schema.allowed WHERE id = 1 LIMIT 1"
    assert [(method, body) for method, _url, body in calls] == [
        ("POST", f"EXPLAIN (TYPE VALIDATE) {bound}"),
        ("GET", None),
        ("POST", bound),
    ]
    assert result["rows"] == [{"id": 1}]


def test_trino_validate_explain_failure_blocks_query_execution():
    adapter = I2DataPlatformAdapter("http://trino:8080", "runtime-user")
    calls = []

    def transport(method, url, body):
        calls.append((method, url, body))
        return {
            "id": "validate-failed",
            "stats": {"state": "FAILED"},
            "error": {"message": "column cannot be resolved"},
        }

    adapter._trino.transport = transport

    with pytest.raises(ValueError, match="column cannot be resolved"):
        adapter.execute_query(
            "SELECT missing FROM catalog.schema.allowed LIMIT 1",
            {},
            "g2-token",
        )

    assert len(calls) == 1
    assert str(calls[0][2]).startswith("EXPLAIN (TYPE VALIDATE) ")
