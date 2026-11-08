#!/usr/bin/env python3
"""
ERP-Sentry — Embedding & Vector Store
========================================
Provides two backends for document embeddings:

1. **TF-IDF** (default) — scikit-learn, no GPU needed, fast.
2. **Sentence-Transformers** — optional; better semantic quality but needs
   ``pip install sentence-transformers``.

The vector store is a simple numpy-based cosine-similarity index persisted
to ``rag/vector_store.npz``.
"""

from __future__ import annotations

import json
import re
import sys
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
from pathlib import Path
from typing import Any

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config as cfg

# ──────────────────────────────────────────────
# Text chunking
# ──────────────────────────────────────────────

def chunk_text(
    text: str,
    chunk_size: int = cfg.RAG_CHUNK_SIZE,
    overlap: int = cfg.RAG_CHUNK_OVERLAP,
) -> list[str]:
    """
    Split *text* into overlapping chunks of roughly *chunk_size* characters,
    preferring sentence boundaries.
    """
    # Normalise whitespace
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    sentences = re.split(r"(?<=[.!?])\s+|\n{2,}", text)

    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for sent in sentences:
        sent = sent.strip()
        if not sent:
            continue
        if current_len + len(sent) > chunk_size and current:
            chunks.append(" ".join(current))
            # Keep last *overlap* chars worth of sentences
            keep: list[str] = []
            keep_len = 0
            for s in reversed(current):
                if keep_len + len(s) > overlap:
                    break
                keep.insert(0, s)
                keep_len += len(s)
            current = keep
            current_len = keep_len
        current.append(sent)
        current_len += len(sent)

    if current:
        chunks.append(" ".join(current))

    return chunks


# ──────────────────────────────────────────────
# Embedding backends
# ──────────────────────────────────────────────

class TfidfEmbedder:
    """Scikit-learn TF-IDF vectoriser (no GPU, instant)."""

    def __init__(self) -> None:
        from sklearn.feature_extraction.text import TfidfVectorizer
        self.vectoriser = TfidfVectorizer(
            max_features=5000,
            stop_words="english",
            sublinear_tf=True,
        )
        self._fitted = False

    def fit(self, texts: list[str]) -> None:
        self.vectoriser.fit(texts)
        self._fitted = True

    def encode(self, texts: list[str]) -> np.ndarray:
        if not self._fitted:
            self.fit(texts)
            return self.vectoriser.transform(texts).toarray()  # type: ignore[return-value]
        return self.vectoriser.transform(texts).toarray()  # type: ignore[return-value]


class SentenceTransformerEmbedder:
    """Hugging-Face sentence-transformers backend (optional)."""

    MODEL_NAME = "all-MiniLM-L6-v2"

    def __init__(self) -> None:
        from sentence_transformers import SentenceTransformer
        self.model = SentenceTransformer(self.MODEL_NAME)

    def fit(self, texts: list[str]) -> None:  # noqa: ARG002
        pass  # not needed — pretrained

    def encode(self, texts: list[str]) -> np.ndarray:
        return self.model.encode(texts, show_progress_bar=False, convert_to_numpy=True)


def get_embedder(backend: str = cfg.EMBEDDING_BACKEND):
    """Return the appropriate embedder instance."""
    if backend == "sentence-transformers":
        try:
            return SentenceTransformerEmbedder()
        except ImportError:
            print("⚠️  sentence-transformers not installed — falling back to TF-IDF.")
            return TfidfEmbedder()
    return TfidfEmbedder()


# ──────────────────────────────────────────────
# Vector store (numpy cosine similarity)
# ──────────────────────────────────────────────

class VectorStore:
    """Minimal in-memory vector store backed by numpy."""

    def __init__(self) -> None:
        self.embeddings: np.ndarray | None = None
        self.documents: list[str] = []
        self.metadata: list[dict[str, Any]] = []

    # ── build ────────────────────────────────
    def add(self, texts: list[str], metas: list[dict[str, Any]] | None = None) -> None:
        self.documents.extend(texts)
        if metas:
            self.metadata.extend(metas)
        else:
            self.metadata.extend([{}] * len(texts))

    def build_index(self, embedder) -> None:
        """Compute embeddings for all stored documents."""
        embedder.fit(self.documents)
        self.embeddings = embedder.encode(self.documents)

    # ── query ────────────────────────────────
    def search(
        self,
        query_vec: np.ndarray,
        top_k: int = cfg.RAG_TOP_K,
    ) -> list[dict[str, Any]]:
        """Return the *top_k* most similar documents (cosine similarity)."""
        if self.embeddings is None or len(self.embeddings) == 0:
            return []

        # Cosine similarity
        query_norm = query_vec / (np.linalg.norm(query_vec, axis=-1, keepdims=True) + 1e-10)
        doc_norms = self.embeddings / (np.linalg.norm(self.embeddings, axis=-1, keepdims=True) + 1e-10)

        if query_norm.ndim == 1:
            query_norm = query_norm.reshape(1, -1)

        # Handle dimension mismatch (TF-IDF query vs stored — should match if same vectoriser)
        if query_norm.shape[1] != doc_norms.shape[1]:
            return []

        sims = (query_norm @ doc_norms.T).flatten()
        top_idx = np.argsort(sims)[::-1][:top_k]

        results: list[dict[str, Any]] = []
        for idx in top_idx:
            results.append(
                {
                    "text": self.documents[idx],
                    "score": float(sims[idx]),
                    "metadata": self.metadata[idx],
                }
            )
        return results

    # ── persistence ──────────────────────────
    def save(self, path: Path = cfg.VECTOR_STORE_PATH) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(
            str(path),
            embeddings=self.embeddings,
            documents=np.array(self.documents, dtype=object),
            metadata=np.array([json.dumps(m) for m in self.metadata], dtype=object),
        )
        print(f"  💾  Vector store saved → {path}")

    def load(self, path: Path = cfg.VECTOR_STORE_PATH) -> None:
        data = np.load(str(path), allow_pickle=True)
        self.embeddings = data["embeddings"]
        self.documents = list(data["documents"])
        self.metadata = [json.loads(m) for m in data["metadata"]]
        print(f"  📂  Vector store loaded ← {path}  ({len(self.documents)} chunks)")


# ──────────────────────────────────────────────
# Convenience — build from policy directory
# ──────────────────────────────────────────────

def build_policy_index(
    policies_dir: Path = cfg.POLICIES_DIR,
    save_path: Path = cfg.VECTOR_STORE_PATH,
    backend: str = cfg.EMBEDDING_BACKEND,
) -> tuple[VectorStore, Any]:
    """
    Read all ``.txt`` files from *policies_dir*, chunk them, embed,
    and return a ready-to-query ``(store, embedder)`` pair.
    """
    store = VectorStore()
    embedder = get_embedder(backend)

    policy_files = sorted(policies_dir.glob("*.txt"))
    if not policy_files:
        raise FileNotFoundError(f"No .txt policy files found in {policies_dir}")

    for pf in policy_files:
        text = pf.read_text(encoding="utf-8")
        chunks = chunk_text(text)
        metas = [{"source": pf.name, "chunk_index": i} for i in range(len(chunks))]
        store.add(chunks, metas)
        print(f"  📄  {pf.name}: {len(chunks)} chunks")

    store.build_index(embedder)
    store.save(save_path)

    return store, embedder


# ──────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 60)
    print("  ERP-Sentry — Building Policy Embeddings")
    print("=" * 60)
    store, embedder = build_policy_index()
    print(f"\n  ✅  Indexed {len(store.documents)} chunks from {cfg.POLICIES_DIR}")
