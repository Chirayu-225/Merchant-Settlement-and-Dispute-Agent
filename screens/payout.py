"""Payout check: why did my bank get less than my sales, and is anything wrong?"""
import json
from datetime import date as Date
from html import escape

import pandas as pd
import streamlit as st

import db
from payouts import pipeline, tickets
from product import events
from screens.common import (assumption, html, kpis, measured, needs_testing, pill, rs, section,
                            verdict)


def _day_label(row: dict) -> str:
    day = Date.fromisoformat(row["settlement_date"]).strftime("%a %d %b %Y")
    if row["status"] == "PENDING":
        return f"{day}  ·  not settled yet"
    if row["anomalies"] is None:
        return f"{day}  ·  not checked"
    count = len(json.loads(row["anomalies"]))
    return f"{day}  ·  " + ("all good" if count == 0 else "problem found")


def _days(merchant_id: str) -> list[dict]:
    return db.many(
        "SELECT s.settlement_date, s.gross, s.status, COALESCE(b.amount, 0) AS received, r.anomalies "
        "FROM settlements s "
        "LEFT JOIN bank_credits b ON b.merchant_id = s.merchant_id AND b.utr = s.utr "
        "LEFT JOIN payout_results r ON r.merchant_id = s.merchant_id "
        "AND r.settlement_date = s.settlement_date "
        "WHERE s.merchant_id=? ORDER BY s.settlement_date DESC", (merchant_id,))


def _ledger(breakdown: dict) -> str:
    rows = [f'<tr><td>Sales</td><td class="amt">{rs(breakdown["gross_sales"])}</td></tr>']
    for item in breakdown["deductions"]:
        if item["amount"] > 0:
            refs = ", ".join(item["record_ids"][:3]) + (" …" if len(item["record_ids"]) > 3 else "")
            rows.append(f'<tr class="minus"><td>− {escape(item["label"])}'
                        f'<span class="ref">{escape(refs)}</span></td>'
                        f'<td class="amt">−{rs(item["amount"])}</td></tr>')
    rows.append(f'<tr class="total"><td>Should reach your bank</td>'
                f'<td class="amt">{rs(breakdown["expected_net"])}</td></tr>')
    pending = (breakdown["settlement"] or {}).get("status") == "PENDING"
    got = "On its way (not settled yet)" if pending else rs(breakdown["received"])
    rows.append(f'<tr><td>Actually reached your bank</td><td class="amt">{got}</td></tr>')
    return f'<table class="ledger">{"".join(rows)}</table>'


def _feedback(merchant_id: str, date: str) -> None:
    """A 'no' asks why, so the answer points at a fix."""
    key = f"fb_{merchant_id}_{date}"
    if st.session_state.get(key + "_done"):
        st.caption("Thanks, your answer was recorded.")
        return
    st.markdown("**Did this explanation make sense?**")
    yes, no, _ = st.columns([1, 1, 5])
    if yes.button("Yes", key=key + "_yes"):
        events.record_feedback(merchant_id, date, True)
        st.session_state[key + "_done"] = True
        st.rerun()
    if no.button("No", key=key + "_no"):
        st.session_state[key + "_asking"] = True
    if st.session_state.get(key + "_asking"):
        reason = st.radio("What was the problem?", list(events.FEEDBACK_REASONS),
                          format_func=events.FEEDBACK_REASONS.get, key=key + "_reason",
                          horizontal=True)
        if st.button("Send", key=key + "_send"):
            events.record_feedback(merchant_id, date, False, reason)
            st.session_state[key + "_done"] = True
            st.rerun()


