#!/usr/bin/env python3
"""Node2 canary 증거 ZIP을 추출·실행하지 않고 checksum과 계약 집합으로 검증한다."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import struct
import sys
import zipfile
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = (
    REPOSITORY_ROOT / "evals" / "node2_qwen35_2b_full3000_canary.v1.json"
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_LORA_TENSOR = re.compile(
    r"^(?:base_model\.model\.)?(.+)\.lora_([AB])\.weight$"
)


class EvidenceVerificationError(ValueError):
    """제공된 archive가 불변 canary checksum·record·adapter 계약과 다름을 알린다."""


def _sha256_stream(source: BinaryIO) -> str:
    digest = hashlib.sha256()
    for chunk in iter(lambda: source.read(1024 * 1024), b""):
        digest.update(chunk)
    return digest.hexdigest()


def _sha256_file(path: Path) -> str:
    with path.open("rb") as source:
        return _sha256_stream(source)


def _normalized_distribution(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _verify_serving_resolution(manifest: dict[str, Any]) -> int:
    plan = manifest["serving_plan"]
    policy = plan["installation_policy"]
    requirements_path = REPOSITORY_ROOT / str(policy["requirements_path"])
    lock_path = REPOSITORY_ROOT / str(policy["resolved_lock_path"])
    if _sha256_file(requirements_path) != policy["requirements_sha256"]:
        raise EvidenceVerificationError("serving requirements SHA-256 mismatch")
    if _sha256_file(lock_path) != policy["resolved_lock_sha256"]:
        raise EvidenceVerificationError("serving lock SHA-256 mismatch")
    try:
        text = lock_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise EvidenceVerificationError("serving lock is unavailable") from error

    pinned_entries = re.findall(
        r"^([A-Za-z0-9_.-]+)==([^\s\\]+)(?:\s+\\)?$",
        text,
        flags=re.MULTILINE,
    )
    direct_entries = re.findall(
        r"^([A-Za-z0-9_.-]+)\s+@\s+(https://[^\s\\]+)(?:\s+\\)?$",
        text,
        flags=re.MULTILINE,
    )
    versions = {
        _normalized_distribution(name): version for name, version in pinned_entries
    }
    direct_urls = {
        _normalized_distribution(name): url for name, url in direct_entries
    }
    entry_count = len(pinned_entries) + len(direct_entries)
    if (
        len(pinned_entries) != len(versions)
        or len(direct_entries) != len(direct_urls)
        or set(versions) & set(direct_urls)
    ):
        raise EvidenceVerificationError("serving lock has duplicate distributions")
    if entry_count != policy["resolved_package_count"]:
        raise EvidenceVerificationError("serving lock package count mismatch")

    for layer in policy.get("additional_layers", []):
        layer_requirements = REPOSITORY_ROOT / str(layer["requirements_path"])
        layer_lock = REPOSITORY_ROOT / str(layer["resolved_lock_path"])
        if _sha256_file(layer_requirements) != layer["requirements_sha256"]:
            raise EvidenceVerificationError(
                "additional serving requirements SHA-256 mismatch"
            )
        if _sha256_file(layer_lock) != layer["resolved_lock_sha256"]:
            raise EvidenceVerificationError("additional serving lock SHA-256 mismatch")
        try:
            layer_text = layer_lock.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as error:
            raise EvidenceVerificationError(
                "additional serving lock is unavailable"
            ) from error

        layer_pinned_entries = re.findall(
            r"^([A-Za-z0-9_.-]+)==([^\s\\]+)(?:\s+\\)?$",
            layer_text,
            flags=re.MULTILINE,
        )
        layer_direct_entries = re.findall(
            r"^([A-Za-z0-9_.-]+)\s+@\s+(https://[^\s\\]+)(?:\s+\\)?$",
            layer_text,
            flags=re.MULTILINE,
        )
        layer_versions = {
            _normalized_distribution(name): version
            for name, version in layer_pinned_entries
        }
        layer_direct_urls = {
            _normalized_distribution(name): url
            for name, url in layer_direct_entries
        }
        layer_entry_count = len(layer_pinned_entries) + len(layer_direct_entries)
        if (
            len(layer_pinned_entries) != len(layer_versions)
            or len(layer_direct_entries) != len(layer_direct_urls)
            or set(layer_versions) & set(layer_direct_urls)
        ):
            raise EvidenceVerificationError(
                "additional serving lock has duplicate distributions"
            )
        if layer_entry_count != layer["resolved_package_count"]:
            raise EvidenceVerificationError(
                "additional serving lock package count mismatch"
            )

        new_count = 0
        mismatch_count = 0
        for name, version in layer_versions.items():
            if name in versions:
                mismatch_count += int(versions[name] != version)
            elif name in direct_urls:
                mismatch_count += 1
            else:
                versions[name] = version
                new_count += 1
        for name, url in layer_direct_urls.items():
            if name in direct_urls:
                mismatch_count += int(direct_urls[name] != url)
            elif name in versions:
                mismatch_count += 1
            else:
                direct_urls[name] = url
                new_count += 1

        if new_count != layer["new_package_count"]:
            raise EvidenceVerificationError(
                "additional serving lock new package count mismatch"
            )
        if mismatch_count != layer["overlap_version_mismatch_count"]:
            raise EvidenceVerificationError(
                "additional serving lock overlap version mismatch"
            )
        if layer_text.count("--hash=sha256:") < layer_entry_count:
            raise EvidenceVerificationError(
                "additional serving lock is missing artifact hashes"
            )

    expected = dict(plan["packages"])
    expected.update(plan["vllm_cuda_release_pins"])
    for name, expected_version in expected.items():
        normalized_name = _normalized_distribution(name)
        actual = versions.get(normalized_name)
        if normalized_name == "vllm" and normalized_name in direct_urls:
            contract = plan["binary_contract"]
            if direct_urls[normalized_name] != contract["vllm_wheel_url"]:
                raise EvidenceVerificationError("serving lock vLLM URL mismatch")
            actual = contract["exact_distribution_versions"]["vllm"]
        if actual is None or actual.split("+", 1)[0] != expected_version:
            raise EvidenceVerificationError(
                f"serving lock version mismatch for {name}"
            )

    required_header_values = (
        f"--python-platform {policy['resolution_target'].split('-python', 1)[0]}",
        "--python-version 3.12",
        "--torch-backend cu129",
        f"--exclude-newer {policy['resolution_exclude_newer']}",
        "--generate-hashes",
    )
    if not all(value in text for value in required_header_values):
        raise EvidenceVerificationError("serving lock resolution header mismatch")
    if policy["resolution_has_artifact_hashes"] and (
        text.count("--hash=sha256:") < entry_count
    ):
        raise EvidenceVerificationError("serving lock is missing artifact hashes")
    return entry_count


def _sha256_member(archive: zipfile.ZipFile, name: str) -> str:
    with archive.open(name) as source:
        return _sha256_stream(source)


def _safe_member(name: str) -> bool:
    path = PurePosixPath(name)
    return bool(name) and not path.is_absolute() and ".." not in path.parts


def _parse_sums(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for line_number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        match = re.fullmatch(r"([0-9a-f]{64})\s+\*?(.+)", line)
        if match is None:
            raise EvidenceVerificationError(
                f"invalid SHA256SUMS line {line_number}"
            )
        digest, name = match.groups()
        name = name.replace("\\", "/")
        if not _safe_member(name) or name in result:
            raise EvidenceVerificationError(
                f"unsafe or duplicate SHA256SUMS member: {name}"
            )
        result[name] = digest
    if not result:
        raise EvidenceVerificationError("SHA256SUMS is empty")
    return result


def _verify_checksum_manifest(
    archive: zipfile.ZipFile,
    *,
    root: str,
    checksum_name: str = "SHA256SUMS",
) -> int:
    if not root.endswith("/"):
        raise EvidenceVerificationError("archive root must end with a slash")
    members = tuple(archive.infolist())
    unsafe = [entry.filename for entry in members if not _safe_member(entry.filename)]
    if unsafe:
        raise EvidenceVerificationError(f"unsafe ZIP members: {unsafe[:3]}")
    outside = [entry.filename for entry in members if not entry.filename.startswith(root)]
    if outside:
        raise EvidenceVerificationError(f"ZIP members outside expected root: {outside[:3]}")
    manifest_path = root + checksum_name
    try:
        expected = _parse_sums(archive.read(manifest_path).decode("utf-8"))
    except KeyError as error:
        raise EvidenceVerificationError(f"missing {manifest_path}") from error
    actual_names = {
        entry.filename[len(root) :]
        for entry in members
        if not entry.is_dir() and entry.filename != manifest_path
    }
    if actual_names != set(expected):
        missing = sorted(set(expected) - actual_names)
        unlisted = sorted(actual_names - set(expected))
        raise EvidenceVerificationError(
            f"SHA256SUMS membership mismatch: missing={missing[:3]} unlisted={unlisted[:3]}"
        )
    for relative_name, expected_digest in expected.items():
        actual_digest = _sha256_member(archive, root + relative_name)
        if actual_digest != expected_digest:
            raise EvidenceVerificationError(
                f"SHA-256 mismatch for {relative_name}"
            )
    return len(expected)


def _load_json_member(archive: zipfile.ZipFile, name: str) -> dict[str, Any]:
    try:
        value = json.loads(archive.read(name))
    except (KeyError, json.JSONDecodeError, UnicodeDecodeError) as error:
        raise EvidenceVerificationError(f"invalid JSON member: {name}") from error
    if not isinstance(value, dict):
        raise EvidenceVerificationError(f"JSON member must be an object: {name}")
    return value


def _load_json_lines(
    archive: zipfile.ZipFile,
    name: str,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    try:
        source = archive.open(name)
    except KeyError as error:
        raise EvidenceVerificationError(f"missing JSONL member: {name}") from error
    with source, io.TextIOWrapper(source, encoding="utf-8") as text:
        for line_number, line in enumerate(text, 1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as error:
                raise EvidenceVerificationError(
                    f"invalid JSONL member {name} at line {line_number}"
                ) from error
            if not isinstance(value, dict):
                raise EvidenceVerificationError(
                    f"JSONL record must be an object: {name}:{line_number}"
                )
            result.append(value)
    return result


def _verify_records(
    archive: zipfile.ZipFile,
    root: str,
    expectations: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    loaded: dict[str, list[dict[str, Any]]] = {}
    for expectation in expectations:
        relative = str(expectation["path"])
        records = _load_json_lines(archive, root + relative)
        loaded[relative] = records
        if len(records) != expectation["count"]:
            raise EvidenceVerificationError(
                f"record count mismatch for {relative}: {len(records)}"
            )
        case_ids = [record.get("case_id") for record in records]
        if any(not isinstance(case_id, str) or not case_id for case_id in case_ids):
            raise EvidenceVerificationError(f"invalid case_id in {relative}")
        if len(case_ids) != len(set(case_ids)):
            raise EvidenceVerificationError(f"duplicate case_id in {relative}")
        expected_nodes = expectation.get("node_counts")
        if expected_nodes is not None:
            observed_nodes = dict(Counter(record.get("node") for record in records))
            if observed_nodes != expected_nodes:
                raise EvidenceVerificationError(
                    f"node count mismatch for {relative}: {observed_nodes}"
                )
    return loaded


def _parse_condition(condition: str) -> tuple[str, Any]:
    field, separator, raw_value = condition.partition("=")
    if not separator or not field:
        raise EvidenceVerificationError(f"invalid metric condition: {condition}")
    values: dict[str, Any] = {"true": True, "false": False, "null": None}
    return field, values.get(raw_value, raw_value)


def _verify_metrics(
    records: dict[str, list[dict[str, Any]]],
    expectations: list[dict[str, Any]],
) -> None:
    for expectation in expectations:
        path = str(expectation["path"])
        try:
            rows = records[path]
        except KeyError as error:
            raise EvidenceVerificationError(
                f"metric source was not loaded: {path}"
            ) from error
        for condition, expected_count in expectation["count_if"].items():
            field, expected_value = _parse_condition(condition)
            observed = sum(row.get(field) == expected_value for row in rows)
            if observed != expected_count:
                raise EvidenceVerificationError(
                    f"metric mismatch for {path} {condition}: {observed}"
                )


def _definition_closure(document: dict[str, Any], roots: list[str]) -> set[str]:
    definitions = document.get("$defs")
    if not isinstance(definitions, dict):
        raise EvidenceVerificationError("contract has no $defs object")
    pending = list(roots)
    result: set[str] = set()
    while pending:
        name = pending.pop()
        if name in result:
            continue
        definition = definitions.get(name)
        if not isinstance(definition, dict):
            raise EvidenceVerificationError(f"missing contract definition: {name}")
        result.add(name)
        serialized = json.dumps(definition, ensure_ascii=False)
        pending.extend(
            reference
            for reference in re.findall(r'"\$ref":\s*"#/\$defs/([^"/]+)"', serialized)
            if reference not in result
        )
    return result


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _verify_contract(
    nested: zipfile.ZipFile,
    nested_root: str,
    contract: dict[str, Any],
) -> int:
    current_path = REPOSITORY_ROOT / str(contract["current_contract_path"])
    try:
        current = json.loads(current_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise EvidenceVerificationError("current contract is unavailable") from error
    source = _load_json_member(
        nested,
        nested_root + str(contract["source_contract_path"]),
    )
    if source.get("version") != contract["source_version"]:
        raise EvidenceVerificationError("source contract version mismatch")
    if current.get("version") != contract["current_version"]:
        raise EvidenceVerificationError("current contract version mismatch")
    roots = [str(name) for name in contract["definition_roots"]]
    source_names = _definition_closure(source, roots)
    current_names = _definition_closure(current, roots)
    if source_names != current_names:
        raise EvidenceVerificationError("Node2 contract definition sets differ")
    for name in sorted(source_names):
        if _canonical_json(source["$defs"][name]) != _canonical_json(
            current["$defs"][name]
        ):
            raise EvidenceVerificationError(
                f"Node2 contract definition changed: {name}"
            )
    return len(source_names)


def _system_prompt_counts(records: list[dict[str, Any]]) -> Counter[tuple[str, str]]:
    result: Counter[tuple[str, str]] = Counter()
    for record in records:
        messages = record.get("messages")
        if not isinstance(messages, list):
            raise EvidenceVerificationError("compiled record has no messages")
        system = [
            message.get("content")
            for message in messages
            if isinstance(message, dict) and message.get("role") == "system"
        ]
        if len(system) != 1 or not isinstance(system[0], str):
            raise EvidenceVerificationError("compiled record has invalid system prompt")
        node = record.get("node")
        if not isinstance(node, str):
            raise EvidenceVerificationError("compiled record has invalid node")
        result[(node, hashlib.sha256(system[0].encode("utf-8")).hexdigest())] += 1
    return result


def _verify_prompts(
    train: list[dict[str, Any]],
    validation: list[dict[str, Any]],
    prompts: dict[str, Any],
) -> None:
    sys.path.insert(0, str(REPOSITORY_ROOT))
    from src.ai.prompt_registry import get_prompt

    train_counts = _system_prompt_counts(train)
    validation_counts = _system_prompt_counts(validation)
    for node, expectation in prompts.items():
        prompt = get_prompt(str(expectation["prompt_id"]))
        metadata = prompt.metadata()
        expected_hash = str(expectation["sha256"])
        if (
            prompt.version != expectation["version"]
            or metadata["hash"] != expected_hash
        ):
            raise EvidenceVerificationError(f"current prompt mismatch for {node}")
        if train_counts[(node, expected_hash)] != expectation["train_records"]:
            raise EvidenceVerificationError(f"training prompt count mismatch for {node}")
        if (
            validation_counts[(node, expected_hash)]
            != expectation["validation_records"]
        ):
            raise EvidenceVerificationError(
                f"validation prompt count mismatch for {node}"
            )
    expected_train = sum(item["train_records"] for item in prompts.values())
    expected_validation = sum(
        item["validation_records"] for item in prompts.values()
    )
    if sum(train_counts.values()) != expected_train:
        raise EvidenceVerificationError("unexpected training system prompt")
    if sum(validation_counts.values()) != expected_validation:
        raise EvidenceVerificationError("unexpected validation system prompt")


def _adapter_modules(
    archive: zipfile.ZipFile,
    name: str,
) -> tuple[dict[str, set[str]], set[str]]:
    try:
        source = archive.open(name)
    except KeyError as error:
        raise EvidenceVerificationError(f"missing adapter: {name}") from error
    with source:
        length_bytes = source.read(8)
        if len(length_bytes) != 8:
            raise EvidenceVerificationError("invalid safetensors header length")
        header_length = struct.unpack("<Q", length_bytes)[0]
        if header_length <= 0 or header_length > 16 * 1024 * 1024:
            raise EvidenceVerificationError("unsafe safetensors header length")
        header_bytes = source.read(header_length)
        if len(header_bytes) != header_length:
            raise EvidenceVerificationError("truncated safetensors header")
    try:
        header = json.loads(header_bytes)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise EvidenceVerificationError("invalid safetensors header") from error
    modules: dict[str, set[str]] = {}
    dtypes: set[str] = set()
    for key, value in header.items():
        if key == "__metadata__":
            continue
        if not isinstance(value, dict) or not isinstance(value.get("dtype"), str):
            raise EvidenceVerificationError(f"invalid tensor metadata: {key}")
        match = _LORA_TENSOR.fullmatch(key)
        if match is None:
            raise EvidenceVerificationError(f"unexpected adapter tensor: {key}")
        module, side = match.groups()
        modules.setdefault(module, set()).add(side)
        dtypes.add(value["dtype"])
    return modules, dtypes


def _verify_adapter(
    archive: zipfile.ZipFile,
    root: str,
    expectation: dict[str, Any],
    expected_sha256: str,
) -> dict[str, int]:
    adapter_path = root + str(expectation["path"])
    if _sha256_member(archive, adapter_path) != expected_sha256:
        raise EvidenceVerificationError("adapter SHA-256 mismatch")
    corrected = _load_json_member(
        archive,
        root + str(expectation["corrected_manifest_path"]),
    )
    modules, dtypes = _adapter_modules(archive, adapter_path)
    if any(sides != {"A", "B"} for sides in modules.values()):
        raise EvidenceVerificationError("adapter has an incomplete LoRA A/B pair")
    actual_names = set(modules)
    corrected_names = set(
        corrected.get("targeting_correction", {}).get("actual_module_names", [])
    )
    tensor_count = sum(len(sides) for sides in modules.values())
    counts = {
        "tensor_count": tensor_count,
        "module_count": len(modules),
        "mlp_modules": sum(".mlp." in name for name in modules),
        "self_attention_modules": sum(".self_attn." in name for name in modules),
        "linear_attention_modules": sum("linear_attn" in name for name in modules),
    }
    for field, observed in counts.items():
        if observed != expectation[field]:
            raise EvidenceVerificationError(
                f"adapter {field} mismatch: {observed}"
            )
    if dtypes != {expectation["dtype"]}:
        raise EvidenceVerificationError(f"adapter dtype mismatch: {sorted(dtypes)}")
    if actual_names != corrected_names:
        raise EvidenceVerificationError(
            "corrected manifest does not match adapter modules"
        )
    return counts


def verify(evidence_zip: Path, manifest_path: Path = DEFAULT_MANIFEST) -> dict[str, Any]:
    """정적 준비 증거를 검증하고 첫 불변식 불일치에서 즉시 중단한다."""
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise EvidenceVerificationError("canary manifest is unavailable") from error
    expected_archive_hash = manifest["evidence"]["archive_sha256"]
    if not _SHA256.fullmatch(expected_archive_hash):
        raise EvidenceVerificationError("manifest archive SHA-256 is invalid")
    actual_archive_hash = _sha256_file(evidence_zip)
    if actual_archive_hash != expected_archive_hash:
        raise EvidenceVerificationError("evidence archive SHA-256 mismatch")
    serving_lock_packages = _verify_serving_resolution(manifest)

    evidence = manifest["evidence"]
    root = str(evidence["root"])
    with zipfile.ZipFile(evidence_zip) as outer:
        outer_files = _verify_checksum_manifest(outer, root=root)
        outer_records = _verify_records(
            outer,
            root,
            manifest["records"]["outer"],
        )
        _verify_metrics(outer_records, manifest["metrics"])
        adapter_counts = _verify_adapter(
            outer,
            root,
            manifest["adapter"],
            manifest["subject"]["adapter_sha256"],
        )
        nested_entry = root + str(evidence["nested_input_entry"])
        nested_bytes = outer.read(nested_entry)
        if hashlib.sha256(nested_bytes).hexdigest() != evidence["nested_input_sha256"]:
            raise EvidenceVerificationError("nested input ZIP SHA-256 mismatch")
        with zipfile.ZipFile(io.BytesIO(nested_bytes)) as nested:
            nested_root = str(evidence["nested_root"])
            nested_files = _verify_checksum_manifest(nested, root=nested_root)
            nested_records = _verify_records(
                nested,
                nested_root,
                manifest["records"]["nested"],
            )
            definition_count = _verify_contract(
                nested,
                nested_root,
                manifest["contract"],
            )
            _verify_prompts(
                nested_records["data/train.jsonl"],
                nested_records["data/validation.jsonl"],
                manifest["contract"]["prompts"],
            )

    return {
        "status": "PASS_STATIC_PREPARED",
        "deployable": False,
        "external_actions_performed": False,
        "manifest_version": manifest["manifest_version"],
        "archive_sha256": actual_archive_hash,
        "adapter_sha256": manifest["subject"]["adapter_sha256"],
        "outer_files_verified": outer_files,
        "nested_files_verified": nested_files,
        "serving_lock_packages_verified": serving_lock_packages,
        "node2_contract_definitions_unchanged": definition_count,
        "adapter": adapter_counts,
        "known_not_run": manifest["known_not_run"],
        "next_stage": "RUNPOD_CANARY_REQUIRES_EXPLICIT_APPROVAL",
    }


def main() -> int:
    """canary archive 검증 결과를 비밀 없는 JSON으로 출력하고 실패 코드를 보존한다."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-zip", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        result = verify(args.evidence_zip, args.manifest)
        exit_code = 0
    except (EvidenceVerificationError, OSError, zipfile.BadZipFile) as error:
        result = {
            "status": "FAIL",
            "deployable": False,
            "external_actions_performed": False,
            "error": str(error),
        }
        exit_code = 1
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
