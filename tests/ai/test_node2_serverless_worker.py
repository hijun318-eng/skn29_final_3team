from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
WORKER = ROOT / "infrastructure/ai/node2_serverless"


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, WORKER / filename)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


handler_module = _load("node2_serverless_handler", "handler.py")
main_module = _load("node2_serverless_main", "main.py")


def test_openai_chat_injects_only_the_fixed_2b_alias() -> None:
    route, method, body = handler_module.normalize_job_input(
        {
            "openai_route": "/v1/chat/completions",
            "openai_input": {"messages": [{"role": "user", "content": "query"}]},
        }
    )

    assert (route, method) == ("/v1/chat/completions", "POST")
    assert body["model"] == "node2-qwen35-2b-full3000-20260825"


def test_worker_rejects_a_different_model_alias() -> None:
    with pytest.raises(handler_module.InvalidJobInput, match="fixed Node2 alias"):
        handler_module.normalize_job_input(
            {
                "messages": [{"role": "user", "content": "query"}],
                "model": "answervice-sql",
            }
        )


@pytest.mark.parametrize(
    "body",
    [
        {"messages": [], "guided_json": {}},
        {"messages": [], "extra_body": {"guided_json": {}}},
    ],
)
def test_worker_rejects_removed_guided_json(body: dict[str, object]) -> None:
    with pytest.raises(handler_module.InvalidJobInput, match="response_format"):
        handler_module.normalize_job_input(body)


def test_worker_rejects_arbitrary_local_vllm_routes() -> None:
    with pytest.raises(handler_module.InvalidJobInput, match="not allowed"):
        handler_module.normalize_job_input(
            {"openai_route": "/metrics", "openai_input": {}}
        )


@pytest.mark.parametrize("route", ["/v1/models", "/health"])
def test_read_only_routes_are_get_only(route: str) -> None:
    assert handler_module.normalize_job_input({"openai_route": route}) == (
        route,
        "GET",
        None,
    )
    with pytest.raises(handler_module.InvalidJobInput, match="only supports GET"):
        handler_module.normalize_job_input(
            {"openai_route": route, "openai_input": {}}
        )


def test_image_digest_is_required_before_startup() -> None:
    digest = "sha256:" + "a" * 64
    assert main_module.require_image_digest({"NODE2_VLLM_IMAGE_DIGEST": digest}) == digest
    with pytest.raises(RuntimeError, match="pushed image"):
        main_module.require_image_digest({})


def test_cached_model_path_requires_a_pinned_huggingface_snapshot(
    tmp_path: Path,
) -> None:
    revision = "b" * 40
    snapshot = (
        tmp_path
        / "models--private-owner--node2-qwen35-2b-full3000"
        / "snapshots"
        / revision
    )
    snapshot.mkdir(parents=True)

    assert main_module.resolve_cached_model_path(
        {
            "MODEL_NAME": "private-owner/node2-qwen35-2b-full3000",
            "MODEL_REVISION": revision,
        },
        tmp_path,
    ) == snapshot.resolve()

    with pytest.raises(RuntimeError, match="40-character commit SHA"):
        main_module.resolve_cached_model_path(
            {
                "MODEL_NAME": "private-owner/node2-qwen35-2b-full3000",
                "MODEL_REVISION": "main",
            },
            tmp_path,
        )


def test_cached_model_path_fails_when_runpod_cache_is_missing(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="snapshot is missing"):
        main_module.resolve_cached_model_path(
            {
                "MODEL_NAME": "private-owner/node2-qwen35-2b-full3000",
                "MODEL_REVISION": "b" * 40,
            },
            tmp_path,
        )


