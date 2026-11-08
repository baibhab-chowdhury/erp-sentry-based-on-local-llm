# Fine-Tuning Guide: LoRA / QLoRA for ERP-Sentry

> **Status**: Reference guide — not executed automatically because
> full LoRA fine-tuning requires ≥ 8 GB VRAM.  The RTX 3050 Laptop (4 GB)
> can run inference on 3B models but cannot fine-tune without offloading.

---

## 1. Overview

We fine-tune a small language model (Llama 3.2 3B or Qwen 2.5 3B) on our
synthetic ERP compliance dataset so it better detects Segregation-of-Duties
violations and transaction anomalies.

**LoRA** (Low-Rank Adaptation) freezes the base weights and trains small
rank-decomposition matrices — drastically reducing GPU memory.  
**QLoRA** adds 4-bit quantisation of the frozen weights, fitting on
consumer GPUs.

---

## 2. Prerequisites

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| GPU VRAM | 6 GB (QLoRA 3B) | 16 GB (LoRA 7B) |
| RAM | 16 GB | 32 GB |
| Disk | 10 GB free | 20 GB free |
| CUDA | 11.8+ | 12.1+ |

### Install dependencies

```bash
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121
pip install peft>=0.7.0 trl>=0.7.0 transformers>=4.36.0 datasets accelerate
pip install bitsandbytes          # 4-bit quantisation (Linux best support)
# OR use Unsloth (faster, easier):
pip install unsloth
```

> ⚠️  `bitsandbytes` has limited Windows support. Consider WSL2 or use
> Unsloth which handles Windows better.

---

## 3. Dataset

Run the dataset preparation script first:

```bash
python -m finetuning.prepare_dataset
```

This produces:

| File | Format | Purpose |
|------|--------|---------|
| `train_alpaca.jsonl` | Alpaca | Instruction tuning |
| `val_alpaca.jsonl` | Alpaca | Validation |
| `train_chat.jsonl` | Chat (messages) | Chat-model tuning |
| `val_chat.jsonl` | Chat (messages) | Validation |

### Sample (Alpaca format)

```json
{
  "instruction": "Given the following ERP transaction log entry, determine whether it is suspicious...\n\nTransaction ID: TXN-000123\nUser: John Smith (USR-0007)\nType: PAYMENT\nAmount: $87,500.00\nTimestamp: 2024-03-17T02:30:00\n...",
  "input": "",
  "output": "This transaction is SUSPICIOUS. Risk level: HIGH.\n\nReasons:\n- The transaction amount ($87,500.00) exceeds the normal threshold of $50,000.00.\n- The transaction was executed outside normal business hours.\n\nRecommendation: Flag for review..."
}
```

---

## 4. Fine-Tuning with Unsloth (Recommended)

Unsloth provides 2× faster training and 60% less memory.

```python
from unsloth import FastLanguageModel
from trl import SFTTrainer
from transformers import TrainingArguments
from datasets import load_dataset

# 1. Load model with 4-bit quantisation
model, tokenizer = FastLanguageModel.from_pretrained(
    model_name="unsloth/Llama-3.2-3B-Instruct",
    max_seq_length=2048,
    load_in_4bit=True,           # QLoRA
    dtype=None,                  # auto-detect
)

# 2. Add LoRA adapters
model = FastLanguageModel.get_peft_model(
    model,
    r=16,                        # LoRA rank
    lora_alpha=32,
    lora_dropout=0.05,
    target_modules=[
        "q_proj", "k_proj", "v_proj", "o_proj",
        "gate_proj", "up_proj", "down_proj",
    ],
    bias="none",
    use_gradient_checkpointing="unsloth",
)

# 3. Load dataset
dataset = load_dataset("json", data_files={
    "train": "finetuning/train_alpaca.jsonl",
    "validation": "finetuning/val_alpaca.jsonl",
})

# 4. Format prompt
def format_prompt(example):
    return {
        "text": (
            f"### Instruction:\n{example['instruction']}\n\n"
            f"### Response:\n{example['output']}"
        )
    }

dataset = dataset.map(format_prompt)

# 5. Train
trainer = SFTTrainer(
    model=model,
    tokenizer=tokenizer,
    train_dataset=dataset["train"],
    eval_dataset=dataset["validation"],
    dataset_text_field="text",
    max_seq_length=2048,
    args=TrainingArguments(
        output_dir="finetuning/checkpoints",
        num_train_epochs=3,
        per_device_train_batch_size=2,
        gradient_accumulation_steps=4,
        learning_rate=2e-4,
        weight_decay=0.01,
        warmup_steps=10,
        logging_steps=10,
        eval_strategy="steps",
        eval_steps=50,
        save_strategy="steps",
        save_steps=100,
        fp16=True,
        optim="adamw_8bit",
    ),
)

trainer.train()

# 6. Save LoRA adapter
model.save_pretrained("finetuning/lora_adapter")
tokenizer.save_pretrained("finetuning/lora_adapter")
```

