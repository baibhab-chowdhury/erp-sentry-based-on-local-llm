#!/usr/bin/env python3
"""
ERP-Sentry — Synthetic ERP Data Generator
===========================================
Produces realistic, labelled ERP data with deliberately injected
Segregation-of-Duties (SoD) violations and anomalous transactions.

Outputs
-------
* ``data/users.csv``
* ``data/transactions.csv``
* ``data/access_roles.csv``
* ``data/erp_data.db``   (SQLite with the same three tables)

Usage::

    python -m data.generate_synthetic_erp          # from project root
    python data/generate_synthetic_erp.py           # direct
"""

from __future__ import annotations

import csv
import random
import sqlite3
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

# Allow running from project root or from data/
import sys
import io
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config as cfg

try:
    from faker import Faker
    fake = Faker()
    Faker.seed(cfg.RANDOM_SEED)
except ImportError:
    # Graceful fallback using standard library if faker is not yet installed
    class SimpleFake:
        def __init__(self):
            self.first_names = ["James", "Mary", "Robert", "Patricia", "John", "Jennifer", "Michael", "Linda",
                                "David", "Elizabeth", "William", "Barbara", "Richard", "Susan", "Joseph", "Jessica",
                                "Thomas", "Sarah", "Charles", "Karen", "Christopher", "Nancy", "Daniel", "Lisa",
                                "Matthew", "Betty", "Anthony", "Margaret", "Mark", "Sandra", "Priya", "Rahul",
                                "Amit", "Sneha", "Vikram", "Ananya", "Rohan", "Pooja", "Arjun", "Kavita"]
            self.last_names = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis",
                               "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez", "Wilson", "Anderson",
                               "Thomas", "Taylor", "Moore", "Jackson", "Martin", "Sharma", "Verma", "Patel",
                               "Chatterjee", "Banerjee", "Mukherjee", "Das", "Sen", "Gupta", "Roy"]

        def name(self) -> str:
            return f"{random.choice(self.first_names)} {random.choice(self.last_names)}"

        def first_name(self) -> str:
            return random.choice(self.first_names)

        def company_email(self) -> str:
            fn = random.choice(self.first_names).lower()
            ln = random.choice(self.last_names).lower()
            domain = random.choice(["irmcloud.app", "trpglobal.uk", "techriskpartners.com", "enterprise-audit.local"])
            return f"{fn}.{ln}@{domain}"

        def date_between(self, start_date: str = "-5y", end_date: str = "-30d") -> datetime.date:
            days_ago_start = 1825 if "5y" in start_date else 1095
            days_ago_end = 30 if "30d" in end_date else 10
            days = random.randint(days_ago_end, days_ago_start)
            return (datetime.now() - timedelta(days=days)).date()

        def date_time_between(self, start_date: str = "-6M", end_date: str = "now") -> datetime:
            days = random.randint(1, 180)
            base = datetime.now() - timedelta(days=days)
            # Default to business hours 9am-6pm, Mon-Fri
            hour = random.randint(9, 17)
            minute = random.randint(0, 59)
            second = random.randint(0, 59)
            # Ensure weekday
            if base.weekday() >= 5:
                base = base - timedelta(days=base.weekday() - 4)
            return base.replace(hour=hour, minute=minute, second=second)

    fake = SimpleFake()

random.seed(cfg.RANDOM_SEED)

# ──────────────────────────────────────────────
# Reference data
# ──────────────────────────────────────────────
DEPARTMENTS = [
    "Accounts Payable",
    "Accounts Receivable",
    "Procurement",
    "Finance",
    "Human Resources",
    "IT Administration",
    "Sales",
    "Warehouse",
]

ROLES = [
    "AP Clerk",
    "AR Clerk",
    "Procurement Officer",
    "Finance Manager",
    "HR Specialist",
    "IT Admin",
    "Sales Executive",
    "Warehouse Supervisor",
    "Controller",
    "CFO",
]

