"""동일 질문 묶음으로 RAG 검색 모드별 성공 호출 수와 지연시간 기준선을 측정한다."""

import json
import time
from pathlib import Path
from typing import List, Dict, Any

from .vector_application import VectorRagApplication


class BaselineBenchmark:
    """JSON 질문 파일을 읽어 하나의 RAG 애플리케이션에 검색 모드별로 반복 실행한다.

    질문 파일이 없으면 빈 스위트로 계속하고, JSON 해석 오류는 호출자에게 전파한다.
    이 기준선은 검색 정확도 평가가 아니라 호출 성공 여부와 지연시간 진단용이다.
    """

    def __init__(self, app: VectorRagApplication, queries_path: Path):
        self.app = app
        self.queries_path = queries_path
        self._load_queries()

    def _load_queries(self):
        self.queries = []
        if self.queries_path.exists():
            with open(self.queries_path, "r", encoding="utf-8") as f:
                self.queries = json.load(f)
        else:
            print(f"Warning: Test queries not found at {self.queries_path}")

    def run_benchmark(self, model_id: str, retrieval_modes: List[str]) -> Dict[str, Any]:
        """각 검색 모드에서 비어 있지 않은 질문을 실행해 성공 호출의 지연시간을 집계한다.

        개별 검색 예외는 오류로 출력하고 해당 호출을 집계에서 제외하며, 반환값에는
        모델·모드별 실행 수, 합계·평균 지연시간과 성공 비율을 담는다.
        """

        results = {}

        for mode in retrieval_modes:
            print(f"Running benchmark for {model_id} - Mode: {mode}")
            mode_results = {
                "queries_executed": 0,
                "total_latency_ms": 0,
                "average_latency_ms": 0,
                "success_rate": 0,
            }

            success_count = 0
            for q in self.queries:
                query_text = q.get("query", "")
                if not query_text:
                    continue

                try:
                    start = time.perf_counter()
                    # Perform search using the app
                    # In a real benchmark, we'd also evaluate recall against gold dataset
                    res = self.app.search(
                        query=query_text,
                        role="SYSTEM_ADMIN",  # Default test role
                        top_k=5,
                        retrieval_mode=mode,
                        maximum_chunks_per_document=2
                    )
                    latency = (time.perf_counter() - start) * 1000

                    mode_results["queries_executed"] += 1
                    mode_results["total_latency_ms"] += latency
                    success_count += 1
                except Exception as e:
                    print(f"Error executing query '{query_text}' in mode {mode}: {e}")

            if mode_results["queries_executed"] > 0:
                mode_results["average_latency_ms"] = mode_results["total_latency_ms"] / mode_results["queries_executed"]
                mode_results["success_rate"] = success_count / mode_results["queries_executed"]

            results[f"{model_id}_{mode}"] = mode_results

        return {
            "status": "BENCHMARK_COMPLETED",
            "model_id": model_id,
            "results": results
        }

if __name__ == "__main__":
    import os
    import sys

    root_dir = Path(os.getcwd())
    app = VectorRagApplication(root_dir)
    queries_path = root_dir / "evals" / "testsets" / "rag" / "smoke_queries.json"

    benchmark = BaselineBenchmark(app, queries_path)
    modes = ["LEXICAL_ONLY", "VECTOR_ONLY", "HYBRID", "HYBRID_RERANK"]
    report = benchmark.run_benchmark(app._settings.model_id, modes)

    print(json.dumps(report, indent=2, ensure_ascii=False))