def _result(merchant_id: str, date: str) -> None:
    result = db.one("SELECT * FROM payout_results WHERE merchant_id=? AND settlement_date=?",
                    (merchant_id, date))
    if not result:
        verdict("info", "This day has not been checked yet.", "Press 'Check this day'.")
        return
    breakdown = json.loads(result["breakdown"])
    found = json.loads(result["anomalies"])
    handoffs = json.loads(result["handoffs"] or "[]")
    pending = (breakdown["settlement"] or {}).get("status") == "PENDING"
    deducted = sum(d["amount"] for d in breakdown["deductions"] if d["amount"] > 0)

    # One sentence first: is anything wrong?
    if found:
        verdict("bad", f"{rs(result['amount_owed'])} may be owed to you.",
                " ".join(a["label"] + "." for a in found) + " A support ticket is ready below.")
    elif pending:
        verdict("info", "Not settled yet. Nothing is wrong.",
                f"{rs(breakdown['expected_net'])} is on its way to your bank.")
    else:
        verdict("good", "Everything matches.",
                f"Your bank got {rs(deducted)} less than your sales because of the deductions "
                f"listed below. No errors were found.")

    kpis([("Sales", rs(breakdown["gross_sales"]), f"{breakdown['txn_count']} payments", ""),
          ("Deducted", rs(deducted), "fees, tax, refunds, chargebacks, loan", ""),
          ("Reached bank", "Pending" if pending else rs(breakdown["received"]), "", ""),
          ("May be owed to you", rs(result["amount_owed"]), "",
           "bad" if result["amount_owed"] > 0 else "good")])
    measured("figures for this day, from synthetic records")

    left, right = st.columns([1.05, 1])
    with left:
        html(f'<div class="card"><h4>Where the money went</h4>{_ledger(breakdown)}</div>')
        assumption("Fee rates (UPI 0%, card 1.8%, wallet 1.5%, GST 18%) are demo values, "
                   "not Paytm pricing. Source: product/assumptions.py.")
    with right:
        source = result["explanation_source"].replace("cache:", "")
        who = {"offline": "Written by a fixed template (no AI key set).",
               "template_fallback": "Fixed template. The AI's text failed the number check."}.get(
                   source, f"Written by {source}. Every number was checked against the records.")
        body = escape(result["explanation"]).replace("\n", "<br>")
        html(f'<div class="card"><h4>Explanation</h4><div style="font-size:0.92rem;'
             f'line-height:1.55;color:#22324A">{body}</div>'
             f'<div class="muted" style="margin-top:8px">{escape(who)}</div></div>')
        _feedback(merchant_id, date)

    if handoffs:
        section("Chargebacks on this day", "Each one was handed to the dispute agent.")
        for item in handoffs:
            tone = "good" if item["status"] in ("AUTO_SUBMITTED", "DRY_RUN_READY") else "warn"
            word = "Agent replied" if tone == "good" else "Needs a person"
            html(f'<div class="card">{pill(word, tone)} &nbsp;<b>{escape(item["chargeback_id"])}</b> · '
                 f'{rs(item["amount"])} → dispute {escape(item["dispute_id"])}'
                 f'<div class="muted" style="margin-top:4px">{escape(item["what_happened"])}</div></div>')

    for ticket in db.many("SELECT * FROM tickets WHERE merchant_id=? AND settlement_date=? "
                          "ORDER BY ticket_id", (merchant_id, date)):
        section("Support ticket")
        if ticket["status"] == "RAISED":
            verdict("good", "Ticket raised.", ticket["summary"])
        else:
            html(f'<div class="card">{escape(ticket["summary"])}</div>')
            if st.button("Raise this ticket", key=ticket["ticket_id"], type="primary"):
                tickets.raise_ticket(ticket["ticket_id"])
                events.log_event("ticket_raised", "merchant", merchant_id, date,
                                 {"ticket_id": ticket["ticket_id"], "anomaly_type": ticket["anomaly_type"],
                                  "amount": ticket["amount"]})
                st.rerun()


def render(dry_run: bool, use_cache: bool) -> None:
    merchants = db.many("SELECT * FROM merchants ORDER BY merchant_id='MID-DEMO' DESC, name")
    pick_shop, pick_day, go = st.columns([1.2, 1.6, 0.8], vertical_alignment="bottom")
    merchant = pick_shop.selectbox("Shop", merchants, format_func=lambda m: m["name"])
    days = _days(merchant["merchant_id"])
    labels = {d["settlement_date"]: _day_label(d) for d in days}
    # Open on the most recent day with a problem, so the first thing shown is the agent at work.
    problem_days = [d["settlement_date"] for d in days
                    if d["anomalies"] and json.loads(d["anomalies"])]
    first = list(labels).index(problem_days[0]) if problem_days else 0
    date = pick_day.selectbox("Day", list(labels), index=first, format_func=labels.get,
                              key=f"day_{merchant['merchant_id']}")
    if go.button("Check this day", type="primary", width="stretch"):
        events.log_event("why_clicked", "merchant", merchant["merchant_id"], date)
        with st.spinner("Checking the day's records..."):
            pipeline.run(merchant["merchant_id"], date, "English", use_cache, dry_run=dry_run)
    seen = st.session_state.setdefault("seen_days", set())
    if (merchant["merchant_id"], date) not in seen:
        seen.add((merchant["merchant_id"], date))
        events.log_event("payout_viewed", "merchant", merchant["merchant_id"], date)

    _result(merchant["merchant_id"], date)

    with st.expander("All days for this shop"):
        st.dataframe(pd.DataFrame([{
            "Day": d["settlement_date"], "Sales": rs(d["gross"]),
            "Reached bank": "Pending" if d["status"] == "PENDING" else rs(d["received"]),
            "Status": labels[d["settlement_date"]].split("·")[-1].strip().capitalize()} for d in days]),
            hide_index=True, width="stretch")
    needs_testing("Explanations in Hindi and Tamil are not offered until a native speaker has "
                  "checked them.")
