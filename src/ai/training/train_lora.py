"""train LoRA 학습·평가 데이터의 생성, 실행, 검증 절차와 CLI 진입점을 제공한다.

Train a BF16 Qwen3-4B SQL LoRA adapter on one NVIDIA GPU.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from src.ai.training.dataset import DatasetError, load_compiled


DEFAULT_MODEL = "Qwen/Qwen3-4B-Instruct-2507"
DEFAULT_REVISION = "cdbee75f17c01a7cc42f958dc650907174af0554"
# 이 값은 업무 날짜가 아니라 동일 split·shuffle을 재현하기 위한 release seed다.
# 학습 결과 비교 시 manifest와 함께 변경하므로 질문 기간 계산에는 사용하지 않는다.
DEFAULT_SEED = 20260729


def _tokenize(tokenizer: Any, record: dict[str, Any], max_length: int) -> dict[str, list[int]]:
    messages = record["messages"]
    prompt_ids = tokenizer.apply_chat_template(
        messages[:-1],
        tokenize=True,
        add_generation_prompt=True,
        enable_thinking=False,
    )
    input_ids = tokenizer.apply_chat_template(
        messages,
        tokenize=True,
        add_generation_prompt=False,
        enable_thinking=False,
    )
    if input_ids[: len(prompt_ids)] != prompt_ids:
        raise DatasetError(f"{record['case_id']}: chat template prefix mismatch")
    if len(input_ids) > max_length:
        raise DatasetError(
            f"{record['case_id']}: {len(input_ids)} tokens exceeds max_length={max_length}"
        )
    labels = [-100] * len(prompt_ids) + input_ids[len(prompt_ids) :]
    if all(label == -100 for label in labels):
        raise DatasetError(f"{record['case_id']}: assistant answer has no trainable tokens")
    return {"input_ids": input_ids, "attention_mask": [1] * len(input_ids), "labels": labels}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    """검증된 train split을 고정 base revision에 QLoRA 학습하고 adapter와 실행 manifest를 저장한다."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--revision", default=DEFAULT_REVISION)
    parser.add_argument("--max-length", type=int, default=12_288)
    parser.add_argument("--epochs", type=float, default=2.0)
    parser.add_argument("--learning-rate", type=float, default=2e-4)
    parser.add_argument("--gradient-accumulation", type=int, default=8)
    parser.add_argument("--lora-rank", type=int, default=16)
    parser.add_argument("--lora-alpha", type=int, default=32)
    parser.add_argument("--max-steps", type=int, default=-1)
    parser.add_argument("--resume-from-checkpoint")
    args = parser.parse_args()

    train_records = load_compiled(args.data, "train")
    validation_records = load_compiled(args.data, "validation")
    if not train_records or not validation_records:
        raise DatasetError("dataset requires at least one train and one validation record")
    unverified = [
        record["case_id"]
        for record in train_records + validation_records
        if record["trino_status"] != "PASS"
    ]
    if unverified:
        raise DatasetError(f"train/validation records require Trino PASS evidence: {unverified[:5]}")

    import torch
    import transformers
    from peft import LoraConfig, get_peft_model
    from torch.utils.data import Dataset
    from transformers import (
        AutoModelForCausalLM,
        AutoTokenizer,
        DataCollatorForSeq2Seq,
        Trainer,
        TrainingArguments,
        set_seed,
    )

    if not torch.cuda.is_available():
        raise RuntimeError("CUDA GPU is required; run this command on the RunPod A40")
    if not torch.cuda.is_bf16_supported():
        raise RuntimeError("the selected GPU/runtime does not support BF16")

    set_seed(DEFAULT_SEED)
    tokenizer = AutoTokenizer.from_pretrained(args.model, revision=args.revision)
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token

    class TokenizedDataset(Dataset):
        def __init__(self, records: list[dict[str, Any]]) -> None:
            self.items = [_tokenize(tokenizer, record, args.max_length) for record in records]

        def __len__(self) -> int:
            return len(self.items)

        def __getitem__(self, index: int) -> dict[str, list[int]]:
            return self.items[index]

    model = AutoModelForCausalLM.from_pretrained(
        args.model,
        revision=args.revision,
        torch_dtype=torch.bfloat16,
        low_cpu_mem_usage=True,
    )
    model.config.use_cache = False
    model.enable_input_require_grads()
    model = get_peft_model(
        model,
        LoraConfig(
            task_type="CAUSAL_LM",
            r=args.lora_rank,
            lora_alpha=args.lora_alpha,
            lora_dropout=0.05,
            bias="none",
            target_modules=[
                "q_proj",
                "k_proj",
                "v_proj",
                "o_proj",
                "gate_proj",
                "up_proj",
                "down_proj",
            ],
        ),
    )
    model.print_trainable_parameters()

    training_args = TrainingArguments(
        output_dir=str(args.output_dir),
        num_train_epochs=args.epochs,
        max_steps=args.max_steps,
        per_device_train_batch_size=1,
        per_device_eval_batch_size=1,
        gradient_accumulation_steps=args.gradient_accumulation,
        learning_rate=args.learning_rate,
        lr_scheduler_type="cosine",
        warmup_ratio=0.03,
        weight_decay=0.01,
        bf16=True,
        tf32=True,
        gradient_checkpointing=True,
        gradient_checkpointing_kwargs={"use_reentrant": False},
        eval_strategy="epoch",
        save_strategy="epoch",
        logging_steps=10,
        save_total_limit=2,
        load_best_model_at_end=True,
        metric_for_best_model="eval_loss",
        greater_is_better=False,
        optim="adamw_torch_fused",
        seed=DEFAULT_SEED,
        data_seed=DEFAULT_SEED,
        report_to="none",
    )
    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=TokenizedDataset(train_records),
        eval_dataset=TokenizedDataset(validation_records),
        data_collator=DataCollatorForSeq2Seq(
            tokenizer=tokenizer,
            padding=True,
            label_pad_token_id=-100,
            pad_to_multiple_of=8,
        ),
        processing_class=tokenizer,
    )
    result = trainer.train(resume_from_checkpoint=args.resume_from_checkpoint)
    trainer.save_model(str(args.output_dir))
    tokenizer.save_pretrained(args.output_dir)

    manifest = {
        "base_model": args.model,
        "requested_revision": args.revision,
        "resolved_revision": getattr(model.config, "_commit_hash", None),
        "dataset": str(args.data),
        "dataset_sha256": _sha256(args.data),
        "train_records": len(train_records),
        "validation_records": len(validation_records),
        "seed": DEFAULT_SEED,
        "thinking": False,
        "max_length": args.max_length,
        "epochs": args.epochs,
        "learning_rate": args.learning_rate,
        "gradient_accumulation": args.gradient_accumulation,
        "lora_rank": args.lora_rank,
        "lora_alpha": args.lora_alpha,
        "torch": torch.__version__,
        "transformers": transformers.__version__,
        "train_metrics": result.metrics,
    }
    (args.output_dir / "training_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
