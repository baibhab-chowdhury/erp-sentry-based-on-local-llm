#!/usr/bin/env python3
"""
ERP-Sentry — Fine-Tuning Dataset Preparation
================================================
Converts synthetic ERP violation data into instruction-tuning datasets
suitable for LoRA / QLoRA fine-tuning.

Outputs:
  * ``finetuning/train_alpaca.jsonl``  — Alpaca-format instruction tuning
  * ``finetuning/val_alpaca.jsonl``
  * ``finetuning/train_chat.jsonl``    — Chat-format (multi-turn)
  * ``finetuning/val_chat.jsonl``

Each sample asks the model to analyse an ERP transaction/access pattern
and identify SoD violations, anomalies, and risk levels.

Usage::

    python -m finetuning.prepare_dataset
    python finetuning/prepare_dataset.py
"""

from __future__ import annotations

import json
import random
import sqlite3
import sys
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config as cfg

random.seed(cfg.RANDOM_SEED)


# ──────────────────────────────────────────────
# Load data
# ──────────────────────────────────────────────
def _load_db() -> tuple[list[dict], list[dict], list[dict]]:
    db_path = cfg.SQLITE_DB_PATH
    if not db_path.exists():
        raise FileNotFoundError(
            f"Database not found at {db_path}. "
            "Run `python -m data.generate_synthetic_erp` first."
        )
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    users = [dict(r) for r in conn.execute("SELECT * FROM users").fetchall()]
    txns = [dict(r) for r in conn.execute("SELECT * FROM transactions").fetchall()]
    access = [dict(r) for r in conn.execute("SELECT * FROM access_roles").fetchall()]
    conn.close()
    return users, txns, access


# ──────────────────────────────────────────────
# Build Alpaca-format samples
# ──────────────────────────────────────────────
INSTRUCTION_TEMPLATES = [
    (
        "Given the following ERP transaction log entry, determine whether it "
        "is suspicious and explain why or why not.\n\n{input_text}",
        "transaction",
    ),
    (
        "Analyse the following user access permissions and identify any "
        "Segregation of Duties (SoD) violations.\n\n{input_text}",
        "access",
    ),
    (
        "Review this set of transactions by the same user and assess the "
        "overall risk level (LOW / MEDIUM / HIGH / CRITICAL).\n\n{input_text}",
        "multi_txn",
    ),
]


def _format_txn(txn: dict) -> str:
    return (
        f"Transaction ID: {txn['txn_id']}\n"
        f"User: {txn['user_name']} ({txn['user_id']})\n"
        f"Type: {txn['transaction_type']}\n"
        f"Amount: ${txn['amount_usd']:,.2f}\n"
        f"Timestamp: {txn['timestamp']}\n"
        f"Vendor: {txn['vendor']}\n"
        f"Description: {txn['description']}\n"
        f"Status: {txn['status']}"
    )


def _format_access(user: dict, perms: list[str]) -> str:
    perm_str = "\n".join(f"  - {p}" for p in perms)
    return (
        f"User: {user['full_name']} ({user['user_id']})\n"
        f"Department: {user['department']}\n"
        f"Role: {user['role']}\n"
        f"Assigned Permissions:\n{perm_str}"
    )


def _generate_txn_response(txn: dict) -> str:
    """Generate a gold-standard response for a transaction sample."""
    reasons: list[str] = []
    risk = "LOW"

    if txn["is_anomaly"]:
        flags = txn.get("anomaly_flags", "")
        if "HIGH_AMOUNT" in flags:
            reasons.append(
                f"The transaction amount (${txn['amount_usd']:,.2f}) exceeds the "
                f"normal threshold of ${cfg.HIGH_AMOUNT_THRESHOLD:,.2f}."
            )
            risk = "HIGH"
        if "OFF_HOURS" in flags:
            reasons.append("The transaction was executed outside normal business hours.")
            risk = "MEDIUM" if risk == "LOW" else risk
        if "WEEKEND" in flags:
            reasons.append("The transaction was processed on a weekend.")
            risk = "MEDIUM" if risk == "LOW" else risk

    if not reasons:
        return (
            "This transaction appears NORMAL. The amount, timing, and type are "
            "consistent with standard business operations. Risk level: LOW."
        )

    return (
        f"This transaction is SUSPICIOUS. Risk level: {risk}.\n\n"
        f"Reasons:\n" + "\n".join(f"- {r}" for r in reasons) + "\n\n"
        "Recommendation: Flag for review by the compliance team and verify "
        "supporting documentation."
    )


