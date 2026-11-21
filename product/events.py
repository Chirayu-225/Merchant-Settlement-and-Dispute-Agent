"""Product instrumentation: the event schema, the metrics built on it, and what each metric
would trigger. The demo has no real users, so metrics built on these events show
"Needs testing" in the app and are tested here with synthetic event rows only."""
import json
from datetime import datetime, timedelta

import db

EVENT_SCHEMA = {
    "payout_viewed": {"persona": "merchant", "when": "A shop owner opens a settlement day that has been checked",
                      "props": "none"},
    "why_clicked": {"persona": "merchant", "when": "The shop owner clicks 'Why is it less?'",
                    "props": "none"},
    "ticket_raised": {"persona": "merchant", "when": "The shop owner approves a drafted support ticket",
                      "props": "ticket_id, anomaly_type, amount"},
    "feedback_submitted": {"persona": "merchant", "when": "The shop owner answers 'Did this make sense?'",
                           "props": "helpful, reason"},
    "dispute_opened": {"persona": "support", "when": "A support agent opens a dispute", "props": "none"},
    "dispute_processed": {"persona": "support", "when": "A support agent runs the pipeline on a dispute",
                          "props": "none"},
    "payout_checked": {"persona": "system", "when": "The payout pipeline finishes a day",
                       "props": "errors, chargebacks"},
    "dispute_decided": {"persona": "system", "when": "The dispute pipeline reaches the gate",
                        "props": "decision (auto_submit | escalate)"},
}

# For each metric: what it needs, and what a drop would make the team do.
METRIC_ACTIONS = [
    {"metric": "Ticket deflection on clean days",
     "definition": "Of shop-day views where the ground truth is 'no error' and the owner clicked "
                   "'Why is it less?', the share with no ticket raised within 48 hours.",
     "events": "why_clicked, ticket_raised (+ ground-truth day label)",
     "if_it_drops": "Owners still raise tickets on clean days: the explanation is not answering their question.",
     "then_we": "Read the feedback reasons. If 'number looks wrong', check the number check and the "
                "reconciliation. If 'confusing term', rewrite that term. Only then touch the prompt."},
    {"metric": "Recovery capture on error days",
     "definition": "Of shop-days with a real planted error where the owner clicked 'Why is it less?', "
                   "the share where a ticket with the right amount was raised.",
     "events": "why_clicked, ticket_raised (+ ground-truth day label and impact)",
     "if_it_drops": "Real money is left unclaimed: owners see the error and do not act, or the amount is off.",
     "then_we": "Look at where in the screen owners stop. Make the ticket button part of the problem card, "
                "and show the amount owed more prominently."},
    {"metric": "Explanation helpfulness",
     "definition": "Share of 'Did this make sense?' answers that are yes, split by reason on a no.",
     "events": "feedback_submitted",
     "if_it_drops": "The reason mix says what to fix: wrong number, too long, or a confusing term.",
     "then_we": "Fix the top reason first. A wrong number is a guardrail breach and goes before the other two."},
    {"metric": "Escalations reached before their deadline",
     "definition": "Of escalated disputes the ground truth says should be contested, the share a support "
                   "agent reached before respond-by.",
     "events": "dispute_decided, dispute_processed (+ respond-by from the notice)",
     "if_it_drops": "The gate is sending more work to humans than they can clear, and money is being lost.",
     "then_we": "Open the autonomy dial. Loosen the amount limit or add support capacity, whichever is "
                "cheaper than the rupees being lost."},
]


def log_event(event: str, persona: str = "system", merchant_id: str | None = None,
              ref: str | None = None, props: dict | None = None, ts: datetime | None = None) -> None:
    if event not in EVENT_SCHEMA:
        raise ValueError(f"Unknown event '{event}'. Add it to EVENT_SCHEMA first.")
    db.execute("INSERT INTO events (ts, persona, event, merchant_id, ref, props) VALUES (?,?,?,?,?,?)",
               ((ts or datetime.now()).isoformat(timespec="seconds"), persona, event, merchant_id,
                ref, json.dumps(props or {})))


FEEDBACK_REASONS = {"number_looks_wrong": "A number looks wrong",
                    "too_long": "It is too long",
                    "confusing_term": "A word or term is confusing",
                    "other": "Something else"}


def record_feedback(merchant_id: str, settlement_date: str, helpful: bool,
                    reason: str | None = None) -> None:
    """A 'no' must say why, so the score points at a fix."""
    if not helpful and reason not in FEEDBACK_REASONS:
        raise ValueError("A 'no' needs one of the reasons: " + ", ".join(FEEDBACK_REASONS))
    db.execute("INSERT INTO feedback (ts, merchant_id, settlement_date, helpful, reason) "
               "VALUES (?,?,?,?,?)",
               (datetime.now().isoformat(timespec="seconds"), merchant_id, settlement_date,
                1 if helpful else 0, None if helpful else reason))
    log_event("feedback_submitted", "merchant", merchant_id, settlement_date,
              {"helpful": helpful, "reason": reason})


def _day_events(event: str) -> list[dict]:
    return db.many("SELECT * FROM events WHERE event=? AND merchant_id IS NOT NULL ORDER BY ts", (event,))


def _truth(merchant_id: str, date: str) -> dict | None:
    return db.one("SELECT gt_anomaly, gt_impact FROM day_labels WHERE merchant_id=? AND settlement_date=?",
                  (merchant_id, date))


def deflection_on_clean_days(window_hours: float = 48) -> dict:
    """Day type comes from the GROUND-TRUTH label, never from what the agent found."""
    eligible = deflected = 0
    tickets = _day_events("ticket_raised")
    seen = set()
    for click in _day_events("why_clicked"):
        key = (click["merchant_id"], click["ref"])
        truth = _truth(*key)
        if key in seen or not truth or truth["gt_anomaly"] != "none":
            continue
        seen.add(key)
        eligible += 1
        start = datetime.fromisoformat(click["ts"])
        raised = [t for t in tickets if (t["merchant_id"], t["ref"]) == key
                  and start <= datetime.fromisoformat(t["ts"]) <= start + timedelta(hours=window_hours)]
        deflected += 0 if raised else 1
    return {"eligible": eligible, "deflected": deflected,
            "rate": deflected / eligible if eligible else None}


def recovery_capture_on_error_days(tolerance: float = 0.05) -> dict:
    eligible = captured = 0
    tickets = _day_events("ticket_raised")
    seen = set()
    for click in _day_events("why_clicked"):
        key = (click["merchant_id"], click["ref"])
        truth = _truth(*key)
        if key in seen or not truth or truth["gt_anomaly"] == "none":
            continue
        seen.add(key)
        eligible += 1
        for ticket in tickets:
            if (ticket["merchant_id"], ticket["ref"]) == key:
                amount = json.loads(ticket["props"]).get("amount")
                if amount is not None and abs(float(amount) - truth["gt_impact"]) <= tolerance:
                    captured += 1
                    break
    return {"eligible": eligible, "captured": captured,
            "rate": captured / eligible if eligible else None}
