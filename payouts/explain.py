"""Turns a reconciled day into a short, plain-language explanation for the merchant.

The LLM only writes. Every figure it is given was computed by code, and verify.py checks
its text afterwards. The fixed English template below is used when no LLM is available or
when the LLM's text fails that check.
"""
from datetime import date
import json

import llm

SYSTEM = """You explain a daily payout to a small shop owner who uses a payment app.
You are given a reconciliation that code has already computed. Your only job is to put it
into short, simple words in the language asked for.

Rules:
- Use ONLY the numbers in the data. Copy each number exactly. Do no arithmetic of your own.
- Write amounts as "Rs" followed by the number, using ordinary digits (0-9).
- Write the date exactly as given, in YYYY-MM-DD form.
- Do not use any percentage, count or figure that is not in the data.
- Start with how much was sold and how much reached the bank.
- Then list each deduction that is more than zero, one per line.
- If there are problems, describe each one in one sentence and include its record IDs
  exactly as given.
- If there are chargeback disputes, give one sentence for each: its dispute ID exactly as
  given, its amount, and what happened to it (translate "what_happened"; add nothing).
  Do not say the chargeback money will come back.
- If money is owed to the merchant, say how much and that a support ticket is ready for
  their approval. Do not promise that the money will be returned.
- If the settlement status is PENDING, say the money is still on its way.
- Keep it under 150 words. No greetings, no sign-off.

Reply with JSON only: {"explanation": "the text"}"""


def _data_for_llm(breakdown: dict, anomalies: list[dict], amount_owed: float,
                  handoffs: list[dict]) -> dict:
    settlement = breakdown["settlement"]
    return {
        "date": breakdown["date"],
        "shop": breakdown["merchant_name"],
        "payments_received_count": breakdown["txn_count"],
        "total_sales": breakdown["gross_sales"],
        "deductions": [{"name": d["label"], "amount": d["amount"], "record_ids": d["record_ids"]}
                       for d in breakdown["deductions"] if d["amount"] > 0],
        "settlement_id": settlement["settlement_id"] if settlement else None,
        "settlement_status": settlement["status"] if settlement else "MISSING",
        "settlement_amount": settlement["net_amount"] if settlement else None,
        "amount_that_reached_bank": breakdown["received"],
        "difference_between_sales_and_bank": breakdown["difference_from_sales"],
        "problems_found": [{"what": a["label"], "detail": a["detail"], "amount": a["impact"],
                            "record_ids": a["record_ids"]} for a in anomalies],
        "chargeback_disputes": [{"chargeback_id": h["chargeback_id"],
                                 "dispute_id": h["dispute_id"], "amount": h["amount"],
                                 "what_happened": h["what_happened"]} for h in handoffs],
        "amount_owed_to_shop": amount_owed,
    }


def template_explanation(breakdown: dict, anomalies: list[dict], amount_owed: float,
                         handoffs: list[dict] | None = None) -> str:
    """A fixed English explanation built by code. Always passes the number check."""
    def r(value: float) -> str:
        return f"₹{value:,.2f}"
    day = date.fromisoformat(breakdown["date"])
    settlement = breakdown["settlement"]
    pending = bool(settlement and settlement["status"] == "PENDING")
    got = ("Nothing has reached your bank yet." if pending and not breakdown["received"]
           else f"{r(breakdown['received'])} reached your bank.")
    lines = [f"On {day.day} {day:%b %Y} you sold {r(breakdown['gross_sales'])} across "
             f"{breakdown['txn_count']} payments. {got}"]
    taken = [d for d in breakdown["deductions"] if d["amount"] > 0]
    if taken:
        lines.append("What was deducted:")
        lines += [f"- {d['label']}: {r(d['amount'])}" for d in taken]
    if settlement and settlement["status"] == "PENDING":
        lines.append(f"Your settlement {settlement['settlement_id']} of "
                     f"{r(settlement['net_amount'])} is still on its way to your bank.")
    if handoffs:
        lines.append("Chargeback disputes:")
        lines += [f"- {h['chargeback_id']} ({r(h['amount'])}): dispute {h['dispute_id']}. "
                  f"{h['what_happened']}" for h in handoffs]
    if anomalies:
        lines.append("Problems found:")
        for anomaly in anomalies:
            ids = ", ".join(anomaly["record_ids"])
            lines.append(f"- {anomaly['label']} ({r(anomaly['impact'])}). Records: {ids}"
                         if ids else f"- {anomaly['label']} ({r(anomaly['impact'])}).")
        lines.append(f"You may be owed {r(amount_owed)}. A support ticket is ready for "
                     f"your approval.")
    elif not (settlement and settlement["status"] == "PENDING"):
        lines.append("The amounts match. No errors were found.")
    return "\n".join(lines)


def generate(breakdown: dict, anomalies: list[dict], amount_owed: float, language: str,
             feedback: list[str] | None = None, use_cache: bool = True,
             handoffs: list[dict] | None = None) -> tuple[str, dict]:
    """Ask the LLM for an explanation. Returns (text, meta)."""
    user = (f"Language to write in: {language}\n\n"
            f"Reconciliation data:\n"
            f"{json.dumps(_data_for_llm(breakdown, anomalies, amount_owed, handoffs or []), indent=2)}")
    if feedback:
        user += ("\n\nYour previous text failed the number check. Fix these problems:\n- "
                 + "\n- ".join(feedback))
    result, meta = llm.call_json(
        "explain", SYSTEM, user,
        lambda: {"explanation": template_explanation(breakdown, anomalies, amount_owed, handoffs)},
        use_cache)
    return str(result.get("explanation", "")), meta
