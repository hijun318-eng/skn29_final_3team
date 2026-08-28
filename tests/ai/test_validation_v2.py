import copy
import json
from collections import Counter

import pytest

from src.ai.sql_policy import validate_sql
from src.ai.training.build_smoke_manifest import select_smoke
from src.ai.training.build_validation_v2 import (
    select_validation_v2,
    structural_signature,
)
from src.ai.training.evaluate_endpoint import _run_trino, _schema, evaluate_record
from tests.ai.test_contracts import arbitrary_node2_request, arbitrary_node2_response


def _reviewed_spec(case_id, split, request, domain):
    return {
        "case_id": case_id,
        "split": split,
        "node": "node2",
        "domain": domain,
        "scenario_group": case_id,
        "synthetic": True,
        "schema_version": "reviewed-contract",
        "seed_version": "human-review",
        "review_status": "APPROVED",
        "trino_status": "NOT_RUN",
        "result_sha256": None,
        "input": request,
        "expected_output": {"reviewed_transport_payload": True},
    }


SINGLE_ASSET_REQUEST = {
    "schema_context": {
        "assets": [{
            "urn": "urn:example:alpha-signal",
            "fqn": "alpha_space.telemetry.signal_log",
            "grain": {"kind": "event", "keys": ["signal_key"]},
            "columns": [
                {"name": "signal_key", "native_type": "varchar", "nullable": False, "role": "key"},
                {"name": "observed_at", "native_type": "timestamp", "nullable": False, "role": "time"},
                {"name": "magnitude", "native_type": "double", "nullable": True, "role": "measure"},
            ],
        }],
    },
    "join_graph": {"edges": []},
    "metric_rules": [{
        "id": "alpha-magnitude",
        "source": {
            "kind": "column",
            "field": {
                "asset_fqn": "alpha_space.telemetry.signal_log",
                "column": "magnitude",
            },
        },
        "aggregation": "sum",
        "dimensions": [],
        "required_filters": [{"field": "quality", "operator": "eq"}],
        "time_field": "observed_at",
    }],
    "time_rules": {
        "interval": "[start,end)",
        "start_parameter": "window_start",
        "end_parameter": "window_end",
        "fields": [{"native_type": "timestamp", "bucket": "day", "timezone_mode": "context"}],
    },
}


def test_validation_slices_use_structure_not_names_or_operational_domains():
    isomorphic = copy.deepcopy(SINGLE_ASSET_REQUEST)
    isomorphic["schema_context"]["assets"][0].update({
        "urn": "urn:example:beta-reading",
        "fqn": "beta_lab.archive.reading_book",
    })
    for column, name in zip(
        isomorphic["schema_context"]["assets"][0]["columns"],
        ("reading_key", "captured_at", "amplitude"),
    ):
        column["name"] = name
    isomorphic["metric_rules"][0].update({"id": "beta-amplitude", "time_field": "captured_at"})
    isomorphic["metric_rules"][0]["source"]["field"] = {
        "asset_fqn": "beta_lab.archive.reading_book",
        "column": "amplitude",
    }

    joined = copy.deepcopy(isomorphic)
    joined["schema_context"]["assets"].append({
        "urn": "urn:example:beta-label",
        "fqn": "beta_lab.archive.label_book",
        "grain": {"kind": "entity", "keys": ["reading_key"]},
        "columns": [{"name": "reading_key", "native_type": "varchar", "nullable": False, "role": "key"}],
    })
    joined["join_graph"]["edges"].append({
        "left": "beta_lab.archive.reading_book",
        "right": "beta_lab.archive.label_book",
        "kind": "left",
        "cardinality": "many_to_one",
        "equality_conditions": [{"left_column": "reading_key", "right_column": "reading_key"}],
        "temporal_conditions": [],
        "preaggregation": {"required": False, "grain": [], "keys": []},
    })

    train = _reviewed_spec("train-alpha", "train", SINGLE_ASSET_REQUEST, "stream-a")
    validation = _reviewed_spec("validation-beta", "validation", isomorphic, "stream-b")
    ood = _reviewed_spec("validation-beta-join", "validation", joined, "stream-b")
    held_out = _reviewed_spec("gold-beta-join", "gold", joined, "stream-b")

    validation_id, validation_ood = select_validation_v2(
        [held_out, ood, validation, train]
    )

    assert structural_signature(train) == structural_signature(validation)
    assert structural_signature(train) != structural_signature(ood)
    assert validation_id == [validation]
    assert validation_ood == [ood]


