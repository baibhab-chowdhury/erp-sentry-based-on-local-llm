#!/usr/bin/env python3
"""
ERP-Sentry — RAG Query Engine
================================
Retrieval-Augmented Generation pipeline:

1. Embed the user's question with the same backend used for indexing.
2. Retrieve the top-k most relevant policy chunks from the vector store.
3. Construct a grounded prompt with the retrieved context.
4. Send the prompt to the local Ollama model.
5. Return the answer with source citations.

Usage::

    from rag.query_engine import RAGQueryEngine
    engine = RAGQueryEngine()
    answer = engine.query("What is the expense approval limit for $30,000?")
"""

from __future__ import annotations

import sys
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
from pathlib import Path
from typing import Any

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config as cfg
from rag.embeddings import VectorStore, build_policy_index, get_embedder

# ──────────────────────────────────────────────
# Prompt template
# ──────────────────────────────────────────────
SYSTEM_PROMPT = """\
You are ERP-Sentry, an expert compliance assistant for enterprise resource \
planning (ERP) systems. Answer the user's question using ONLY the policy \
excerpts provided below. If the answer is not in the provided context, say \
"I could not find this information in the current policy documents."

Always cite the source document name at the end of your answer."""

CONTEXT_TEMPLATE = """\
--- POLICY CONTEXT ---
{context}
--- END CONTEXT ---

USER QUESTION: {question}

Provide a clear, concise answer with source citations."""


# ──────────────────────────────────────────────
# Query Engine
# ──────────────────────────────────────────────
class RAGQueryEngine:
    """End-to-end RAG pipeline: retrieve → augment → generate."""

    def __init__(
        self,
        model: str = cfg.DEFAULT_MODEL,
        policies_dir: Path = cfg.POLICIES_DIR,
        vector_store_path: Path = cfg.VECTOR_STORE_PATH,
        backend: str = cfg.EMBEDDING_BACKEND,
        top_k: int = cfg.RAG_TOP_K,
    ) -> None:
        self.model = model
        self.top_k = top_k
        self.backend = backend
        self.embedder = get_embedder(backend)

        self.store = VectorStore()
        if vector_store_path.exists():
            self.store.load(vector_store_path)
            # Re-fit embedder on stored docs so query vectors match
            self.embedder.fit(self.store.documents)
        else:
            print("  ⚙️  Vector store not found — building from policies …")
            self.store, self.embedder = build_policy_index(
                policies_dir=policies_dir,
                save_path=vector_store_path,
                backend=backend,
            )

    # ── retrieve ─────────────────────────────
    def retrieve(self, question: str) -> list[dict[str, Any]]:
        """Return the top-k policy chunks relevant to *question*."""
        query_vec = self.embedder.encode([question])
        return self.store.search(query_vec, top_k=self.top_k)

    # ── augmented prompt ─────────────────────
    @staticmethod
    def _build_prompt(question: str, chunks: list[dict[str, Any]]) -> str:
        context_parts: list[str] = []
        for i, c in enumerate(chunks, 1):
            source = c["metadata"].get("source", "unknown")
            context_parts.append(f"[{i}] (Source: {source})\n{c['text']}")
        context_block = "\n\n".join(context_parts)
        return CONTEXT_TEMPLATE.format(context=context_block, question=question)

    # ── generate ─────────────────────────────
    def _call_ollama(self, prompt: str) -> str:
        """Send the augmented prompt to the local Ollama instance."""
        payload = {
            "model": self.model,
            "prompt": prompt,
            "system": SYSTEM_PROMPT,
            "stream": False,
            "options": {
                "temperature": cfg.DEFAULT_TEMPERATURE,
                "top_p": cfg.DEFAULT_TOP_P,
                "num_ctx": cfg.DEFAULT_NUM_CTX,
                "num_predict": cfg.DEFAULT_MAX_TOKENS,
            },
        }
        try:
            resp = requests.post(
                cfg.OLLAMA_GENERATE_URL,
                json=payload,
                timeout=cfg.REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            return resp.json().get("response", "").strip()
        except requests.ConnectionError:
            return (
                "⚠️  Cannot connect to Ollama at "
                f"{cfg.OLLAMA_BASE_URL}. "
                "Please ensure `ollama serve` is running."
            )
        except requests.Timeout:
            return "⚠️  Ollama request timed out. Try a smaller model or shorter context."
        except Exception as exc:  # noqa: BLE001
            return f"⚠️  Ollama error: {exc}"

    # ── public API ───────────────────────────
    def query(self, question: str) -> dict[str, Any]:
        """
        Full RAG pipeline.

        Returns
        -------
        dict with keys:
            answer   — generated text
            sources  — list of {source, score, snippet}
            model    — model name used
        """
        chunks = self.retrieve(question)
        prompt = self._build_prompt(question, chunks)
        answer = self._call_ollama(prompt)

        sources = [
            {
                "source": c["metadata"].get("source", "unknown"),
                "score": round(c["score"], 4),
                "snippet": c["text"][:200] + "…" if len(c["text"]) > 200 else c["text"],
            }
            for c in chunks
        ]

        return {
            "answer": answer,
            "sources": sources,
            "model": self.model,
        }


# ──────────────────────────────────────────────
# CLI demo
# ──────────────────────────────────────────────
def main() -> None:
    print("=" * 60)
    print("  ERP-Sentry — Policy Q&A  (type 'quit' to exit)")
    print("=" * 60)

    engine = RAGQueryEngine()

    while True:
        print()
        question = input("❓  Your question: ").strip()
        if not question or question.lower() in ("quit", "exit", "q"):
            print("👋  Bye!")
            break

        result = engine.query(question)
        print(f"\n💬  Answer ({result['model']}):\n")
        print(result["answer"])
        print("\n📚  Sources:")
        for s in result["sources"]:
            print(f"   • {s['source']} (score: {s['score']})")


if __name__ == "__main__":
    main()
