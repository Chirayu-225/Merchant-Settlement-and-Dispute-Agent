"""SQLite storage shared by both features: synthetic records, results, one audit log and
the LLM cache."""
import json
import sqlite3
from datetime import datetime

import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);

-- Payout side
CREATE TABLE IF NOT EXISTS merchants (
    merchant_id TEXT PRIMARY KEY, name TEXT, language TEXT, loan_daily REAL
);
CREATE TABLE IF NOT EXISTS transactions (
    txn_id TEXT PRIMARY KEY, merchant_id TEXT, amount REAL, method TEXT, status TEXT,
    paid_at TEXT, settlement_date TEXT
);
CREATE TABLE IF NOT EXISTS refunds (
    refund_id TEXT PRIMARY KEY, txn_id TEXT, merchant_id TEXT, amount REAL, settlement_date TEXT
);
CREATE TABLE IF NOT EXISTS chargebacks (
    chargeback_id TEXT PRIMARY KEY, txn_id TEXT, merchant_id TEXT, amount REAL,
    settlement_date TEXT, dispute_id TEXT
);
CREATE TABLE IF NOT EXISTS loan_deductions (
    deduction_id TEXT PRIMARY KEY, merchant_id TEXT, amount REAL, settlement_date TEXT
);
CREATE TABLE IF NOT EXISTS settlements (
    settlement_id TEXT PRIMARY KEY, merchant_id TEXT, settlement_date TEXT, gross REAL,
    fees REAL, gst REAL, refunds REAL, chargebacks REAL, loan REAL, net_amount REAL,
    status TEXT, utr TEXT
);
CREATE TABLE IF NOT EXISTS bank_credits (
    credit_id TEXT PRIMARY KEY, merchant_id TEXT, utr TEXT, amount REAL, credited_at TEXT
);
CREATE TABLE IF NOT EXISTS day_labels (
    merchant_id TEXT, settlement_date TEXT, gt_anomaly TEXT, gt_impact REAL,
    PRIMARY KEY (merchant_id, settlement_date)
);
CREATE TABLE IF NOT EXISTS payout_results (
    merchant_id TEXT, settlement_date TEXT, breakdown TEXT, anomalies TEXT, amount_owed REAL,
    handoffs TEXT, explanation TEXT, language TEXT, explanation_source TEXT,
    explanation_verified INTEGER, attempts INTEGER, duration_seconds REAL, processed_at TEXT,
    PRIMARY KEY (merchant_id, settlement_date)
);
CREATE TABLE IF NOT EXISTS tickets (
    ticket_id TEXT PRIMARY KEY, merchant_id TEXT, settlement_date TEXT, anomaly_type TEXT,
    amount REAL, summary TEXT, evidence TEXT, status TEXT, created_at TEXT, raised_at TEXT
);

-- Dispute side
CREATE TABLE IF NOT EXISTS orders (
    order_id TEXT PRIMARY KEY, merchant_id TEXT, customer_id TEXT, item TEXT,
    amount REAL, created_at TEXT, device_id TEXT, ship_to TEXT
);
CREATE TABLE IF NOT EXISTS payments (
    txn_id TEXT PRIMARY KEY, order_id TEXT, amount REAL, status TEXT, method TEXT,
    auth_method TEXT, auth_verified INTEGER, paid_at TEXT, device_id TEXT
);
CREATE TABLE IF NOT EXISTS deliveries (
    delivery_id TEXT PRIMARY KEY, order_id TEXT, status TEXT, delivered_at TEXT,
    proof_type TEXT, proof_ref TEXT, delivered_to TEXT
);
CREATE TABLE IF NOT EXISTS disputes (
    dispute_id TEXT PRIMARY KEY, notice_text TEXT, status TEXT, is_demo INTEGER,
    scenario TEXT, gt_action TEXT, gt_decision TEXT, gt_reason TEXT,
    merchant_id TEXT, chargeback_id TEXT, suite TEXT DEFAULT 'main'
);
CREATE TABLE IF NOT EXISTS submissions (
    dispute_id TEXT PRIMARY KEY, response_text TEXT, submitted_at TEXT, dry_run INTEGER
);
CREATE TABLE IF NOT EXISTS escalations (
    dispute_id TEXT PRIMARY KEY, failed_checks TEXT, handoff_note TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS dispute_results (
    dispute_id TEXT PRIMARY KEY, decision TEXT, checks TEXT, assessment TEXT, draft TEXT,
    llm_providers TEXT, duration_seconds REAL, processed_at TEXT
);

-- Product layer
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, persona TEXT, event TEXT,
    merchant_id TEXT, ref TEXT, props TEXT
);
CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, merchant_id TEXT, settlement_date TEXT,
    helpful INTEGER, reason TEXT
);

-- Shared
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT, feature TEXT, ref TEXT, step TEXT, detail TEXT, ts TEXT
);
CREATE TABLE IF NOT EXISTS llm_cache (
    key TEXT PRIMARY KEY, task TEXT, provider TEXT, response TEXT, created_at TEXT
);
"""

DATA_TABLES = ["merchants", "transactions", "refunds", "chargebacks", "loan_deductions",
               "settlements", "bank_credits", "day_labels", "payout_results", "tickets",
               "orders", "payments", "deliveries", "disputes", "submissions", "escalations",
               "dispute_results", "audit_log", "events", "feedback"]


def connect() -> sqlite3.Connection:
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(config.DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_schema() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)


def reset_schema() -> None:
    """Drop every data table and rebuild it. The LLM cache is kept."""
    with connect() as conn:
        for table in DATA_TABLES:
            conn.execute(f"DROP TABLE IF EXISTS {table}")
        conn.executescript(SCHEMA)


def exists() -> bool:
    if not config.DB_PATH.exists():
        return False
    with connect() as conn:
        columns = [r["name"] for r in conn.execute("PRAGMA table_info(disputes)")]
        if "suite" not in columns:
            return False  # a database from an older version of the schema
        for table in ("merchants", "disputes"):
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
            if not row or conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0:
                return False
    return True


def one(sql: str, params: tuple = ()) -> dict | None:
    with connect() as conn:
        row = conn.execute(sql, params).fetchone()
    return dict(row) if row else None


def many(sql: str, params: tuple = ()) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def execute(sql: str, params: tuple = ()) -> None:
    with connect() as conn:
        conn.execute(sql, params)


def get_meta(key: str) -> str | None:
    row = one("SELECT value FROM meta WHERE key=?", (key,))
    return row["value"] if row else None


def set_meta(key: str, value: str) -> None:
    execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (key, value))


def now() -> datetime:
    """The demo clock, fixed by the generator so deadlines and runs are reproducible."""
    ref = get_meta("reference_now")
    return datetime.fromisoformat(ref) if ref else datetime.now()


def payout_ref(merchant_id: str, date: str) -> str:
    return f"{merchant_id}|{date}"


def audit(feature: str, ref: str, step: str, detail: dict) -> None:
    """One audit log for both features. feature is 'payout' or 'dispute'."""
    execute("INSERT INTO audit_log (feature, ref, step, detail, ts) VALUES (?,?,?,?,?)",
            (feature, ref, step, json.dumps(detail, default=str),
             now().isoformat(timespec="seconds")))
