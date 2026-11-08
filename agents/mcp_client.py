#!/usr/bin/env python3
"""
ERP-Sentry — MCP Client Demo
================================
A simple MCP client that launches the ``mcp_server.py`` as a subprocess
(stdio transport) and demonstrates calling each tool.

Usage::

    python -m agents.mcp_client
    python agents/mcp_client.py
"""

from __future__ import annotations

import json
import subprocess
import sys
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# ──────────────────────────────────────────────
# JSON-RPC helpers
# ──────────────────────────────────────────────
_msg_id = 0


def _next_id() -> int:
    global _msg_id
    _msg_id += 1
    return _msg_id


def make_request(method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build a JSON-RPC 2.0 request."""
    req: dict[str, Any] = {
        "jsonrpc": "2.0",
        "id": _next_id(),
        "method": method,
    }
    if params is not None:
        req["params"] = params
    return req


def make_notification(method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build a JSON-RPC 2.0 notification (no id)."""
    note: dict[str, Any] = {
        "jsonrpc": "2.0",
        "method": method,
    }
    if params is not None:
        note["params"] = params
    return note


# ──────────────────────────────────────────────
# MCP client
# ──────────────────────────────────────────────
class MCPClient:
    """Manage an MCP server subprocess and send/receive JSON-RPC messages."""

    def __init__(self, server_script: str | Path | None = None) -> None:
        if server_script is None:
            server_script = Path(__file__).resolve().parent / "mcp_server.py"
        self.server_script = str(server_script)
        self.process: subprocess.Popen | None = None

    def start(self) -> None:
        """Launch the MCP server as a subprocess."""
        self.process = subprocess.Popen(
            [sys.executable, self.server_script],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,  # line-buffered
        )
        print(f"  🚀  MCP server started (PID {self.process.pid})")

    def stop(self) -> None:
        """Terminate the server subprocess."""
        if self.process:
            self.process.stdin.close()  # type: ignore[union-attr]
            self.process.terminate()
            self.process.wait(timeout=5)
            print("  🛑  MCP server stopped.")

    def send(self, msg: dict[str, Any]) -> dict[str, Any] | None:
        """
        Send a JSON-RPC message to the server and return the response.
        For notifications (no ``id``), returns ``None``.
        """
        assert self.process and self.process.stdin and self.process.stdout

        line = json.dumps(msg) + "\n"
        self.process.stdin.write(line)
        self.process.stdin.flush()

        # Notifications don't get a response
        if "id" not in msg:
            return None

        resp_line = self.process.stdout.readline()
        if not resp_line:
            return None
        return json.loads(resp_line)

    # ── Convenience wrappers ─────────────────
    def initialize(self) -> dict[str, Any] | None:
        resp = self.send(make_request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "erp-sentry-client", "version": "1.0.0"},
        }))
        # Send initialized notification
        self.send(make_notification("notifications/initialized"))
        return resp

    def list_tools(self) -> dict[str, Any] | None:
        return self.send(make_request("tools/list"))

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any] | None:
        return self.send(make_request("tools/call", {
            "name": name,
            "arguments": arguments or {},
        }))


# ──────────────────────────────────────────────
# Demo
# ──────────────────────────────────────────────
def main() -> None:
    print("=" * 60)
    print("  ERP-Sentry — MCP Client Demo")
    print("=" * 60)

    client = MCPClient()
    client.start()

    try:
        # 1. Initialize
        print("\n── 1. Initialize ──")
        resp = client.initialize()
        print(json.dumps(resp, indent=2))

        # 2. List tools
        print("\n── 2. List Tools ──")
        resp = client.list_tools()
        if resp and "result" in resp:
            for tool in resp["result"].get("tools", []):
                print(f"  🔧  {tool['name']}: {tool['description'][:80]}…")
        else:
            print(json.dumps(resp, indent=2))

        # 3. Query transactions
        print("\n── 3. Query ERP Transactions ──")
        resp = client.call_tool("query_erp_transactions", {
            "transaction_type": "PAYMENT",
            "min_amount": 10000,
            "limit": 5,
        })
        _print_tool_result(resp)

        # 4. Check SoD violations (without LLM to keep it fast)
        print("\n── 4. Check SoD Violations ──")
        resp = client.call_tool("check_sod_violations", {
            "enrich_with_llm": False,
        })
        _print_tool_result(resp)

        # 5. Search policies
        print("\n── 5. Search Policies (RAG) ──")
        resp = client.call_tool("search_policies", {
            "question": "What are the approval thresholds for expenses over $25,000?",
        })
        _print_tool_result(resp)

        # 6. Summarize text
        print("\n── 6. Summarize Text ──")
        resp = client.call_tool("summarize_text", {
            "text": (
                "The quarterly financial review meeting highlighted several key areas. "
                "Revenue grew 12% year-over-year, driven primarily by the SaaS division. "
                "Operating expenses increased 8% due to new hires in engineering and sales. "
                "The CFO recommended tightening discretionary spending in Q4 to meet margin targets. "
                "The board approved the proposed capital expenditure budget of $2.5M for the new "
                "data center expansion. Action items include completing the vendor selection "
                "for cloud infrastructure by end of month."
            ),
        })
        _print_tool_result(resp)

    finally:
        client.stop()

    print("\n  ✅  MCP client demo complete.")


def _print_tool_result(resp: dict[str, Any] | None) -> None:
    """Pretty-print a tools/call response."""
    if resp is None:
        print("  (no response)")
        return
    if "error" in resp:
        print(f"  ❌  Error: {resp['error']}")
        return
    content_list = resp.get("result", {}).get("content", [])
    for item in content_list:
        text = item.get("text", "")
        # Try to parse and pretty-print JSON
        try:
            data = json.loads(text)
            # For long outputs, just show a summary
            if isinstance(data, list) and len(data) > 3:
                print(f"  → {len(data)} records returned. First 2:")
                print(json.dumps(data[:2], indent=2, default=str))
            elif isinstance(data, dict) and "findings" in data:
                print(f"  → {data.get('total_findings', '?')} findings detected.")
                for f in data.get("findings", [])[:3]:
                    print(f"    [{f.get('severity')}] {f.get('details', '')[:100]}…")
            else:
                print(json.dumps(data, indent=2, default=str)[:500])
        except json.JSONDecodeError:
            print(f"  → {text[:300]}")


if __name__ == "__main__":
    main()
