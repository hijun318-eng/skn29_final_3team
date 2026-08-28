"""Start the pinned Node2 vLLM server, then the RunPod worker loop."""

from __future__ import annotations

import logging
import os
import re
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path, PurePosixPath


MODEL_ALIAS = "node2-qwen35-2b-full3000-20260825"
NODE2_ROOT = PurePosixPath("/opt/node2")
HF_CACHE_ROOT = Path("/runpod-volume/huggingface-cache/hub")
VLLM_HOST = "127.0.0.1"
VLLM_PORT = 8000
IMAGE_DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
HF_REPO_ID_PATTERN = re.compile(
    r"^[A-Za-z0-9](?:[A-Za-z0-9._-]{0,94}[A-Za-z0-9])?/"
    r"[A-Za-z0-9](?:[A-Za-z0-9._-]{0,94}[A-Za-z0-9])?$"
)
HF_COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
LOGGER = logging.getLogger("node2-serverless")

vllm_process: subprocess.Popen[bytes] | None = None


def require_image_digest(environment: dict[str, str] | None = None) -> str:
    values = os.environ if environment is None else environment
    digest = values.get("NODE2_VLLM_IMAGE_DIGEST", "")
    if IMAGE_DIGEST_PATTERN.fullmatch(digest) is None:
        raise RuntimeError(
            "NODE2_VLLM_IMAGE_DIGEST must be the pushed image sha256 digest"
        )
    return digest


def resolve_cached_model_path(
    environment: dict[str, str] | None = None,
    cache_root: Path = HF_CACHE_ROOT,
) -> Path:
    """Resolve one immutable Hugging Face snapshot supplied by RunPod cache."""
    values = os.environ if environment is None else environment
    repo_id = values.get("MODEL_NAME", "")
    revision = values.get("MODEL_REVISION", "")
    if HF_REPO_ID_PATTERN.fullmatch(repo_id) is None:
        raise RuntimeError("MODEL_NAME must be a Hugging Face namespace/repository ID")
    if HF_COMMIT_PATTERN.fullmatch(revision) is None:
        raise RuntimeError("MODEL_REVISION must be a pinned 40-character commit SHA")

    try:
        resolved_root = cache_root.resolve(strict=True)
    except FileNotFoundError as error:
        raise RuntimeError(f"RunPod Hugging Face cache root is missing: {cache_root}") from error

    snapshot = (
        resolved_root
        / f"models--{repo_id.replace('/', '--')}"
        / "snapshots"
        / revision
    )
    try:
        resolved_snapshot = snapshot.resolve(strict=True)
        resolved_snapshot.relative_to(resolved_root)
    except (FileNotFoundError, ValueError) as error:
        raise RuntimeError(
            f"pinned Hugging Face snapshot is missing from RunPod cache: {repo_id}@{revision}"
        ) from error
    if not resolved_snapshot.is_dir():
        raise RuntimeError(f"cached Hugging Face snapshot is not a directory: {resolved_snapshot}")
    return resolved_snapshot


def build_vllm_command(model_path: Path | PurePosixPath) -> list[str]:
    """Return the A40-canary command unchanged for A40/A5000 sm86 workers."""
    return [
        "vllm",
        "serve",
        str(model_path),
        "--host",
        VLLM_HOST,
        "--port",
        str(VLLM_PORT),
        "--served-model-name",
        MODEL_ALIAS,
        "--language-model-only",
        "--dtype",
        "bfloat16",
        "--max-model-len",
        "5120",
        "--max-num-seqs",
        "1",
        "--gpu-memory-utilization",
        "0.85",
        "--mamba-cache-mode",
        "align",
        "--generation-config",
        "vllm",
        "--enforce-eager",
    ]


def run_preflight(image_digest: str, model_path: Path) -> None:
    command = [
        sys.executable,
        str(NODE2_ROOT / "scripts/preflight_node2_vllm.py"),
        "--manifest",
        str(NODE2_ROOT / "evals/node2_qwen35_2b_full3000_canary.v1.json"),
        "--checkpoint",
        str(model_path),
        "--image-digest",
        image_digest,
    ]
    subprocess.run(command, check=True)


def wait_for_vllm(process: subprocess.Popen[bytes]) -> None:
    timeout_seconds = int(os.getenv("NODE2_STARTUP_TIMEOUT_SECONDS", "600"))
    if not 60 <= timeout_seconds <= 1200:
        raise RuntimeError("NODE2_STARTUP_TIMEOUT_SECONDS must be between 60 and 1200")
    deadline = time.monotonic() + timeout_seconds
    health_url = f"http://{VLLM_HOST}:{VLLM_PORT}/health"

    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(
                f"vLLM exited during startup with code {process.returncode}"
            )
        try:
            with urllib.request.urlopen(health_url, timeout=5) as response:
                if response.status == 200:
                    LOGGER.info("vLLM health check passed")
                    return
        except (urllib.error.URLError, ConnectionError, OSError):
            pass
        time.sleep(2)
    raise RuntimeError(f"vLLM did not become healthy within {timeout_seconds}s")


def stop_vllm() -> None:
    global vllm_process
    if vllm_process is None or vllm_process.poll() is not None:
        return
    vllm_process.terminate()
    try:
        vllm_process.wait(timeout=20)
    except subprocess.TimeoutExpired:
        vllm_process.kill()
        vllm_process.wait(timeout=10)


def _forward_signal(signum: int, _frame: object) -> None:
    LOGGER.info("received signal %s", signum)
    stop_vllm()
    raise SystemExit(128 + signum)


def main() -> None:
    global vllm_process

    image_digest = require_image_digest()
    model_path = resolve_cached_model_path()
    run_preflight(image_digest, model_path)
    for handled_signal in (signal.SIGTERM, signal.SIGINT):
        signal.signal(handled_signal, _forward_signal)

    command = build_vllm_command(model_path)
    LOGGER.info("starting fixed Node2 vLLM alias %s", MODEL_ALIAS)
    vllm_process = subprocess.Popen(command)
    try:
        wait_for_vllm(vllm_process)

        import handler as proxy_handler
        import runpod

        proxy_handler.vllm_process = vllm_process
        runpod.serverless.start(
            {
                "handler": proxy_handler.handler,
                "concurrency_modifier": lambda _current: 1,
                "return_aggregate_stream": True,
            }
        )
    finally:
        stop_vllm()


if __name__ == "__main__":
    main()
