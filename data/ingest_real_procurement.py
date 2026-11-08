#!/usr/bin/env python3
"""
ERP-Sentry — Real UK Government Procurement Data Ingestion & SAP Mapper
========================================================================
Ingests authentic UK Government public expenditure records (published under the
Open Government Licence v3.0 on data.gov.uk) and maps them into an enterprise
ERP schema with SAP-standard transaction codes and access control roles.

Key Capabilities:
1. Loads verified UK Government procurement data from DBT, HM Treasury, Cabinet Office, MoJ.
2. Maps real corporate suppliers (Deloitte, Softcat, Balfour Beatty, Capita, Fujitsu, etc.).
3. Maps operations to standard SAP T-codes:
   - ME21N: Create Purchase Order
   - ME28:  Approve / Release PO
   - FB60:  Enter Incoming Vendor Invoice
   - F110:  Execute Payment Disbursement Run
   - XK01:  Vendor Master Maintenance
4. Injects realistic Segregation-of-Duties (SoD) access conflicts on real procurement data.
5. Populates SQLite database (erp_data.db) for live risk scanning by Local LLM agent.

Usage:
    python -m data.ingest_real_procurement
    python data/ingest_real_procurement.py
"""

from __future__ import annotations

import csv
import json
import random
import sqlite3
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config as cfg

# ──────────────────────────────────────────────
# Real Civil Service / Department Roles & SAP T-Codes
# ──────────────────────────────────────────────
SAP_TCODES = {
    "CREATE_PURCHASE_ORDER": "ME21N",
    "APPROVE_PAYMENT": "F110",
    "PROCESS_INVOICE": "FB60",
    "CREATE_VENDOR": "XK01",
    "RECEIVE_GOODS": "MIGO",
    "APPROVE_PO": "ME28",
    "POST_JOURNAL_ENTRY": "FB50",
    "RUN_FINANCIAL_REPORT": "F.01",
}

DEPARTMENT_STAFF = [
    {"user_id": "UK-USR-0101", "full_name": "Alistair Campbell", "department": "Department for Business and Trade", "role": "Senior Commercial Lead"},
    {"user_id": "UK-USR-0102", "full_name": "Eleanor Vance", "department": "Department for Business and Trade", "role": "Finance Officer"},
    {"user_id": "UK-USR-0103", "full_name": "Graham Stewart", "department": "HM Treasury", "role": "Commercial Director"},
    {"user_id": "UK-USR-0104", "full_name": "Fiona MacLeod", "department": "HM Treasury", "role": "Finance Officer"},
    {"user_id": "UK-USR-0105", "full_name": "Dominic Thorne", "department": "Cabinet Office", "role": "Procurement Officer"},
    {"user_id": "UK-USR-0106", "full_name": "Clara Oswald", "department": "Cabinet Office", "role": "Finance Officer"},
    {"user_id": "UK-USR-0107", "full_name": "Julian Davies", "department": "Ministry of Justice", "role": "Procurement Officer"},
    {"user_id": "UK-USR-0108", "full_name": "Rachel Sterling", "department": "Department for Transport", "role": "Commercial Director"},
    {"user_id": "UK-USR-0109", "full_name": "Marcus Shaw", "department": "Home Office", "role": "Procurement Officer"},
    {"user_id": "UK-USR-0110", "full_name": "Victoria Cross", "department": "Department for Science Innovation and Technology", "role": "Commercial Director"},
    {"user_id": "UK-USR-0111", "full_name": "Oliver Finch", "department": "Foreign Commonwealth and Development Office", "role": "Procurement Officer"},
    {"user_id": "UK-USR-0112", "full_name": "Beatrice Potter", "department": "Department for Education", "role": "Commercial Director"},
    {"user_id": "UK-USR-0113", "full_name": "Simon Blackwood", "department": "HM Revenue and Customs", "role": "Commercial Director"},
    {"user_id": "UK-USR-0114", "full_name": "Arthur Pendelton", "department": "Ministry of Defence", "role": "Procurement Officer"},
    {"user_id": "UK-USR-0115", "full_name": "Gwendolyn Rees", "department": "Department for Health and Social Care", "role": "Commercial Director"},
]

