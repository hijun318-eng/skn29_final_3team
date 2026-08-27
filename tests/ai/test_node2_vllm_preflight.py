from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.preflight_node2_vllm import (
    ServingPreflightError,
    _needed_libraries,
    _public_version,
    _uv_version,
    _validate_checkpoint,
    _validate_installation_policy,
    _version_errors,
)


ROOT = Path(__file__).resolve().parents[2]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _checkpoint(tmp_path: Path) -> tuple[Path, dict[str, object]]:
    config = {
        "architectures": ["Qwen3_5ForConditionalGeneration"],
        "model_type": "qwen3_5",
        "text_config": {"model_type": "qwen3_5_text"},
    }
    (tmp_path / "config.json").write_text(json.dumps(config), encoding="utf-8")
    (tmp_path / "tokenizer.json").write_text("{}", encoding="utf-8")
    (tmp_path / "tokenizer_config.json").write_text("{}", encoding="utf-8")
    (tmp_path / "model.safetensors").write_bytes(b"static weights")
    files = {
        name: _sha256(tmp_path / name)
        for name in (
            "config.json",
            "tokenizer.json",
            "tokenizer_config.json",
            "model.safetensors",
        )
    }
    merge_manifest_path = tmp_path / "merge_manifest.json"
    merge_manifest_path.write_text(
        json.dumps(
            {
                "expected_keys": 10,
                "saved_keys": 10,
                "replaced_language_keys": 4,
                "preserved_base_keys": 6,
                "base_model": "Qwen/Qwen3.5-2B",
                "base_revision": "base-revision",
                "adapter_sha256": "a" * 64,
                "files": files,
            }
        ),
        encoding="utf-8",
    )
    expectation = {
        "architecture": "Qwen3_5ForConditionalGeneration",
        "model_type": "qwen3_5",
        "text_model_type": "qwen3_5_text",
        "minimum_replaced_language_keys": 1,
        "expected_total_keys": 10,
        "expected_replaced_language_keys": 4,
        "expected_preserved_base_keys": 6,
        "expected_base_model": "Qwen/Qwen3.5-2B",
        "expected_base_revision": "base-revision",
        "expected_adapter_sha256": "a" * 64,
        "expected_merge_manifest_sha256": _sha256(merge_manifest_path),
    }
    return tmp_path, expectation


def test_public_version_accepts_the_pinned_cuda_local_build() -> None:
    assert _public_version("2.11.0+cu129") == "2.11.0"


def test_uv_version_accepts_current_arch_suffix() -> None:
    assert _uv_version("uv 0.12.6 (x86_64-unknown-linux-gnu)") == "0.12.6"


def test_needed_libraries_extracts_cuda_abi_from_readelf() -> None:
    output = """
      0x0001 (NEEDED) Shared library: [libtorch.so]
      0x0001 (NEEDED) Shared library: [libcudart.so.12]
    """

    assert _needed_libraries(output) == {"libtorch.so", "libcudart.so.12"}


def test_version_errors_report_missing_and_mismatched_distributions() -> None:
    errors = _version_errors(
        {"torch": "2.11.0", "vllm": "0.21.0"},
        {"torch": "2.10.0+cu128"},
    )

    assert errors == [
        "torch version mismatch: expected=2.11.0 actual=2.10.0+cu128",
        "missing distribution: vllm",
    ]


def test_checkpoint_validation_hashes_static_output(tmp_path: Path) -> None:
    checkpoint, expectation = _checkpoint(tmp_path)

    result = _validate_checkpoint(checkpoint, expectation)

    assert result["expected_keys"] == result["saved_keys"] == 10
    assert result["replaced_language_keys"] == 4
    assert result["files_hashed"] == 4


def test_checkpoint_validation_rejects_tampered_output(tmp_path: Path) -> None:
    checkpoint, expectation = _checkpoint(tmp_path)
    (checkpoint / "model.safetensors").write_bytes(b"tampered")

    with pytest.raises(ServingPreflightError, match="hash mismatch"):
        _validate_checkpoint(checkpoint, expectation)


def test_checkpoint_validation_rejects_a_rewritten_merge_manifest(
    tmp_path: Path,
) -> None:
    checkpoint, expectation = _checkpoint(tmp_path)
    merge_manifest = json.loads(
        (checkpoint / "merge_manifest.json").read_text(encoding="utf-8")
    )
    merge_manifest["files"]["model.safetensors"] = "b" * 64
    (checkpoint / "merge_manifest.json").write_text(
        json.dumps(merge_manifest), encoding="utf-8"
    )

    with pytest.raises(ServingPreflightError, match="merge manifest hash mismatch"):
        _validate_checkpoint(checkpoint, expectation)


def test_manifest_pins_vllm_cuda_stack_and_blocks_legacy_guided_json() -> None:
    manifest = json.loads(
        (ROOT / "evals/node2_qwen35_2b_full3000_canary.v1.json").read_text(
            encoding="utf-8"
        )
    )
    plan = manifest["serving_plan"]

    assert plan["platform"]["python_version"] == "3.12"
    assert plan["platform"]["torch_backend"] == "cu129"
    assert plan["platform"]["allowed_gpu_names"] == [
        "NVIDIA A40",
        "NVIDIA RTX A5000",
    ]
    assert plan["platform"]["allowed_compute_capabilities"] == ["8.6"]
    assert plan["packages"]["vllm"] == "0.21.0"
    assert plan["packages"]["torch"] == "2.11.0"
    assert plan["packages"]["transformers"] == "5.14.1"
    assert plan["packages"]["runpod"] == "1.12.0"
    worker_layer = plan["installation_policy"]["additional_layers"][0]
    assert worker_layer["new_package_count"] == 26
    assert worker_layer["overlap_version_mismatch_count"] == 0
    assert plan["binary_contract"]["exact_distribution_versions"]["vllm"] == (
        "0.21.0+cu129"
    )
    assert plan["binary_contract"]["required_cuda_library"] == "libcudart.so.12"
    assert "libcudart.so.13" in plan["binary_contract"]["forbidden_cuda_libraries"]
    assert plan["binary_contract"]["required_runtime_executables"] == ["ninja"]
    assert plan["static_checkpoint"]["language_model_only"] is True
    assert plan["static_checkpoint"]["expected_merge_manifest_sha256"] == (
        "db8c3c52c5566711ad0b5c8dca17cbc7f7f3508ff94b0084248efa2282d33d74"
    )
    assert plan["structured_outputs"]["request_field"] == "response_format"
    assert plan["structured_outputs"]["legacy_guided_json_supported"] is False
    assert manifest["activation"]["api_compatibility"]["status"].startswith(
        "BLOCKED"
    )


def test_manifest_hashes_base_and_runpod_worker_locks() -> None:
    manifest = json.loads(
        (ROOT / "evals/node2_qwen35_2b_full3000_canary.v1.json").read_text(
            encoding="utf-8"
        )
    )

    checked = _validate_installation_policy(manifest["serving_plan"])

    assert checked["requirements_sha256"]
    assert checked["lock_sha256"]
    assert checked["layer_1_runpod_serverless_worker_requirements_sha256"]
    assert checked["layer_1_runpod_serverless_worker_lock_sha256"]
