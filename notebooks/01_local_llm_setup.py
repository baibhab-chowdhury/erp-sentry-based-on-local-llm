# %% [markdown]
# # 01 — Local LLM Setup with Ollama
#
# This notebook walks through setting up and testing local LLMs on Windows
# using Ollama.  By the end you will have verified that Ollama is running,
# pulled the models we need, and run a simple inference.

# %% [markdown]
# ## 1. Prerequisites
#
# * **Ollama** installed → https://ollama.com/download
# * **NVIDIA GPU** drivers up to date (for GPU acceleration)
# * **Python 3.10+** with the project requirements installed

# %%
# Check Python version
import sys
print(f"Python {sys.version}")
assert sys.version_info >= (3, 10), "Need Python ≥ 3.10"

# %%
# Verify project imports
import requests
import json
import time

# Add project root to path
from pathlib import Path
sys.path.insert(0, str(Path.cwd().parent))
import config as cfg

print(f"Ollama URL:     {cfg.OLLAMA_BASE_URL}")
print(f"Default model:  {cfg.DEFAULT_MODEL}")

# %% [markdown]
# ## 2. Check Ollama Status

# %%
def check_ollama() -> bool:
    """Verify Ollama is running and reachable."""
    try:
        resp = requests.get(cfg.OLLAMA_TAGS_URL, timeout=5)
        resp.raise_for_status()
        models = [m["name"] for m in resp.json().get("models", [])]
        print(f"✅ Ollama is running! ({len(models)} models available)")
        for m in models:
            print(f"   • {m}")
        return True
    except requests.ConnectionError:
        print("❌ Cannot connect to Ollama.")
        print("   Run `ollama serve` in a terminal, then re-run this cell.")
        return False

ollama_ok = check_ollama()

# %% [markdown]
# ## 3. Pull Required Models
#
# If models aren't pulled yet, run these in your terminal:
#
# ```bash
# ollama pull llama3.2:3b
# ollama pull qwen2.5:3b
# ollama pull llama3.2:1b     # optional — lightweight
# ollama pull phi3:mini        # optional — for benchmarking
# ```

# %%
# Check which models we need
if ollama_ok:
    resp = requests.get(cfg.OLLAMA_TAGS_URL, timeout=5)
    pulled = {m["name"] for m in resp.json().get("models", [])}

    for model in cfg.AVAILABLE_MODELS:
        found = any(model in p for p in pulled)
        status = "✅" if found else "⚠️  Not pulled"
        print(f"  {status}  {model}")

# %% [markdown]
# ## 4. Test Inference — Generate Endpoint

# %%
def test_generate(model: str, prompt: str) -> dict:
    """Send a prompt to Ollama /api/generate and return timing + response."""
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.3,
            "num_predict": 200,
        },
    }
    t0 = time.perf_counter()
    resp = requests.post(cfg.OLLAMA_GENERATE_URL, json=payload, timeout=120)
    elapsed = time.perf_counter() - t0
    resp.raise_for_status()
    data = resp.json()
    return {
        "model": model,
        "response": data.get("response", ""),
        "eval_count": data.get("eval_count", 0),
        "elapsed_s": round(elapsed, 2),
    }

# %%
if ollama_ok:
    result = test_generate(
        cfg.DEFAULT_MODEL,
        "Explain Segregation of Duties in ERP systems in 3 sentences.",
    )
    print(f"Model:    {result['model']}")
    print(f"Tokens:   {result['eval_count']}")
    print(f"Time:     {result['elapsed_s']}s")
    print(f"\nResponse:\n{result['response']}")

# %% [markdown]
# ## 5. Test Inference — Chat Endpoint

# %%
def test_chat(model: str, messages: list[dict]) -> dict:
    """Send messages to Ollama /api/chat."""
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
    }
    t0 = time.perf_counter()
    resp = requests.post(cfg.OLLAMA_CHAT_URL, json=payload, timeout=120)
    elapsed = time.perf_counter() - t0
    resp.raise_for_status()
    data = resp.json()
    return {
        "model": model,
        "response": data.get("message", {}).get("content", ""),
        "elapsed_s": round(elapsed, 2),
    }

# %%
if ollama_ok:
    result = test_chat(
        cfg.DEFAULT_MODEL,
        [
            {"role": "system", "content": "You are an ERP compliance expert."},
            {"role": "user", "content": "What are the top 3 SoD risks in accounts payable?"},
        ],
    )
    print(f"Time: {result['elapsed_s']}s\n")
    print(result["response"])

# %% [markdown]
# ## 6. GPU Information

# %%
import shutil
import subprocess

nvidia_smi = shutil.which("nvidia-smi")
if nvidia_smi:
    out = subprocess.check_output(
        [nvidia_smi, "--query-gpu=name,memory.total,memory.used,driver_version",
         "--format=csv,noheader"],
        text=True,
    ).strip()
    print(f"GPU: {out}")
else:
    print("nvidia-smi not found on PATH")

# %% [markdown]
# ## ✅ Summary
#
# You now have:
# * Ollama running and reachable
# * At least one model pulled (llama3.2:3b recommended)
# * Verified both `/api/generate` and `/api/chat` endpoints
# * Confirmed GPU availability
#
# **Next:** Run `02_rag_demo.py` to set up the RAG pipeline.
