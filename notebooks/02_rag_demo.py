# %% [markdown]
# # 02 — RAG Pipeline Demo
#
# This notebook demonstrates the Retrieval-Augmented Generation pipeline:
# 1. Load & chunk company policy documents
# 2. Build a TF-IDF vector store
# 3. Query with semantic retrieval + LLM generation

# %%
import sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd().parent))

import config as cfg
from rag.embeddings import chunk_text, build_policy_index, get_embedder, VectorStore
from rag.query_engine import RAGQueryEngine

# %% [markdown]
# ## 1. Explore Policy Documents

# %%
policy_files = sorted(cfg.POLICIES_DIR.glob("*.txt"))
print(f"Found {len(policy_files)} policy documents:\n")
for pf in policy_files:
    text = pf.read_text(encoding="utf-8")
    print(f"  📄 {pf.name} — {len(text):,} chars, ~{len(text.split()):,} words")

# %% [markdown]
# ## 2. Text Chunking

# %%
sample_text = policy_files[0].read_text(encoding="utf-8")
chunks = chunk_text(sample_text, chunk_size=500, overlap=50)

print(f"Document: {policy_files[0].name}")
print(f"Chunks:   {len(chunks)}\n")

for i, chunk in enumerate(chunks[:3]):
    print(f"--- Chunk {i} ({len(chunk)} chars) ---")
    print(chunk[:200] + "…\n")

# %% [markdown]
# ## 3. Build Vector Store

# %%
store, embedder = build_policy_index()

print(f"\nTotal chunks indexed: {len(store.documents)}")
print(f"Embedding shape:      {store.embeddings.shape}")

# %% [markdown]
# ## 4. Test Retrieval (No LLM)

# %%
query = "What are the expense approval limits?"
query_vec = embedder.encode([query])
results = store.search(query_vec, top_k=3)

print(f"Query: '{query}'\n")
for i, r in enumerate(results):
    print(f"  [{i+1}] Score: {r['score']:.4f}  Source: {r['metadata'].get('source', '?')}")
    print(f"      {r['text'][:150]}…\n")

# %% [markdown]
# ## 5. Full RAG Pipeline (Retrieve + Generate)

# %%
engine = RAGQueryEngine(model=cfg.DEFAULT_MODEL)

questions = [
    "What are the approval thresholds for expenses over $25,000?",
    "Which permission pairs violate Segregation of Duties?",
    "How should a data breach be reported?",
]

for q in questions:
    print(f"\n{'='*60}")
    print(f"❓ {q}")
    print("=" * 60)
    result = engine.query(q)
    print(f"\n💬 Answer ({result['model']}):\n{result['answer']}\n")
    print("📚 Sources:")
    for s in result["sources"]:
        print(f"   • {s['source']} (score: {s['score']})")

# %% [markdown]
# ## ✅ Summary
#
# The RAG pipeline successfully:
# * Chunked policy documents into semantic segments
# * Built a TF-IDF vector store for fast retrieval
# * Retrieved relevant context for user queries
# * Generated grounded answers with source citations
#
# **Next:** Run `03_sod_detection.py` for the SoD detection walkthrough.
