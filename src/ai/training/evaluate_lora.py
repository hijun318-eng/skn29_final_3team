"""Generate SQL on a held-out split and report structural exact-match metrics."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from src.ai.training.dataset import DatasetError, load_compiled, validate_model_output, write_jsonl


def _normalize_sql(sql: str) -> str:
    return re.sub(r"\s+", " ", sql.strip().rstrip(";")).casefold()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--split", choices=("gold", "acceptance"), default="gold")
    parser.add_argument("--model", default="Qwen/Qwen3-4B")
    parser.add_argument("--revision", default="main")
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

    predictions = []
    for record in records:
        prompt = tokenizer.apply_chat_template(
            record["messages"][:-1],
            tokenize=False,
            add_generation_prompt=True,
            enable_thinking=False,
        )
        inputs = tokenizer(prompt, return_tensors="pt").to(model.device)
        with torch.inference_mode():
            generated = model.generate(
                **inputs,
                do_sample=False,
                max_new_tokens=args.max_new_tokens,
                pad_token_id=tokenizer.eos_token_id,
            )
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
                "generated_text": text,
            }
        )

    write_jsonl(args.output, predictions)
    total = len(predictions)
    summary = {
        "model": args.model,
        "adapter": args.adapter,
        "split": args.split,
        "total": total,
        "valid_json": sum(item["valid_json"] for item in predictions),
        "valid_structure": sum(item["valid_structure"] for item in predictions),
        "sql_exact_match": sum(item["sql_exact_match"] for item in predictions),
        "exact_match": sum(item["exact_match"] for item in predictions),
    }
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
