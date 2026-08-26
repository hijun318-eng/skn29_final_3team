"""동일 RAG corpus에서 로컬·외부 embedding의 문서 회수율과 지연을 비교한다."""

from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.request
from pathlib import Path

import numpy as np
import psycopg
from sentence_transformers import SentenceTransformer


QUESTIONS = (
    ("개인정보가 잘못 전달됐을 때 어떻게 해야 해?", ("02 개인정보",)),
    ("보고서 작성 시 반드시 확인할 기준을 알려줘", ("03 보고서",)),
    ("고객 불만을 접수한 뒤 처리 절차를 알려줘", ("06 고객응대", "15 고객의견")),
    ("객실에 문제가 생겼을 때 대응 절차를 알려줘", ("13 객실",)),
    ("예약 불일치가 발생하면 어떻게 처리해?", ("09 입실 퇴실 예약 결제",)),
    ("시설 고장이 발생하면 먼저 무엇을 해야 해?", ("11 시설",)),
    ("안전사고 발생 시 대응 절차를 알려줘", ("14 안전",)),
    ("예약 취소와 환불 기준을 알려줘", ("16 취소",)),
)


def normalized(vectors: np.ndarray) -> np.ndarray:
    """embedding 행을 cosine 유사도 계산에 사용할 단위 벡터로 정규화한다."""
    values = np.asarray(vectors, dtype=np.float32)
    return values / np.linalg.norm(values, axis=1, keepdims=True)


def ranked_documents(scores: np.ndarray, titles: list[str], limit: int = 5) -> list[str]:
    """chunk 점수 순서에서 중복 문서 제목을 제거한 상위 문서를 반환한다."""
    result: list[str] = []
    for index in np.argsort(-scores):
        title = titles[int(index)]
        if title not in result:
            result.append(title)
        if len(result) == limit:
            break
    return result


def evaluate(model: str, query_vectors: np.ndarray, chunk_vectors: np.ndarray, titles: list[str]) -> dict:
    """고정 평가 질문의 문서 recall@1·3·5를 같은 corpus 기준으로 계산한다."""
    scores = normalized(query_vectors) @ normalized(chunk_vectors).T
    rows = []
    for index, (question, expected) in enumerate(QUESTIONS):
        documents = ranked_documents(scores[index], titles)
        rows.append(
            {
                "question": question,
                "expected_documents": list(expected),
                "top_documents": documents,
                "recall_at_1": bool(set(expected) & set(documents[:1])),
                "recall_at_3": bool(set(expected) & set(documents[:3])),
                "recall_at_5": bool(set(expected) & set(documents[:5])),
            }
        )
    return {
        "model": model,
        "samples": len(rows),
        "recall_at_1": round(sum(row["recall_at_1"] for row in rows) / len(rows), 4),
        "recall_at_3": round(sum(row["recall_at_3"] for row in rows) / len(rows), 4),
        "recall_at_5": round(sum(row["recall_at_5"] for row in rows) / len(rows), 4),
        "records": rows,
    }


def openai_queries() -> tuple[np.ndarray, float]:
    """평가 질문을 외부 embedding endpoint에 보내 벡터와 호출 지연을 측정한다."""
    endpoint = os.environ["OPENAI_EMBEDDING_ENDPOINT"]
    payload = json.dumps(
        {
            "input": [question for question, _ in QUESTIONS],
            "model": "text-embedding-3-small",
            "dimensions": 1024,
            "encoding_format": "float",
        },
        ensure_ascii=False,
    ).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}",
            "Content-Type": "application/json",
            "User-Agent": "answervice-rag-eval/1.0",
        },
    )
    started = time.perf_counter()
    with urllib.request.urlopen(request, timeout=60) as response:
        result = json.loads(response.read().decode("utf-8"))
    elapsed_ms = (time.perf_counter() - started) * 1000
    rows = sorted(result["data"], key=lambda row: row["index"])
    return np.asarray([row["embedding"] for row in rows], dtype=np.float32), elapsed_ms


def main() -> None:
    """DB corpus를 읽어 두 embedding 모델을 비교하고 checksum 포함 결과를 저장한다."""
    database_url = os.environ["RAG_DATABASE_URL_HOST"]
    with psycopg.connect(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT chunk.content, document.title, chunk.embedding::text
                FROM document_chunks AS chunk
                JOIN documents AS document ON document.manual_id = chunk.manual_id
                WHERE chunk.deleted_at IS NULL AND document.deleted_at IS NULL
                ORDER BY chunk.chunk_id
                """
            )
            rows = cursor.fetchall()
    contents = [str(row[0]) for row in rows]
    titles = [str(row[1]) for row in rows]
    openai_chunks = np.asarray(
        [np.fromstring(str(row[2]).strip("[]"), sep=",", dtype=np.float32) for row in rows]
    )
    if len(rows) != 363 or openai_chunks.shape != (363, 1024):
        raise RuntimeError(f"unexpected corpus shape: {len(rows)} / {openai_chunks.shape}")

    openai_query_vectors, openai_query_ms = openai_queries()
    openai_result = evaluate(
        "OpenAI text-embedding-3-small",
        openai_query_vectors,
        openai_chunks,
        titles,
    )
    openai_result["query_embedding_ms"] = round(openai_query_ms, 2)

    model_started = time.perf_counter()
    qwen = SentenceTransformer(
        os.environ["QWEN_MODEL_PATH"],
        device="cpu",
        local_files_only=True,
    )
    qwen.max_seq_length = 2048
    model_load_ms = (time.perf_counter() - model_started) * 1000
    chunk_started = time.perf_counter()
    qwen_chunks = qwen.encode(
        contents,
        batch_size=8,
        normalize_embeddings=True,
        show_progress_bar=False,
        convert_to_numpy=True,
    )
    chunk_embedding_ms = (time.perf_counter() - chunk_started) * 1000
    query_started = time.perf_counter()
    qwen_queries = qwen.encode(
        [question for question, _ in QUESTIONS],
        prompt_name="query",
        normalize_embeddings=True,
        show_progress_bar=False,
        convert_to_numpy=True,
    )
    query_embedding_ms = (time.perf_counter() - query_started) * 1000
    qwen_result = evaluate(
        "Qwen3-Embedding-0.6B",
        qwen_queries,
        qwen_chunks,
        titles,
    )
    qwen_result.update(
        {
            "model_load_ms": round(model_load_ms, 2),
            "corpus_embedding_ms": round(chunk_embedding_ms, 2),
            "query_embedding_ms": round(query_embedding_ms, 2),
        }
    )

    corpus_hash = hashlib.sha256(
        json.dumps(list(zip(titles, contents)), ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()
    report = {
        "measured_at": time.strftime("%Y-%m-%d %H:%M:%S Asia/Seoul"),
        "comparison_contract": {
            "documents": len(set(titles)),
            "chunks": len(contents),
            "dimensions": 1024,
            "questions": len(QUESTIONS),
            "top_k": [1, 3, 5],
            "metric": "cosine similarity with document-title deduplication",
            "corpus_sha256": corpus_hash,
        },
        "results": [openai_result, qwen_result],
        "limitations": [
            "Eight domain smoke questions are insufficient for model selection.",
            "Latency scopes query embedding only; OpenAI network and local Qwen CPU are different execution environments.",
            "A reviewer-approved Gold set of at least 80 questions is still required.",
        ],
    }
    output = Path(__file__).with_name("embedding_comparison_same_corpus_20260824.json")
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(output), "results": report["results"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