def test_validation_selection_is_deterministic_limited_and_copied():
    train = _reviewed_spec("train", "train", SINGLE_ASSET_REQUEST, "arbitrary")
    first = _reviewed_spec("a-id", "validation", SINGLE_ASSET_REQUEST, "arbitrary")
    second = _reviewed_spec("b-id", "validation", SINGLE_ASSET_REQUEST, "another")

    selected, ood = select_validation_v2([second, first, train], limit_per_slice=1)

    assert selected == [first]
    assert ood == []
    selected[0]["domain"] = "mutated"
    assert first["domain"] == "arbitrary"
    with pytest.raises(ValueError, match="non-negative"):
        select_validation_v2([train], limit_per_slice=-1)


def test_aggregation_and_join_topology_are_structural():
    summed = copy.deepcopy(SINGLE_ASSET_REQUEST)
    averaged = copy.deepcopy(summed)
    averaged["metric_rules"][0]["aggregation"] = "average"
    assert structural_signature(
        _reviewed_spec("sum", "train", summed, "names-ignored")
    ) != structural_signature(
        _reviewed_spec("average", "validation", averaged, "names-ignored")
    )

    edge = {
        "kind": "inner",
        "cardinality": "many_to_one",
        "equality_conditions": [{"left_column": "key", "right_column": "key"}],
        "temporal_conditions": [],
        "preaggregation": {"required": False, "grain": [], "keys": []},
    }
    star = copy.deepcopy(SINGLE_ASSET_REQUEST)
    star["join_graph"]["edges"] = [
        {**edge, "left": "graph.one.a", "right": "graph.one.b"},
        {**edge, "left": "graph.one.a", "right": "graph.one.c"},
        {**edge, "left": "graph.one.a", "right": "graph.one.d"},
    ]
    chain = copy.deepcopy(star)
    chain["join_graph"]["edges"] = [
        {**edge, "left": "graph.two.w", "right": "graph.two.x"},
        {**edge, "left": "graph.two.x", "right": "graph.two.y"},
        {**edge, "left": "graph.two.y", "right": "graph.two.z"},
    ]
    assert structural_signature(
        _reviewed_spec("star", "train", star, "names-ignored")
    ) != structural_signature(
        _reviewed_spec("chain", "validation", chain, "names-ignored")
    )


def test_structural_signature_rejects_formula_outside_live_contract():
    formula = copy.deepcopy(SINGLE_ASSET_REQUEST)
    formula["metric_rules"][0]["source"] = {
        "kind": "formula",
        "operator": "divide",
        "operands": ["left_measure", "right_measure"],
    }

    with pytest.raises(ValueError, match="column-source metric contract"):
        structural_signature(
            _reviewed_spec("formula", "validation", formula, "invalid-contract")
        )


def _endpoint_bindings(namespace):
    return {
        f"{namespace}_window_start": {
            "value_type": "timestamp",
            "value": "2001-01-01T00:00:00+00:00",
        },
        f"{namespace}_window_end": {
            "value_type": "timestamp",
            "value": "2001-01-02T00:00:00+00:00",
        },
        f"{namespace}_status": {
            "value_type": "string",
            "value": "arbitrary-state",
        },
    }


