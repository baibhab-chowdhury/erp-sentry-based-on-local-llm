#!/usr/bin/env python3
"""
ERP-Sentry — Environment Verification
=======================================
Run this first to make sure everything is ready:

    python setup_check.py

It checks:
  1. Python version
  2. Required pip packages
  3. Ollama reachability & pulled models
  4. GPU availability (nvidia-smi)
  5. Data directory structure
"""

from __future__ import annotations

import importlib
import json
import shutil
import subprocess
import sys
import textwrap
import urllib.request
import urllib.error
from pathlib import Path

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import config as cfg

# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────
PASS = "✅"
WARN = "⚠️"
FAIL = "❌"

results: list[tuple[str, str, str]] = []   # (status, check_name, detail)


def record(status: str, name: str, detail: str = "") -> None:
    results.append((status, name, detail))
    print(f"  {status}  {name}" + (f" — {detail}" if detail else ""))


# ──────────────────────────────────────────────
# 1. Python version
# ──────────────────────────────────────────────
def check_python() -> None:
    v = sys.version_info
    if v >= (3, 10):
        record(PASS, "Python version", f"{v.major}.{v.minor}.{v.micro}")
    else:
        record(FAIL, "Python version", f"{v.major}.{v.minor} — need ≥ 3.10")


# ──────────────────────────────────────────────
# 2. Required packages
# ──────────────────────────────────────────────
REQUIRED_PACKAGES: list[tuple[str, str]] = [
    ("requests", "requests"),
    ("pandas", "pandas"),
    ("numpy", "numpy"),
    ("faker", "faker"),
    ("sklearn", "scikit-learn"),
    ("streamlit", "streamlit"),
    ("plotly", "plotly"),
    ("psutil", "psutil"),
]

OPTIONAL_PACKAGES: list[tuple[str, str]] = [
    ("sentence_transformers", "sentence-transformers"),
]


def check_packages() -> None:
    for import_name, pip_name in REQUIRED_PACKAGES:
        try:
            importlib.import_module(import_name)
            record(PASS, f"Package: {pip_name}")
        except ImportError:
            record(FAIL, f"Package: {pip_name}", f"pip install {pip_name}")

    for import_name, pip_name in OPTIONAL_PACKAGES:
        try:
            importlib.import_module(import_name)
            record(PASS, f"Optional: {pip_name}")
        except ImportError:
            record(WARN, f"Optional: {pip_name}", "not installed (TF-IDF fallback will be used)")


# ──────────────────────────────────────────────
# 3. Ollama
# ──────────────────────────────────────────────
def check_ollama() -> None:
    # Reachability
    try:
        req = urllib.request.Request(cfg.OLLAMA_TAGS_URL)
        with urllib.request.urlopen(req, timeout=5) as response:
            if response.status == 200:
                body = response.read().decode("utf-8")
                tags = json.loads(body)
                record(PASS, "Ollama reachable", cfg.OLLAMA_BASE_URL)
            else:
                record(FAIL, "Ollama reachable", f"HTTP {response.status}")
                return
    except urllib.error.URLError as e:
        record(FAIL, "Ollama reachable", f"Cannot connect — is `ollama serve` running? ({e.reason})")
        return
    except Exception as exc:
        record(FAIL, "Ollama reachable", str(exc))
        return

    # Pulled models
    pulled: set[str] = set()
    for m in tags.get("models", []):
        name = m.get("name", "")
        pulled.add(name)

    for model in cfg.AVAILABLE_MODELS:
        # Ollama tags may include :latest suffix
        if model in pulled or f"{model}:latest" in pulled or any(model in p for p in pulled):
            record(PASS, f"Model pulled: {model}")
        else:
            record(WARN, f"Model pulled: {model}", f"Run: ollama pull {model}")


# ──────────────────────────────────────────────
# 4. GPU
# ──────────────────────────────────────────────
def check_gpu() -> None:
    nvidia_smi = shutil.which("nvidia-smi")
    if nvidia_smi is None:
        record(WARN, "GPU (nvidia-smi)", "nvidia-smi not on PATH")
        return
    try:
        out = subprocess.check_output(
            [nvidia_smi, "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader"],
            text=True,
            timeout=10,
        ).strip()
        record(PASS, "GPU detected", out)
    except Exception as exc:
        record(WARN, "GPU detection", str(exc))


# ──────────────────────────────────────────────
# 5. Directory structure
# ──────────────────────────────────────────────
EXPECTED_DIRS = [
    cfg.DATA_DIR,
    cfg.RAG_DIR,
    cfg.POLICIES_DIR,
    cfg.BENCHMARK_DIR,
    cfg.FINETUNING_DIR,
    cfg.PROJECT_ROOT / "agents",
    cfg.PROJECT_ROOT / "app",
    cfg.PROJECT_ROOT / "notebooks",
]


def check_dirs() -> None:
    for d in EXPECTED_DIRS:
        if d.is_dir():
            record(PASS, f"Directory: {d.relative_to(cfg.PROJECT_ROOT)}")
        else:
            record(WARN, f"Directory: {d.relative_to(cfg.PROJECT_ROOT)}", "missing — will be created on first run")


# ──────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────
def main() -> None:
    print("=" * 60)
    print("  ERP-Sentry — Environment Check")
    print("=" * 60)

    check_python()
    print()
    check_packages()
    print()
    check_ollama()
    print()
    check_gpu()
    print()
    check_dirs()

    # Summary
    fails = sum(1 for s, *_ in results if s == FAIL)
    warns = sum(1 for s, *_ in results if s == WARN)
    passes = sum(1 for s, *_ in results if s == PASS)

    print()
    print("=" * 60)
    print(f"  Results:  {passes} passed · {warns} warnings · {fails} failed")
    if fails:
        print("  ⛔  Fix the failures above before running the project.")
    elif warns:
        print("  ⚡  All critical checks passed. Warnings are optional.")
    else:
        print("  🎉  Everything looks great — you're ready to go!")
    print("=" * 60)

    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
