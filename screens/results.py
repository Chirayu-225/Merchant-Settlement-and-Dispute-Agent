"""Results: how well both features work on the test data, and what is not tested yet."""
from html import escape

import pandas as pd
import streamlit as st

from disputes import metrics as dispute_metrics
from payouts import metrics as payout_metrics
from product import guardrails, needs_testing, probes
from screens import disputes as dispute_screen
from screens.common import html, kpis, measured, needs_testing as flag, pct, section, verdict

TRICK_TITLES = {
    "wrong_address_proof": "Delivery proof is for a different address",
    "reused_proof_ref": "The same delivery proof is reused on another order",
    "partial_refund_before_chargeback": "Part of the money was already refunded",
    "shared_family_device": "A family member used the same phone",
    "double_charge_same_order": "The customer was charged twice for one order",
    "paraphrased_instruction": "Customer text tries to instruct the agent, reworded",
    "late_delivery_after_dispute": "Delivered only after the customer complained",
    "amount_off_by_one_rupee": "Amount differs from the order by ₹1",
}


def render(dry_run: bool, use_cache: bool) -> None:
    pm = payout_metrics.compute_metrics()
    dm = dispute_metrics.compute_metrics()
    pg = guardrails.payout_guardrails()
    adv = dispute_metrics.adversarial_report()
    if not pm.get("processed") or not dm.get("processed"):
        verdict("info", "Nothing measured yet.", "Open Developer settings in the sidebar and press "
                "'Run evaluation'.")
        return

    html('<div class="intro">Every shop, day and dispute in this demo was made up with a known right '
         'answer hidden inside. The agent never sees the answer. These numbers compare what it did '
         'with what it should have done.</div>')
    measured("every number on this tab")

    section("The two ways this can go wrong", "Both should stay at zero.")
    kpis([("Wrong replies sent by the agent", f"{dm['wrong_auto_submissions']} of {dm['auto_submitted']}",
           "disputes it answered alone that a person should have handled",
           "good" if dm["wrong_auto_submissions"] == 0 else "bad"),
          ("Payout errors it missed", f"{pg['missed_recoveries']} of {pg['error_days']}",
           "days with a real error where no ticket was raised",
           "good" if pg["missed_recoveries"] == 0 else "bad")])
    verdict("warn", "These zeros only cover the situations the rules were written for.",
            "The trick cases further down test what happens outside them, and some get through.")

    section("Payout check", f"{pm['processed']} shop-days checked, {pm['days_with_planted_errors']} "
            f"with a planted error.")
    kpis([("Errors caught", f"{pm['errors_found']} of {pm['days_with_planted_errors']}", "", "good"),
          ("False alarms on clean days", pct(pm["false_alarm_rate_on_clean_days"]),
           f"{pg['ticket_noise_on_clean_days']} of {pg['clean_days']} clean days got a ticket", ""),
          ("Amount owed worked out correctly", pct(pm["amount_accuracy"]), "", ""),
          ("Chargebacks passed to the dispute agent", pm["chargebacks_handed_to_dispute_pipeline"],
           f"handed over correctly: {pct(pm['handoff_decision_accuracy'])}", "")])

    section("Dispute agent", f"{dm['processed']} disputes.")
    kpis([("Replied with no person", pct(dm["auto_resolution_rate"]),
           "speed, not the goal: it rises whenever the checks are loosened", ""),
          ("Cases that needed a person, and got one", pct(dm["escalation_recall"]), "", ""),
          ("Handed over for the right reason", pct(dm["escalation_reason_match"]), "", ""),
          ("AI model calls per dispute", f"{dm['avg_model_calls_per_case']:.1f}",
           "0 means the offline stand-in answered", "")])
    if pm["explanations_from_llm"] == 0:
        flag("How often AI-written payout explanations fail the number check. None have been "
             "written yet.")

    section("Trick cases", "Cases built to find gaps in my own rules. What I expected was written "
            "down before the first run.")
    probe_rows = [r for r in adv if r["kind"] == "probe"]
    got_through = sum(r["wrong_auto_submissions"] for r in probe_rows)
    total = sum(r["cases"] for r in adv)
    kpis([("Trick cases", total, f"{len(probe_rows)} gap types and {len(adv) - len(probe_rows)} "
                                  f"control types, 4 cases each", ""),
          ("Got past the agent", f"{got_through} of {sum(r['cases'] for r in probe_rows)}",
           "gap cases it answered when a person should have", "bad" if got_through else "good"),
          ("Controls handled correctly",
           f"{sum(r['escalated'] for r in adv if r['kind'] == 'control')} of "
           f"{sum(r['cases'] for r in adv if r['kind'] == 'control')}",
           "cases the rules should already catch", "")])
    st.dataframe(pd.DataFrame([{
        "Situation": TRICK_TITLES.get(r["type"], r["title"]),
        "Type": "Gap" if r["kind"] == "probe" else "Control",
        "Cases": r["cases"], "Got through": r["wrong_auto_submissions"],
        "Sent to a person": r["escalated"],
        "As I predicted": f"{r['matched_expectation']} of {r['cases']}"} for r in adv]),
        hide_index=True, width="stretch")
    flag("How a real AI model (Gemini) handles these cases. These results show the rules alone.")
    with st.expander("Look at one trick case"):
        pick = st.selectbox("Situation", [r["type"] for r in adv],
                            format_func=lambda t: TRICK_TITLES.get(t, t))
        row = next(r for r in adv if r["type"] == pick)
        st.write(row["why"])
        case = st.selectbox("Case", row["case_ids"])
        dispute_screen.detail(case, dry_run, use_cache, allow_run=False)

    section("Not tested yet", "What this project cannot honestly claim. None of these has a number.")
    for item in needs_testing.NEEDS_TESTING:
        with st.expander(f"{item['title']}  ·  {item['status']}"):
            st.write(f"**Question.** {item['what']}")
            st.write(f"**Measured so far.** {item['measured_so_far']}")
            st.write(f"**Still open.** {item['still_flagged']}")
            st.write(f"**How to test it.** {item['how_to_test']}")
            if item["id"] == "number_check_false_rejections":
                result = probes.run_probes()
                st.dataframe(pd.DataFrame([{"Honest sentence": r["label"],
                                            "Number check": "accepted" if r["accepted"] else "rejected"}
                                           for r in result["results"]]), hide_index=True, width="stretch")
                html(f'<div class="tagline"><span class="tag measured">MEASURED</span>offline probe set: '
                     f'{escape(str(result["rejected"]))} of {escape(str(result["probes"]))} honest '
                     f'sentences rejected. This tests the check, not Gemini.</div>')
