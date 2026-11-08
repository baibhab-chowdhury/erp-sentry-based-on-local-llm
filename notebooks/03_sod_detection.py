# %% [markdown]
# # 03 — ERP SoD Detection Walkthrough
#
# Step-by-step demonstration of the Segregation of Duties violation
# detection pipeline:
# 1. Generate synthetic ERP data
# 2. Apply rule-based pre-filters
# 3. Enrich findings with LLM explanations
# 4. Analyse the risk report

# %%
import sys, json
from pathlib import Path
from collections import defaultdict
sys.path.insert(0, str(Path.cwd().parent))

import pandas as pd
import config as cfg

# %% [markdown]
# ## 1. Generate Synthetic Data

# %%
from data.generate_synthetic_erp import generate_users, generate_access_roles, generate_transactions, save_sqlite

users = generate_users()
access = generate_access_roles(users)
transactions = generate_transactions(users)

# Save to DB
save_sqlite(users, transactions, access)

print(f"Users:        {len(users)}")
print(f"Access roles: {len(access)}")
print(f"Transactions: {len(transactions)}")

# %%
df_users = pd.DataFrame(users)
df_users.head(10)

# %%
df_txns = pd.DataFrame(transactions)
df_txns.describe()

# %% [markdown]
# ## 2. Explore the Data

# %%
# Anomalous transactions
anomalies = df_txns[df_txns["is_anomaly"] == True]
print(f"Anomalous transactions: {len(anomalies)} / {len(df_txns)}")
print(f"\nAnomaly flag distribution:")
for flag_combo in anomalies["anomaly_flags"].value_counts().items():
    print(f"  {flag_combo[0] or '(none)'}: {flag_combo[1]}")

# %%
# SoD violations in access
df_access = pd.DataFrame(access)
violations = df_access[df_access["is_sod_violation"] == True]
print(f"Access entries with SoD violations: {len(violations)}")
print(f"Unique violating users: {violations['user_id'].nunique()}")

# %% [markdown]
# ## 3. Rule-Based SoD Detection

# %%
from agents.risk_detector import (
    detect_sod_conflicts, detect_off_hours_transactions,
    detect_high_amount_transactions
)

sod_findings = detect_sod_conflicts(access, users)
offhour_findings = detect_off_hours_transactions(transactions)
high_amt_findings = detect_high_amount_transactions(transactions)

print(f"SoD conflicts:        {len(sod_findings)}")
print(f"Off-hours txns:       {len(offhour_findings)}")
print(f"High-amount txns:     {len(high_amt_findings)}")
print(f"Total pre-filter:     {len(sod_findings) + len(offhour_findings) + len(high_amt_findings)}")

# %%
# Examine SoD conflicts
print("Sample SoD Conflicts:\n")
for f in sod_findings[:5]:
    print(f"  [{f.severity}] {f.user_name} ({f.user_id})")
    print(f"    {f.details}\n")

# %% [markdown]
# ## 4. Full Scan with LLM Enrichment

# %%
from agents.risk_detector import run_full_scan

# Set enrich=True to have the LLM explain each finding
report = run_full_scan(enrich=True, max_enrich=5)

print(f"Total findings: {report['total_findings']}")
print(f"Severity breakdown: {json.dumps(report['severity_summary'], indent=2)}")

# %%
# Show LLM assessments
for f in report["findings"][:3]:
    if f.get("llm_assessment"):
        print(f"\n{'='*60}")
        print(f"[{f['severity']}] {f['category']} — {f['user_name']}")
        print(f"Details: {f['details']}")
        print(f"\nLLM Assessment:\n{f['llm_assessment']}")

# %% [markdown]
# ## 5. Export Report

# %%
out_path = cfg.DATA_DIR / "risk_report.json"
with open(out_path, "w") as fh:
    json.dump(report, fh, indent=2, default=str)
print(f"Report saved → {out_path}")

# By severity
df_findings = pd.DataFrame(report["findings"])
if not df_findings.empty:
    print(df_findings.groupby("severity").size())

# %% [markdown]
# ## ✅ Summary
#
# Pipeline stages:
# 1. **Synthetic data** with realistic violations injected
# 2. **Rule-based pre-filters** catch SoD conflicts, off-hours, high amounts
# 3. **LLM enrichment** provides natural-language risk explanations
# 4. **Structured report** with severity levels for auditors
#
# **Next:** Run `04_benchmarking.py` for model comparison.
