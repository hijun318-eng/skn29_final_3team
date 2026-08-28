#!/usr/bin/env python3
"""GPU 없이 Node2 Serverless image의 고정 package·offline·checkpoint 경계를 검증한다."""

from __future__ import annotations

import importlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path


IMAGE_ROOT = Path("/opt/node2")
LEGACY_BAKED_MODEL_PATH = Path("/models/node2-qwen35-2b-full3000-20260825")
PREFLIGHT_PATH = IMAGE_ROOT / "scripts/preflight_node2_vllm.py"
MANIFEST_PATH = IMAGE_ROOT / "evals/node2_qwen35_2b_full3000_canary.v1.json"


def _load_preflight_module():
    spec = importlib.util.spec_from_file_location("node2_image_preflight", PREFLIGHT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load preflight module: {PREFLIGHT_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    """image 내부 정적 preflight를 실행하고 GPU에서 남은 검증 경계를 명시한다."""

    try:
        preflight = _load_preflight_module()
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        plan = manifest["serving_plan"]

        installation = preflight._validate_installation_policy(plan)
        platform = preflight._validate_platform(plan)
        packages = preflight._validate_python_stack(plan)
        importlib.import_module("runpod")

        if LEGACY_BAKED_MODEL_PATH.exists():
            raise RuntimeError("legacy baked checkpoint must not be present")

        for variable in (
            "HF_HUB_OFFLINE",
            "TRANSFORMERS_OFFLINE",
            "HF_DATASETS_OFFLINE",
        ):
            if os.environ.get(variable) != "1":
                raise RuntimeError(f"offline environment is not enforced: {variable}")

        nvcc = subprocess.run(
            ["nvcc", "--version"],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        ).stdout.strip().splitlines()[-1]
        result = {
            "status": "PASS_NODE2_SERVERLESS_IMAGE_STATIC",
            "gpu_validation": "NOT_RUN_NO_GPU_ATTACHED",
            "production_switch_allowed": False,
            "installation": installation,
            "platform": platform,
            "packages": {
                "vllm": packages["vllm"],
                "torch": packages["torch"],
                "transformers": packages["transformers"],
                "runpod": packages["runpod"],
                "pip_freeze_sha256": packages["pip_freeze_sha256"],
                "vllm_wheel_sha256": packages["vllm_wheel_sha256"],
                "vllm_needed_libraries": packages["vllm_needed_libraries"],
            },
            "checkpoint": {
                "status": "DEFERRED_TO_PINNED_RUNPOD_HUGGINGFACE_CACHE",
                "runtime_preflight_required": True,
            },
            "nvcc": nvcc,
            "next_stage": (
                "RUN_SAME_IMAGE_WITH_PINNED_RUNPOD_HF_CACHE_ON_A40_OR_A5000_GPU"
            ),
        }
        exit_code = 0
    except Exception as error:  # image verifier must emit one machine-readable failure
        result = {
            "status": "FAIL",
            "production_switch_allowed": False,
            "error": str(error),
        }
        exit_code = 1

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
