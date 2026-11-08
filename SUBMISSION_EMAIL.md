# Application Email Template for iRM / TRP Global

**To:** `HR.SUPPORT@trpglobal.uk`  
**Subject:** Application: Paid AI/LLM Internship — Local LLMs, ERP Access-Risk & MCP Agent — Baibhab  

---

Dear iRM Hiring Team,

I am writing to express my strong interest in the **Paid AI/LLM Internship (Local LLMs · Fine-tuning on ERP data · AI Agents & MCP)** at **iRM (A TRP Global company)**. 

Having seen your focus on enterprise privacy, on-prem local models on Windows, and detecting access-risk exceptions in ERP data, I built an end-to-end local AI project tailored specifically to your domain: **ERP-Sentry**.

### 🔗 Project Links:
- **GitHub Repository:** [Insert your GitHub repo URL here, e.g., `https://github.com/your-username/erp-sentry-local-llm`]
- **Interactive Walkthrough Notebooks:** Available directly in `/notebooks` inside the repository.

---

### How ERP-Sentry Directly Addresses Your Problem Space:

1. **On-Prem Local LLM on Windows (Ollama):**
   - Configured and evaluated on Windows PC using local Ollama instances running **Llama 3.2 3B**, **Qwen 2.5 3B**, and **Llama 3.2 1B** on an NVIDIA RTX 3050 Laptop GPU (4GB VRAM) with complete offline privacy (zero data leakage for sensitive enterprise financial records).

2. **Use Case 2: ERP Access-Risk & Segregation of Duties (SoD) Detection:**
   - Detects the exact scenario highlighted in the JD: **the same person creating a Purchase Order (PO) and processing its payment**.
   - Identifies vendor master fraud risks, off-hours/weekend execution anomalies, unusually high disbursements, and toxic authorization combinations.
   - Combines rule-based pre-filtering with local LLM chain-of-thought risk reasoning and severity classification.

3. **AI Agents & Model Context Protocol (MCP) Server:**
   - Features a fully operational **MCP Server** (`agents/mcp_server.py`) using JSON-RPC 2.0 over stdio following the official MCP specification.
   - Exposes enterprise tools (`query_erp_transactions`, `check_sod_violations`, `search_policies`, `summarize_text`) allowing local agents to securely query ERP databases and compliance policies.

4. **Use Case 1: Internal Team Productivity Suite:**
   - Local LLM tools for everyday team workflows: executive audit report generation, automated meeting minute extraction, email drafting from bullet points, and natural language policy search.

5. **Benchmarking Suite (Speed, Memory, Token Throughput):**
   - Benchmarks local models on Windows PC tracking **tokens per second (TPS)**, **time-to-first-token (TTFT)**, **total latency**, and **VRAM consumption (MB)** via `nvidia-smi`.
   - Compares Llama 3.2 3B vs Qwen 2.5 3B trade-offs across summarization, classification, and complex audit reasoning tasks.

6. **RAG & Policy Vector Embeddings:**
   - Vector search engine grounding risk findings in corporate policies (SOX 404, ISO 27001 Access Governance, Delegation of Authority) using TF-IDF / sentence-transformers and cosine similarity.

7. **Fine-Tuning Preparation (LoRA / QLoRA):**
   - Pre-generated domain instruction dataset (`train_alpaca.jsonl`, `train_chat.jsonl`) pairing ERP transaction logs with audit justifications.
   - Comprehensive guide for parameter-efficient fine-tuning (PEFT/Unsloth) on consumer GPUs.

8. **Interactive UI & Live Demo Ready:**
   - Includes a full **Streamlit Web Dashboard** (`app/dashboard.py`) and step-by-step Jupyter notebooks for a live walkthrough on my Windows PC.

---

### Availability & Location:
I am located in Kolkata, very comfortable commuting to your **Sector V / Rajarhat** office for the hybrid requirement (at least 1 day/week in-office), and available for the full 2-month internship with enthusiasm towards a potential full-time role.

Per the interview note, **I am fully prepared to give a live demo of the local LLM, MCP server, and risk detection agent running directly on my Windows machine.**

My CV is attached. I look forward to the opportunity to discuss how I can contribute to iRM's private AI initiatives.

Warm regards,  
**Baibhab**  
[Your Phone Number]  
[Your LinkedIn Profile]  
[Your GitHub Profile]  
