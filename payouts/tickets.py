"""Support tickets for real errors. Mock: tickets live in the local database only.

A ticket is drafted by the agent and raised only when the merchant approves it.
One ticket per merchant, day and problem type, so nothing is raised twice.
"""
from datetime import datetime
import json

import db


def ticket_id_for(merchant_id: str, date: str, anomaly_type: str) -> str:
    return f"TKT-{merchant_id}-{date}-{anomaly_type}".upper().replace("_", "-")


def draft_tickets(breakdown: dict, anomalies: list[dict]) -> list[str]:
    """Create or refresh draft tickets for a day. Raised tickets are never changed."""
    merchant_id, date = breakdown["merchant_id"], breakdown["date"]
    grouped: dict[str, list[dict]] = {}
    for anomaly in anomalies:
        grouped.setdefault(anomaly["type"], []).append(anomaly)

    wanted = set()
    for anomaly_type, items in grouped.items():
        ticket_id = ticket_id_for(merchant_id, date, anomaly_type)
        wanted.add(ticket_id)
        existing = db.one("SELECT status FROM tickets WHERE ticket_id=?", (ticket_id,))
        if existing and existing["status"] == "RAISED":
            continue
        amount = round(sum(item["impact"] for item in items), 2)
        day = datetime.fromisoformat(date)
        summary = f"{items[0]['label']} on {day.day} {day:%b %Y}: ₹{amount:,.2f}"
        evidence = {"details": [item["detail"] for item in items],
                    "record_ids": sorted({r for item in items for r in item["record_ids"]}),
                    "settlement_id": (breakdown["settlement"] or {}).get("settlement_id")}
        db.execute(
            "INSERT OR REPLACE INTO tickets (ticket_id, merchant_id, settlement_date, "
            "anomaly_type, amount, summary, evidence, status, created_at, raised_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (ticket_id, merchant_id, date, anomaly_type, amount, summary, json.dumps(evidence),
             "DRAFT", db.now().isoformat(timespec="seconds"), None))

    # Drop drafts for problems that no longer exist on a re-run.
    for row in db.many("SELECT ticket_id FROM tickets WHERE merchant_id=? AND settlement_date=? "
                       "AND status='DRAFT'", (merchant_id, date)):
        if row["ticket_id"] not in wanted:
            db.execute("DELETE FROM tickets WHERE ticket_id=?", (row["ticket_id"],))
    return sorted(wanted)


def raise_ticket(ticket_id: str) -> dict:
    """Raise a drafted ticket after the merchant approves. Safe to call twice."""
    ticket = db.one("SELECT * FROM tickets WHERE ticket_id=?", (ticket_id,))
    if not ticket:
        raise KeyError(f"Unknown ticket {ticket_id}")
    if ticket["status"] == "RAISED":
        return {"ticket_id": ticket_id, "status": "RAISED", "duplicate": True,
                "raised_at": ticket["raised_at"]}
    raised_at = db.now().isoformat(timespec="seconds")
    db.execute("UPDATE tickets SET status='RAISED', raised_at=? WHERE ticket_id=?",
               (raised_at, ticket_id))
    return {"ticket_id": ticket_id, "status": "RAISED", "duplicate": False, "raised_at": raised_at}
