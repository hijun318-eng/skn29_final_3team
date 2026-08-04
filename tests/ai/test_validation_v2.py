from src.ai.training.build_case_specs import _urn
from src.ai.training.build_validation_v2 import select_validation_v2
from src.ai.training.evaluate_endpoint import evaluate_record


def _record(candidate_id, split, domain, metric, node="node2", output="scalar"):
    return {
        "candidate_id": candidate_id,
        "target_split": split,
        "domain": domain,
        "metric_id": metric,
        "aggregation": "sum",
        "dimension": "none",
        "filter_shape": "actual",
        "output_shape": output,
        "period_shape": "month",
        "node": node,
    }


def test_validation_id_and_ood_are_selected_without_gold():
    records = [
        _record("candidate-0001", "train", "pms", "revenue"),
        _record("candidate-0002", "validation", "pms", "revenue"),
        _record("candidate-0003", "reserve", "pms", "revenue", output="trend"),
        _record("candidate-0004", "gold", "pms", "revenue", output="trend"),
    ]

    validation_id, validation_ood = select_validation_v2(records, {"pms": 1})

    assert [record["candidate_id"] for record in validation_id] == ["candidate-0002"]
    assert [record["candidate_id"] for record in validation_ood] == ["candidate-0003"]


def test_raw_urn_comes_from_product_context_contract():
    assert _urn("crm.dbo.crm_members") == (
        "urn:li:dataset:(urn:li:dataPlatform:mssql,crm.crm_db.dbo.crm_members,PROD)"
    )
    assert _urn("serving.analytics.hotel_daily_metrics") == (
        "urn:li:dataset:(urn:li:dataPlatform:trino,serving.analytics.hotel_daily_metrics,PROD)"
    )


def test_endpoint_evaluator_applies_g2_to_generated_sql():
    context = {
        "context_version": "test",
        "policy_version": "test",
        "execution_time": {"as_of": "2026-08-01T00:00:00+09:00"},
        "assets": [
            {
                "urn": "urn:hotel",
                "trino_fqn": "serving.analytics.hotel_daily_metrics",
                "columns": ["property_id"],
            }
        ],
        "metrics": [],
        "joins": [],
    }
    sql = "SELECT property_id FROM serving.analytics.hotel_daily_metrics LIMIT 1000"
    record = {
        "case_id": "validation-1",
        "node": "node2",
        "messages": [
            {"role": "system", "content": "system"},
            {"role": "user", "content": __import__("json").dumps({"context_package": context})},
            {"role": "assistant", "content": __import__("json").dumps({"sql": sql})},
        ],
    }

    result = evaluate_record(
        record,
        base_url="https://model.invalid",
        model="test",
        requester=lambda *_args: {"choices": [{"message": {"content": __import__("json").dumps({"sql": sql})}}]},
    )

    assert result["g2"] == "PASS"
    assert result["sql_exact_match"] is True