# T-code style permissions
PERMISSIONS: dict[str, list[str]] = {
    "AP Clerk":              ["PROCESS_INVOICE", "MATCH_PO_INVOICE", "SCHEDULE_PAYMENT"],
    "AR Clerk":              ["CREATE_INVOICE", "POST_RECEIPT", "MANAGE_CREDIT_MEMO"],
    "Procurement Officer":   ["CREATE_PURCHASE_ORDER", "CREATE_VENDOR", "RECEIVE_GOODS"],
    "Finance Manager":       ["APPROVE_PAYMENT", "POST_JOURNAL_ENTRY", "RUN_FINANCIAL_REPORT"],
    "HR Specialist":         ["MANAGE_EMPLOYEE", "RUN_PAYROLL"],
    "IT Admin":              ["MANAGE_USER_ACCESS", "SYSTEM_CONFIG"],
    "Sales Executive":       ["CREATE_SALES_ORDER", "MANAGE_CUSTOMER"],
    "Warehouse Supervisor":  ["RECEIVE_GOODS", "SHIP_GOODS", "MANAGE_INVENTORY"],
    "Controller":            ["CREATE_JOURNAL_ENTRY", "APPROVE_JOURNAL_ENTRY", "RUN_FINANCIAL_REPORT"],
    "CFO":                   ["APPROVE_PAYMENT", "APPROVE_JOURNAL_ENTRY", "RUN_FINANCIAL_REPORT"],
}

TRANSACTION_TYPES = [
    "PURCHASE_ORDER",
    "INVOICE",
    "PAYMENT",
    "JOURNAL_ENTRY",
    "GOODS_RECEIPT",
    "SALES_ORDER",
    "CREDIT_MEMO",
    "VENDOR_CREATION",
]

COMPANY_NAMES = [
    "Pinnacle Manufacturing Ltd.",
    "Crestwood Supplies Inc.",
    "Nexus Global Trading",
    "Silverline Electronics Co.",
    "Horizon Logistics Partners",
    "BlueStar Chemicals AG",
    "Meridian Health Solutions",
    "Vertex Industrial Corp.",
]

VENDOR_NAMES = [
    "Apex Raw Materials Co.",
    "TrueNorth Hardware Supply",
    "Pacific Components Ltd.",
    "Evergreen Office Supplies",
    "Summit Tech Solutions",
    "Ironclad Fasteners Inc.",
    "BrightWave Electricals",
    "CoreSteel Manufacturing",
    "Redwood Packaging Co.",
    "Atlas Industrial Parts",
]


# ──────────────────────────────────────────────
# Generate users
# ──────────────────────────────────────────────
def generate_users(n: int = cfg.SYNTHETIC_NUM_USERS) -> list[dict[str, Any]]:
    """Create *n* employee records with role and department."""
    users: list[dict[str, Any]] = []
    for i in range(1, n + 1):
        role = random.choice(ROLES)
        dept = random.choice([d for d in DEPARTMENTS if _role_fits_dept(role, d)] or DEPARTMENTS)
        users.append(
            {
                "user_id": f"USR-{i:04d}",
                "full_name": fake.name(),
                "email": fake.company_email(),
                "department": dept,
                "role": role,
                "hire_date": fake.date_between(start_date="-5y", end_date="-30d").isoformat(),
                "is_active": True,
            }
        )
    return users


def _role_fits_dept(role: str, dept: str) -> bool:
    mapping = {
        "AP Clerk": "Accounts Payable",
        "AR Clerk": "Accounts Receivable",
        "Procurement Officer": "Procurement",
        "Finance Manager": "Finance",
        "HR Specialist": "Human Resources",
        "IT Admin": "IT Administration",
        "Sales Executive": "Sales",
        "Warehouse Supervisor": "Warehouse",
        "Controller": "Finance",
        "CFO": "Finance",
    }
    return mapping.get(role) == dept


# ──────────────────────────────────────────────
# Generate access/permissions
# ──────────────────────────────────────────────
def generate_access_roles(
    users: list[dict[str, Any]],
    violation_rate: float = cfg.SYNTHETIC_VIOLATION_RATE,
) -> list[dict[str, Any]]:
    """
    Assign permissions to each user.  Deliberately gives some users
    conflicting permissions to create SoD violations.
    """
    access: list[dict[str, Any]] = []
    violator_count = max(1, int(len(users) * violation_rate))
    violators = random.sample(users, violator_count)
    violator_ids = {u["user_id"] for u in violators}

    for user in users:
        uid = user["user_id"]
        base_perms = list(PERMISSIONS.get(user["role"], []))

        if uid in violator_ids:
            # Inject a conflicting permission pair
            conflict_pair = random.choice(cfg.SOD_CONFLICT_PAIRS)
            for perm in conflict_pair:
                if perm not in base_perms:
                    base_perms.append(perm)

        for perm in base_perms:
            access.append(
                {
                    "access_id": str(uuid.uuid4())[:8].upper(),
                    "user_id": uid,
                    "permission": perm,
                    "granted_date": fake.date_between(start_date="-3y", end_date="-10d").isoformat(),
                    "granted_by": random.choice(["ADMIN", "SYSTEM", fake.first_name()]),
                    "is_sod_violation": uid in violator_ids,
                }
            )

    return access


