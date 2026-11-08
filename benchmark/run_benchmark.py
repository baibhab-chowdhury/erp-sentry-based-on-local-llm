#!/usr/bin/env python3
"""
ERP-Sentry — Model Benchmarking Suite
=========================================
Comprehensive benchmarking of local Ollama models across multiple dimensions:

* Tokens per second (generation speed)
* Time to first token (latency)
* Total response latency
* VRAM usage (via ``nvidia-smi``)
* Quality assessment per task category

Results are saved to ``benchmark/results.json`` and can be viewed in the
Streamlit dashboard.

Usage::

    python -m benchmark.run_benchmark
    python benchmark/run_benchmark.py
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config as cfg

try:
    import psutil
except ImportError:
    psutil = None  # type: ignore[assignment]


# ──────────────────────────────────────────────
# Resource monitoring
# ──────────────────────────────────────────────
def get_gpu_info() -> dict[str, Any]:
    """Query nvidia-smi for GPU name, VRAM total/used/free."""
    nvidia_smi = shutil.which("nvidia-smi")
    if nvidia_smi is None:
        return {"available": False, "error": "nvidia-smi not on PATH"}

    try:
        out = subprocess.check_output(
            [
                nvidia_smi,
                "--query-gpu=name,memory.total,memory.used,memory.free,utilization.gpu",
                "--format=csv,noheader,nounits",
            ],
            text=True,
            timeout=10,
        ).strip()
        parts = [p.strip() for p in out.split(",")]
        return {
            "available": True,
            "name": parts[0],
            "vram_total_mb": int(parts[1]),
            "vram_used_mb": int(parts[2]),
            "vram_free_mb": int(parts[3]),
            "gpu_utilization_pct": int(parts[4]),
        }
    except Exception as exc:
        return {"available": False, "error": str(exc)}


def get_system_info() -> dict[str, Any]:
    """Gather system-level info for the report header."""
    info: dict[str, Any] = {
        "platform": sys.platform,
        "python_version": sys.version,
    }
    if psutil:
        info["cpu_count"] = psutil.cpu_count(logical=True)
        mem = psutil.virtual_memory()
        info["ram_total_gb"] = round(mem.total / (1024 ** 3), 1)
        info["ram_available_gb"] = round(mem.available / (1024 ** 3), 1)
    info["gpu"] = get_gpu_info()
    return info


# ──────────────────────────────────────────────
# Benchmark a single prompt
# ──────────────────────────────────────────────
def benchmark_prompt(
    model: str,
    prompt: str,
    system: str = "You are a helpful ERP compliance assistant.",
) -> dict[str, Any]:
    """
    Send *prompt* to *model* via Ollama's streaming API and measure
    time-to-first-token, total time, and tokens/sec.
    """
    # Record VRAM before
    gpu_before = get_gpu_info()

    payload = {
        "model": model,
        "prompt": prompt,
        "system": system,
        "stream": True,
        "options": {
            "temperature": 0.3,
            "num_ctx": cfg.DEFAULT_NUM_CTX,
            "num_predict": 256,
        },
    }

    t_start = time.perf_counter()
    t_first_token: float | None = None
    full_response: list[str] = []
    total_eval_count = 0
    total_eval_duration = 0

    try:
        with requests.post(
            cfg.OLLAMA_GENERATE_URL,
            json=payload,
            stream=True,
            timeout=cfg.REQUEST_TIMEOUT,
        ) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines(decode_unicode=True):
                if not line:
                    continue
                chunk = json.loads(line)

                if t_first_token is None and chunk.get("response"):
                    t_first_token = time.perf_counter() - t_start

                full_response.append(chunk.get("response", ""))

                if chunk.get("done"):
                    total_eval_count = chunk.get("eval_count", 0)
                    total_eval_duration = chunk.get("eval_duration", 0)

    except requests.ConnectionError:
        return {
            "error": f"Cannot connect to Ollama at {cfg.OLLAMA_BASE_URL}",
            "model": model,
        }
    except Exception as exc:
        return {"error": str(exc), "model": model}

    t_total = time.perf_counter() - t_start
    gpu_after = get_gpu_info()

    # Tokens/sec from Ollama's own measurement (nanoseconds)
    tokens_per_sec = 0.0
    if total_eval_duration > 0:
        tokens_per_sec = total_eval_count / (total_eval_duration / 1e9)

    return {
        "model": model,
        "time_to_first_token_s": round(t_first_token or 0, 4),
        "total_latency_s": round(t_total, 4),
        "eval_tokens": total_eval_count,
        "tokens_per_sec": round(tokens_per_sec, 2),
        "response_text": "".join(full_response),
        "vram_used_before_mb": gpu_before.get("vram_used_mb"),
        "vram_used_after_mb": gpu_after.get("vram_used_mb"),
    }


# ──────────────────────────────────────────────
# Run full benchmark suite
# ──────────────────────────────────────────────
def run_benchmarks(
    models: list[str] | None = None,
    tasks_path: Path | None = None,
) -> dict[str, Any]:
    """
    Benchmark each model on every task in the tasks file.

    Returns a dict suitable for JSON serialisation.
    """
    if models is None:
        models = list(cfg.AVAILABLE_MODELS)
    if tasks_path is None:
        tasks_path = cfg.BENCHMARK_DIR / "benchmark_tasks.json"

    # Load tasks
    with open(tasks_path, encoding="utf-8") as fh:
        tasks_data = json.load(fh)
    tasks: list[dict[str, Any]] = tasks_data.get("tasks", [])

    if not tasks:
        raise ValueError(f"No tasks found in {tasks_path}")

    # Filter to models actually available in Ollama
    available: set[str] = set()
    try:
        resp = requests.get(cfg.OLLAMA_TAGS_URL, timeout=5)
        resp.raise_for_status()
        for m in resp.json().get("models", []):
            available.add(m["name"])
    except Exception:
        print("  ⚠️  Could not query Ollama for available models — will try all.")
        available = set(models)

    results: dict[str, Any] = {
        "benchmark_id": datetime.now().strftime("%Y%m%d_%H%M%S"),
        "timestamp": datetime.now().isoformat(),
        "system_info": get_system_info(),
        "models_tested": [],
        "results_by_model": {},
    }

    for model in models:
        # Check if model is pulled (allow partial match)
        if not any(model in a for a in available):
            print(f"  ⚠️  Model '{model}' not found in Ollama — skipping.")
            continue

        print(f"\n  🤖  Benchmarking: {model}")
        print(f"  {'─' * 50}")
        results["models_tested"].append(model)
        model_results: list[dict[str, Any]] = []

        for task in tasks:
            print(f"    ▸ {task['id']} ({task['category']}) … ", end="", flush=True)
            res = benchmark_prompt(model, task["prompt"])
            res["task_id"] = task["id"]
            res["category"] = task["category"]

            if "error" in res:
                print(f"❌ {res['error']}")
            else:
                print(
                    f"✅ {res['tokens_per_sec']:.1f} tok/s | "
                    f"TTFT {res['time_to_first_token_s']:.2f}s | "
                    f"Total {res['total_latency_s']:.2f}s"
                )
            model_results.append(res)

        results["results_by_model"][model] = model_results

    return results


# ──────────────────────────────────────────────
# Report / comparison table
# ──────────────────────────────────────────────
def print_comparison_table(results: dict[str, Any]) -> None:
    """Print a summary comparison table to stdout."""
    print("\n" + "=" * 80)
    print("  MODEL COMPARISON TABLE")
    print("=" * 80)

    header = f"  {'Model':<25} {'Avg tok/s':>10} {'Avg TTFT':>10} {'Avg Latency':>12} {'Tasks':>6}"
    print(header)
    print("  " + "─" * 75)

    for model in results.get("models_tested", []):
        model_res = results["results_by_model"].get(model, [])
        valid = [r for r in model_res if "error" not in r]

        if not valid:
            print(f"  {model:<25} {'(errors)':>10}")
            continue

        avg_tps = sum(r["tokens_per_sec"] for r in valid) / len(valid)
        avg_ttft = sum(r["time_to_first_token_s"] for r in valid) / len(valid)
        avg_lat = sum(r["total_latency_s"] for r in valid) / len(valid)

        print(
            f"  {model:<25} {avg_tps:>10.1f} {avg_ttft:>9.2f}s {avg_lat:>11.2f}s {len(valid):>6}"
        )

    print()


# ──────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────
def main() -> None:
    print("=" * 60)
    print("  ERP-Sentry — Model Benchmark Suite")
    print("=" * 60)

    results = run_benchmarks()

    # Save
    out_path = cfg.BENCHMARK_RESULTS_PATH
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(results, fh, indent=2, default=str)
    print(f"\n  💾  Results saved → {out_path}")

    # Print comparison
    print_comparison_table(results)
    print("  ✅  Benchmark complete.")


if __name__ == "__main__":
    main()