def test_vllm_command_matches_the_a40_canary_contract() -> None:
    model_path = Path(
        "/runpod-volume/huggingface-cache/hub/"
        "models--private-owner--node2-qwen35-2b-full3000/"
        f"snapshots/{'b' * 40}"
    )
    command = main_module.build_vllm_command(model_path)

    assert command[:3] == [
        "vllm",
        "serve",
        str(model_path),
    ]
    for expected in (
        "--language-model-only",
        "--enforce-eager",
        "--max-model-len",
        "--max-num-seqs",
        "--gpu-memory-utilization",
    ):
        assert expected in command
    assert command[command.index("--served-model-name") + 1] == (
        "node2-qwen35-2b-full3000-20260825"
    )
    assert command[command.index("--max-model-len") + 1] == "5120"
    assert command[command.index("--max-num-seqs") + 1] == "1"
    assert command[command.index("--gpu-memory-utilization") + 1] == "0.85"


def test_dockerfile_pins_cuda_base_and_installs_both_hash_locks() -> None:
    dockerfile = (WORKER / "Dockerfile").read_text(encoding="utf-8")

    assert (
        "nvidia/cuda:12.9.1-devel-ubuntu24.04@"
        "sha256:e542739fcaa4f45da5add8c4cf5769783a61628b2518304a5bbe4ace468b8c8f"
        in dockerfile
    )
    assert "node2_qwen35_2b_full3000_vllm-cu129.lock.txt" in dockerfile
    assert "node2_qwen35_2b_full3000_serverless-cu129.lock.txt" in dockerfile
    assert "--require-hashes" in dockerfile
    assert "--no-build" in dockerfile
    assert "COPY --from=node2_model" not in dockerfile
    assert "RunPod's Hugging Face model cache" in dockerfile


def test_huggingface_publish_script_is_private_and_hash_verified() -> None:
    script = (ROOT / "scripts/publish_node2_hf_model.ps1").read_text(
        encoding="utf-8"
    )

    assert "Get-FileHash" in script
    assert "--private" in script
    assert "Refusing to upload" in script
    assert "HF_XET_HIGH_PERFORMANCE" in script
    assert "model_revision=" in script


def test_local_image_receipt_is_source_bound_and_not_a_gpu_pass() -> None:
    receipt = json.loads(
        (
            ROOT
            / "evals/node2_qwen35_2b_full3000_serverless_image.local.json"
        ).read_text(encoding="utf-8")
    )
    source_paths = {
        "dockerfile": WORKER / "Dockerfile",
        "dockerignore": WORKER / "Dockerfile.dockerignore",
        "handler": WORKER / "handler.py",
        "main": WORKER / "main.py",
        "build_script": ROOT / "scripts/build_node2_serverless_image.ps1",
        "publish_script": ROOT / "scripts/publish_node2_hf_model.ps1",
        "preflight": ROOT / "scripts/preflight_node2_vllm.py",
        "static_verifier": ROOT / "scripts/verify_node2_serverless_image_static.py",
        "canary_manifest": ROOT / "evals/node2_qwen35_2b_full3000_canary.v1.json",
    }

    for label, path in source_paths.items():
        assert hashlib.sha256(path.read_bytes()).hexdigest() == receipt["source_sha256"][label]
    assert receipt["build"]["registry_pushed"] is False
    assert receipt["model"]["baked_into_image"] is False
    assert receipt["model"]["delivery"] == "RUNPOD_HUGGINGFACE_MODEL_CACHE"
    assert receipt["checks"]["gpu_preflight"].startswith("NOT_RUN")
    assert receipt["production_switch_allowed"] is False


def test_huggingface_receipt_pins_private_model_commit() -> None:
    receipt = json.loads(
        (
            ROOT
            / "evals/node2_qwen35_2b_full3000_huggingface.receipt.json"
        ).read_text(encoding="utf-8")
    )

    assert receipt["repository"]["repo_id"] == "yoondaesung/answerviceqwen352b"
    assert receipt["repository"]["private"] is True
    assert receipt["repository"]["commit_sha"] == (
        "28e9974a42163c5ca97137622669d40cfc14d73b"
    )
    assert receipt["checkpoint"]["remote_model_weight_sha256"] == (
        receipt["checkpoint"]["local_model_weight_sha256"]
    )
    assert receipt["checkpoint"]["remote_merge_manifest_sha256"] == (
        receipt["checkpoint"]["local_merge_manifest_sha256"]
    )
    assert receipt["production_switch_allowed"] is False
