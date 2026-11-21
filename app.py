"""Merchant Settlement and Dispute Agent.

Run:  streamlit run app.py

Two features in one pipeline:
  Payout check   why a shop's bank got less than its sales, and whether anything is wrong
  Disputes       reply to customer chargebacks before the deadline, or hand them to a person
"""
import streamlit as st

import config
import db
import evaluate
import generate_data
import llm
import snapshot
from screens import audit, common, disputes, payout, results

st.set_page_config(page_title="Merchant Settlement & Dispute Agent", page_icon="₹", layout="wide")
common.style()

if not db.exists():
    # A saved, still-true measurement opens instantly. If the code changed since it was saved,
    # it is ignored and everything is measured fresh below.
    if not snapshot.restore():
        generate_data.generate()
db.init_schema()

# Offline measurement is quick and needs no keys, so the app shows real numbers on first load.
# With keys set, evaluation calls an AI model, so it waits for a click.
if evaluate.last_stamp() is None and llm.provider_order()[0] == "offline":
    with st.spinner("First load: checking every payout day and dispute in the demo data..."):
        evaluate.run_all()

with st.sidebar:
    st.markdown("### Demo data")
    if st.button("Reset demo data", width="stretch"):
        generate_data.generate()
        st.rerun()
    st.caption("All shops, payouts and disputes are made up. Paytm systems and support tickets "
               "are simulated.")
    st.divider()
    st.markdown("### Developer settings")
    st.caption(f"AI model: {llm.provider_status()}")
    dry_run = st.checkbox("Dry run", value=config.DRY_RUN,
                          help="On: the agent drafts dispute replies but never sends them.")
    use_cache = st.checkbox("Reuse saved AI answers", value=True,
                            help="Reuses answers from earlier runs so free-tier AI credits are not "
                                 "spent twice. Does nothing in offline mode.")
    st.caption(f"Dispute amount limit: ₹{config.AMOUNT_LIMIT:,.0f}  \n"
               f"Deadline buffer: {config.DEADLINE_SLACK_HOURS:.0f} hours  \n"
               f"Demo clock: {db.now().strftime('%d %b %Y, %H:%M')}")
    if st.button("Run evaluation", width="stretch",
                 help="Re-checks every payout day and dispute and updates the Results tab."):
        with st.spinner("Checking every payout day and dispute..."):
            evaluate.run_all(use_cache=use_cache)
        st.rerun()

mode = "Offline mode" if llm.provider_order()[0] == "offline" else llm.provider_status()
common.html(f'<div class="topbar"><div><div class="name">Merchant Settlement &amp; Dispute Agent</div>'
            f'<div class="sub">Explains every payout. Fights chargebacks before the deadline.</div></div>'
            f'<div class="badge">{mode} · demo data</div></div>')
common.html('<div class="intro"><b>What this does.</b> A shop sells ₹20,000 but only ₹17,000 reaches '
            'the bank. The <b>payout check</b> explains every rupee of the gap and raises a ticket if '
            'something is wrong. When a customer disputes a payment, the <b>dispute agent</b> collects '
            'the proof and replies before the deadline, but only if 7 safety checks pass. Anything '
            'unclear goes to a person, earliest deadline first.</div>')

tabs = st.tabs(["Payout check", "Disputes", "Results", "Audit log"])
for tab, screen in zip(tabs, [payout, disputes, results, audit]):
    with tab:
        screen.render(dry_run, use_cache)

common.html('<div class="footer">Built for the Paytm Build for India hackathon. All data is synthetic. '
            'Figures are labelled <b>Measured</b> (with the mode and date that produced them), '
            '<b>Assumption</b> (with its source) or <b>Needs testing</b> (no number shown).</div>')
