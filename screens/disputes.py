"""Disputes: customers who asked their bank for money back. The agent replies to clear cases
before the deadline and hands the rest to a person, earliest deadline first."""
import json
from datetime import datetime
from html import escape

import pandas as pd
import streamlit as st

import config
import db
from disputes import graph, rules, tools
from product import events
from screens.common import (REASONS, STATUS, assumption, html, kpis, measured, pill, rs, section,
                            verdict)


def _hours_left(respond_by: str) -> float:
    return round((datetime.fromisoformat(respond_by) - db.now()).total_seconds() / 3600, 1)


def queue(suite: str = "main") -> list[dict]:
    shops = {m["merchant_id"]: m["name"] for m in db.many("SELECT * FROM merchants")}
    rows = []
    for row in db.many("SELECT * FROM disputes WHERE suite=?", (suite,)):
        try:
            parsed = rules.parse_notice(row["notice_text"])
        except rules.NoticeError:
            parsed = None
        rows.append({
            "id": row["dispute_id"], "status": row["status"],
            "shop": shops.get(row["merchant_id"], "Not linked to a payout"),
            "reason": REASONS.get(parsed["reason_code"], parsed["reason_code"]) if parsed else "Unreadable notice",
            "amount": parsed["amount"] if parsed else None,
            "respond_by": parsed["respond_by"] if parsed else "9999",
            "hours_left": _hours_left(parsed["respond_by"]) if parsed else None,
            "from_payout": bool(row["chargeback_id"]),
        })
    return sorted(rows, key=lambda r: r["respond_by"])


def _due(hours: float | None) -> str:
    if hours is None:
        return "–"
    if hours < 0:
        return "Overdue"
    return f"{hours:.0f} h" if hours < 48 else f"{hours / 24:.1f} days"


def _table(rows: list[dict]) -> None:
    frame = pd.DataFrame([{
        "Due in": _due(r["hours_left"]), "Dispute": r["id"], "Shop": r["shop"], "Reason": r["reason"],
        "Amount": rs(r["amount"]), "Status": STATUS.get(r["status"], (r["status"], ""))[0]}
        for r in rows])

    def colour(row):
        status = {"Needs a person": "color:#7A4A06;font-weight:600",
                  "Agent replied": "color:#0B5E3A;font-weight:600"}.get(row["Status"], "")
        hours = next(r["hours_left"] for r in rows if r["id"] == row["Dispute"])
        urgent = "color:#C0262D;font-weight:600" if hours is not None and hours < 24 else ""
        return [urgent if c == "Due in" else status if c == "Status" else "" for c in row.index]

    st.dataframe(frame.style.apply(colour, axis=1), hide_index=True, width="stretch", height=300)


def _checks(checks: list[dict]) -> str:
    out = []
    for c in checks:
        icon, cls = {True: ("✓", "pass"), False: ("✕", "fail"), None: ("–", "skip")}[c["passed"]]
        out.append(f'<div class="check"><div class="icon {cls}">{icon}</div><div>'
                   f'<div class="t">{escape(c["label"])}</div><div class="d">{escape(c["detail"])}</div>'
                   f'</div></div>')
    return "".join(out)


