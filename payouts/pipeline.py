"""The payout pipeline for one merchant day:

match and break down (code) -> hand chargebacks to the dispute pipeline -> flag errors
(code) -> explain (LLM) -> check the explanation's numbers (code) -> draft tickets for the
merchant to approve.
"""
import json
import time

import config
import db
from disputes import llm_steps
from payouts import anomalies as anomaly_checks
from payouts import explain, handoff, reconcile, tickets, verify
from product import events


def audit(merchant_id: str, date: str, step: str, detail: dict) -> None:
    db.audit("payout", db.payout_ref(merchant_id, date), step, detail)


def run(merchant_id: str, date: str, language: str | None = None, use_cache: bool = True,
        explainer=explain, dry_run: bool | None = None, resolve_disputes: bool = True,
        dispute_steps=llm_steps) -> dict:
    """Reconcile one day and store the result. `explainer` and `dispute_steps` are
    swappable for tests."""
    started = time.perf_counter()
    dry_run = config.DRY_RUN if dry_run is None else dry_run

    breakdown = reconcile.build_breakdown(merchant_id, date)
    audit(merchant_id, date, "reconcile",
          {"gross_sales": breakdown["gross_sales"], "expected_net": breakdown["expected_net"],
           "received": breakdown["received"],
           "deductions": {d["key"]: d["amount"] for d in breakdown["deductions"]}})

    handoffs = handoff.resolve_chargebacks(breakdown, dry_run, use_cache, resolve_disputes,
                                           dispute_steps)
    if handoffs:
        audit(merchant_id, date, "handoff", {"chargebacks": handoffs, "dry_run": dry_run})

    found = anomaly_checks.detect(breakdown)
    amount_owed = reconcile.money(sum(a["impact"] for a in found))
    audit(merchant_id, date, "flag", {"anomalies": found, "amount_owed": amount_owed})

    if language is None:
        merchant = db.one("SELECT language FROM merchants WHERE merchant_id=?", (merchant_id,))
        language = merchant["language"]

    text, source, verified, attempts, feedback = "", "template", False, 0, None
    while attempts <= config.MAX_EXPLANATION_RETRIES:
        attempts += 1
        try:
            candidate, meta = explainer.generate(breakdown, found, amount_owed, language,
                                                 feedback, use_cache, handoffs)
        except Exception as exc:
            audit(merchant_id, date, "explain", {"attempt": attempts, "error": str(exc)[:300]})
            break
        ok, problems = verify.verify_explanation(candidate, breakdown, found, amount_owed,
                                                 handoffs)
        audit(merchant_id, date, "explain",
              {"attempt": attempts, "llm": meta, "verified": ok, "problems": problems})
        if ok:
            text, verified = candidate, True
            source = ("cache:" if meta["cached"] else "") + meta["provider"]
            break
        feedback = problems

    if not verified:
        # Never show a merchant numbers that code could not confirm.
        text = explain.template_explanation(breakdown, found, amount_owed, handoffs)
        source, verified = "template_fallback", True
        audit(merchant_id, date, "fallback", {"reason": "explanation failed the number check"})

    ticket_ids = tickets.draft_tickets(breakdown, found)
    audit(merchant_id, date, "tickets", {"drafted": ticket_ids})

    events.log_event("payout_checked", persona="system", merchant_id=merchant_id, ref=date,
                     props={"errors": len(found), "chargebacks": len(handoffs)})
    duration = time.perf_counter() - started
    stored = {k: v for k, v in breakdown.items() if k != "refund_rows"}
    db.execute(
        "INSERT OR REPLACE INTO payout_results (merchant_id, settlement_date, breakdown, "
        "anomalies, amount_owed, handoffs, explanation, language, explanation_source, "
        "explanation_verified, attempts, duration_seconds, processed_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (merchant_id, date, json.dumps(stored), json.dumps(found), amount_owed,
         json.dumps(handoffs), text, language, source, 1 if verified else 0, attempts, duration,
         db.now().isoformat(timespec="seconds")))
    return {"breakdown": stored, "anomalies": found, "amount_owed": amount_owed,
            "handoffs": handoffs, "explanation": text, "language": language,
            "explanation_source": source, "attempts": attempts, "ticket_ids": ticket_ids,
            "duration_seconds": duration}
