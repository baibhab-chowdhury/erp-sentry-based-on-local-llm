"""
ERP-Sentry — Central Configuration
====================================
All tuneable knobs live here so every module imports one file.
"""

import os
from pathlib import Path

# ──────────────────────────────────────────────
# Paths
# ──────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent
DATA_DIR = PROJECT_ROOT / "data"
RAG_DIR = PROJECT_ROOT / "rag"
POLICIES_DIR = RAG_DIR / "policies"
BENCHMARK_DIR = PROJECT_ROOT / "benchmark"
FINETUNING_DIR = PROJECT_ROOT / "finetuning"
SQLITE_DB_PATH = DATA_DIR / "erp_data.db"
VECTOR_STORE_PATH = RAG_DIR / "vector_store.npz"

# ──────────────────────────────────────────────
# Ollama
# ──────────────────────────────────────────────
OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
OLLAMA_GENERATE_URL: str = f"{OLLAMA_BASE_URL}/api/generate"
OLLAMA_CHAT_URL: str = f"{OLLAMA_BASE_URL}/api/chat"
OLLAMA_EMBED_URL: str = f"{OLLAMA_BASE_URL}/api/embeddings"
OLLAMA_TAGS_URL: str = f"{OLLAMA_BASE_URL}/api/tags"

# Default models (must be pulled in Ollama first)
DEFAULT_MODEL: str = os.getenv("ERP_SENTRY_MODEL", "llama3.2:3b")
EMBEDDING_MODEL: str = os.getenv("ERP_SENTRY_EMBED_MODEL", "llama3.2:3b")

# Models available for benchmarking / selection
AVAILABLE_MODELS: list[str] = [
    "llama3.2:3b",
    "llama3.2:1b",
    "qwen2.5:3b",
    "phi3:mini",
]

# ──────────────────────────────────────────────
# Generation parameters
# ──────────────────────────────────────────────
DEFAULT_TEMPERATURE: float = 0.3
DEFAULT_TOP_P: float = 0.9
DEFAULT_NUM_CTX: int = 4096          # context window tokens
DEFAULT_MAX_TOKENS: int = 1024       # max generation length
REQUEST_TIMEOUT: int = 120           # seconds

# ──────────────────────────────────────────────
# RAG
# ──────────────────────────────────────────────
RAG_CHUNK_SIZE: int = 500            # characters per chunk
RAG_CHUNK_OVERLAP: int = 50          # overlap between chunks
RAG_TOP_K: int = 3                   # top-k retrieval results
EMBEDDING_BACKEND: str = os.getenv(  # "tfidf" or "sentence-transformers"
    "ERP_SENTRY_EMBED_BACKEND", "tfidf"
)

# ──────────────────────────────────────────────
# Risk / SoD detection thresholds
# ──────────────────────────────────────────────
HIGH_AMOUNT_THRESHOLD: float = 50_000.0      # USD — flag if above
OFF_HOURS_START: int = 20                     # 8 PM
OFF_HOURS_END: int = 6                        # 6 AM
WEEKEND_DAYS: set[int] = {5, 6}               # Saturday=5, Sunday=6

SOD_CONFLICT_PAIRS: list[tuple[str, str]] = [
    ("CREATE_PURCHASE_ORDER", "APPROVE_PAYMENT"),
    ("CREATE_VENDOR", "PROCESS_INVOICE"),
    ("CREATE_JOURNAL_ENTRY", "POST_JOURNAL_ENTRY"),
    ("CREATE_PURCHASE_ORDER", "RECEIVE_GOODS"),
    ("PROCESS_INVOICE", "APPROVE_PAYMENT"),
]

RISK_SEVERITY_LEVELS: dict[str, int] = {
    "CRITICAL": 4,
    "HIGH": 3,
    "MEDIUM": 2,
    "LOW": 1,
    "INFO": 0,
}

# ──────────────────────────────────────────────
# Synthetic data generation
# ──────────────────────────────────────────────
SYNTHETIC_NUM_USERS: int = 25
SYNTHETIC_NUM_TRANSACTIONS: int = 500
SYNTHETIC_VIOLATION_RATE: float = 0.15       # 15 % of transactions are suspicious
RANDOM_SEED: int = 42

# ──────────────────────────────────────────────
# Benchmark
# ──────────────────────────────────────────────
BENCHMARK_RESULTS_PATH = BENCHMARK_DIR / "results.json"

# ──────────────────────────────────────────────
# Streamlit dashboard
# ──────────────────────────────────────────────
STREAMLIT_PAGE_TITLE: str = "ERP-Sentry — AI-Powered ERP Risk Intelligence"
STREAMLIT_PAGE_ICON: str = "🛡️"
PRIMARY_COLOR: str = "#1B3A5C"       # iRM-style dark blue
ACCENT_COLOR: str = "#E8792F"        # iRM-style orange accent