def _endpoint_record(namespace="quartz", node="node2"):
    request = arbitrary_node2_request(namespace)
    response = arbitrary_node2_response(namespace)
    if node == "node2_repair":
        request = {
            "trace_id": f"trace-{namespace}",
            "attempt": 1,
            "rejected_sql": "SELECT invalid_identifier",
            **{
                key: copy.deepcopy(request[key])
                for key in (
                    "normalized_question", "resolved_request", "schema_context",
                    "metric_rules", "join_graph", "time_rules",
                    "parameter_contract", "query_policy",
                )
            },
            "normalized_error_code": "UNKNOWN_COLUMN",
            "repair_scope": ["column"],
        }
        response = {"corrected_sql": response["sql"]}
    return {
        "case_id": f"case-{namespace}-{node}",
        "domain": "arbitrary",
        "node": node,
        "messages": [
            {"role": "system", "content": "structured contract"},
            {"role": "user", "content": json.dumps(request)},
            {"role": "assistant", "content": json.dumps(response)},
        ],
    }, response


def test_endpoint_uses_strict_schema_and_never_sends_server_binding_values(monkeypatch):
    record, generated = _endpoint_record()
    bindings = _endpoint_bindings("quartz")
    observed = {"executions": []}

    def requester(_method, _url, payload, _bearer, _timeout):
        observed["request"] = payload
        return {
            "choices": [{"message": {"content": json.dumps(generated)}}],
            "usage": {"completion_tokens": 1},
        }

    def run_trino(sql, container, user, password):
        observed["executions"].append((sql, container, user, password))
        return "PASS", "same-result", None

    monkeypatch.setattr("src.ai.training.evaluate_endpoint._run_trino", run_trino)
    result = evaluate_record(
        record,
        base_url="https://model.invalid",
        model="arbitrary-model",
        bindings=bindings,
        requester=requester,
        trino_container="runtime-container",
        trino_user="runtime-principal",
        trino_password="runtime-password",
    )

    schema = _schema("node2")
    assert schema["required"] == ["sql"]
    assert set(schema["properties"]) == {"sql"}
    assert schema["additionalProperties"] is False
    assert "guided_json" not in observed["request"]
    assert observed["request"]["seed"] == 0
    response_format = observed["request"]["response_format"]
    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["strict"] is True
    assert response_format["json_schema"]["schema"] == schema
    sent = json.dumps(observed["request"], sort_keys=True)
    assert all(item["value"] not in sent for item in bindings.values())
    assert len(observed["executions"]) == 2
    assert all(validate_sql(item[0]).placeholders == () for item in observed["executions"])
    assert result["g2"] == result["expected_g2"] == "PASS"
    assert result["trino"] == "PASS"
    assert result["result_match"] is True


@pytest.mark.parametrize("failure", ["missing-bindings", "legacy-output"])
def test_endpoint_fails_closed_before_trino_for_untrusted_contracts(monkeypatch, failure):
    record, generated = _endpoint_record("ember")
    bindings = _endpoint_bindings("ember")
    if failure == "missing-bindings":
        bindings = None
    else:
        generated = {**generated, "parameters": []}
    monkeypatch.setattr(
        "src.ai.training.evaluate_endpoint._run_trino",
        lambda *_args: (_ for _ in ()).throw(AssertionError("Trino must not run")),
    )

    result = evaluate_record(
        record,
        base_url="https://model.invalid",
        model="arbitrary-model",
        bindings=bindings,
        requester=lambda *_args: {
            "choices": [{"message": {"content": json.dumps(generated)}}]
        },
        trino_container="runtime-container",
        trino_user="runtime-principal",
    )

    expected = "BINDINGS_REQUIRED" if failure == "missing-bindings" else "MODEL_SCHEMA_INVALID"
    assert result["g2"] == expected
    assert result["trino"] == "NOT_RUN"


def test_endpoint_accepts_structured_repair_contract_without_execution():
    record, generated = _endpoint_record("zephyr", "node2_repair")
    result = evaluate_record(
        record,
        base_url="https://model.invalid",
        model="arbitrary-model",
        bindings=_endpoint_bindings("zephyr"),
        requester=lambda *_args: {
            "choices": [{"message": {"content": json.dumps(generated)}}]
        },
    )

    assert result["g2"] == result["expected_g2"] == "PASS"
    assert result["trino"] == "NOT_RUN"


