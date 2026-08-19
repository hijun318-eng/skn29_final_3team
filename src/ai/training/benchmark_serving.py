"""벤치마크 serving 학습·평가 데이터의 생성, 실행, 검증 절차와 CLI 진입점을 제공한다.

Measure a fixed OpenAI-compatible model endpoint without extra dependencies.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable

import httpx


Requester = Callable[[str, str, dict[str, Any] | None, str | None, float], dict[str, Any]]


def request_json(
    method: str,
    url: str,
    payload: dict[str, Any] | None,
    token: str | None,
    timeout: float,
) -> dict[str, Any]:
    """HTTP JSON 요청을 timeout 안에서 실행하고 상태 코드와 응답 JSON 타입을 검증한다."""
    headers = {"Accept": "application/json", "User-Agent": "answervice-modelops/1.0"}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.request(method, url, json=payload, headers=headers)
            response.raise_for_status()
            result = response.json()
    except httpx.TimeoutException as exc:
        raise TimeoutError("endpoint request timed out or was unavailable") from exc
    except httpx.HTTPStatusError as exc:
        raise OSError(
            f"endpoint returned HTTP {exc.response.status_code}"
        ) from exc
    except httpx.RequestError as exc:
        raise OSError("endpoint request was unavailable") from exc
    if not isinstance(result, dict):
        raise ValueError("endpoint response must be a JSON object")
    return result


def percentile(values: list[float], percent: int) -> float:
    """percentile 입력에서 비교 가능한 결정론적 요약 값을 계산한다."""
    if not values:
        raise ValueError("at least one latency is required")
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * percent / 100) - 1)]


def wait_ready(
    base_url: str,
    token: str | None,
    timeout: float,
    requester: Requester,
) -> tuple[dict[str, Any], float]:
    """모델 목록 endpoint가 응답할 때까지 제한 시간 안에서 polling한다.

    각 probe는 5초로 제한하고 전체 deadline이 지나면 마지막 장애를 성공으로 간주하지 않고
    ``TimeoutError``를 발생시키며, 준비까지 걸린 wall-clock 시간도 함께 반환한다.
    """
    started = time.perf_counter()
    deadline = started + timeout
    while True:
        try:
            return requester("GET", f"{base_url}/v1/models", None, token, 5), time.perf_counter() - started
        except (OSError, TimeoutError, ValueError):
            if time.perf_counter() >= deadline:
                raise TimeoutError("endpoint did not become ready before the deadline")
            time.sleep(2)


def benchmark(
    *,
    base_url: str,
    model: str,
    model_revision: str,
    warm_requests: int = 5,
    timeout: float = 60,
    token: str | None = None,
    requester: Requester = request_json,
    peak_vram_bytes: int | None = None,
) -> dict[str, Any]:
    """모델 endpoint 준비 시간과 warm inference 지연·throughput·VRAM 관측치를 수집한다.

    동일 guided schema 요청을 지정 횟수 수행하며 2회 미만 표본이나 비정상 timeout은
    측정값으로 채우지 않고 입력 오류로 거부한다.
    """
    if warm_requests < 2 or timeout <= 0:
        raise ValueError("warm_requests must be at least 2 and timeout must be positive")
    base_url = base_url.rstrip("/")
    models, readiness_seconds = wait_ready(base_url, token, timeout, requester)
    model_ids = [item.get("id") for item in models.get("data", []) if isinstance(item, dict)]
    if model not in model_ids:
        raise ValueError("the ready endpoint does not advertise the expected model")

    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "Return only the word READY."}],
        "temperature": 0,
        "max_tokens": 8,
    }

    def invoke() -> tuple[float, dict[str, Any]]:
        started = time.perf_counter()
        response = requester("POST", f"{base_url}/v1/chat/completions", payload, token, timeout)
        elapsed_ms = (time.perf_counter() - started) * 1000
        choices = response.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ValueError("chat completion response has no choices")
        return elapsed_ms, response

    cold_ms, cold_response = invoke()
    warm = [invoke()[0] for _ in range(warm_requests)]
    with ThreadPoolExecutor(max_workers=2) as executor:
        concurrent = list(executor.map(lambda _: invoke()[0], range(2)))

    material = json.dumps(
        {"models": models, "cold": cold_response},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return {
        "status": "PASS",
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "protocol": {
            "models_path": "/v1/models",
            "chat_completions_path": "/v1/chat/completions",
        },
        "model": {"id": model, "revision": model_revision},
        "readiness_seconds": round(readiness_seconds, 3),
        "cold_latency_ms": round(cold_ms, 3),
        "warm": {
            "requests": warm_requests,
            "p50_ms": round(percentile(warm, 50), 3),
            "p95_ms": round(percentile(warm, 95), 3),
        },
        "concurrency": {
            "limit": 2,
            "completed": len(concurrent),
            "max_latency_ms": round(max(concurrent), 3),
        },
        "peak_vram_bytes": peak_vram_bytes,
        "observed": {
            "accuracy": None,
            "p50_ms": round(percentile(warm, 50), 3),
            "p95_ms": round(percentile(warm, 95), 3),
            "peak_vram_bytes": peak_vram_bytes,
            "cost_usd": None,
        },
        "response_evidence_sha256": sha256(material).hexdigest(),
    }


def main() -> int:
    """서빙 endpoint benchmark를 실행해 관측 evidence를 stdout과 선택한 JSON 파일에 기록한다."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--model-revision", required=True)
    parser.add_argument("--warm-requests", type=int, default=5)
    parser.add_argument("--timeout", type=float, default=600)
    parser.add_argument("--peak-vram-bytes", type=int)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = benchmark(
        base_url=args.base_url,
        model=args.model,
        model_revision=args.model_revision,
        warm_requests=args.warm_requests,
        timeout=args.timeout,
        token=os.environ.get("MODEL_API_TOKEN"),
        peak_vram_bytes=args.peak_vram_bytes,
    )
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