def detail(dispute_id: str, dry_run: bool, use_cache: bool, allow_run: bool = True) -> None:
    row = db.one("SELECT * FROM disputes WHERE dispute_id=?", (dispute_id,))
    try:
        parsed = rules.parse_notice(row["notice_text"])
    except rules.NoticeError as exc:
        verdict("bad", "The bank's notice could not be read.", str(exc))
        parsed = None

    left, right = st.columns([1, 1.15])
    with left:
        if parsed:
            html(f'<div class="card"><h4>What the customer says</h4>'
                 f'<table class="ledger">'
                 f'<tr><td>Reason</td><td class="amt">{escape(REASONS.get(parsed["reason_code"], parsed["reason_code"]))}</td></tr>'
                 f'<tr><td>Amount</td><td class="amt">{rs(parsed["amount"])}</td></tr>'
                 f'<tr><td>Reply needed by</td><td class="amt">{escape(parsed["respond_by"].replace("T", " "))}</td></tr>'
                 f'<tr><td>Time left</td><td class="amt">{_due(_hours_left(parsed["respond_by"]))}</td></tr>'
                 f'</table><div class="muted" style="margin-top:10px">“{escape(parsed["customer_statement"][:400])}”</div></div>')
        if row["chargeback_id"]:
            cb = db.one("SELECT * FROM chargebacks WHERE chargeback_id=?", (row["chargeback_id"],))
            html(f'<div class="card">{pill("From a payout", "grey")} &nbsp;This chargeback took '
                 f'{rs(cb["amount"])} out of the shop\'s {escape(cb["settlement_date"])} payout. '
                 f'The payout check found it and handed it here.</div>')
        if parsed:
            with st.expander("Proof on file"):
                bundle = tools.collect_evidence(parsed)
                for title, record in [("Order", bundle["order"]), ("Payment", bundle["payment"]),
                                      ("Delivery", bundle["delivery"])]:
                    st.markdown(f"**{title}**")
                    st.json(record, expanded=False) if record else st.caption("No record found.")
                st.caption(f"Earlier orders by the same customer on the same device: {len(bundle['history'])}")
        with st.expander("The bank's notice, as received"):
            st.code(row["notice_text"], language=None)
        if allow_run and st.button("Run the agent on this dispute", key=f"run_{dispute_id}"):
            events.log_event("dispute_processed", "support", ref=dispute_id)
            with st.spinner("Collecting proof and running the safety checks..."):
                graph.process_dispute(dispute_id, dry_run=dry_run, use_cache=use_cache)
            st.rerun()

    with right:
        result = db.one("SELECT * FROM dispute_results WHERE dispute_id=?", (dispute_id,))
        if not result:
            verdict("info", "Not processed yet.", "Run the agent to see its decision.")
            return
        checks = json.loads(result["checks"])
        failed = [c for c in checks if c["passed"] is False]
        if result["decision"] == "auto_submit":
            verdict("good", "The agent replied on its own.",
                    "All 7 safety checks passed." + (" Dry run: nothing was really sent." if dry_run else ""))
        else:
            verdict("warn", "Handed to a person.",
                    f"{len(failed)} of 7 safety checks failed: " + "; ".join(c["label"] for c in failed) + ".")
        html(f'<div class="card"><h4>Safety checks</h4>{_checks(checks)}</div>')
        assumption(f"The ₹{config.AMOUNT_LIMIT:,.0f} amount limit and the "
                   f"{config.DEADLINE_SLACK_HOURS:.0f}-hour deadline buffer are demo choices, "
                   f"not Paytm rules. Source: product/assumptions.py.")
        if result["decision"] == "auto_submit":
            submission = db.one("SELECT * FROM submissions WHERE dispute_id=?", (dispute_id,))
            if submission:
                title = "Reply drafted (dry run, not sent)" if submission["dry_run"] else "Reply sent"
                body = escape(submission["response_text"]).replace("\n", "<br>")
                html(f'<div class="card"><h4>{title}</h4><div style="font-size:0.88rem;'
                     f'line-height:1.5;color:#22324A">{body}</div></div>')
        else:
            escalation = db.one("SELECT * FROM escalations WHERE dispute_id=?", (dispute_id,))
            if escalation:
                with st.expander("Note for the person who picks this up", expanded=True):
                    st.code(escalation["handoff_note"], language=None)


def render(dry_run: bool, use_cache: bool) -> None:
    rows = queue()
    replied = sum(1 for r in rows if r["status"] in ("AUTO_SUBMITTED", "DRY_RUN_READY"))
    waiting = [r for r in rows if r["status"] == "ESCALATED"]
    urgent = sum(1 for r in waiting if r["hours_left"] is not None and r["hours_left"] < 24)
    pending = [r for r in rows if r["status"] == "PENDING"]
    kpis([("Agent replied", replied, "clear cases, all 7 checks passed", "good"),
          ("Needs a person", len(waiting), "worked earliest deadline first", "warn"),
          ("Due within 24 hours", urgent, "of the cases waiting for a person", "bad" if urgent else ""),
          ("Not processed", len(pending), "", "")])
    measured("disputes in the queue; the trick test cases are kept out of it")

    section("Queue", "Earliest deadline first. Deadlines under 24 hours are in red.")
    if pending and st.button(f"Run the agent on {len(pending)} new disputes", type="primary"):
        bar = st.progress(0.0)
        for n, r in enumerate(pending, start=1):
            graph.process_dispute(r["id"], dry_run=dry_run, use_cache=use_cache)
            bar.progress(n / len(pending))
        st.rerun()
    _table(rows)

    section("Open a dispute")
    labels = {r["id"]: f'{r["id"]} · {r["shop"]} · {rs(r["amount"])} · '
                       f'{STATUS.get(r["status"], (r["status"],))[0]}' for r in rows}
    chosen = st.selectbox("Dispute", list(labels), format_func=labels.get, label_visibility="collapsed")
    if st.session_state.get("last_opened") != chosen:
        st.session_state["last_opened"] = chosen
        events.log_event("dispute_opened", "support", ref=chosen)
    detail(chosen, dry_run, use_cache)
