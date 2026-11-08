#!/usr/bin/env python3
"""
ERP-Sentry — MCP Server (JSON-RPC 2.0 over stdio)
=====================================================
A Model Context Protocol server that exposes ERP-Sentry capabilities as
callable tools for any MCP-compatible client (e.g. Claude Desktop, custom
agents).

Implements:
  * ``initialize``     — MCP handshake
  * ``tools/list``     — enumerate available tools
  * ``tools/call``     — execute a tool

Tools exposed:
  * ``query_erp_transactions`` — search the ERP transaction database
  * ``check_sod_violations``   — run the SoD detection scan
  * ``search_policies``        — RAG search over company policies
  * ``summarize_text``         — summarise arbitrary text via LLM

Launched via::

    python -m agents.mcp_server          # reads JSON-RPC from stdin

The server reads one JSON-RPC message per line from **stdin** and writes
one JSON-RPC response per line to **stdout** (newline-delimited JSON).
"""

from __future__ import annotations

import json
import sqlite3
import sys
for stream in (sys.stdin, sys.stdout, sys.stderr):
    if stream and hasattr(stream, "reconfigure"):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config as cfg

# ──────────────────────────────────────────────
# MCP protocol constants
# ──────────────────────────────────────────────
MCP_PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "erp-sentry-mcp"
SERVER_VERSION = "1.0.0"

# ──────────────────────────────────────────────
# Tool definitions (MCP schema)
# ──────────────────────────────────────────────
TOOLS: list[dict[str, Any]] = [
    {
        "name": "query_erp_transactions",
        "description": (
            "Search ERP transactions by user ID, transaction type, "
            "date range, or amount range. Returns matching records."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "user_id": {
                    "type": "string",
                    "description": "Filter by user ID (e.g. USR-0001).",
                },
                "transaction_type": {
                    "type": "string",
                    "description": "Filter by type (PURCHASE_ORDER, INVOICE, PAYMENT, etc.).",
                },
                "min_amount": {
                    "type": "number",
                    "description": "Minimum USD amount.",
                },
                "max_amount": {
                    "type": "number",
                    "description": "Maximum USD amount.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results to return (default 20).",
                },
            },
            "required": [],
        },
    },
    {
        "name": "check_sod_violations",
        "description": (
            "Run a Segregation of Duties scan across all users' "
            "access permissions. Returns detected violations."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "enrich_with_llm": {
                    "type": "boolean",
                    "description": "If true, each finding gets an LLM-generated assessment (slower).",
                },
            },
            "required": [],
        },
    },
    {
        "name": "search_policies",
        "description": (
            "Search company policy documents using RAG. Returns "
            "the answer and source citations."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "The policy question to answer.",
                },
            },
            "required": ["question"],
        },
    },
    {
        "name": "summarize_text",
        "description": "Summarise arbitrary text using the local LLM.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "The text to summarise.",
                },
            },
            "required": ["text"],
        },
    },
]


# ──────────────────────────────────────────────
# Tool implementations
# ──────────────────────────────────────────────
def _tool_query_erp_transactions(args: dict[str, Any]) -> list[dict[str, Any]]:
    """Execute a filtered query against the transactions table."""
    db_path = cfg.SQLITE_DB_PATH
    if not db_path.exists():
        return [{"error": "Database not found. Run data generator first."}]

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    clauses: list[str] = []
    params: list[Any] = []

    if uid := args.get("user_id"):
        clauses.append("user_id = ?")
        params.append(uid)
    if ttype := args.get("transaction_type"):
        clauses.append("transaction_type = ?")
        params.append(ttype)
    if (min_a := args.get("min_amount")) is not None:
        clauses.append("amount_usd >= ?")
        params.append(min_a)
    if (max_a := args.get("max_amount")) is not None:
        clauses.append("amount_usd <= ?")
        params.append(max_a)

    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    limit = int(args.get("limit", 20))

    sql = f"SELECT * FROM transactions{where} ORDER BY timestamp DESC LIMIT ?"
    params.append(limit)

    rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
    conn.close()
    return rows


