"""Mock Paytm tools. These read and write the local SQLite database only.

They are simplified stand-ins, not copies of real Paytm API responses, and nothing here
calls a live Paytm system.
"""
import db


def get_order(order_id: str) -> dict | None:
    return db.one("SELECT * FROM orders WHERE order_id=?", (order_id,))


def get_payment(order_id: str) -> dict | None:
    return db.one("SELECT * FROM payments WHERE order_id=?", (order_id,))


def get_delivery(order_id: str) -> dict | None:
    return db.one("SELECT * FROM deliveries WHERE order_id=?", (order_id,))


def get_customer_history(customer_id: str, device_id: str, before: str, exclude_order: str) -> list[dict]:
    """Earlier orders by the same customer on the same device that were paid successfully."""
    return db.many(
        """SELECT o.* FROM orders o JOIN payments p ON p.order_id = o.order_id
           WHERE o.customer_id=? AND o.device_id=? AND o.created_at<? AND o.order_id<>?
             AND p.status='SUCCESS'
           ORDER BY o.created_at DESC""",
        (customer_id, device_id, before, exclude_order))


def collect_evidence(parsed: dict) -> dict:
    """Pull every record the dispute could need."""
    order = get_order(parsed["order_id"])
    payment = get_payment(parsed["order_id"])
    delivery = get_delivery(parsed["order_id"])
    history = []
    if order:
        history = get_customer_history(order["customer_id"], order["device_id"],
                                       order["created_at"], order["order_id"])
    return {"order": order, "payment": payment, "delivery": delivery, "history": history}


def records_by_id(bundle: dict) -> dict:
    """Index the evidence bundle by record ID, for citation checks."""
    index = {}
    if bundle.get("order"):
        index[bundle["order"]["order_id"]] = bundle["order"]
    if bundle.get("payment"):
        index[bundle["payment"]["txn_id"]] = bundle["payment"]
    if bundle.get("delivery"):
        index[bundle["delivery"]["delivery_id"]] = bundle["delivery"]
    for record in bundle.get("history") or []:
        index[record["order_id"]] = record
    return index


def submit_dispute_response(dispute_id: str, response_text: str, dry_run: bool) -> dict:
    """Submit a dispute response. Idempotent: a dispute can be really submitted only once."""
    existing = db.one("SELECT * FROM submissions WHERE dispute_id=?", (dispute_id,))
    if existing and not existing["dry_run"]:
        return {"status": "ALREADY_SUBMITTED", "dispute_id": dispute_id, "duplicate": True,
                "dry_run": False, "submitted_at": existing["submitted_at"]}
    submitted_at = db.now().isoformat(timespec="seconds")
    db.execute(
        "INSERT OR REPLACE INTO submissions (dispute_id, response_text, submitted_at, dry_run) "
        "VALUES (?,?,?,?)", (dispute_id, response_text, submitted_at, 1 if dry_run else 0))
    return {"status": "DRY_RUN_OK" if dry_run else "SUBMITTED", "dispute_id": dispute_id,
            "duplicate": False, "dry_run": dry_run, "submitted_at": submitted_at}
