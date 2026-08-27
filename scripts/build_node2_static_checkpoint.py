#!/usr/bin/env python3
"""검증된 LoRA 대상만 교체해 Node2 정적 checkpoint를 결정론적으로 조립한다."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from contextlib import ExitStack
from pathlib import Path
from typing import Iterable


ADAPTER_PREFIX = "base_model.model.model."
FULL_MODEL_PREFIX = "model.language_model."
LORA_SUFFIXES = (".lora_A.weight", ".lora_B.weight")
TOKENIZER_FILES = (
    "chat_template.jinja",
    "special_tokens_map.json",
    "tokenizer.json",
    "tokenizer_config.json",
)


class StaticCheckpointBuildError(RuntimeError):
    """base·adapter·병합 checkpoint 중 하나가 고정된 tensor 계약을 위반했음을 알린다."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def adapter_target_keys(adapter_keys: Iterable[str]) -> set[str]:
    """A/B 쌍이 완전한 PEFT LoRA tensor만 full-checkpoint weight 이름으로 변환한다."""
    pairs: dict[str, set[str]] = {}
    for key in adapter_keys:
        if not key.startswith(ADAPTER_PREFIX):
            raise StaticCheckpointBuildError(f"unexpected adapter key prefix: {key}")
        suffix = next((item for item in LORA_SUFFIXES if key.endswith(item)), None)
        if suffix is None:
            raise StaticCheckpointBuildError(f"unexpected adapter key suffix: {key}")
        relative_module = key[len(ADAPTER_PREFIX) : -len(suffix)]
        target = f"{FULL_MODEL_PREFIX}{relative_module}.weight"
        pairs.setdefault(target, set()).add(suffix)

    if not pairs:
        raise StaticCheckpointBuildError("adapter has no LoRA target tensors")
    incomplete = sorted(
        target for target, suffixes in pairs.items() if suffixes != set(LORA_SUFFIXES)
    )
    if incomplete:
        raise StaticCheckpointBuildError(
            f"adapter target is missing an A/B tensor pair: {incomplete[0]}"
        )
    return set(pairs)


def _weight_map(checkpoint: Path) -> dict[str, Path]:
    from safetensors import safe_open

    index = checkpoint / "model.safetensors.index.json"
    if index.is_file():
        try:
            raw = json.loads(index.read_text(encoding="utf-8"))["weight_map"]
        except (OSError, KeyError, json.JSONDecodeError, TypeError) as error:
            raise StaticCheckpointBuildError(
                f"invalid safetensors index: {index}"
            ) from error
        if not isinstance(raw, dict) or not raw:
            raise StaticCheckpointBuildError(f"empty safetensors index: {index}")
        result = {str(key): checkpoint / str(name) for key, name in raw.items()}
    else:
        model = checkpoint / "model.safetensors"
        if not model.is_file():
            raise StaticCheckpointBuildError(
                f"checkpoint has no safetensors weights: {checkpoint}"
            )
        with safe_open(model, framework="pt", device="cpu") as source:
            result = {key: model for key in source.keys()}

    missing = sorted({path for path in result.values() if not path.is_file()})
    if missing:
        raise StaticCheckpointBuildError(f"missing safetensors shard: {missing[0]}")
    return result


def build_static_checkpoint(
    *,
    base: Path,
    merged_text: Path,
    adapter: Path,
    output: Path,
    base_model: str,
    base_revision: str,
) -> dict[str, object]:
    """승인된 adapter 대상만 교체하고 나머지 base tensor와 key 집합을 그대로 보존한다."""
    from safetensors import safe_open
    from safetensors.torch import save_file

    base = base.resolve()
    merged_text = merged_text.resolve()
    adapter = adapter.resolve()
    output = output.resolve()
    if output.exists():
        raise StaticCheckpointBuildError(f"output already exists: {output}")

    adapter_model = adapter / "adapter_model.safetensors"
    if not adapter_model.is_file():
        raise StaticCheckpointBuildError(f"adapter weights are missing: {adapter_model}")
    with safe_open(adapter_model, framework="pt", device="cpu") as source:
        targets = adapter_target_keys(source.keys())

    base_map = _weight_map(base)
    merged_map = _weight_map(merged_text)
    missing_base = sorted(targets - set(base_map))
    missing_merged = sorted(targets - set(merged_map))
    if missing_base:
        raise StaticCheckpointBuildError(
            f"adapter target is absent from base: {missing_base[0]}"
        )
    if missing_merged:
        raise StaticCheckpointBuildError(
            f"adapter target is absent from merged text: {missing_merged[0]}"
        )

    tensors = {}
    with ExitStack() as stack:
        base_sources = {
            path: stack.enter_context(safe_open(path, framework="pt", device="cpu"))
            for path in set(base_map.values())
        }
        merged_sources = {
            path: stack.enter_context(safe_open(path, framework="pt", device="cpu"))
            for path in {merged_map[key] for key in targets}
        }
        for key in sorted(base_map):
            if key in targets:
                tensors[key] = merged_sources[merged_map[key]].get_tensor(key)
            else:
                tensors[key] = base_sources[base_map[key]].get_tensor(key)

    output.mkdir(parents=True)
    weights = output / "model.safetensors"
    save_file(tensors, weights, metadata={"format": "pt"})
    with safe_open(weights, framework="pt", device="cpu") as saved:
        saved_keys = set(saved.keys())
    expected_keys = set(base_map)
    if saved_keys != expected_keys:
        raise StaticCheckpointBuildError("saved checkpoint key set differs from base")

    for source in base.iterdir():
        if source.is_file() and not (
            source.name.endswith(".safetensors")
            or source.name == "model.safetensors.index.json"
        ):
            shutil.copy2(source, output / source.name)
    for name in TOKENIZER_FILES:
        source = adapter / name
        if source.is_file():
            shutil.copy2(source, output / name)

    target_list = "\n".join(sorted(targets)) + "\n"
    manifest = {
        "serving_mode": "merged_full_static_adapter_targets_only",
        "base_model": base_model,
        "base_revision": base_revision,
        "base_snapshot": str(base),
        "merged_text": str(merged_text),
        "adapter": str(adapter),
        "adapter_sha256": _sha256(adapter_model),
        "expected_keys": len(expected_keys),
        "saved_keys": len(saved_keys),
        "replaced_language_keys": len(targets),
        "preserved_base_keys": len(expected_keys - targets),
        "adapter_target_keys_sha256": hashlib.sha256(
            target_list.encode("utf-8")
        ).hexdigest(),
        "files": {
            path.name: _sha256(path)
            for path in sorted(output.iterdir())
            if path.is_file()
        },
    }
    (output / "merge_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def main() -> int:
    """필수 checkpoint 경로를 검증해 조립하고 tensor 수량 영수증을 출력한다."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--merged-text", type=Path, required=True)
    parser.add_argument("--adapter", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--base-model", required=True)
    parser.add_argument("--base-revision", required=True)
    args = parser.parse_args()
    result = build_static_checkpoint(
        base=args.base,
        merged_text=args.merged_text,
        adapter=args.adapter,
        output=args.output,
        base_model=args.base_model,
        base_revision=args.base_revision,
    )
    print(
        json.dumps(
            {
                "status": "PASS",
                "expected_keys": result["expected_keys"],
                "saved_keys": result["saved_keys"],
                "replaced_language_keys": result["replaced_language_keys"],
                "preserved_base_keys": result["preserved_base_keys"],
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
