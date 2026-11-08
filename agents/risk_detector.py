#!/usr/bin/env python3
"""
ERP-Sentry — Access-Risk & SoD Violation Detector
=====================================================
The core agent that:

1. Loads transaction & access data from the SQLite database.
2. Applies rule-based pre-filters for Segregation-of-Duties conflicts,
   off-hours activity, and unusually high amounts.
3. Sends flagged patterns to a local LLM for natural-language risk
   assessment and explanation.
4. Outputs a structured risk report.

Usage::

    python -m agents.risk_detector
    python agents/risk_detector.py
"""

from __future__ import annotations

import json
import sqlite3
import sys
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config as cfg


# ──────────────────────────────────────────────
# Data models
# ──────────────────────────────────────────────
@dataclass
class RiskFinding:
    """A single flagged risk item."""
    finding_id: str
    category: str            # SOD_CONFLICT | OFF_HOURS | HIGH_AMOUNT | COMBINED
    severity: str            # CRITICAL | HIGH | MEDIUM | LOW
    user_id: str
    user_name: str
    details: str             # human-readable rule-based description
    related_txns: list[str] = field(default_factory=list)
    llm_assessment: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


# ──────────────────────────────────────────────
# Database helpers
# ──────────────────────────────────────────────
def _connect(db_path: Path = cfg.SQLITE_DB_PATH) -> sqlite3.Connection:
    if not db_path.exists():
        raise FileNotFoundError(
            f"Database not found at {db_path}. "
            "Run `python -m data.generate_synthetic_erp` first."
        )
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def load_users(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [dict(r) for r in conn.execute("SELECT * FROM users").fetchall()]


def load_transactions(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [dict(r) for r in conn.execute("SELECT * FROM transactions").fetchall()]


def load_access_roles(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [dict(r) for r in conn.execute("SELECT * FROM access_roles").fetchall()]


# ──────────────────────────────────────────────
# Rule-based pre-filters
# ──────────────────────────────────────────────
_finding_counter = 0


def _next_id() -> str:
    global _finding_counter
    _finding_counter += 1
    return f"RISK-{_finding_counter:04d}"


def detect_sod_conflicts(
    access_roles: list[dict[str, Any]],
    users: list[dict[str, Any]],
) -> list[RiskFinding]:
    """
    Check whether any user holds two permissions that form a
    conflicting pair defined in ``config.SOD_CONFLICT_PAIRS``.
    """
    user_map: dict[str, str] = {u["user_id"]: u["full_name"] for u in users}
    user_perms: dict[str, set[str]] = defaultdict(set)
    for ar in access_roles:
        user_perms[ar["user_id"]].add(ar["permission"])

    findings: list[RiskFinding] = []
    def _has_perm(needle: str, user_perm_set: set[str]) -> bool:
        return any(needle in p for p in user_perm_set)

    for uid, perms in user_perms.items():
        for perm_a, perm_b in cfg.SOD_CONFLICT_PAIRS:
            if _has_perm(perm_a, perms) and _has_perm(perm_b, perms):
                findings.append(
                    RiskFinding(
                        finding_id=_next_id(),
                        category="SOD_CONFLICT",
                        severity="CRITICAL",
                        user_id=uid,
                        user_name=user_map.get(uid, "Unknown"),
                        details=(
                            f"User holds conflicting permissions: "
                            f"'{perm_a}' and '{perm_b}'. "
                            f"This violates Segregation of Duties."
                        ),
                    )
                )
    return findings


def detect_off_hours_transactions(
    transactions: list[dict[str, Any]],
) -> list[RiskFinding]:
    """Flag transactions executed outside normal business hours or on weekends."""
    findings: list[RiskFinding] = []
    for txn in transactions:
        ts = datetime.fromisoformat(txn["timestamp"])
        reasons: list[str] = []
        if ts.weekday() in cfg.WEEKEND_DAYS:
            reasons.append(f"weekend ({ts.strftime('%A')})")
        if ts.hour >= cfg.OFF_HOURS_START or ts.hour < cfg.OFF_HOURS_END:
            reasons.append(f"off-hours ({ts.strftime('%H:%M')})")
        if reasons:
            findings.append(
                RiskFinding(
                    finding_id=_next_id(),
                    category="OFF_HOURS",
                    severity="MEDIUM",
                    user_id=txn["user_id"],
                    user_name=txn["user_name"],
                    details=(
                        f"Transaction {txn['txn_id']} ({txn['transaction_type']}) "
                        f"for ${txn['amount_usd']:,.2f} executed during "
                        f"{', '.join(reasons)}."
                    ),
                    related_txns=[txn["txn_id"]],
                )
            )
    return findings


def detect_high_amount_transactions(
    transactions: list[dict[str, Any]],
) -> list[RiskFinding]:
    """Flag transactions with unusually high amounts."""
    findings: list[RiskFinding] = []
    for txn in transactions:
        if txn["amount_usd"] > cfg.HIGH_AMOUNT_THRESHOLD:
            findings.append(
                RiskFinding(
                    finding_id=_next_id(),
                    category="HIGH_AMOUNT",
                    severity="HIGH",
                    user_id=txn["user_id"],
                    user_name=txn["user_name"],
                    details=(
                        f"Transaction {txn['txn_id']} ({txn['transaction_type']}) "
                        f"has an unusually high amount: ${txn['amount_usd']:,.2f} "
                        f"(threshold: ${cfg.HIGH_AMOUNT_THRESHOLD:,.2f})."
                    ),
                    related_txns=[txn["txn_id"]],
                )
            )
    return findings


# ──────────────────────────────────────────────
# LLM-powered risk assessment
# ──────────────────────────────────────────────
RISK_ASSESSMENT_PROMPT = """\
You are an ERP compliance auditor AI. Analyse the following flagged risk \
finding and provide:
1. A concise risk explanation (2-3 sentences).
2. Potential business impact.
3. Recommended remediation action.

FINDING:
Category: {category}
Severity: {severity}
User: {user_name} ({user_id})
Details: {details}

Respond in a structured format."""


def enrich_with_llm(
    findings: list[RiskFinding],
    model: str = cfg.DEFAULT_MODEL,
    max_enrich: int = 20,
) -> list[RiskFinding]:
    """
    Send the top *max_enrich* findings to the local LLM for a
    natural-language risk assessment. Skips gracefully if Ollama is
    unreachable.
    """
    # Sort by severity (critical first)
    severity_order = {v: k for k, v in cfg.RISK_SEVERITY_LEVELS.items()}
    sorted_findings = sorted(
        findings,
        key=lambda f: cfg.RISK_SEVERITY_LEVELS.get(f.severity, 0),
        reverse=True,
    )

    for finding in sorted_findings[:max_enrich]:
        prompt = RISK_ASSESSMENT_PROMPT.format(
            category=finding.category,
            severity=finding.severity,
            user_name=finding.user_name,
            user_id=finding.user_id,
            details=finding.details,
        )
        try:
            resp = requests.post(
                cfg.OLLAMA_GENERATE_URL,
                json={
                    "model": model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "temperature": 0.2,
                        "num_predict": 300,
                        "num_ctx": cfg.DEFAULT_NUM_CTX,
                    },
                },
                timeout=cfg.REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            finding.llm_assessment = resp.json().get("response", "").strip()
        except requests.ConnectionError:
            finding.llm_assessment = (
                "[LLM unavailable — Ollama not running]"
            )
        except Exception as exc:  # noqa: BLE001
            finding.llm_assessment = f"[LLM error: {exc}]"

    return findings


# ──────────────────────────────────────────────
# Report generation
# ──────────────────────────────────────────────
def generate_report(findings: list[RiskFinding]) -> dict[str, Any]:
    """Build a structured JSON report from the findings list."""
    summary: dict[str, int] = defaultdict(int)
    for f in findings:
        summary[f.severity] += 1

    return {
        "report_title": "ERP-Sentry Risk Assessment Report",
        "generated_at": datetime.now().isoformat(),
        "total_findings": len(findings),
        "severity_summary": dict(summary),
        "findings": [asdict(f) for f in findings],
    }


# ──────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────
def run_full_scan(
    db_path: Path = cfg.SQLITE_DB_PATH,
    model: str = cfg.DEFAULT_MODEL,
    enrich: bool = True,
    max_enrich: int = 20,
) -> dict[str, Any]:
    """
    Execute the complete risk-detection pipeline and return the report dict.
    """
    conn = _connect(db_path)
    users = load_users(conn)
    transactions = load_transactions(conn)
    access_roles = load_access_roles(conn)
    conn.close()

    # Rule-based detection
    findings: list[RiskFinding] = []
    findings.extend(detect_sod_conflicts(access_roles, users))
    findings.extend(detect_off_hours_transactions(transactions))
    findings.extend(detect_high_amount_transactions(transactions))

    # LLM enrichment
    if enrich:
        findings = enrich_with_llm(findings, model=model, max_enrich=max_enrich)

    return generate_report(findings)


# ──────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────
def main() -> None:
    print("=" * 60)
    print("  ERP-Sentry — Risk Detection Scan")
    print("=" * 60)

    report = run_full_scan()

    # Pretty-print summary
    print(f"\n  📊  Total findings: {report['total_findings']}")
    for sev, count in sorted(report["severity_summary"].items()):
        print(f"      {sev}: {count}")

    # Save report
    out_path = cfg.DATA_DIR / "risk_report.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)
    print(f"\n  💾  Report saved → {out_path}")

    # Show top 5 findings
    print("\n  🔍  Top findings:")
    for f in report["findings"][:5]:
        print(f"    [{f['severity']}] {f['category']}: {f['details'][:120]}…")
        if f.get("llm_assessment"):
            snippet = f["llm_assessment"][:200].replace("\n", " ")
            print(f"         LLM: {snippet}…")

    print("\n  ✅  Scan complete.")


if __name__ == "__main__":
    main()
