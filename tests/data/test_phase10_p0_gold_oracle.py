"""Phase 10 P0 Gold 교정과 독립 read-only oracle 경계를 검증한다."""

from __future__ import annotations

import asyncio
import json
from decimal import Decimal
from pathlib import Path

import pytest

from infrastructure.acceptance import phase10_p0_gold_oracle as oracle


ROOT = Path(__file__).resolve().parents[2]


def _cases() -> list[dict]:
    """봉인된 source draft를 case 객체로 읽는다."""

    return [
        json.loads(line)
        for line in oracle.SOURCE_CASES.read_text(encoding="utf-8").splitlines()
    ]


def test_corrected_inventory_and_high_risk_cases_are_fail_closed() -> None:
    """11개 승인 지적과 clarification taxonomy가 예상한 계약으로 교정된다."""

    cases = oracle.corrected_cases(_cases())
    index = {case["case_id"]: case for case in cases}

    assert sum(case["allow_or_block"] == "ALLOW" for case in cases) == 35
    assert sum(case["allow_or_block"] == "BLOCK" for case in cases) == 20
    assert index["P0-S-011"]["utterances"] == [
        "지난달 객실 매출을 일별로 보여줘"
    ]
    for case_id in ("P0-S-021", "P0-S-022", "P0-S-023"):
        assert index[case_id]["expected_query_strategy"] == "VIEW_REUSE"
        assert index[case_id]["expected_assets"] == [oracle.HOTEL_ASSET]
    for case_id in ("P0-S-024", "P0-S-030"):
        assert index[case_id]["allow_or_block"] == "BLOCK"
        assert index[case_id]["expected_result"]["kind"] == "NONE"
    assert index["P0-X-009"]["expected_error_code"] == "METRIC_NOT_AVAILABLE"
    assert index["P0-X-010"]["expected_error_code"] == "METRIC_NOT_AVAILABLE"
    assert index["P0-X-011"]["expected_error_code"] == "ACCESS_DENIED"
    for case_id in ("P0-S-026", "P0-S-027", "P0-S-028"):
        assert index[case_id]["expected_error_code"] == "CONTEXT_INCOMPLETE"
    assert index["P0-M-007"]["expected_resolved_request"]["period"] is not None
    assert index["P0-M-009"]["expected_resolved_request"]["period"] is not None


def test_every_corrected_allow_case_builds_a_bounded_select() -> None:
    """ALLOW 35건은 승인 view의 SELECT만 만들고 모든 BLOCK은 query를 만들지 않는다."""

    for case in oracle.corrected_cases(_cases()):
        if case["allow_or_block"] == "BLOCK":
            continue
        sql, _scalar = oracle.build_oracle_sql(case)
        assert sql.startswith("SELECT ")
        assert sql.endswith(f"LIMIT {oracle.MAX_ROWS}")
        assert ";" not in sql
        assert (
            f" FROM {oracle.HOTEL_ASSET} " in sql
            or f" FROM {oracle.VOC_ORACLE_ASSET} " in sql
        )


def test_same_view_multi_metric_and_scalar_assertion_are_explicit() -> None:
    """교정한 multi-metric은 JOIN 없이 실행되고 scalar 합계는 tolerance 0으로 봉인된다."""

    index = {
        case["case_id"]: case for case in oracle.corrected_cases(_cases())
    }
    sql, scalar = oracle.build_oracle_sql(index["P0-S-021"])
    assert "room_revenue" in sql and "fnb_revenue" in sql
    assert " JOIN " not in sql
    assert scalar is False

    assertion, review = oracle._result_assertion(
        metric_ids=["room_revenue"],
        scalar=True,
        columns=["room_revenue"],
        rows=[[100]],
    )
    assert assertion == {
        "kind": "TOLERANCE",
        "sha256": None,
        "value": 100,
        "absolute_tolerance": 0,
    }
    assert review == 100


def test_voc_oracle_uses_independent_one_row_per_review_equivalence() -> None:
    """VOC 독립 oracle은 1:1 source 제약에 근거한 AVG로 runtime ratio 식 재사용을 피한다."""

    index = {
        case["case_id"]: case for case in oracle.corrected_cases(_cases())
    }
    sql, scalar = oracle.build_oracle_sql(index["P0-S-010"])
    assert "AVG(CAST(rating_overall AS DOUBLE))" in sql
    assert "COUNT(DISTINCT" not in sql
    assert f" FROM {oracle.VOC_ORACLE_ASSET} " in sql
    assert "source_business_date" in sql
    for column in oracle._VOC_FORBIDDEN_SOURCE_COLUMNS:
        assert column not in sql
    assert scalar is False