def _tool_check_sod_violations(args: dict[str, Any]) -> dict[str, Any]:
    """Run the full SoD detection pipeline."""
    from agents.risk_detector import run_full_scan

    enrich = bool(args.get("enrich_with_llm", False))
    report = run_full_scan(enrich=enrich, max_enrich=10)
    return report


def _tool_search_policies(args: dict[str, Any]) -> dict[str, Any]:
    """RAG search over policy documents."""
    from rag.query_engine import RAGQueryEngine

    question = args.get("question", "")
    if not question:
        return {"error": "Missing required parameter: question"}
    engine = RAGQueryEngine()
    return engine.query(question)


def _tool_summarize_text(args: dict[str, Any]) -> dict[str, str]:
    """Summarise text via the local LLM."""
    from agents.productivity_agent import summarise_text

    text = args.get("text", "")
    if not text:
        return {"error": "Missing required parameter: text"}
    return {"summary": summarise_text(text)}


TOOL_DISPATCH: dict[str, Any] = {
    "query_erp_transactions": _tool_query_erp_transactions,
    "check_sod_violations": _tool_check_sod_violations,
    "search_policies": _tool_search_policies,
    "summarize_text": _tool_summarize_text,
}


# ──────────────────────────────────────────────
# JSON-RPC helpers
# ──────────────────────────────────────────────
def _ok(id_: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": id_, "result": result}


def _error(id_: Any, code: int, message: str, data: Any = None) -> dict[str, Any]:
    err: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": id_, "error": err}


# ──────────────────────────────────────────────
# MCP message handler
# ──────────────────────────────────────────────
def handle_message(msg: dict[str, Any]) -> dict[str, Any] | None:
    """Process a single JSON-RPC message and return the response."""
    method = msg.get("method", "")
    id_ = msg.get("id")
    params = msg.get("params", {})

    # ── initialize ───────────────────────────
    if method == "initialize":
        return _ok(id_, {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {
                "tools": {},
            },
            "serverInfo": {
                "name": SERVER_NAME,
                "version": SERVER_VERSION,
            },
        })

    # ── notifications (no response) ──────────
    if method == "notifications/initialized":
        return None  # notification — no response

    # ── tools/list ───────────────────────────
    if method == "tools/list":
        return _ok(id_, {"tools": TOOLS})

    # ── tools/call ───────────────────────────
    if method == "tools/call":
        tool_name = params.get("name", "")
        tool_args = params.get("arguments", {})

        handler = TOOL_DISPATCH.get(tool_name)
        if handler is None:
            return _error(id_, -32601, f"Unknown tool: {tool_name}")

        try:
            import contextlib
            with contextlib.redirect_stdout(sys.stderr):
                result = handler(tool_args)
            # MCP tools/call expects content array
            content = [{"type": "text", "text": json.dumps(result, default=str, indent=2)}]
            return _ok(id_, {"content": content})
        except Exception as exc:  # noqa: BLE001
            return _error(id_, -32000, f"Tool execution error: {exc}")

    # ── unknown method ───────────────────────
    return _error(id_, -32601, f"Method not found: {method}")


# ──────────────────────────────────────────────
# Main loop — stdio transport
# ──────────────────────────────────────────────
def main() -> None:
    """Read JSON-RPC messages from stdin, write responses to stdout."""
    # Log to stderr so it doesn't pollute the JSON-RPC channel
    sys.stderr.write(f"[{SERVER_NAME}] MCP server started (stdio transport)\n")
    sys.stderr.flush()

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        try:
            msg = json.loads(line)
        except json.JSONDecodeError as exc:
            resp = _error(None, -32700, f"Parse error: {exc}")
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()
            continue

        resp = handle_message(msg)
        if resp is not None:
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()

    sys.stderr.write(f"[{SERVER_NAME}] Server shutting down.\n")
    sys.stderr.flush()


if __name__ == "__main__":
    main()
