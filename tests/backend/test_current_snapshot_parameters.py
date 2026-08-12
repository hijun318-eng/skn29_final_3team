from datetime import date

from app.adapters.context_registry_repository import PublishedContextRelease
from app.adapters.contract_model import ContractModelAdapter
from app.contracts import AnalysisRequest, RequestContext
from app.services.context_builder import ContextPackageBuilder
from app.services.pipeline_support import PipelineSupport


class _Adapter:
    @staticmethod
    def get_asset_schema(_urn):
        return {
            "columns": [
                {"name": "membership_grade"},
                {"name": "points_balance"},
                {"name": "joined_at"},
                {"name": "member_status"},
            ]
        }


def _release(_as_of):
    return PublishedContextRelease(
        "00000000-0000-0000-0000-000000000201",
        "test-release",
        1,
        "f" * 64,
        "time-policy:v1:" + "a" * 64,
        "Asia/Seoul",
        "gregorian-kr",
    )


def _package():
    metric_filter = {
        "field": "member_status",
        "operator": "eq",
        "value_type": "string",
        "value": "ACTIVE",
    }
    metrics = tuple(
        {
            "id": metric_id,
            "asset_fqn": "crm.dbo.crm_members",
            "field": "points_balance",
            "aggregation": aggregation,
            "time_field": "joined_at",
            "temporal_semantics": "current_snapshot",
            "required_filters": (metric_filter,),
        }
        for metric_id, aggregation in (
            ("current_points_balance_sum", "sum"),
            ("current_points_balance_average", "avg"),
        )
    )
    assets = [{
        "urn": "urn:li:dataset:crm-members",
        "fqn": "crm.dbo.crm_members",
        "metrics": metrics,
        "dimensions": ({
            "id": "membership_grade",
            "asset_fqn": "crm.dbo.crm_members",
            "field": "membership_grade",
        },),
    }]
    support = PipelineSupport(_Adapter(), ContextPackageBuilder(), _release)
    package = support.build_context(
        AnalysisRequest(
            question="2026년 4월 회원 등급별 사용 가능 포인트 합계와 평균",
            parameters={
                "period_start": "2026-04-01",
                "period_end_exclusive": "2026-05-01",
            },
        ),
        RequestContext(as_of=date(2026, 8, 12)),
        assets,
    )
    return support, package


def test_snapshot_context_deduplicates_filters_and_omits_period_bindings():
    _support, package = _package()

    assert [(item.name, item.value) for item in package.parameter_bindings] == [
        ("required_filter_1", "ACTIVE")
    ]


def test_snapshot_model_plan_drops_joined_at_period_and_passes_g2():
    support, package = _package()

    class Model:
        last_trace = {}

        @staticmethod
        def generate(_node, _payload):
            return {
                "sql": (
                    "SELECT membership_grade, "
                    "SUM(points_balance) AS current_points_balance_sum, "
                    "AVG(points_balance) AS current_points_balance_average "
                    "FROM crm.dbo.crm_members "
                    "WHERE joined_at >= DATE ':period_start' "
                    "AND joined_at < DATE ':period_end_exclusive' "
                    "AND member_status = :required_filter_1 "
                    "GROUP BY membership_grade ORDER BY membership_grade LIMIT 1000"
                ),
                "parameters": [],
                "references": [{
                    "urn": "urn:li:dataset:crm-members",
                    "trino_fqn": "crm.dbo.crm_members",
                    "columns": [
                        "membership_grade",
                        "points_balance",
                        "member_status",
                    ],
                    "metric_ids": [
                        "current_points_balance_sum",
                        "current_points_balance_average",
                    ],
                }],
                "model": {"model_version": "test-model"},
            }

    plan = ContractModelAdapter(Model()).generate(
        "node2",
        {
            "request_id": "request-1",
            "question": "회원 등급별 사용 가능 포인트 합계와 평균",
            "package": package,
            "context": RequestContext(as_of=date(2026, 8, 12)),
        },
    )

    assert "joined_at" not in plan["sql"].lower()
    assert "period_" not in plan["sql"].lower()
    assert plan["parameters"] == {
        "required_filter_1": {"value_type": "string", "value": "ACTIVE"}
    }
    assert support.g2_violation(plan, package) is None


def test_snapshot_result_summary_names_current_active_member_semantics():
    class Model:
        last_trace = {}

        @staticmethod
        def generate(_node, _payload):
            return {
                "explanation": "등급별 포인트 집계입니다.",
                "model": {"model_version": "test-model"},
            }

    result = ContractModelAdapter(Model()).generate(
        "node3",
        {
            "query": {"rows": [], "query_id": "query-1", "status": "SUCCEEDED"},
            "assets": [{
                "urn": "urn:li:dataset:crm-members",
                "metrics": ({
                    "id": "current_points_balance_sum",
                    "temporal_semantics": "current_snapshot",
                },),
            }],
            "context": RequestContext(as_of=date(2026, 8, 12)),
        },
    )

    assert "현재 활성 회원 기준 스냅샷" in result["summary"]
    assert "가입일 기간" in result["summary"]
