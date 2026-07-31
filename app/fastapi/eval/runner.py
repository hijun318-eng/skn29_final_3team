"""평가 세트 실행기 — 기획서 §18.1 필수 수용 세트.

gold_30.json의 30건 질문을 Pipeline에 전달하고 결과를 비교한다.
사용: python -m eval.runner

기획서 합격 기준:
- success 예상 질문이 DONE 상태로 완료
- clarify 예상 질문이 모호성으로 중단
- blocked 예상 질문이 Gate에서 차단
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

_EVAL_DIR = Path(__file__).resolve().parent
_GOLD_PATH = _EVAL_DIR / "gold_30.json"


def load_gold() -> dict[str, Any]:
    """gold_30.json을 로드한다."""
    with open(_GOLD_PATH, encoding="utf-8") as f:
        return json.load(f)


async def run_single(item: dict[str, Any]) -> dict[str, Any]:
    """단일 평가 항목을 실행하고 결과를 반환한다."""
    question = item["question"]
    expected = item["expected"]
    category = item["category"]

    try:
        from app.pipeline.controller import run_pipeline

        result = await run_pipeline(question)

        state = result.state.value
        # expected에 따른 판정
        if expected == "success":
            passed = state == "DONE"
            actual = state
        elif expected == "clarify":
            passed = state == "FAILED" and "모호" in (result.error or "")
            actual = f"FAILED({result.error[:30]})" if result.error else state
        elif expected == "blocked":
            passed = state == "FAILED"
            actual = f"FAILED({result.error[:30]})" if result.error else state
        else:
            passed = False
            actual = state

        return {
            "id": item["id"],
            "category": category,
            "question": question[:40],
            "expected": expected,
            "actual": actual,
            "passed": passed,
        }
    except Exception as e:
        return {
            "id": item["id"],
            "category": category,
            "question": question[:40],
            "expected": expected,
            "actual": f"ERROR: {e!s}",
            "passed": False,
        }


async def run_all() -> None:
    """전체 평가 세트를 실행하고 통계를 출력한다."""
    gold = load_gold()
    items = gold["items"]
    print(f"=== 평가 세트: {gold['meta']['version']} ({len(items)}건) ===")
    print()

    results = []
    for item in items:
        r = await run_single(item)
        results.append(r)
        mark = "✓" if r["passed"] else "✗"
        print(f"  {mark} {r['id']} [{r['category']}] {r['question']}")
        if not r["passed"]:
            print(f"    expected={r['expected']} actual={r['actual']}")

    # 카테고리별 통계
    print()
    print("=== 카테고리별 결과 ===")
    categories: dict[str, dict[str, int]] = {}
    for r in results:
        cat = r["category"]
        if cat not in categories:
            categories[cat] = {"pass": 0, "fail": 0}
        if r["passed"]:
            categories[cat]["pass"] += 1
        else:
            categories[cat]["fail"] += 1

    for cat, counts in sorted(categories.items()):
        total = counts["pass"] + counts["fail"]
        rate = counts["pass"] / total * 100 if total > 0 else 0
        print(f"  {cat}: {counts['pass']}/{total} ({rate:.0f}%)")

    total_pass = sum(1 for r in results if r["passed"])
    total = len(results)
    print()
    print(f"=== 전체: {total_pass}/{total} ({total_pass / total * 100:.0f}%) ===")


if __name__ == "__main__":
    asyncio.run(run_all())
