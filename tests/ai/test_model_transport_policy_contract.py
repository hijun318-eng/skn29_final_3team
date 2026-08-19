"""프로그래밍 가능한 모델 transport와 독립 SQL 정책의 조합을 검증한다.

이 테스트는 외부 모델·DataHub·Trino를 호출하지 않는 contract/unit 증거다. 따라서
응답을 생성기의 정답으로 재사용하지 않고, 독립적으로 작성한 응답을 서버 AST 정책이
다시 검증하는 경계만 확인한다.
"""

from src.ai.schema import validate_payload
from src.ai.sql_policy import validate_sql
from tests.ai.test_contracts import arbitrary_node2_request
from tests.ai.test_node2 import independent_candidate
from tests.support.fakes import ContractFakeModelAdapter


def test_programmable_transport_and_ast_policy_compose_without_a_local_generator():
    """주입 응답은 transport 계약과 서버 AST 정책을 각각 통과해야 한다."""

    request = arbitrary_node2_request("cinder")
    response = independent_candidate("cinder")
    adapter = ContractFakeModelAdapter([response])

    observed = adapter.generate("node2", request)
    checked = validate_sql(
        observed["sql"], max_limit=request["query_policy"]["max_limit"]
    )

    assert checked.ok
    assert tuple(observed["used_assets"]) == checked.physical_tables
    assert adapter.remaining == 0


def test_repair_transport_only_validates_the_injected_contract():
    """repair double은 답을 합성하지 않고 주입된 응답의 schema만 검증한다."""

    request = arbitrary_node2_request("cinder")
    repair_request = {
        "trace_id": "trace-arbitrary",
        "attempt": 1,
        "rejected_sql": "SELECT missing_name LIMIT 1",
        **{
            key: request[key]
            for key in (
                "normalized_question",
                "resolved_request",
                "schema_context",
                "metric_rules",
                "join_graph",
                "time_rules",
                "parameter_contract",
                "query_policy",
            )
        },
        "normalized_error_code": "UNKNOWN_COLUMN",
        "repair_scope": ["column"],
    }
    response = {"corrected_sql": independent_candidate("cinder")["sql"]}
    validate_payload("node2_repair_request", repair_request)
    adapter = ContractFakeModelAdapter(response)

    observed = adapter.generate("node2_repair", repair_request)

    assert observed == response