# ──────────────────────────────────────────────
# Generate transactions
# ──────────────────────────────────────────────
def generate_transactions(
    users: list[dict[str, Any]],
    n: int = cfg.SYNTHETIC_NUM_TRANSACTIONS,
    violation_rate: float = cfg.SYNTHETIC_VIOLATION_RATE,
) -> list[dict[str, Any]]:
    """
    Create *n* ERP transaction records. A fraction deliberately includes
    anomalies: off-hours, weekends, unusually high amounts, or actions
    by users who should not perform them.
    """
    txns: list[dict[str, Any]] = []
    anomaly_count = int(n * violation_rate)
    anomaly_indices = set(random.sample(range(n), anomaly_count))

    for i in range(n):
        user = random.choice(users)
        txn_type = random.choice(TRANSACTION_TYPES)
        is_anomaly = i in anomaly_indices

        # Base realistic timestamp (business hours, weekdays)
        ts = fake.date_time_between(start_date="-6M", end_date="now")
        amount = round(random.uniform(50, 15_000), 2)

        flags: list[str] = []

        if is_anomaly:
            anomaly_kind = random.choice(["off_hours", "weekend", "high_amount", "both"])
            if anomaly_kind in ("off_hours", "both"):
                hour = random.choice([0, 1, 2, 3, 4, 22, 23])
                ts = ts.replace(hour=hour, minute=random.randint(0, 59))
                flags.append("OFF_HOURS")
            if anomaly_kind in ("weekend", "both"):
                # Shift to Saturday or Sunday
                days_ahead = (5 - ts.weekday()) % 7 or 7
                ts = ts + timedelta(days=days_ahead)
                flags.append("WEEKEND")
            if anomaly_kind in ("high_amount", "both"):
                amount = round(random.uniform(55_000, 250_000), 2)
                flags.append("HIGH_AMOUNT")

        txns.append(
            {
                "txn_id": f"TXN-{i + 1:06d}",
                "user_id": user["user_id"],
                "user_name": user["full_name"],
                "transaction_type": txn_type,
                "amount_usd": amount,
                "currency": "USD",
                "timestamp": ts.isoformat(),
                "vendor": random.choice(VENDOR_NAMES),
                "company": random.choice(COMPANY_NAMES),
                "description": _txn_description(txn_type),
                "status": random.choice(["COMPLETED", "PENDING", "APPROVED"]),
                "is_anomaly": is_anomaly,
                "anomaly_flags": "|".join(flags) if flags else "",
            }
        )

    return txns


def _txn_description(txn_type: str) -> str:
    templates: dict[str, list[str]] = {
        "PURCHASE_ORDER": [
            "PO for office supplies",
            "PO for raw materials — Q4 batch",
            "Urgent PO for replacement parts",
            "PO for IT equipment refresh",
        ],
        "INVOICE": [
            "Vendor invoice for consulting services",
            "Invoice for hardware delivery",
            "Monthly retainer invoice",
            "Invoice for maintenance contract",
        ],
        "PAYMENT": [
            "Wire transfer to supplier",
            "Scheduled payment run",
            "Early-pay discount settlement",
            "Manual payment — management approved",
        ],
        "JOURNAL_ENTRY": [
            "Accrual adjustment — month-end",
            "Intercompany transfer entry",
            "Depreciation — fixed assets",
            "FX revaluation entry",
        ],
        "GOODS_RECEIPT": [
            "Received shipment — warehouse A",
            "Partial delivery received",
            "Quality-inspected goods receipt",
            "Returned goods re-receipt",
        ],
        "SALES_ORDER": [
            "Customer order — standard terms",
            "Rush order — priority shipping",
            "Blanket sales order renewal",
            "Online storefront order",
        ],
        "CREDIT_MEMO": [
            "Credit memo for returned goods",
            "Pricing correction credit",
            "Promotional discount credit",
            "Duplicate payment reversal",
        ],
        "VENDOR_CREATION": [
            "New vendor onboarding — domestic",
            "International vendor setup",
            "One-time vendor registration",
            "Preferred supplier enrollment",
        ],
    }
    return random.choice(templates.get(txn_type, ["General transaction"]))