def _generate_access_response(user: dict, perms: list[str]) -> str:
    """Generate a gold-standard response for an access-permissions sample."""
    conflicts: list[tuple[str, str]] = []
    for pa, pb in cfg.SOD_CONFLICT_PAIRS:
        if pa in perms and pb in perms:
            conflicts.append((pa, pb))

    if not conflicts:
        return (
            "No Segregation of Duties violations detected. The permissions "
            "assigned to this user are consistent with their role and do not "
            "contain conflicting access pairs."
        )

    conflict_str = "\n".join(f"- {a} ↔ {b}" for a, b in conflicts)
    return (
        f"SoD VIOLATION DETECTED. The following conflicting permission pairs "
        f"are assigned to {user['full_name']}:\n\n{conflict_str}\n\n"
        f"Risk level: CRITICAL\n\n"
        f"Recommendation: Remove one permission from each conflicting pair "
        f"and reassign to a different user. Implement compensating controls "
        f"until remediation is complete."
    )


def build_alpaca_samples(
    users: list[dict],
    txns: list[dict],
    access: list[dict],
    max_samples: int = 300,
) -> list[dict[str, str]]:
    """Build Alpaca-format {"instruction", "input", "output"} samples."""
    from collections import defaultdict

    samples: list[dict[str, str]] = []

    # -- Transaction samples --
    sampled_txns = random.sample(txns, min(len(txns), max_samples // 2))
    for txn in sampled_txns:
        input_text = _format_txn(txn)
        instruction = INSTRUCTION_TEMPLATES[0][0].format(input_text=input_text)
        output = _generate_txn_response(txn)
        samples.append({
            "instruction": instruction,
            "input": "",
            "output": output,
        })

    # -- Access/SoD samples --
    user_perms: dict[str, list[str]] = defaultdict(list)
    for a in access:
        user_perms[a["user_id"]].append(a["permission"])

    user_map = {u["user_id"]: u for u in users}
    for uid, perms in user_perms.items():
        user = user_map.get(uid)
        if user is None:
            continue
        input_text = _format_access(user, perms)
        instruction = INSTRUCTION_TEMPLATES[1][0].format(input_text=input_text)
        output = _generate_access_response(user, perms)
        samples.append({
            "instruction": instruction,
            "input": "",
            "output": output,
        })

    random.shuffle(samples)
    return samples[:max_samples]


# ──────────────────────────────────────────────
# Build chat-format samples
# ──────────────────────────────────────────────
def alpaca_to_chat(sample: dict[str, str]) -> dict[str, Any]:
    """
    Convert an Alpaca sample to multi-turn chat format:
    [{"role": "system", ...}, {"role": "user", ...}, {"role": "assistant", ...}]
    """
    return {
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are an ERP compliance auditor AI specialised in "
                    "detecting Segregation of Duties violations and "
                    "transaction anomalies."
                ),
            },
            {"role": "user", "content": sample["instruction"]},
            {"role": "assistant", "content": sample["output"]},
        ]
    }


# ──────────────────────────────────────────────
# Write JSONL
# ──────────────────────────────────────────────
def write_jsonl(data: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for item in data:
            fh.write(json.dumps(item, ensure_ascii=False) + "\n")
    print(f"  💾  {len(data):>4} samples → {path}")


# ──────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────
def main() -> None:
    print("=" * 60)
    print("  ERP-Sentry — Fine-Tuning Dataset Preparation")
    print("=" * 60)

    users, txns, access = _load_db()
    samples = build_alpaca_samples(users, txns, access)

    # Train / val split (90 / 10)
    split_idx = int(len(samples) * 0.9)
    train = samples[:split_idx]
    val = samples[split_idx:]

    out_dir = cfg.FINETUNING_DIR

    # Alpaca format
    write_jsonl(train, out_dir / "train_alpaca.jsonl")
    write_jsonl(val, out_dir / "val_alpaca.jsonl")

    # Chat format
    train_chat = [alpaca_to_chat(s) for s in train]
    val_chat = [alpaca_to_chat(s) for s in val]
    write_jsonl(train_chat, out_dir / "train_chat.jsonl")
    write_jsonl(val_chat, out_dir / "val_chat.jsonl")

    print(f"\n  📊  Total samples: {len(samples)} (train: {len(train)}, val: {len(val)})")
    print("  ✅  Dataset preparation complete.")


if __name__ == "__main__":
    main()
