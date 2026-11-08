#!/usr/bin/env python3
"""
ERP-Sentry — Productivity Agent
==================================
Internal productivity tools powered by a local LLM:

* **Summarise** text or documents
* **Draft professional emails** from bullet points
* **Q&A over company policies** (delegates to RAG)
* **Generate meeting notes** from rough transcripts

Usage::

    python -m agents.productivity_agent
    python agents/productivity_agent.py
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
from rag.query_engine import RAGQueryEngine

# ──────────────────────────────────────────────
# Prompt templates
# ──────────────────────────────────────────────
SUMMARISE_PROMPT = """\
Summarise the following text concisely, preserving key facts and action items. \
Use bullet points where appropriate.

TEXT:
{text}

SUMMARY:"""

EMAIL_PROMPT = """\
Draft a professional business email based on these bullet points. \
Use a polite, formal tone. Include a subject line.

BULLET POINTS:
{bullets}

Recipient context: {context}

EMAIL DRAFT:"""

MEETING_NOTES_PROMPT = """\
Convert the following rough meeting transcript into clean, structured \
meeting notes. Include:
- Meeting title (infer from content)
- Attendees (if mentioned)
- Key discussion points
- Action items with owners (if mentioned)
- Decisions made

TRANSCRIPT:
{transcript}

MEETING NOTES:"""


# ──────────────────────────────────────────────
# Core helper — call Ollama
# ──────────────────────────────────────────────
def _generate(
    prompt: str,
    model: str = cfg.DEFAULT_MODEL,
    system: str = "You are a helpful internal productivity assistant for a corporation.",
    temperature: float = cfg.DEFAULT_TEMPERATURE,
    max_tokens: int = cfg.DEFAULT_MAX_TOKENS,
) -> str:
    """Send a prompt to the local Ollama instance and return the response."""
    payload = {
        "model": model,
        "prompt": prompt,
        "system": system,
        "stream": False,
        "options": {
            "temperature": temperature,
            "top_p": cfg.DEFAULT_TOP_P,
            "num_ctx": cfg.DEFAULT_NUM_CTX,
            "num_predict": max_tokens,
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
            "⚠️  Cannot reach Ollama at "
            f"{cfg.OLLAMA_BASE_URL}. "
            "Please run `ollama serve`."
        )
    except requests.Timeout:
        return "⚠️  Request timed out."
    except Exception as exc:  # noqa: BLE001
        return f"⚠️  Error: {exc}"


# ──────────────────────────────────────────────
# Public tool functions
# ──────────────────────────────────────────────
def summarise_text(text: str, model: str = cfg.DEFAULT_MODEL) -> str:
    """Return a concise summary of *text*."""
    if not text.strip():
        return "⚠️  No text provided."
    prompt = SUMMARISE_PROMPT.format(text=text)
    return _generate(prompt, model=model)


def draft_email(
    bullets: str,
    context: str = "colleague",
    model: str = cfg.DEFAULT_MODEL,
) -> str:
    """Draft a professional email from bullet points."""
    if not bullets.strip():
        return "⚠️  No bullet points provided."
    prompt = EMAIL_PROMPT.format(bullets=bullets, context=context)
    return _generate(prompt, model=model, temperature=0.5)


def policy_qa(
    question: str,
    model: str = cfg.DEFAULT_MODEL,
) -> dict[str, Any]:
    """Answer a question using RAG over company policies."""
    engine = RAGQueryEngine(model=model)
    return engine.query(question)


def generate_meeting_notes(
    transcript: str,
    model: str = cfg.DEFAULT_MODEL,
) -> str:
    """Generate structured meeting notes from a rough transcript."""
    if not transcript.strip():
        return "⚠️  No transcript provided."
    prompt = MEETING_NOTES_PROMPT.format(transcript=transcript)
    return _generate(prompt, model=model, temperature=0.3, max_tokens=1500)


# ──────────────────────────────────────────────
# Interactive CLI
# ──────────────────────────────────────────────
def main() -> None:
    print("=" * 60)
    print("  ERP-Sentry — Productivity Agent")
    print("=" * 60)

    menu = """
    1. Summarise text
    2. Draft email from bullets
    3. Policy Q&A (RAG)
    4. Generate meeting notes
    5. Quit
    """

    while True:
        print(menu)
        choice = input("  Select [1-5]: ").strip()

        if choice == "1":
            print("  Paste text (end with an empty line):")
            lines: list[str] = []
            while True:
                line = input()
                if line == "":
                    break
                lines.append(line)
            text = "\n".join(lines)
            print("\n⏳  Summarising …\n")
            print(summarise_text(text))

        elif choice == "2":
            print("  Paste bullet points (end with an empty line):")
            lines = []
            while True:
                line = input()
                if line == "":
                    break
                lines.append(line)
            bullets = "\n".join(lines)
            context = input("  Recipient context (e.g. 'vendor', 'manager'): ").strip() or "colleague"
            print("\n⏳  Drafting email …\n")
            print(draft_email(bullets, context))

        elif choice == "3":
            question = input("  Your question: ").strip()
            if question:
                print("\n⏳  Searching policies …\n")
                result = policy_qa(question)
                print(f"💬  {result['answer']}\n")
                for s in result["sources"]:
                    print(f"   📄 {s['source']} (score: {s['score']})")

        elif choice == "4":
            print("  Paste transcript (end with an empty line):")
            lines = []
            while True:
                line = input()
                if line == "":
                    break
                lines.append(line)
            transcript = "\n".join(lines)
            print("\n⏳  Generating notes …\n")
            print(generate_meeting_notes(transcript))

        elif choice in ("5", "q", "quit"):
            print("👋  Bye!")
            break
        else:
            print("  ⚠️  Invalid choice.")


if __name__ == "__main__":
    main()
