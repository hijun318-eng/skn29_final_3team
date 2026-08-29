from src.rag.bm25 import bm25_scores


def test_bm25_ranks_matching_document_first() -> None:
    scores = bm25_scores(
        "객실 환불 기준",
        ["객실 예약 환불 기준과 승인 절차", "주차장 안전 점검 방법"],
    )
    assert scores[0] == 1.0
    assert scores[1] == 0.0


def test_bm25_returns_zero_without_matching_terms() -> None:
    assert bm25_scores("환불", ["주차 안전", "시설 점검"]) == [0.0, 0.0]