---

## 5. Fine-Tuning with PEFT (Alternative)

```python
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training

# Quantisation config
bnb_config = BitsAndBytesConfig(
    load_in_4bit=True,
    bnb_4bit_use_double_quant=True,
    bnb_4bit_quant_type="nf4",
    bnb_4bit_compute_dtype="float16",
)

# Load base model
model = AutoModelForCausalLM.from_pretrained(
    "meta-llama/Llama-3.2-3B-Instruct",
    quantization_config=bnb_config,
    device_map="auto",
)
tokenizer = AutoTokenizer.from_pretrained("meta-llama/Llama-3.2-3B-Instruct")

model = prepare_model_for_kbit_training(model)

# LoRA config
lora_config = LoraConfig(
    r=16,
    lora_alpha=32,
    lora_dropout=0.05,
    target_modules=["q_proj", "k_proj", "v_proj", "o_proj"],
    bias="none",
    task_type="CAUSAL_LM",
)
model = get_peft_model(model, lora_config)
model.print_trainable_parameters()
# → trainable params: ~4M / total: ~3B (0.13%)
```

Then use `SFTTrainer` as shown above.

---

## 6. Exporting to Ollama

After fine-tuning, convert the LoRA adapter to an Ollama model:

```bash
# 1. Merge LoRA weights with base model
python -c "
from peft import AutoPeftModelForCausalLM
model = AutoPeftModelForCausalLM.from_pretrained('finetuning/lora_adapter')
model = model.merge_and_unload()
model.save_pretrained('finetuning/merged_model')
"

# 2. Convert to GGUF (requires llama.cpp)
python llama.cpp/convert_hf_to_gguf.py finetuning/merged_model \
    --outfile finetuning/erp-sentry-3b.Q4_K_M.gguf \
    --outtype q4_k_m

# 3. Create Ollama Modelfile
cat > finetuning/Modelfile <<EOF
FROM finetuning/erp-sentry-3b.Q4_K_M.gguf

SYSTEM "You are ERP-Sentry, an AI auditor specialised in ERP compliance, Segregation of Duties analysis, and transaction anomaly detection."

PARAMETER temperature 0.3
PARAMETER top_p 0.9
PARAMETER num_ctx 4096
EOF

# 4. Import into Ollama
ollama create erp-sentry:3b -f finetuning/Modelfile
```

---

## 7. Evaluation

After fine-tuning, re-run the benchmark suite to compare the base model
vs. the fine-tuned model:

```bash
# Edit config.py to add "erp-sentry:3b" to AVAILABLE_MODELS, then:
python -m benchmark.run_benchmark
```

Compare:
- **Accuracy** on SoD detection (precision, recall on the synthetic test set)
- **Response quality** (LLM-as-judge with a larger model)
- **Tokens/sec** (should be similar to base model)

---

## 8. Tips for RTX 3050 (4 GB VRAM)

1. Use **QLoRA** (4-bit quantisation) — reduces VRAM from ~12 GB to ~4-5 GB
   for a 3B model.
2. Set `per_device_train_batch_size=1` with `gradient_accumulation_steps=8`.
3. Enable `gradient_checkpointing=True` to trade compute for memory.
4. Use `optim="adamw_8bit"` for 8-bit Adam optimizer.
5. Keep `max_seq_length ≤ 1024` during training (increase for inference).
6. Consider training on **Google Colab** (free T4 with 15 GB VRAM) or
   **Kaggle** (free P100 with 16 GB).
7. Monitor VRAM with `nvidia-smi -l 2` in a separate terminal.

---

## 9. Directory Structure After Training

```
finetuning/
├── prepare_dataset.py
├── finetune_guide.md          ← This file
├── train_alpaca.jsonl
├── val_alpaca.jsonl
├── train_chat.jsonl
├── val_chat.jsonl
├── checkpoints/               ← Training checkpoints
│   └── checkpoint-100/
├── lora_adapter/              ← Saved LoRA weights
│   ├── adapter_config.json
│   └── adapter_model.safetensors
├── merged_model/              ← Merged full model
└── Modelfile                  ← Ollama import file
```