def test_endpoint_refuses_trino_execution_without_runtime_password(monkeypatch):
    record, generated = _endpoint_record("cinder")
    monkeypatch.setattr(
        "src.ai.training.evaluate_endpoint._run_trino",
        lambda *_args: (_ for _ in ()).throw(AssertionError("Trino must not run")),
    )

    result = evaluate_record(
        record,
        base_url="https://model.invalid",
        model="arbitrary-model",
        bindings=_endpoint_bindings("cinder"),
        requester=lambda *_args: {
            "choices": [{"message": {"content": json.dumps(generated)}}]
        },
        trino_container="runtime-container",
        trino_user="runtime-principal",
    )

    assert result["g2"] == result["expected_g2"] == "PASS"
    assert result["trino"] == "CONFIGURATION_INVALID"


def test_endpoint_trino_receives_bound_sql_via_stdin_not_process_arguments(monkeypatch):
    observed = {}

    class Completed:
        returncode = 0
        stdout = '{"value":1}\n'
        stderr = ""

    def run(command, **kwargs):
        observed["command"] = command
        observed["input"] = kwargs["input"]
        observed["env"] = kwargs["env"]
        return Completed()

    monkeypatch.setattr("src.ai.training.verify_case_specs.subprocess.run", run)
    executable = "SELECT 1 AS value LIMIT 1"
    status, result_hash, diagnostic = _run_trino(
        executable, "runtime-container", "runtime-principal", "runtime-password"
    )

    assert executable not in observed["command"]
    assert "runtime-password" not in observed["command"]
    assert observed["input"] == executable + "\n"
    assert observed["command"][observed["command"].index("--server") + 1] == "https://trino:8443"
    assert observed["command"][observed["command"].index("--truststore-path") + 1] == "/run/secrets/trino-ca.pem"
    assert "--password" in observed["command"]
    assert observed["env"]["TRINO_PASSWORD"] == "runtime-password"
    assert status == "PASS"
    assert result_hash is not None
    assert diagnostic is None


def test_smoke_selection_balances_observed_structural_strata():
    cases = [
        {"case_id": "a", "node": "node2", "evaluation_slice": "ID", "structural_signature_sha256": "sig-1"},
        {"case_id": "b", "node": "node2", "evaluation_slice": "ID", "structural_signature_sha256": "sig-2"},
        {"case_id": "c", "node": "node2", "evaluation_slice": "OOD", "structural_signature_sha256": "sig-3"},
        {"case_id": "d", "node": "node2", "evaluation_slice": "OOD", "structural_signature_sha256": "sig-4"},
        {"case_id": "e", "node": "node2_repair", "evaluation_slice": "ID", "structural_signature_sha256": "sig-5"},
        {"case_id": "f", "node": "node2_repair", "evaluation_slice": "ID", "structural_signature_sha256": "sig-6"},
        {"case_id": "g", "node": "node2_repair", "evaluation_slice": "OOD", "structural_signature_sha256": "sig-7"},
        {"case_id": "h", "node": "node2_repair", "evaluation_slice": "OOD", "structural_signature_sha256": "sig-8"},
    ]

    first = select_smoke(cases, target_size=4)
    second = select_smoke(reversed(cases), target_size=4)

    assert first == second
    assert Counter(item["node"] for item in first) == {"node2": 2, "node2_repair": 2}
    assert Counter(item["evaluation_slice"] for item in first) == {"ID": 2, "OOD": 2}
    assert len({item["structural_signature_sha256"] for item in first}) == 4
    first[0]["case_id"] = "mutated"
    assert cases[0]["case_id"] == "a"


def test_smoke_selection_rejects_unfulfillable_or_unstructured_targets():
    with pytest.raises(ValueError, match="exceeds"):
        select_smoke([], target_size=1)
    with pytest.raises(ValueError, match="structural metadata"):
        select_smoke([{"case_id": "incomplete"}], target_size=1)
