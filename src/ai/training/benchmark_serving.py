"""Measure a fixed OpenAI-compatible model endpoint without extra dependencies."""

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
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


Requester = Callable[[str, str, dict[str, Any] | None, str | None, float], dict[str, Any]]


def request_json(
    method: str,
    url: str,
    payload: dict[str, Any] | None,
    token: str | None,
    timeout: float,
) -> dict[str, Any]:
    headers = {"Accept": "application/json", "User-Agent": "answervice-modelops/1.0"}
    body = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        with urlopen(Request(url, data=body, headers=headers, method=method), timeout=timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise OSError(f"endpoint returned HTTP {exc.code}") from exc
    except (URLError, TimeoutError) as exc:
        raise TimeoutError("endpoint request timed out or was unavailable") from exc
    if not isinstance(result, dict):
        raise ValueError("endpoint response must be a JSON object")
    return result


def percentile(values: list[float], percent: int) -> float:
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
        "response_evidence_sha256": sha256(material).hexdigest(),
    }


def main() -> int:
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
