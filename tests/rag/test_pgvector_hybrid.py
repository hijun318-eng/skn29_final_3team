from __future__ import annotations

from unittest.mock import patch

import numpy as np

from src.rag.pgvector_repository import PgVectorRepository


def _row(
    manual_id: str,
    title: str,
    content: str,
    vector_score: float,
) -> tuple[object, ...]:
    return (
        manual_id,
        title,
        "1.0",
        1,
        1,
        "환불 절차" if "환불" in content else "안전 점검",
        content,
        vector_score,
        f"{manual_id}-chunk",
        0,
        "WORKING_KNOWLEDGE",
        "INTERNAL_WORKING_GUIDE",
        "VALID",
        "APPROVED",
        "MANUAL",
        "OPS",
        None,
        None,
    )


class _Result:
    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        self._rows = rows

    def fetchall(self) -> list[tuple[object, ...]]:
        return self._rows


class _Connection:
    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        self._rows = rows
        self.sql = ""
        self.params: list[object] = []

    def __enter__(self) -> "_Connection":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, sql: str, params: list[object]) -> _Result:
        self.sql = sql
        self.params = params
        return _Result(self._rows)


def test_hybrid_search_uses_bm25_without_weakening_access_filters() -> None:
    connection = _Connection(
        [
            _row("manual-refund", "객실 운영", "객실 환불 기준과 승인 절차", 0.65),
            _row("manual-parking", "시설 운영", "주차장 안전 점검 방법", 0.70),
        ]
    )
    repository = PgVectorRepository("postgresql://test")

    with patch(
        "src.rag.pgvector_repository.psycopg.connect",
        return_value=connection,
    ):
        results = repository.search(
            vector=np.asarray([0.1, 0.2], dtype=np.float32),
            query_text="객실 환불 기준",
            role="MANAGER",
            top_k=2,
            minimum_vector_score=0.60,
            allow_unresolved=False,
            selected_manual_ids=("manual-refund",),
            retrieval_mode="HYBRID",
        )

    assert [result.manual_id for result in results] == [
        "manual-refund",
        "manual-parking",
    ]
    assert results[0].lexical_score == 1.0
    assert results[0].ranking_stage == "dense_bm25"
    assert "d.approval_status = 'APPROVED'" in connection.sql
    assert "%s = ANY(d.role_scope)" in connection.sql
    assert "d.validity_status != 'UNRESOLVED'" in connection.sql
    assert connection.params[1:] == [
        "MANAGER",
        False,
        ["manual-refund"],
        ["manual-refund"],
    ]


def test_vector_only_keeps_vector_threshold_and_ordering() -> None:
    connection = _Connection(
        [
            _row("manual-refund", "객실 운영", "객실 환불 기준", 0.65),
            _row("manual-parking", "시설 운영", "주차 안전", 0.70),
        ]
    )
    repository = PgVectorRepository("postgresql://test")

    with patch(
        "src.rag.pgvector_repository.psycopg.connect",
        return_value=connection,
    ):
        results = repository.search(
            vector=np.asarray([0.1, 0.2], dtype=np.float32),
            query_text="객실 환불 기준",
            role="MANAGER",
            top_k=2,
            minimum_vector_score=0.68,
            allow_unresolved=False,
            retrieval_mode="VECTOR_ONLY",
        )

    assert [result.manual_id for result in results] == ["manual-parking"]
    assert results[0].score == 0.70
