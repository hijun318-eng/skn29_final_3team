#!/usr/bin/env python3
"""RunPod host가 고정된 Node2 vLLM·GPU·checkpoint 계약과 다르면 시작 전에 차단한다."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import importlib.metadata
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = (
    REPOSITORY_ROOT / "evals" / "node2_qwen35_2b_full3000_canary.v1.json"
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_IMAGE_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


class ServingPreflightError(RuntimeError):
    """host·Python stack·GPU·checkpoint 중 하나가 서빙 계약을 위반했음을 알린다."""


def _public_version(value: str) -> str:
    """Return the PEP 440 public version while retaining post releases."""
    return value.split("+", 1)[0]


def _numeric_version(value: str) -> tuple[int, ...]:
    parts = re.findall(r"\d+", value)
    if not parts:
        raise ServingPreflightError(f"invalid numeric version: {value}")
    return tuple(int(part) for part in parts)


def _uv_version(output: str) -> str:
    match = re.fullmatch(r"uv\s+(\d+\.\d+\.\d+)(?:\s+\([^)]*\))?", output.strip())
    if match is None:
        raise ServingPreflightError(f"could not parse uv version: {output}")
    return match.group(1)


def _version_errors(
    expected: Mapping[str, str], installed: Mapping[str, str]
) -> list[str]:
    errors: list[str] = []
    for distribution, expected_version in expected.items():
        actual = installed.get(distribution)
        if actual is None:
            errors.append(f"missing distribution: {distribution}")
        elif _public_version(actual) != expected_version:
            errors.append(
                f"{distribution} version mismatch: "
                f"expected={expected_version} actual={actual}"
            )
    return errors


def _installed_versions(distributions: Mapping[str, str]) -> dict[str, str]:
    installed: dict[str, str] = {}
    for distribution in distributions:
        try:
            installed[distribution] = importlib.metadata.version(distribution)
        except importlib.metadata.PackageNotFoundError:
            continue
    return installed


def _run(command: list[str], *, timeout: int = 30) -> str:
    try:
        result = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        stderr = getattr(error, "stderr", "") or ""
        detail = stderr.strip().splitlines()[-1:] or [str(error)]
        raise ServingPreflightError(
            f"command failed: {command[0]}: {detail[0]}"
        ) from error
    return result.stdout.strip()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _needed_libraries(readelf_output: str) -> set[str]:
    return set(re.findall(r"Shared library: \[([^\]]+)\]", readelf_output))


def _load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ServingPreflightError(f"invalid {label}: {path}") from error
    if not isinstance(value, dict):
        raise ServingPreflightError(f"{label} must be a JSON object: {path}")
    return value


def _validate_checkpoint(
    checkpoint: Path, expectation: Mapping[str, Any]
) -> dict[str, Any]:
    checkpoint = checkpoint.resolve()
    if not checkpoint.is_dir():
        raise ServingPreflightError(f"checkpoint directory is missing: {checkpoint}")

    config = _load_json(checkpoint / "config.json", "checkpoint config")
    if config.get("architectures") != [expectation["architecture"]]:
        raise ServingPreflightError("checkpoint architecture mismatch")
    if config.get("model_type") != expectation["model_type"]:
        raise ServingPreflightError("checkpoint model_type mismatch")
    text_config = config.get("text_config")
    if not isinstance(text_config, dict) or (
        text_config.get("model_type") != expectation["text_model_type"]
    ):
        raise ServingPreflightError("checkpoint text model_type mismatch")

    merge_manifest_path = checkpoint / "merge_manifest.json"
    expected_merge_manifest_hash = expectation.get("expected_merge_manifest_sha256")
    if (
        not isinstance(expected_merge_manifest_hash, str)
        or _SHA256.fullmatch(expected_merge_manifest_hash) is None
    ):
        raise ServingPreflightError("expected merge manifest hash is not pinned")
    if _sha256_file(merge_manifest_path) != expected_merge_manifest_hash:
        raise ServingPreflightError("merge manifest hash mismatch")

    merge = _load_json(merge_manifest_path, "merge manifest")
    expected_keys = merge.get("expected_keys")
    saved_keys = merge.get("saved_keys")
    replaced = merge.get("replaced_language_keys")
    if not isinstance(expected_keys, int) or expected_keys <= 0:
        raise ServingPreflightError("merge manifest has invalid expected_keys")
    if saved_keys != expected_keys:
        raise ServingPreflightError("merge manifest key count mismatch")
    minimum_replaced = int(expectation["minimum_replaced_language_keys"])
    if not isinstance(replaced, int) or replaced < minimum_replaced:
        raise ServingPreflightError("no verified language weights were replaced")
    if expected_keys != expectation.get("expected_total_keys"):
        raise ServingPreflightError("static checkpoint total key count mismatch")
    if replaced != expectation.get("expected_replaced_language_keys"):
        raise ServingPreflightError("static checkpoint replaced key count mismatch")
    if merge.get("preserved_base_keys") != expectation.get(
        "expected_preserved_base_keys"
    ):
        raise ServingPreflightError("static checkpoint preserved key count mismatch")
    if merge.get("base_model") != expectation.get("expected_base_model"):
        raise ServingPreflightError("static checkpoint base model mismatch")
    if merge.get("base_revision") != expectation.get("expected_base_revision"):
        raise ServingPreflightError("static checkpoint base revision mismatch")
    if merge.get("adapter_sha256") != expectation.get("expected_adapter_sha256"):
        raise ServingPreflightError("static checkpoint adapter hash mismatch")

    tokenizer_files = ("tokenizer.json", "tokenizer_config.json")
    missing_tokenizer = [name for name in tokenizer_files if not (checkpoint / name).is_file()]
    if missing_tokenizer:
        raise ServingPreflightError(
            f"checkpoint tokenizer files are missing: {missing_tokenizer}"
        )
    if not (
        (checkpoint / "model.safetensors").is_file()
        or (checkpoint / "model.safetensors.index.json").is_file()
    ):
        raise ServingPreflightError("checkpoint has no safetensors weights")

    files = merge.get("files")
    if not isinstance(files, dict) or not files:
        raise ServingPreflightError("merge manifest has no file hashes")
    for name, expected_hash in files.items():
        if (
            not isinstance(name, str)
            or Path(name).name != name
            or not isinstance(expected_hash, str)
            or not _SHA256.fullmatch(expected_hash)
        ):
            raise ServingPreflightError("merge manifest contains an invalid file hash")
        target = checkpoint / name
        if not target.is_file() or _sha256_file(target) != expected_hash:
            raise ServingPreflightError(f"checkpoint file hash mismatch: {name}")

    return {
        "path": str(checkpoint),
        "architecture": config["architectures"][0],
        "expected_keys": expected_keys,
        "saved_keys": saved_keys,
        "replaced_language_keys": replaced,
        "files_hashed": len(files),
    }


def _validate_platform(plan: Mapping[str, Any]) -> dict[str, Any]:
    expected = plan["platform"]
    actual_os = platform.system().lower()
    actual_arch = platform.machine().lower()
    actual_python = f"{sys.version_info.major}.{sys.version_info.minor}"
    if actual_os != expected["os"]:
        raise ServingPreflightError(
            f"OS mismatch: expected={expected['os']} actual={actual_os}"
        )
    if actual_arch not in {expected["architecture"], "amd64"}:
        raise ServingPreflightError(
            f"architecture mismatch: expected={expected['architecture']} actual={actual_arch}"
        )
    if actual_python != expected["python_version"]:
        raise ServingPreflightError(
            f"Python mismatch: expected={expected['python_version']} actual={actual_python}"
        )

    uv_output = _run(["uv", "--version"])
    actual_uv = _uv_version(uv_output)
    if actual_uv != expected["resolver_version"]:
        raise ServingPreflightError(
            f"uv version mismatch: expected={expected['resolver_version']} actual={actual_uv}"
        )
    return {"os": actual_os, "architecture": actual_arch, "python": actual_python, "uv": actual_uv}


def _validate_gpu(plan: Mapping[str, Any]) -> dict[str, Any]:
    expected = plan["platform"]
    output = _run(
        [
            "nvidia-smi",
            "--query-gpu=driver_version,name,memory.total",
            "--format=csv,noheader,nounits",
            "--id=0",
        ]
    )
    first_line = output.splitlines()[0] if output else ""
    fields = [field.strip() for field in first_line.split(",", 2)]
    if len(fields) != 3:
        raise ServingPreflightError("could not parse nvidia-smi output")
    driver, name, memory_mib_text = fields
    if _numeric_version(driver) < _numeric_version(expected["minimum_nvidia_driver"]):
        raise ServingPreflightError(
            f"NVIDIA driver is below the strict canary minimum: {driver}"
        )

    try:
        torch = importlib.import_module("torch")
        if not torch.cuda.is_available():
            raise ServingPreflightError("torch cannot access CUDA")
        if torch.version.cuda != expected["torch_cuda_version"]:
            raise ServingPreflightError(
                f"torch CUDA build mismatch: expected={expected['torch_cuda_version']} "
                f"actual={torch.version.cuda}"
            )
        capability = tuple(int(part) for part in torch.cuda.get_device_capability(0))
        minimum_capability = _numeric_version(expected["minimum_compute_capability"])
        if capability < minimum_capability:
            raise ServingPreflightError(
                f"GPU compute capability is below minimum: {capability}"
            )
        allowed_gpu_names = expected.get("allowed_gpu_names", [])
        if allowed_gpu_names and name not in allowed_gpu_names:
            raise ServingPreflightError(
                f"GPU is outside the canary allowlist: {name}"
            )
        capability_text = ".".join(str(part) for part in capability)
        allowed_capabilities = expected.get("allowed_compute_capabilities", [])
        if allowed_capabilities and capability_text not in allowed_capabilities:
            raise ServingPreflightError(
                "GPU compute capability is outside the canary allowlist: "
                f"{capability_text}"
            )
        if expected["require_bfloat16"] and not torch.cuda.is_bf16_supported():
            raise ServingPreflightError("GPU does not support bfloat16")
        memory_gib = int(memory_mib_text) / 1024
        if memory_gib < float(expected["minimum_vram_gib"]):
            raise ServingPreflightError(
                f"GPU VRAM is below minimum: {memory_gib:.2f} GiB"
            )
    except AttributeError as error:
        raise ServingPreflightError("installed torch lacks required CUDA APIs") from error

    return {
        "name": name,
        "driver": driver,
        "memory_gib": round(memory_gib, 2),
        "compute_capability": capability_text,
        "torch_cuda": torch.version.cuda,
        "bfloat16": True,
    }


def _validate_installation_policy(plan: Mapping[str, Any]) -> dict[str, str]:
    policy = plan["installation_policy"]
    contract = plan["binary_contract"]
    checked: dict[str, str] = {}
    for label, path_key, hash_key in (
        ("requirements", "requirements_path", "requirements_sha256"),
        ("lock", "resolved_lock_path", "resolved_lock_sha256"),
    ):
        target = (REPOSITORY_ROOT / policy[path_key]).resolve()
        try:
            target.relative_to(REPOSITORY_ROOT)
        except ValueError as error:
            raise ServingPreflightError(
                f"{label} path escapes repository root: {target}"
            ) from error
        expected_hash = policy[hash_key]
        if not target.is_file() or _sha256_file(target) != expected_hash:
            raise ServingPreflightError(f"{label} file hash mismatch: {target}")
        checked[f"{label}_sha256"] = expected_hash

    for index, layer in enumerate(policy.get("additional_layers", []), start=1):
        if not isinstance(layer, dict):
            raise ServingPreflightError("additional installation layer must be an object")
        layer_name = layer.get("name")
        if not isinstance(layer_name, str) or not layer_name:
            raise ServingPreflightError("additional installation layer has no name")
        for label, path_key, hash_key in (
            ("requirements", "requirements_path", "requirements_sha256"),
            ("lock", "resolved_lock_path", "resolved_lock_sha256"),
        ):
            target = (REPOSITORY_ROOT / layer[path_key]).resolve()
            try:
                target.relative_to(REPOSITORY_ROOT)
            except ValueError as error:
                raise ServingPreflightError(
                    f"additional {label} path escapes repository root: {target}"
                ) from error
            expected_hash = layer[hash_key]
            if not target.is_file() or _sha256_file(target) != expected_hash:
                raise ServingPreflightError(
                    f"additional {label} file hash mismatch: {target}"
                )
            checked[f"layer_{index}_{layer_name}_{label}_sha256"] = expected_hash

    lock_text = (REPOSITORY_ROOT / policy["resolved_lock_path"]).read_text(
        encoding="utf-8"
    )
    if contract["vllm_wheel_url"] not in lock_text:
        raise ServingPreflightError("vLLM wheel URL is absent from the hash lock")
    expected_hash_pin = f"--hash=sha256:{contract['vllm_wheel_sha256']}"
    if expected_hash_pin not in lock_text:
        raise ServingPreflightError("vLLM wheel hash is absent from the hash lock")
    return checked


def _validate_vllm_binary(plan: Mapping[str, Any]) -> dict[str, Any]:
    contract = plan["binary_contract"]
    for distribution, expected_version in contract["exact_distribution_versions"].items():
        try:
            actual_version = importlib.metadata.version(distribution)
        except importlib.metadata.PackageNotFoundError as error:
            raise ServingPreflightError(
                f"missing distribution for binary contract: {distribution}"
            ) from error
        if actual_version != expected_version:
            raise ServingPreflightError(
                f"{distribution} binary version mismatch: "
                f"expected={expected_version} actual={actual_version}"
            )

    distribution = importlib.metadata.distribution("vllm")
    direct_url_text = distribution.read_text("direct_url.json")
    if direct_url_text is None:
        raise ServingPreflightError("vLLM direct_url.json is missing")
    try:
        direct_url = json.loads(direct_url_text)
    except json.JSONDecodeError as error:
        raise ServingPreflightError("vLLM direct_url.json is invalid") from error
    if direct_url.get("url") != contract["vllm_wheel_url"]:
        raise ServingPreflightError("vLLM wheel source URL mismatch")

    vllm_module = importlib.import_module("vllm")
    package_file = getattr(vllm_module, "__file__", None)
    if not package_file:
        raise ServingPreflightError("could not locate the vLLM package")
    extension = Path(package_file).resolve().parent / contract["vllm_extension"]
    if not extension.is_file():
        raise ServingPreflightError(f"vLLM native extension is missing: {extension}")
    needed = _needed_libraries(_run(["readelf", "-d", str(extension)]))
    required_library = contract["required_cuda_library"]
    if required_library not in needed:
        raise ServingPreflightError(
            f"vLLM native extension does not require {required_library}"
        )
    forbidden = sorted(set(contract["forbidden_cuda_libraries"]) & needed)
    if forbidden:
        raise ServingPreflightError(
            f"vLLM native extension has forbidden CUDA dependencies: {forbidden}"
        )

    executable_paths: dict[str, str] = {}
    venv_bin = Path(sys.executable).parent
    for executable_name in contract["required_runtime_executables"]:
        expected_executable = venv_bin / executable_name
        discovered = shutil.which(executable_name)
        if (
            not expected_executable.is_file()
            or discovered is None
            or Path(discovered).resolve() != expected_executable.resolve()
        ):
            raise ServingPreflightError(
                f"runtime PATH must resolve {executable_name} from {venv_bin}"
            )
        executable_paths[executable_name] = discovered
    return {
        "vllm_wheel_url": direct_url["url"],
        "vllm_wheel_sha256": contract["vllm_wheel_sha256"],
        "vllm_native_extension": str(extension),
        "vllm_needed_libraries": sorted(needed),
        "runtime_executables": executable_paths,
    }


def _validate_python_stack(plan: Mapping[str, Any]) -> dict[str, Any]:
    expected = dict(plan["packages"])
    expected.update(plan["vllm_cuda_release_pins"])
    installed = _installed_versions(expected)
    errors = _version_errors(expected, installed)
    if errors:
        raise ServingPreflightError("; ".join(errors))

    for module in (
        "torch",
        "torchaudio",
        "torchvision",
        "tokenizers",
        "transformers",
        "vllm",
    ):
        try:
            importlib.import_module(module)
        except Exception as error:
            raise ServingPreflightError(f"import failed: {module}: {error}") from error
    try:
        transformers = importlib.import_module("transformers")
        getattr(transformers, "Qwen3_5ForCausalLM")
        qwen_vllm = importlib.import_module("vllm.model_executor.models.qwen3_5")
        getattr(qwen_vllm, "Qwen3_5ForConditionalGeneration")
    except (ImportError, AttributeError) as error:
        raise ServingPreflightError("Qwen3.5 classes are unavailable") from error

    binary = _validate_vllm_binary(plan)
    _run([sys.executable, "-m", "pip", "check"], timeout=120)
    freeze = _run([sys.executable, "-m", "pip", "freeze", "--all"], timeout=120)
    normalized = (
        "\n".join(
            sorted(line.strip() for line in freeze.splitlines() if line.strip())
        )
        + "\n"
    )
    return {
        **installed,
        **binary,
        "pip_freeze_sha256": hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
    }


def preflight(
    manifest_path: Path,
    checkpoint: Path,
    image_digest: str,
) -> dict[str, Any]:
    """불변 image digest와 runtime stack·GPU·정적 checkpoint를 모두 대조한다."""
    manifest = _load_json(manifest_path, "canary manifest")
    if not _IMAGE_DIGEST.fullmatch(image_digest):
        raise ServingPreflightError("a sha256 container image digest is required")
    plan = manifest["serving_plan"]
    if plan["status"] not in {"NOT_RUN", "CANARY_SMOKE_PASS_NOT_DEPLOYED"}:
        raise ServingPreflightError("serving manifest has an unsafe status")
    if plan["structured_outputs"]["legacy_guided_json_supported"] is not False:
        raise ServingPreflightError("legacy guided_json must remain disabled")

    installation = _validate_installation_policy(plan)
    platform_result = _validate_platform(plan)
    versions = _validate_python_stack(plan)
    gpu = _validate_gpu(plan)
    checkpoint_result = _validate_checkpoint(checkpoint, plan["static_checkpoint"])
    return {
        "status": "PASS_SERVING_PREFLIGHT",
        "production_switch_allowed": False,
        "manifest_version": manifest["manifest_version"],
        "image_digest": image_digest,
        "installation": installation,
        "platform": platform_result,
        "gpu": gpu,
        "packages": versions,
        "checkpoint": checkpoint_result,
        "next_stage": "START_ISOLATED_VLLM_CANARY",
    }


def main() -> int:
    """RunPod preflight를 실행하고 배포 가능 여부를 숨기지 않는 JSON으로 종료한다."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument(
        "--image-digest",
        default=os.environ.get("NODE2_VLLM_IMAGE_DIGEST", ""),
    )
    args = parser.parse_args()
    try:
        result = preflight(args.manifest, args.checkpoint, args.image_digest)
        exit_code = 0
    except (KeyError, TypeError, ServingPreflightError) as error:
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
