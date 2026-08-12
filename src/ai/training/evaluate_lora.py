"""Generate SQL on a held-out split and report structural exact-match metrics."""

from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path
from typing import Any

from src.ai.training.dataset import DatasetError, load_compiled, validate_model_output, write_jsonl


DEFAULT_MODEL = "Qwen/Qwen3.5-4B"
DEFAULT_REVISION = None
IMMUTABLE_EVIDENCE_FIELDS = (
    "model_sha256",
    "prompt_sha256",
    "case_set_sha256",
    "decoding_sha256",
    "runtime_sha256",
    "artifact_sha256",
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class EvidenceError(ValueError):
    """Raised when captured comparison evidence cannot be trusted."""


def validate_captured_evidence(evidence: Any) -> dict[str, str]:
    """Require immutable SHA-256 evidence before comparing two captures."""
    if not isinstance(evidence, dict):
        raise EvidenceError("captured evidence must be an object")
    missing = [field for field in IMMUTABLE_EVIDENCE_FIELDS if field not in evidence]
    if missing:
        raise EvidenceError(f"captured evidence is missing {missing}")
    invalid = [
        field
        for field in IMMUTABLE_EVIDENCE_FIELDS
        if not isinstance(evidence[field], str) or _SHA256.fullmatch(evidence[field]) is None
    ]
    if invalid:
        raise EvidenceError(f"captured evidence has invalid hashes {invalid}")
    return {field: evidence[field] for field in IMMUTABLE_EVIDENCE_FIELDS}


def compare_captured_evidence(
    baseline: dict[str, Any], candidate: dict[str, Any]
) -> dict[str, Any]:
    """Return comparable only when every immutable capture hash is identical."""
    baseline_hashes = validate_captured_evidence(baseline)
    candidate_hashes = validate_captured_evidence(candidate)
    mismatched = [
        field
        for field in IMMUTABLE_EVIDENCE_FIELDS
        if baseline_hashes[field] != candidate_hashes[field]
    ]
    return {
        "comparable": not mismatched,
        "mismatched_fields": mismatched,
        "baseline": baseline_hashes,
        "candidate": candidate_hashes,
    }


def observed_metrics(
    *,
    accuracy: float,
    p50_ms: float,
    p95_ms: float,
    peak_vram_bytes: int | None,
    cost_usd: float | None = None,
) -> dict[str, Any]:
    """Keep only observed metrics; unknown cost remains explicitly nullable."""
    if isinstance(accuracy, bool) or not isinstance(accuracy, (int, float)) or not 0 <= accuracy <= 1:
        raise ValueError("accuracy must be between zero and one")
    for name, value in (("p50_ms", p50_ms), ("p95_ms", p95_ms), ("peak_vram_bytes", peak_vram_bytes)):
        if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0):
            raise ValueError(f"{name} must be non-negative or null")
    if cost_usd is not None and (isinstance(cost_usd, bool) or not isinstance(cost_usd, (int, float)) or cost_usd < 0):
        raise ValueError("cost_usd must be non-negative or null")
    return {
        "accuracy": accuracy,
        "p50_ms": p50_ms,
        "p95_ms": p95_ms,
        "peak_vram_bytes": peak_vram_bytes,
        "cost_usd": cost_usd,
    }


def _normalize_sql(sql: str) -> str:
    return re.sub(r"\s+", " ", sql.strip().rstrip(";")).casefold()


def _percentile(values: list[float], percentile: int) -> float:
    ordered = sorted(values)
    index = max(0, (len(ordered) * percentile + 99) // 100 - 1)
    return ordered[index]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument(
        "--split",
        choices=("validation", "gold", "acceptance"),
        default="validation",
    )
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--revision", default=DEFAULT_REVISION)
    parser.add_argument("--adapter")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-new-tokens", type=int, default=1_500)
    args = parser.parse_args()

    records = load_compiled(args.data, args.split)
    if not records:
        raise DatasetError(f"dataset has no {args.split} records")

    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA GPU is required; run this command on the RunPod A40")
    tokenizer_source = args.adapter or args.model
    tokenizer = AutoTokenizer.from_pretrained(tokenizer_source, revision=None if args.adapter else args.revision)
    model = AutoModelForCausalLM.from_pretrained(
        args.model,
        revision=args.revision,
        torch_dtype=torch.bfloat16,
        device_map="auto",
        low_cpu_mem_usage=True,
    )
    if args.adapter:
        model = PeftModel.from_pretrained(model, args.adapter)
    model.eval()
    torch.cuda.reset_peak_memory_stats()

    predictions = []
    latencies_ms = []
    for record in records:
        prompt = tokenizer.apply_chat_template(
            record["messages"][:-1],
            tokenize=False,
            add_generation_prompt=True,
            enable_thinking=False,
        )
        inputs = tokenizer(prompt, return_tensors="pt").to(model.device)
        torch.cuda.synchronize()
        started = time.perf_counter()
        with torch.inference_mode():
            generated = model.generate(
                **inputs,
                do_sample=False,
                max_new_tokens=args.max_new_tokens,
                pad_token_id=tokenizer.eos_token_id,
            )
        torch.cuda.synchronize()
        latency_ms = (time.perf_counter() - started) * 1_000
        latencies_ms.append(latency_ms)
        text = tokenizer.decode(generated[0, inputs.input_ids.shape[1] :], skip_special_tokens=True).strip()
        expected = json.loads(record["messages"][2]["content"])
        valid_json = True
        valid_structure = True
        try:
            actual = json.loads(text)
        except json.JSONDecodeError:
            actual = None
            valid_json = False
            valid_structure = False
        if valid_json:
            try:
                validate_model_output(record["node"], actual)
            except DatasetError:
                valid_structure = False
        sql_field = "sql" if record["node"] == "node2" else "corrected_sql"
        sql_match = bool(
            valid_structure
            and _normalize_sql(actual[sql_field]) == _normalize_sql(expected[sql_field])
        )
        exact_match = actual == expected
        predictions.append(
            {
                "case_id": record["case_id"],
                "valid_json": valid_json,
                "valid_structure": valid_structure,
                "sql_exact_match": sql_match,
                "exact_match": exact_match,
                "latency_ms": latency_ms,
                "generated_text": text,
            }
        )

    write_jsonl(args.output, predictions)
    total = len(predictions)
    peak_vram_bytes = torch.cuda.max_memory_allocated()
    summary = {
        "model": args.model,
        "adapter": args.adapter,
        "split": args.split,
        "total": total,
        "valid_json": sum(item["valid_json"] for item in predictions),
        "valid_structure": sum(item["valid_structure"] for item in predictions),
        "sql_exact_match": sum(item["sql_exact_match"] for item in predictions),
        "exact_match": sum(item["exact_match"] for item in predictions),
        "latency_p50_ms": _percentile(latencies_ms, 50),
        "latency_p95_ms": _percentile(latencies_ms, 95),
        "peak_vram_bytes": peak_vram_bytes,
        "observed": observed_metrics(
            accuracy=sum(item["sql_exact_match"] for item in predictions) / total,
            p50_ms=_percentile(latencies_ms, 50),
            p95_ms=_percentile(latencies_ms, 95),
            peak_vram_bytes=peak_vram_bytes,
            cost_usd=None,
        ),
    }
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
