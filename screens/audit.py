"""Audit log: every step the agent took, for every payout day and every dispute."""
import json
from datetime import datetime

import streamlit as st

import db
from screens.common import html

STEP_NAMES = {"reconcile": "Added up the day's records", "handoff": "Passed chargebacks to disputes",
              "anomalies": "Looked for errors", "flag": "Flagged problems", "explain": "Wrote the explanation",
              "verify": "Checked every number", "tickets": "Drafted tickets",
              "ingest": "Read the bank's notice", "retrieve": "Collected proof",
              "assess": "Assessed the case", "draft": "Drafted a reply", "gate": "Ran the 7 safety checks",
              "submit": "Replied", "escalate": "Handed to a person"}


def render(dry_run: bool, use_cache: bool) -> None:
    html('<div class="intro">One log for both features. Nothing the agent does is hidden: open any '
         'payout day or dispute to see each step, in order, with what it saw and decided.</div>')
    left, right = st.columns([1, 2])
    feature = left.radio("Feature", ["payout", "dispute"], horizontal=True,
                         format_func=lambda f: "Payout checks" if f == "payout" else "Disputes")
    refs = [r["ref"] for r in db.many("SELECT DISTINCT ref FROM audit_log WHERE feature=? ORDER BY ref",
                                      (feature,))]
    if not refs:
        st.info("Nothing logged for this feature yet.")
        return
    shops = {m["merchant_id"]: m["name"] for m in db.many("SELECT * FROM merchants")}

    def label(ref: str) -> str:
        if feature == "payout" and "|" in ref:
            merchant_id, day = ref.split("|", 1)
            return f"{shops.get(merchant_id, merchant_id)} · {datetime.fromisoformat(day):%d %b %Y}"
        return ref
    chosen = right.selectbox("Record", refs, key="audit_ref", format_func=label)
    entries = db.many("SELECT * FROM audit_log WHERE feature=? AND ref=? ORDER BY id", (feature, chosen))
    st.caption(f"{len(entries)} steps logged · all steps carry the demo clock "
               f"({db.now():%d %b %Y, %H:%M}), so only their order is meaningful here")
    for n, entry in enumerate(entries, start=1):
        name = STEP_NAMES.get(entry["step"], entry["step"])
        with st.expander(f"{n}. {name}"):
            st.json(json.loads(entry["detail"]))
