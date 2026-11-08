#!/usr/bin/env python3
"""
ERP-Sentry — Streamlit Dashboard
====================================
A unified web interface that ties together every ERP-Sentry capability:

* Tab 1: ERP Risk Scanner (SoD detection)
* Tab 2: Policy Q&A (RAG)
* Tab 3: Productivity Tools
* Tab 4: Benchmark Results
* Tab 5: MCP Server

Launch::

    streamlit run app/dashboard.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import streamlit as st
import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config as cfg

# ──────────────────────────────────────────────
# Page config
# ──────────────────────────────────────────────
st.set_page_config(
    page_title=cfg.STREAMLIT_PAGE_TITLE,
    page_icon=cfg.STREAMLIT_PAGE_ICON,
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom CSS for iRM-style branding
st.markdown(
    f"""
    <style>
    .stApp {{
        font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
    }}
    .main-header {{
        background: linear-gradient(135deg, {cfg.PRIMARY_COLOR} 0%, #2d5f8a 100%);
        padding: 1.5rem 2rem;
        border-radius: 10px;
        color: white;
        margin-bottom: 1.5rem;
    }}
    .main-header h1 {{
        margin: 0;
        font-size: 2rem;
    }}
    .main-header p {{
        margin: 0.3rem 0 0;
        opacity: 0.85;
        font-size: 0.95rem;
    }}
    .metric-card {{
        background: #f8f9fa;
        border-left: 4px solid {cfg.ACCENT_COLOR};
        padding: 1rem;
        border-radius: 6px;
        margin-bottom: 0.5rem;
    }}
    .risk-critical {{ border-left-color: #dc3545; background: #fff5f5; }}
    .risk-high {{ border-left-color: #fd7e14; background: #fff8f0; }}
    .risk-medium {{ border-left-color: #ffc107; background: #fffdf0; }}
    .risk-low {{ border-left-color: #28a745; background: #f0fff4; }}
    </style>
    """,
    unsafe_allow_html=True,
)


# ──────────────────────────────────────────────
# Sidebar
# ──────────────────────────────────────────────
def render_sidebar() -> str:
    """Render sidebar with model selector and system status."""
    with st.sidebar:
        st.image(
            "https://img.shields.io/badge/ERP--Sentry-v1.0-blue?style=for-the-badge",
            width=200,
        )
        st.markdown("### ⚙️ Configuration")

        # Model selector
        model = st.selectbox(
            "LLM Model",
            cfg.AVAILABLE_MODELS,
            index=0,
            help="Select the Ollama model to use for inference.",
        )

        st.markdown("---")
        st.markdown("### 📡 System Status")

        # Ollama status
        try:
            resp = requests.get(cfg.OLLAMA_TAGS_URL, timeout=3)
            resp.raise_for_status()
            models = [m["name"] for m in resp.json().get("models", [])]
            st.success(f"Ollama: Running ({len(models)} models)")
            with st.expander("Pulled models"):
                for m in models:
                    st.code(m, language=None)
        except Exception:
            st.error("Ollama: Not reachable")
            st.caption(f"Expected at `{cfg.OLLAMA_BASE_URL}`")

        # GPU info
        try:
            import shutil
            nvidia_smi = shutil.which("nvidia-smi")
            if nvidia_smi:
                out = subprocess.check_output(
                    [nvidia_smi, "--query-gpu=name,memory.used,memory.total", "--format=csv,noheader,nounits"],
                    text=True, timeout=5,
                ).strip()
                parts = [p.strip() for p in out.split(",")]
                st.info(f"GPU: {parts[0]}")
                used, total = int(parts[1]), int(parts[2])
                st.progress(used / total, text=f"VRAM: {used}/{total} MB")
            else:
                st.warning("GPU: nvidia-smi not found")
        except Exception:
            st.warning("GPU: Could not query")

        # DB status & Dataset Manager
        st.markdown("---")
        st.markdown("### 🗄️ ERP Dataset Source")
        if cfg.SQLITE_DB_PATH.exists():
            import sqlite3
            try:
                conn = sqlite3.connect(str(cfg.SQLITE_DB_PATH))
                txn_count = conn.execute("SELECT count(*) FROM transactions").fetchone()[0]
                sample_vendor = conn.execute("SELECT vendor FROM transactions LIMIT 1").fetchone()
                conn.close()
                is_real = sample_vendor and any(v in sample_vendor[0] for v in ["Deloitte", "Softcat", "Capita", "Fujitsu", "Balfour", "Computacenter"])
                if is_real:
                    st.success("🇬🇧 Real UK Govt Procurement (OGL v3)")
                    st.caption(f"Verified data.gov.uk spend ({txn_count} records)")
                else:
                    st.info(f"📊 Synthetic ERP Benchmark ({txn_count} records)")
            except Exception:
                st.success("Database: Connected")
        else:
            st.warning("Database: Not generated yet")

        col_d1, col_d2 = st.columns(2)
        with col_d1:
            if st.button("🇬🇧 Load Real Data", use_container_width=True, help="Load authentic UK Government spend data"):
                from data.ingest_real_procurement import main as load_real
                load_real()
                st.rerun()
        with col_d2:
            if st.button("📊 Load Synthetic", use_container_width=True, help="Generate synthetic test data"):
                from data.generate_synthetic_erp import main as load_synth
                load_synth()
                st.rerun()

        st.markdown("---")
        st.caption("Built for iRM (TRP Global) · On-Prem Local LLM")

    return model  # type: ignore[return-value]


# ──────────────────────────────────────────────
# Tab 1: ERP Risk Scanner
# ──────────────────────────────────────────────
def tab_risk_scanner(model: str) -> None:
    st.markdown(
        '<div class="main-header">'
        '<h1>🔍 ERP Risk Scanner</h1>'
        '<p>Detect Segregation of Duties violations and transaction anomalies</p>'
        '</div>',
        unsafe_allow_html=True,
    )

    if not cfg.SQLITE_DB_PATH.exists():
        st.warning(
            "⚠️ No data found. Generate synthetic data first:\n\n"
            "```bash\npython -m data.generate_synthetic_erp\n```"
        )
        return

    col1, col2, col3 = st.columns(3)
    with col1:
        enrich = st.checkbox("Enrich with LLM analysis", value=True)
    with col2:
        max_enrich = st.slider("Max findings to enrich", 5, 50, 15)
    with col3:
        st.empty()

    if st.button("🚀 Run Risk Scan", type="primary", use_container_width=True):
        with st.spinner("Scanning transactions and access controls …"):
            from agents.risk_detector import run_full_scan
            report = run_full_scan(model=model, enrich=enrich, max_enrich=max_enrich)

        # Summary metrics
        st.markdown("### 📊 Scan Summary")
        cols = st.columns(5)
        severity_map = {"CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡", "LOW": "🟢"}
        total = report["total_findings"]
        cols[0].metric("Total Findings", total)
        for i, (sev, icon) in enumerate(severity_map.items(), 1):
            count = report["severity_summary"].get(sev, 0)
            if i < len(cols):
                cols[i].metric(f"{icon} {sev}", count)

        # Findings table
        st.markdown("### 📋 Detailed Findings")
        if report["findings"]:
            df = pd.DataFrame(report["findings"])
            display_cols = ["finding_id", "severity", "category", "user_name", "details"]
            available_cols = [c for c in display_cols if c in df.columns]
            st.dataframe(
                df[available_cols],
                use_container_width=True,
                hide_index=True,
            )

            # Expandable LLM assessments
            st.markdown("### 🤖 LLM Risk Assessments")
            for finding in report["findings"][:max_enrich]:
                if finding.get("llm_assessment"):
                    severity_class = f"risk-{finding['severity'].lower()}"
                    with st.expander(
                        f"[{finding['severity']}] {finding['finding_id']} — {finding['category']}"
                    ):
                        st.markdown(f"**User:** {finding['user_name']} (`{finding['user_id']}`)")
                        st.markdown(f"**Details:** {finding['details']}")
                        st.markdown("---")
                        st.markdown(f"**LLM Assessment:**\n\n{finding['llm_assessment']}")

            # Download report
            st.download_button(
                "📥 Download Full Report (JSON)",
                data=json.dumps(report, indent=2, default=str),
                file_name="erp_sentry_risk_report.json",
                mime="application/json",
            )
        else:
            st.success("✅ No risk findings detected!")


# ──────────────────────────────────────────────
# Tab 2: Policy Q&A
# ──────────────────────────────────────────────
def tab_policy_qa(model: str) -> None:
    st.markdown(
        '<div class="main-header">'
        '<h1>📚 Policy Q&A</h1>'
        '<p>Ask questions about company policies using RAG</p>'
        '</div>',
        unsafe_allow_html=True,
    )

    # Show available policies
    with st.expander("📄 Available Policy Documents"):
        policy_files = sorted(cfg.POLICIES_DIR.glob("*.txt"))
        if policy_files:
            for pf in policy_files:
                st.markdown(f"- **{pf.stem.replace('_', ' ').title()}** (`{pf.name}`)")
        else:
            st.warning("No policy files found.")

    # Example questions
    examples = [
        "What are the approval thresholds for expenses?",
        "What permissions are considered SoD conflicts?",
        "How should new vendors be onboarded?",
        "What is the data retention policy for financial records?",
        "What happens if a data breach is suspected?",
    ]

    st.markdown("**Example questions:**")
    example_cols = st.columns(len(examples))
    selected_example = ""
    for i, ex in enumerate(examples):
        if example_cols[i].button(ex[:30] + "…", key=f"ex_{i}"):
            selected_example = ex

    question = st.text_input(
        "💬 Ask a question:",
        value=selected_example,
        placeholder="e.g., What is the maximum expense I can approve without CFO sign-off?",
    )

    if question and st.button("🔍 Search & Answer", type="primary"):
        with st.spinner("Retrieving relevant policies and generating answer …"):
            from rag.query_engine import RAGQueryEngine
            engine = RAGQueryEngine(model=model)
            result = engine.query(question)

        st.markdown("### 💬 Answer")
        st.markdown(result["answer"])

        st.markdown("### 📚 Sources")
        for s in result["sources"]:
            with st.expander(f"📄 {s['source']} (relevance: {s['score']:.3f})"):
                st.markdown(s["snippet"])


# ──────────────────────────────────────────────
# Tab 3: Productivity Tools
# ──────────────────────────────────────────────
def tab_productivity(model: str) -> None:
    st.markdown(
        '<div class="main-header">'
        '<h1>⚡ Productivity Tools</h1>'
        '<p>Summarise documents, draft emails, and generate meeting notes</p>'
        '</div>',
        unsafe_allow_html=True,
    )

    tool = st.radio(
        "Select tool:",
        ["📝 Summarise Text", "✉️ Draft Email", "📋 Meeting Notes"],
        horizontal=True,
    )

    if tool == "📝 Summarise Text":
        text = st.text_area(
            "Paste text to summarise:",
            height=200,
            placeholder="Paste a document, report, or article here …",
        )
        if text and st.button("Summarise", type="primary"):
            with st.spinner("Summarising …"):
                from agents.productivity_agent import summarise_text
                summary = summarise_text(text, model=model)
            st.markdown("### Summary")
            st.markdown(summary)

    elif tool == "✉️ Draft Email":
        bullets = st.text_area(
            "Bullet points for the email:",
            height=150,
            placeholder="- Meeting rescheduled to Friday\n- Need Q3 report by EOD\n- Budget approved",
        )
        context = st.text_input(
            "Recipient context:",
            placeholder="e.g., manager, vendor, client",
            value="colleague",
        )
        if bullets and st.button("Draft Email", type="primary"):
            with st.spinner("Drafting email …"):
                from agents.productivity_agent import draft_email
                email = draft_email(bullets, context=context, model=model)
            st.markdown("### Email Draft")
            st.code(email, language=None)

    elif tool == "📋 Meeting Notes":
        transcript = st.text_area(
            "Paste rough meeting transcript:",
            height=200,
            placeholder="John: Let's discuss the Q3 numbers …\nSarah: Revenue is up 12% …",
        )
        if transcript and st.button("Generate Notes", type="primary"):
            with st.spinner("Generating meeting notes …"):
                from agents.productivity_agent import generate_meeting_notes
                notes = generate_meeting_notes(transcript, model=model)
            st.markdown("### Meeting Notes")
            st.markdown(notes)


# ──────────────────────────────────────────────
# Tab 4: Benchmark Results
# ──────────────────────────────────────────────
def tab_benchmarks() -> None:
    st.markdown(
        '<div class="main-header">'
        '<h1>📊 Benchmark Results</h1>'
        '<p>Compare model performance across ERP tasks</p>'
        '</div>',
        unsafe_allow_html=True,
    )

    results_path = cfg.BENCHMARK_RESULTS_PATH
    if not results_path.exists():
        st.warning(
            "⚠️ No benchmark results found. Run the benchmark first:\n\n"
            "```bash\npython -m benchmark.run_benchmark\n```"
        )
        return

    with open(results_path, encoding="utf-8") as fh:
        results = json.load(fh)

    # System info
    sys_info = results.get("system_info", {})
    gpu_info = sys_info.get("gpu", {})
    col1, col2, col3 = st.columns(3)
    col1.metric("CPU Cores", sys_info.get("cpu_count", "?"))
    col2.metric("RAM", f"{sys_info.get('ram_total_gb', '?')} GB")
    col3.metric("GPU", gpu_info.get("name", "N/A"))

    st.markdown("---")

    # Build comparison dataframe
    rows: list[dict[str, Any]] = []
    for model_name in results.get("models_tested", []):
        model_res = results["results_by_model"].get(model_name, [])
        valid = [r for r in model_res if "error" not in r]
        if not valid:
            continue
        rows.append({
            "Model": model_name,
            "Avg Tokens/s": round(sum(r["tokens_per_sec"] for r in valid) / len(valid), 1),
            "Avg TTFT (s)": round(sum(r["time_to_first_token_s"] for r in valid) / len(valid), 3),
            "Avg Latency (s)": round(sum(r["total_latency_s"] for r in valid) / len(valid), 2),
            "Tasks Completed": len(valid),
        })

    if rows:
        df = pd.DataFrame(rows)
        st.markdown("### Model Comparison")
        st.dataframe(df, use_container_width=True, hide_index=True)

        # Charts
        import plotly.express as px

        col1, col2 = st.columns(2)
        with col1:
            fig = px.bar(
                df, x="Model", y="Avg Tokens/s",
                title="Generation Speed (tokens/sec)",
                color="Avg Tokens/s",
                color_continuous_scale="Blues",
            )
            st.plotly_chart(fig, use_container_width=True)

        with col2:
            fig = px.bar(
                df, x="Model", y="Avg TTFT (s)",
                title="Time to First Token",
                color="Avg TTFT (s)",
                color_continuous_scale="Oranges",
            )
            st.plotly_chart(fig, use_container_width=True)

        # Per-category breakdown
        st.markdown("### Per-Category Performance")
        all_results: list[dict] = []
        for model_name in results.get("models_tested", []):
            for r in results["results_by_model"].get(model_name, []):
                if "error" not in r:
                    all_results.append({
                        "Model": model_name,
                        "Category": r.get("category", "unknown"),
                        "Tokens/s": r.get("tokens_per_sec", 0),
                        "Latency (s)": r.get("total_latency_s", 0),
                    })

        if all_results:
            df_detail = pd.DataFrame(all_results)
            fig = px.box(
                df_detail, x="Category", y="Tokens/s", color="Model",
                title="Tokens/sec by Task Category",
            )
            st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No valid benchmark data to display.")

    # Download
    st.download_button(
        "📥 Download Raw Results (JSON)",
        data=json.dumps(results, indent=2, default=str),
        file_name="benchmark_results.json",
        mime="application/json",
    )


# ──────────────────────────────────────────────
# Tab 5: MCP Server
# ──────────────────────────────────────────────
def tab_mcp_server() -> None:
    st.markdown(
        '<div class="main-header">'
        '<h1>🔌 MCP Server</h1>'
        '<p>Model Context Protocol — expose ERP-Sentry tools to AI agents</p>'
        '</div>',
        unsafe_allow_html=True,
    )

    st.markdown("""
    The MCP server exposes ERP-Sentry capabilities as callable tools via the
    [Model Context Protocol](https://modelcontextprotocol.io) (JSON-RPC 2.0 over stdio).

    ### Available Tools
    """)

    tools_info = [
        ("query_erp_transactions", "Search ERP transactions by user, type, amount, or date range."),
        ("check_sod_violations", "Run a full Segregation of Duties scan and return detected violations."),
        ("search_policies", "RAG-powered search over company policy documents."),
        ("summarize_text", "Summarise arbitrary text using the local LLM."),
    ]

    for name, desc in tools_info:
        st.markdown(f"- **`{name}`** — {desc}")

    st.markdown("---")

    st.markdown("### 🚀 Launch MCP Server")
    st.code("python -m agents.mcp_server", language="bash")

    st.markdown("### 🧪 Test with MCP Client")
    st.code("python -m agents.mcp_client", language="bash")

    st.markdown("### 📋 Claude Desktop Configuration")
    mcp_config = {
        "mcpServers": {
            "erp-sentry": {
                "command": "python",
                "args": ["-m", "agents.mcp_server"],
                "cwd": str(cfg.PROJECT_ROOT),
            }
        }
    }
    st.json(mcp_config)

    st.markdown("### 🔧 Test a Tool Call")

    tool_choice = st.selectbox("Tool", [t[0] for t in tools_info])

    if tool_choice == "query_erp_transactions":
        col1, col2 = st.columns(2)
        txn_type = col1.selectbox("Transaction type", ["", "PURCHASE_ORDER", "INVOICE", "PAYMENT", "JOURNAL_ENTRY"])
        min_amount = col2.number_input("Min amount", value=0, step=1000)
        if st.button("Execute Tool"):
            args: dict[str, Any] = {"limit": 10}
            if txn_type:
                args["transaction_type"] = txn_type
            if min_amount > 0:
                args["min_amount"] = min_amount
            _execute_mcp_tool_inline(tool_choice, args)

    elif tool_choice == "check_sod_violations":
        enrich = st.checkbox("Enrich with LLM", value=False)
        if st.button("Execute Tool"):
            _execute_mcp_tool_inline(tool_choice, {"enrich_with_llm": enrich})

    elif tool_choice == "search_policies":
        question = st.text_input("Policy question")
        if question and st.button("Execute Tool"):
            _execute_mcp_tool_inline(tool_choice, {"question": question})

    elif tool_choice == "summarize_text":
        text = st.text_area("Text to summarize")
        if text and st.button("Execute Tool"):
            _execute_mcp_tool_inline(tool_choice, {"text": text})


def _execute_mcp_tool_inline(tool_name: str, args: dict[str, Any]) -> None:
    """Execute an MCP tool directly (without launching the server subprocess)."""
    with st.spinner(f"Executing `{tool_name}` …"):
        # Import the tool dispatch directly
        from agents.mcp_server import TOOL_DISPATCH
        handler = TOOL_DISPATCH.get(tool_name)
        if handler is None:
            st.error(f"Unknown tool: {tool_name}")
            return
        try:
            result = handler(args)
            st.json(result)
        except Exception as exc:
            st.error(f"Error: {exc}")


# ──────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────
def main() -> None:
    model = render_sidebar()

    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "🔍 ERP Risk Scanner",
        "📚 Policy Q&A",
        "⚡ Productivity",
        "📊 Benchmarks",
        "🔌 MCP Server",
    ])

    with tab1:
        tab_risk_scanner(model)
    with tab2:
        tab_policy_qa(model)
    with tab3:
        tab_productivity(model)
    with tab4:
        tab_benchmarks()
    with tab5:
        tab_mcp_server()


if __name__ == "__main__":
    main()