# ──────────────────────────────────────────────
# Persist to CSV + SQLite
# ──────────────────────────────────────────────
def save_csv(rows: list[dict[str, Any]], path: Path) -> None:
    """Write a list of dicts to a CSV file."""
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    print(f"  💾  Wrote {len(rows):,} rows → {path}")


def save_sqlite(
    users: list[dict[str, Any]],
    transactions: list[dict[str, Any]],
    access_roles: list[dict[str, Any]],
    db_path: Path = cfg.SQLITE_DB_PATH,
) -> None:
    """Persist all three tables to a SQLite database."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()

    # Users
    cur.execute("DROP TABLE IF EXISTS users")
    cur.execute(
        """
        CREATE TABLE users (
            user_id      TEXT PRIMARY KEY,
            full_name    TEXT,
            email        TEXT,
            department   TEXT,
            role         TEXT,
            hire_date    TEXT,
            is_active    INTEGER
        )
        """
    )
    cur.executemany(
        "INSERT INTO users VALUES (?,?,?,?,?,?,?)",
        [
            (u["user_id"], u["full_name"], u["email"], u["department"], u["role"], u["hire_date"], int(u["is_active"]))
            for u in users
        ],
    )

    # Access roles
    cur.execute("DROP TABLE IF EXISTS access_roles")
    cur.execute(
        """
        CREATE TABLE access_roles (
            access_id       TEXT PRIMARY KEY,
            user_id         TEXT,
            permission      TEXT,
            granted_date    TEXT,
            granted_by      TEXT,
            is_sod_violation INTEGER,
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        )
        """
    )
    cur.executemany(
        "INSERT INTO access_roles VALUES (?,?,?,?,?,?)",
        [
            (a["access_id"], a["user_id"], a["permission"], a["granted_date"], a["granted_by"], int(a["is_sod_violation"]))
            for a in access_roles
        ],
    )

    # Transactions
    cur.execute("DROP TABLE IF EXISTS transactions")
    cur.execute(
        """
        CREATE TABLE transactions (
            txn_id            TEXT PRIMARY KEY,
            user_id           TEXT,
            user_name         TEXT,
            transaction_type  TEXT,
            amount_usd        REAL,
            currency          TEXT,
            timestamp         TEXT,
            vendor            TEXT,
            company           TEXT,
            description       TEXT,
            status            TEXT,
            is_anomaly        INTEGER,
            anomaly_flags     TEXT,
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        )
        """
    )
    cur.executemany(
        "INSERT INTO transactions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            (
                t["txn_id"], t["user_id"], t["user_name"], t["transaction_type"],
                t["amount_usd"], t["currency"], t["timestamp"], t["vendor"],
                t["company"], t["description"], t["status"],
                int(t["is_anomaly"]), t["anomaly_flags"],
            )
            for t in transactions
        ],
    )

    conn.commit()
    conn.close()
    print(f"  💾  SQLite database → {db_path}")


# ──────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────
def main() -> None:
    print("=" * 60)
    print("  ERP-Sentry — Synthetic Data Generator")
    print("=" * 60)

    users = generate_users()
    access_roles = generate_access_roles(users)
    transactions = generate_transactions(users)

    save_csv(users, cfg.DATA_DIR / "users.csv")
    save_csv(access_roles, cfg.DATA_DIR / "access_roles.csv")
    save_csv(transactions, cfg.DATA_DIR / "transactions.csv")
    save_sqlite(users, transactions, access_roles)

    # Summary stats
    violations = sum(1 for a in access_roles if a["is_sod_violation"])
    anomalies = sum(1 for t in transactions if t["is_anomaly"])
    print()
    print(f"  📊  Users:          {len(users)}")
    print(f"  📊  Access entries: {len(access_roles)} ({violations} with SoD violations)")
    print(f"  📊  Transactions:   {len(transactions)} ({anomalies} anomalous)")
    print("  ✅  Done!")


if __name__ == "__main__":
    main()
