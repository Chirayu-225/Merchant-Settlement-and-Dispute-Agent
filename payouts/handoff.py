"""The link between the two features.

When a payout has a chargeback deduction, the dispute behind it is handed to the dispute
pipeline. The merchant then sees what happened to each chargeback next to the payout.
"""
import db
from disputes import graph, llm_steps

# Plain sentences shown to the merchant. No digits, so the number check has nothing to flag.
WHAT_HAPPENED = {
    "AUTO_SUBMITTED": "The agent checked your records and sent a reply contesting it.",
    "DRY_RUN_READY": ("The agent checked your records and prepared a reply contesting it. "
                      "Dry run: nothing was sent."),
    "ESCALATED": "The agent could not settle it alone and passed it to a support agent with a note.",
    "PENDING": "It is still open and has not been looked at yet.",
}


def resolve_chargebacks(breakdown: dict, dry_run: bool, use_cache: bool = True,
                        resolve: bool = True, steps=llm_steps) -> list[dict]:
    """Run each of the day's chargebacks through the dispute pipeline (once) and report back."""
    handoffs = []
    for chargeback in breakdown["chargeback_rows"]:
        dispute = db.one("SELECT dispute_id, status FROM disputes WHERE dispute_id=?",
                         (chargeback["dispute_id"],))
        if not dispute:
            continue
        status, ran_now = dispute["status"], False
        needs_run = status == "PENDING" or (status == "DRY_RUN_READY" and not dry_run)
        if resolve and needs_run:
            graph.process_dispute(dispute["dispute_id"], dry_run=dry_run, use_cache=use_cache,
                                  steps=steps)
            status = db.one("SELECT status FROM disputes WHERE dispute_id=?",
                            (dispute["dispute_id"],))["status"]
            ran_now = True
        result = db.one("SELECT decision FROM dispute_results WHERE dispute_id=?",
                        (dispute["dispute_id"],))
        handoffs.append({
            "chargeback_id": chargeback["chargeback_id"],
            "dispute_id": dispute["dispute_id"],
            "txn_id": chargeback["txn_id"],
            "amount": round(float(chargeback["amount"]), 2),
            "status": status,
            "decision": result["decision"] if result else None,
            "what_happened": WHAT_HAPPENED.get(status, WHAT_HAPPENED["PENDING"]),
            "processed_in_this_run": ran_now,
        })
    return handoffs
