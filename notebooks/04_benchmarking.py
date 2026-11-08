# %% [markdown]
# # 04 — Model Benchmarking
#
# Compare local LLM performance on ERP-related tasks:
# * Tokens per second
# * Time to first token
# * Total latency
# * VRAM usage
# * Quality per category

# %%
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path.cwd().parent))

import pandas as pd
import config as cfg

# %% [markdown]
# ## 1. System Information

# %%
from benchmark.run_benchmark import get_system_info, get_gpu_info

sys_info = get_system_info()
print(f"Platform:    {sys_info['platform']}")
print(f"CPU cores:   {sys_info.get('cpu_count', '?')}")
print(f"RAM:         {sys_info.get('ram_total_gb', '?')} GB")

gpu = sys_info.get("gpu", {})
if gpu.get("available"):
    print(f"GPU:         {gpu['name']}")
    print(f"VRAM:        {gpu['vram_total_mb']} MB total, {gpu['vram_free_mb']} MB free")
else:
    print(f"GPU:         Not available ({gpu.get('error', '')})")

# %% [markdown]
# ## 2. Load Benchmark Tasks

# %%
tasks_path = cfg.BENCHMARK_DIR / "benchmark_tasks.json"
with open(tasks_path) as fh:
    tasks_data = json.load(fh)
tasks = tasks_data["tasks"]

print(f"Loaded {len(tasks)} benchmark tasks:\n")
for t in tasks:
    print(f"  [{t['category']}] {t['id']}")

# %% [markdown]
# ## 3. Run Single-Model Benchmark (Quick Test)

# %%
from benchmark.run_benchmark import benchmark_prompt

# Quick test with one task
result = benchmark_prompt(cfg.DEFAULT_MODEL, tasks[0]["prompt"])

if "error" in result:
    print(f"Error: {result['error']}")
else:
    print(f"Model:       {result['model']}")
    print(f"Tokens:      {result['eval_tokens']}")
    print(f"Tokens/sec:  {result['tokens_per_sec']:.1f}")
    print(f"TTFT:        {result['time_to_first_token_s']:.3f}s")
    print(f"Latency:     {result['total_latency_s']:.2f}s")
    print(f"VRAM before: {result['vram_used_before_mb']} MB")
    print(f"VRAM after:  {result['vram_used_after_mb']} MB")
    print(f"\nResponse preview:\n{result['response_text'][:300]}…")

# %% [markdown]
# ## 4. Run Full Benchmark Suite
#
# ⚠️ This will take several minutes depending on how many models are pulled.

# %%
from benchmark.run_benchmark import run_benchmarks, print_comparison_table

results = run_benchmarks()
print_comparison_table(results)

# Save results
out_path = cfg.BENCHMARK_RESULTS_PATH
out_path.parent.mkdir(parents=True, exist_ok=True)
with open(out_path, "w") as fh:
    json.dump(results, fh, indent=2, default=str)
print(f"\nResults saved → {out_path}")

# %% [markdown]
# ## 5. Visualise Results

# %%
# Build comparison DataFrame
rows = []
for model_name in results.get("models_tested", []):
    model_res = results["results_by_model"].get(model_name, [])
    valid = [r for r in model_res if "error" not in r]
    if valid:
        rows.append({
            "Model": model_name,
            "Avg Tokens/s": round(sum(r["tokens_per_sec"] for r in valid) / len(valid), 1),
            "Avg TTFT (s)": round(sum(r["time_to_first_token_s"] for r in valid) / len(valid), 3),
            "Avg Latency (s)": round(sum(r["total_latency_s"] for r in valid) / len(valid), 2),
            "Tasks": len(valid),
        })

df = pd.DataFrame(rows)
print(df.to_string(index=False))

# %%
# Per-task breakdown
all_results = []
for model_name in results.get("models_tested", []):
    for r in results["results_by_model"].get(model_name, []):
        if "error" not in r:
            all_results.append({
                "Model": model_name,
                "Task": r.get("task_id", ""),
                "Category": r.get("category", ""),
                "Tokens/s": r.get("tokens_per_sec", 0),
                "TTFT (s)": r.get("time_to_first_token_s", 0),
                "Latency (s)": r.get("total_latency_s", 0),
            })

df_detail = pd.DataFrame(all_results)
if not df_detail.empty:
    print("\nPer-category averages:")
    print(df_detail.groupby(["Model", "Category"])["Tokens/s"].mean().round(1).unstack())

# %% [markdown]
# ## ✅ Summary
#
# Key metrics to compare when choosing a model for production:
#
# | Metric | Best for |
# |--------|----------|
# | Tokens/sec | Throughput — higher is better |
# | TTFT | Responsiveness — lower is better |
# | Total latency | End-to-end speed — lower is better |
# | VRAM usage | Fits on your GPU |
# | Response quality | Accuracy on ERP tasks |
#
# The benchmark results are saved and can be viewed in the Streamlit dashboard.