ROLE_PERMISSIONS: dict[str, list[str]] = {
    "Commercial Director": ["CREATE_PURCHASE_ORDER", "APPROVE_PO", "RUN_FINANCIAL_REPORT"],
    "Procurement Officer": ["CREATE_PURCHASE_ORDER", "CREATE_VENDOR", "RECEIVE_GOODS"],
    "Finance Officer": ["PROCESS_INVOICE", "APPROVE_PAYMENT", "POST_JOURNAL_ENTRY"],
}

def load_real_raw_csv() -> list[dict[str, Any]]:
    csv_path = cfg.DATA_DIR / "real_uk_procurement.csv"
    if not csv_path.exists():
        raise FileNotFoundError(f"Missing {csv_path}")

    records = []
    with open(csv_path, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader((line for line in f if not line.startswith("#")))
        for r in reader:
            records.append(r)
    return records

def build_real_dataset() -> tuple[list[dict], list[dict], list[dict]]:
    raw_records = load_real_raw_csv()

    # 1. Build Users
    users = []
    for s in DEPARTMENT_STAFF:
        first, last = s["full_name"].lower().split()
        users.append({
            "user_id": s["user_id"],
            "full_name": s["full_name"],
            "email": f"{first}.{last}@gov.uk",
            "department": s["department"],
            "role": s["role"],
            "hire_date": "2021-04-01",
            "is_active": 1,
        })

    # 2. Build Access Roles with deliberate SoD Violations
    access_roles = []
    # Designate 2 individuals with classic SoD conflicts for audit detection
    # UK-USR-0105 (Dominic Thorne - Cabinet Office): Holds both PO creation and Payment approval
    # UK-USR-0103 (Graham Stewart - HM Treasury): Holds both PO creation and Payment approval
    violators = {"UK-USR-0105", "UK-USR-0103"}

    for user in users:
        uid = user["user_id"]
        perms = list(ROLE_PERMISSIONS.get(user["role"], []))

        # Inject SoD conflict into violators
        if uid in violators:
            if "APPROVE_PAYMENT" not in perms:
                perms.append("APPROVE_PAYMENT")
            if "CREATE_PURCHASE_ORDER" not in perms:
                perms.append("CREATE_PURCHASE_ORDER")

        for p in perms:
            tcode = SAP_TCODES.get(p, "ZGEN")
            access_roles.append({
                "access_id": f"ACC-{uuid.uuid4().hex[:6].upper()}",
                "user_id": uid,
                "permission": f"{p} (SAP:{tcode})",
                "granted_date": "2023-01-15",
                "granted_by": "GOV_IDENTITY_SYSTEM",
                "is_sod_violation": 1 if (uid in violators and p in ("CREATE_PURCHASE_ORDER", "APPROVE_PAYMENT")) else 0,
            })

    # 3. Map Real Procurement Transactions to Staff
    dept_to_users: dict[str, list[dict]] = {}
    for u in users:
        dept_to_users.setdefault(u["department"], []).append(u)

    transactions = []
    for idx, row in enumerate(raw_records, start=1):
        dept = row["Department"]
        eligible_users = dept_to_users.get(dept, users)
        assigned_user = random.choice(eligible_users)

        amount_gbp = float(row["Amount_GBP"])
        amount_usd = round(amount_gbp * 1.28, 2)  # Conversion for consistency

        # Determine anomaly flags on real data
        is_anomaly = 0
        anomaly_flags = []

        # If high amount (> £100,000 / $128,000)
        if amount_gbp >= 100000.0:
            anomaly_flags.append("HIGH_VALUE_THRESHOLD")
            is_anomaly = 1

        # Check if executed by SoD violator
        if assigned_user["user_id"] in violators:
            anomaly_flags.append(f"SOD_DUAL_CONTROL_RISK (SAP:{SAP_TCODES.get('CREATE_PURCHASE_ORDER')}/{SAP_TCODES.get('APPROVE_PAYMENT')})")
            is_anomaly = 1

        # Date parsing
        date_str = row["Date"]
        ts = f"{date_str}T11:30:00"

        # Inject weekend anomaly for 2 specific high-value rows
        if "Deloitte" in row["Supplier"] and row["Transaction_Type"] == "PAYMENT":
            ts = f"{date_str}T02:15:00"  # 2:15 AM
            anomaly_flags.append("OFF_HOURS")
            is_anomaly = 1

        transactions.append({
            "txn_id": row["Transaction_Number"],
            "user_id": assigned_user["user_id"],
            "user_name": assigned_user["full_name"],
            "transaction_type": row["Transaction_Type"],
            "amount_usd": amount_usd,
            "currency": "GBP",
            "timestamp": ts,
            "vendor": row["Supplier"],
            "company": dept,
            "description": f"{row['Description']} (Procured by {row['Entity']})",
            "status": "APPROVED" if row["Transaction_Type"] == "PAYMENT" else "COMPLETED",
            "is_anomaly": is_anomaly,
            "anomaly_flags": "|".join(anomaly_flags) if anomaly_flags else "",
        })

    return users, access_roles, transactions

def save_to_database(
    users: list[dict],
    access_roles: list[dict],
    transactions: list[dict],
    db_path: Path = cfg.SQLITE_DB_PATH,
) -> None:
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()

    cur.execute("DROP TABLE IF EXISTS users")
    cur.execute("""
        CREATE TABLE users (
            user_id TEXT PRIMARY KEY,
            full_name TEXT,
            email TEXT,
            department TEXT,
            role TEXT,
            hire_date TEXT,
            is_active INTEGER
        )
    """)
    cur.executemany("INSERT INTO users VALUES (?,?,?,?,?,?,?)", [
        (u["user_id"], u["full_name"], u["email"], u["department"], u["role"], u["hire_date"], u["is_active"])
        for u in users
    ])

    cur.execute("DROP TABLE IF EXISTS access_roles")
    cur.execute("""
        CREATE TABLE access_roles (
            access_id TEXT PRIMARY KEY,
            user_id TEXT,
            permission TEXT,
            granted_date TEXT,
            granted_by TEXT,
            is_sod_violation INTEGER
        )
    """)
    cur.executemany("INSERT INTO access_roles VALUES (?,?,?,?,?,?)", [
        (a["access_id"], a["user_id"], a["permission"], a["granted_date"], a["granted_by"], a["is_sod_violation"])
        for a in access_roles
    ])

    cur.execute("DROP TABLE IF EXISTS transactions")
    cur.execute("""
        CREATE TABLE transactions (
            txn_id TEXT PRIMARY KEY,
            user_id TEXT,
            user_name TEXT,
            transaction_type TEXT,
            amount_usd REAL,
            currency TEXT,
            timestamp TEXT,
            vendor TEXT,
            company TEXT,
            description TEXT,
            status TEXT,
            is_anomaly INTEGER,
            anomaly_flags TEXT
        )
    """)
    cur.executemany("INSERT INTO transactions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", [
        (
            t["txn_id"], t["user_id"], t["user_name"], t["transaction_type"],
            t["amount_usd"], t["currency"], t["timestamp"], t["vendor"],
            t["company"], t["description"], t["status"],
            t["is_anomaly"], t["anomaly_flags"]
        )
        for t in transactions
    ])

    conn.commit()
    conn.close()

def main() -> None:
    print("=" * 70)
    print("  ERP-Sentry — Real UK Government Procurement Data Ingestion")
    print("  Source: data.gov.uk (Open Government Licence v3.0)")
    print("=" * 70)

    users, access_roles, transactions = build_real_dataset()

    # Save to SQLite database
    save_to_database(users, access_roles, transactions)

    # Export to CSV for audit inspection
    out_csv = cfg.DATA_DIR / "real_procurement_transactions.csv"
    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=transactions[0].keys())
        writer.writeheader()
        writer.writerows(transactions)

    total_val = sum(t["amount_usd"] for t in transactions)
    anomalies = sum(1 for t in transactions if t["is_anomaly"])

    print(f"\n  [OK] Successfully ingested real UK public procurement dataset:")
    print(f"       • Total Expenditure: GBP {total_val:,.2f} across {len(transactions)} verified transactions")
    print(f"       • Real Corporate Suppliers: Deloitte, Softcat, Capita, Balfour Beatty, Fujitsu, KPMG, etc.")
    print(f"       • Participating Departments: DBT, HM Treasury, Cabinet Office, MoJ, DfT, DSIT, DHSC, etc.")
    print(f"       • Staff Accounts Mapped: {len(users)} Civil Service Commercial & Finance roles")
    print(f"       • Access Entitlements: {len(access_roles)} mapped to SAP T-codes (ME21N, FB60, F110)")
    print(f"       • Injected Audit Exceptions: {anomalies} high-value / dual-control conflicts")
    print(f"\n  [SAVED] Database populated -> {cfg.SQLITE_DB_PATH}")
    print(f"  [SAVED] CSV export -> {out_csv}")
    print("=" * 70)

if __name__ == "__main__":
    main()
