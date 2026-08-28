import copy
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile

import pytest

from src.ai.sql_policy import validate_sql
from src.ai.training import verify_case_specs as verifier
from src.ai.training.verify_case_specs import (
    BINDING_MANIFEST_VERSION,
    PlanContractError,
    _result_hash,
    _rows_hash,
    load_binding_manifest,
    validate_g2,
    validate_output,
)
from tests.ai.test_contracts import arbitrary_node2_request, arbitrary_node2_response


def _bindings(request):
    result = {}
    timestamp_index = 0
    for index, parameter in enumerate(request["parameter_contract"]["parameters"]):
        value_type = parameter["type"]
        if value_type == "timestamp":
            value = (
                datetime(2001, 1, 1, tzinfo=timezone.utc)
                + timedelta(days=timestamp_index)
            ).isoformat()
            timestamp_index += 1
        elif value_type == "date":
            value = (datetime(2001, 1, 1) + timedelta(days=index)).date().isoformat()
        elif value_type == "boolean":
            value = False
        elif value_type == "number":
            value = index + 0.5
        else:
            value = f"arbitrary-value-{index}"
        result[parameter["name"]] = {"value_type": value_type, "value": value}
    return result


def _repair_request(namespace):
    request = arbitrary_node2_request(namespace)
    return {
        "trace_id": f"trace-{namespace}",
        "attempt": 1,
        "rejected_sql": "SELECT invalid_identifier",
        **{
            key: copy.deepcopy(request[key])
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


def test_result_hash_ignores_row_order():
    first = _result_hash('{"name":"B","value":2}\n{"name":"A","value":1}\n')
    second = _result_hash('{"value":1,"name":"A"}\n{"value":2,"name":"B"}\n')

    assert first == second
    assert first == _rows_hash([{"value": 2, "name": "B"}, {"value": 1, "name": "A"}])


def test_single_case_executor_keeps_bound_values_out_of_process_arguments(monkeypatch):
    observed = {}

    def capture(command, **kwargs):
        observed["command"] = command
        observed["input"] = kwargs["input"]
        observed["env"] = kwargs["env"]
        return object()

    monkeypatch.setattr(verifier.subprocess, "run", capture)
    verifier._execute(
        "SELECT 'server-secret' LIMIT 1",
        container="trino",
        user="worker",
        password="credential-secret",
    )

    assert "server-secret" not in " ".join(observed["command"])
    assert "credential-secret" not in " ".join(observed["command"])
    assert observed["input"] == "SELECT 'server-secret' LIMIT 1\n"
    assert observed["command"][observed["command"].index("--server") + 1] == "https://trino:8443"
    assert observed["command"][observed["command"].index("--truststore-path") + 1] == "/run/secrets/trino-ca.pem"
    assert "--password" in observed["command"]
    assert observed["env"]["TRINO_PASSWORD"] == "credential-secret"


def test_single_case_executor_rejects_missing_password_before_subprocess(monkeypatch):
    monkeypatch.setattr(
        verifier.subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("subprocess must not run")
        ),
    )

    with pytest.raises(ValueError, match="password is required"):
        verifier._execute(
            "SELECT 1",
            container="trino",
            user="worker",
            password="",
        )


def test_validate_output_binds_only_server_values_and_keeps_model_request_value_free():
    request = arbitrary_node2_request("quartz")
    original = copy.deepcopy(request)
    bindings = _bindings(request)

    plan = validate_output(
        "node2", request, arbitrary_node2_response("quartz"), bindings
    )

    assert validate_sql(plan["executable_sql"]).placeholders == ()
    assert set(validate_sql(plan["sql"]).placeholders) == set(bindings)
    assert request == original
    model_payload = json.dumps(request, sort_keys=True)
    assert all(str(item["value"]) not in model_payload for item in bindings.values())


def test_validate_output_binds_the_exact_tree_returned_by_contract_validation(monkeypatch):
    request = arbitrary_node2_request("ember")
    output = arbitrary_node2_response("ember")
    observed = {}
    real_validate = verifier.validate_model_output
    real_bind = verifier.bind_sql_parameters

    def capture_validate(*args, **kwargs):
        result = real_validate(*args, **kwargs)
        observed["validated_tree"] = result.expression
        return result

    def capture_bind(tree, parameters):
        observed["bound_tree"] = tree
        return real_bind(tree, parameters)

    monkeypatch.setattr(verifier, "validate_model_output", capture_validate)
    monkeypatch.setattr(verifier, "bind_sql_parameters", capture_bind)

    validate_output("node2", request, output, _bindings(request))

    assert observed["bound_tree"] is observed["validated_tree"]


def test_validate_output_resolves_multiple_metrics_without_unselected_rules():
    namespace = "ember"
    request = arbitrary_node2_request(namespace)
    output = arbitrary_node2_response(namespace)
    fact = f"{namespace}_catalog.semantic.fact_observations"
    second = copy.deepcopy(request["metric_rules"][0])
    second.update(
        id=f"{namespace}_count",
        source={"kind": "column", "field": {"asset_fqn": fact, "column": "observation_id"}},
        aggregation="count",
        result_field="resolved_count",
        unit="arbitrary_count",
    )
    request["metric_rules"].append(second)
    request["resolved_request"]["metric_ids"].append(second["id"])
    request["query_policy"]["allowed_functions"].append("count")
    output["sql"] = output["sql"].replace(
        "SUM(f.amount) AS resolved_measure",
        "SUM(f.amount) AS resolved_measure, COUNT(f.observation_id) AS resolved_count",
    )
    output["used_columns"].append(
        {"asset_fqn": fact, "column": "observation_id"}
    )
    output["used_metrics"].append(second["id"])

    plan = validate_output("node2", request, output, _bindings(request))

    assert validate_sql(plan["executable_sql"]).placeholders == ()


def test_validate_g2_accepts_governed_ratio_metric() -> None:
    namespace = "ratio"
    request = arbitrary_node2_request(namespace)
    fact = f"{namespace}_catalog.semantic.fact_observations"
    dimension = f"{namespace}_catalog.semantic.dim_entities"
    numerator = request["metric_rules"][0]
    denominator = copy.deepcopy(numerator)
    denominator.update(
        id=f"{namespace}_count",
        source={
            "kind": "column",
            "field": {"asset_fqn": fact, "column": "entity_id"},
        },
        aggregation="count",
        result_field="resolved_count",
        unit="row",
    )
    ratio = {
        "id": f"{namespace}_ratio",
        "source": {
            "kind": "ratio",
            "numerator_metric_id": numerator["id"],
            "denominator_metric_id": denominator["id"],
            "zero_policy": "null_on_zero_denominator",
        },
        "aggregation": "ratio",
        "result_field": "resolved_ratio",
        "unit": "ratio",
        "time_field": None,
        "dimensions": [],
        "required_filters": [],
    }
    request["metric_rules"] = [numerator, denominator, ratio]
    request["resolved_request"]["metric_ids"] = [
        numerator["id"],
        denominator["id"],
        ratio["id"],
    ]
    request["resolved_request"]["output_metric_ids"] = [ratio["id"]]
    request["query_policy"]["allowed_functions"].extend(["count", "cast", "nullif"])
    sql = (
        "SELECT d.category_code, SUM(f.amount) AS resolved_measure, "
        "COUNT(f.entity_id) AS resolved_count, "
        "CAST(SUM(f.amount) AS DOUBLE) / NULLIF(COUNT(f.entity_id), 0) "
        "AS resolved_ratio "
        f"FROM {fact} AS f LEFT JOIN {dimension} AS d "
        "ON f.entity_id = d.entity_id "
        "AND f.observed_at >= d.valid_from AND f.observed_at < d.valid_to "
        "WHERE f.observed_at >= "
        f"from_iso8601_timestamp(:{namespace}_window_start) "
        "AND f.observed_at < "
        f"from_iso8601_timestamp(:{namespace}_window_end) "
        f"AND f.status_code = :{namespace}_status "
        "GROUP BY d.category_code LIMIT 500"
    )
    case = {
        "node": "node2",
        "input": request,
        "expected_output": {"sql": sql},
    }

    plan = validate_g2(case, _bindings(request))

    assert validate_sql(plan["executable_sql"]).placeholders == ()


@pytest.mark.parametrize("mutation", ["missing", "extra", "type", "value"])
def test_binding_contract_fails_closed(mutation):
    request = arbitrary_node2_request("cinder")
    bindings = _bindings(request)
    if mutation == "missing":
        bindings.pop(next(iter(bindings)))
    elif mutation == "extra":
        bindings["undeclared"] = {"value_type": "string", "value": "x"}
    elif mutation == "type":
        first = next(iter(bindings.values()))
        first["value_type"] = "string"
    else:
        first = next(iter(bindings.values()))
        first["value"] = "not-a-timestamp"

    with pytest.raises(PlanContractError) as caught:
        validate_output(
            "node2", request, arbitrary_node2_response("cinder"), bindings
        )

    assert caught.value.code == "PARAMETER_CONTRACT_MISMATCH"


def test_missing_binding_manifest_entry_fails_closed():
    request = arbitrary_node2_request("quartz")
    with pytest.raises(PlanContractError) as caught:
        validate_output("node2", request, arbitrary_node2_response("quartz"), None)
    assert caught.value.code == "BINDINGS_REQUIRED"


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    [
        ("filter", "REQUIRED_FILTER_MISSING"),
        ("filter-disjunction", "REQUIRED_FILTER_MISSING"),
        ("time", "TIME_RULE_MISMATCH"),
        ("equality", "JOIN_GRAPH_MISMATCH"),
        ("temporal", "JOIN_GRAPH_MISMATCH"),
        ("preaggregation", "GRAIN_VIOLATION"),
    ],
)
def test_runtime_semantics_reject_incomplete_join_filter_and_time_contracts(mutation, expected_code):
    namespace = "quartz"
    request = arbitrary_node2_request(namespace)
    output = arbitrary_node2_response(namespace)
    fact = f"{namespace}_catalog.semantic.fact_observations"
    dimension = f"{namespace}_catalog.semantic.dim_entities"
    if mutation == "filter":
        output["sql"] = output["sql"].replace(
            f"f.status_code = :{namespace}_status",
            f"f.status_code <> :{namespace}_status",
        )
    elif mutation == "filter-disjunction":
        output["sql"] = output["sql"].replace(
            f"AND f.status_code = :{namespace}_status",
            f"OR f.status_code = :{namespace}_status",
        )
    elif mutation == "time":
        output["sql"] = output["sql"].replace(
            f"f.observed_at < from_iso8601_timestamp(:{namespace}_window_end)",
            f"f.observed_at <= from_iso8601_timestamp(:{namespace}_window_end)",
        )
    elif mutation == "equality":
        output["sql"] = output["sql"].replace(
            "f.entity_id = d.entity_id", "f.observation_id = d.entity_id"
        )
        output["used_columns"].remove({"asset_fqn": fact, "column": "entity_id"})
        output["used_columns"].append({"asset_fqn": fact, "column": "observation_id"})
    elif mutation == "temporal":
        output["sql"] = output["sql"].replace(
            " AND f.observed_at >= d.valid_from AND f.observed_at < d.valid_to", ""
        )
        output["used_columns"].remove({"asset_fqn": dimension, "column": "valid_from"})
        output["used_columns"].remove({"asset_fqn": dimension, "column": "valid_to"})
    else:
        request["join_graph"]["edges"][0]["preaggregation"]["required"] = True

    with pytest.raises(PlanContractError) as caught:
        validate_output("node2", request, output, _bindings(request))

    assert caught.value.code == expected_code


def test_repair_uses_same_structured_contract_and_rejected_sql_must_stay_rejected():
    request = _repair_request("zephyr")
    output = {"corrected_sql": arbitrary_node2_response("zephyr")["sql"]}
    case = {"node": "node2_repair", "input": request, "expected_output": output}

    plan = validate_g2(case, _bindings(request))

    assert validate_sql(plan["executable_sql"]).placeholders == ()


def test_binding_manifest_is_strict_and_server_owned():
    request = arbitrary_node2_request("ember")
    bindings = _bindings(request)
    with NamedTemporaryFile(suffix=".json", delete=False) as handle:
        path = Path(handle.name)
    try:
        path.write_text(
            json.dumps(
                {
                    "version": BINDING_MANIFEST_VERSION,
                    "cases": {"case-ember": bindings},
                }
            ),
            encoding="utf-8",
        )
        assert load_binding_manifest(path) == {"case-ember": bindings}
        path.write_text(
            json.dumps({"version": BINDING_MANIFEST_VERSION}), encoding="utf-8"
        )
        with pytest.raises(PlanContractError) as caught:
            load_binding_manifest(path)
        assert caught.value.code == "BINDING_MANIFEST_INVALID"
    finally:
        path.unlink(missing_ok=True)