def test_hash_assertion_changes_when_aggregate_rows_change() -> None:
    """집계 표의 값·순서가 달라지면 canonical Gold hash도 달라진다."""

    first, _ = oracle._result_assertion(
        metric_ids=["room_revenue"],
        scalar=False,
        columns=["period", "room_revenue"],
        rows=[["2025-08-01", 100]],
    )
    second, _ = oracle._result_assertion(
        metric_ids=["room_revenue"],
        scalar=False,
        columns=["period", "room_revenue"],
        rows=[["2025-08-01", 101]],
    )
    assert first["sha256"] != second["sha256"]


def test_decimal_results_are_normalized_as_numeric_values() -> None:
    """Trino DECIMAL은 정수 정밀도를 보존하고 비정수는 tolerance용 수치로 변환한다."""

    assert oracle._normal(Decimal("6878538750")) == 6_878_538_750
    assert oracle._normal(Decimal("0.875")) == pytest.approx(0.875)
    assertion, _review = oracle._result_assertion(
        metric_ids=["room_revenue"],
        scalar=True,
        columns=["room_revenue"],
        rows=[["6878538750"]],
    )
    assert assertion["value"] == 6_878_538_750


def test_non_numeric_scalar_string_is_rejected() -> None:
    """집계 metric 자리에 숫자가 아닌 문자열이 오면 fail-closed 한다."""

    with pytest.raises(oracle.Phase10P0GoldOracleError, match="str is not numeric"):
        oracle._result_assertion(
            metric_ids=["room_revenue"],
            scalar=True,
            columns=["room_revenue"],
            rows=[["not-a-number"]],
        )


def test_collect_cancels_its_exact_query_after_page_timeout() -> None:
    """page timeout이면 동일 query의 승인된 next URI만 취소하고 원 오류를 보존한다."""

    query_id = "20260823_000000_00001_test"
    next_uri = f"https://127.0.0.1:18443/v1/statement/queued/{query_id}/1"

    class TimeoutClient:
        def __init__(self) -> None:
            self.cancelled: tuple[str, str] | None = None

        async def execute(self, _sql: str, *, deadline: float) -> oracle.QueryPage:
            return oracle.QueryPage(
                query_id=query_id,
                state="RUNNING",
                columns=(),
                rows=(),
                next_uri=next_uri,
            )

        async def next_page(
            self,
            _next_uri: str,
            *,
            deadline: float,
        ) -> oracle.QueryPage:
            raise oracle.AdapterError(oracle.AdapterErrorCode.TIMEOUT, "timeout")

        async def cancel_query(
            self,
            observed_query_id: str,
            observed_next_uri: str,
            *,
            deadline: float,
        ) -> None:
            self.cancelled = (observed_query_id, observed_next_uri)

    client = TimeoutClient()
    with pytest.raises(oracle.AdapterError) as captured:
        asyncio.run(oracle._collect(client, "SELECT 1", timeout=1.0))
    assert captured.value.code is oracle.AdapterErrorCode.TIMEOUT
    assert client.cancelled == (query_id, next_uri)


def test_oracle_boundary_rejects_another_output(tmp_path: Path) -> None:
    """versioned output 이름을 바꿔 source나 임의 파일을 덮어쓰지 못한다."""

    args = oracle.parse_args(
        [
            "--target-project",
            oracle.TARGET_PROJECT,
            "--trino-server",
            oracle.TRINO_SERVER,
            "--trino-ca-file",
            str(tmp_path / "missing-ca.pem"),
            "--env-file",
            str(oracle.ENV_FILE),
            "--source-manifest",
            str(oracle.SOURCE_MANIFEST),
            "--source-cases",
            str(oracle.SOURCE_CASES),
            "--semantic-candidate",
            str(oracle.SEMANTIC_CANDIDATE),
            "--output-manifest",
            str(tmp_path / "other.json"),
            "--output-cases",
            str(oracle.OUTPUT_CASES),
            "--receipt",
            str(oracle.RECEIPT_FILE),
            "--review-output",
            str(oracle.REVIEW_FILE),
        ]
    )
    with pytest.raises(oracle.Phase10P0GoldOracleError, match="output manifest"):
        oracle.validate_boundary(args)
