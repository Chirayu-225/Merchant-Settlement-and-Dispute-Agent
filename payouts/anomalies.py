"""Anomaly checks on a reconciled day. All code, no LLM.

Each anomaly says what is wrong, how many rupees it cost the merchant, and which records
prove it.
"""
import config
import db
from payouts.reconcile import deduction, money

LABELS = {
    "duplicate_refund": "The same payment was refunded more than once",
    "fee_overcharge": "More fees were deducted than the fee rates allow",
    "deduction_mismatch": "A deduction on the settlement does not match the records",
    "short_bank_credit": "The bank received less than the settlement amount",
    "missing_bank_credit": "The settlement is marked paid but no bank credit was found",
    "settlement_failed": "The settlement failed and no money was sent",
    "settlement_missing": "No settlement was created for this day",
}


def _anomaly(kind: str, impact: float, detail: str, record_ids: list[str],
             figures: list[float] | None = None) -> dict:
    """`figures` lists every rupee amount quoted in `detail`, so the explanation check
    knows those numbers are legitimate."""
    return {"type": kind, "label": LABELS[kind], "impact": money(impact), "detail": detail,
            "record_ids": [r for r in record_ids if r],
            "figures": [money(f) for f in (figures or [])]}


def _duplicate_refunds(breakdown: dict) -> list[dict]:
    found = []
    seen_today: dict[str, float] = {}
    for refund in breakdown["refund_rows"]:
        txn = db.one("SELECT * FROM transactions WHERE txn_id=?", (refund["txn_id"],))
        if not txn:
            continue
        earlier = db.one(
            "SELECT COALESCE(SUM(amount), 0) AS total FROM refunds WHERE txn_id=? AND "
            "settlement_date<?", (refund["txn_id"], breakdown["date"]))["total"]
        already = earlier + seen_today.get(refund["txn_id"], 0.0)
        seen_today[refund["txn_id"]] = seen_today.get(refund["txn_id"], 0.0) + refund["amount"]
        excess = min(refund["amount"], already + refund["amount"] - txn["amount"])
        if excess > config.TOLERANCE:
            found.append(_anomaly(
                "duplicate_refund", excess,
                f"Payment {txn['txn_id']} was for Rs {txn['amount']:.2f} but refunds on it now "
                f"total Rs {already + refund['amount']:.2f}. Refund {refund['refund_id']} took "
                f"Rs {excess:.2f} too much.",
                [refund["refund_id"], txn["txn_id"]],
                [txn["amount"], already + refund["amount"], excess]))
    return found


def detect(breakdown: dict) -> list[dict]:
    found = _duplicate_refunds(breakdown)
    settlement = breakdown["settlement"]

    if settlement is None:
        if breakdown["gross_sales"] > 0:
            found.append(_anomaly("settlement_missing", max(breakdown["expected_net"], 0.0),
                                  "Sales exist for this day but there is no settlement record.", []))
        return found

    sid = settlement["settlement_id"]

    # Settlement side: do its deductions match what the records and fee rates say?
    expected_fee_total = deduction(breakdown, "fees") + deduction(breakdown, "gst")
    charged_fee_total = settlement["fees"] + settlement["gst"]
    if charged_fee_total - expected_fee_total > config.TOLERANCE:
        found.append(_anomaly(
            "fee_overcharge", charged_fee_total - expected_fee_total,
            f"Fees and GST should be Rs {expected_fee_total:.2f} but Rs {charged_fee_total:.2f} "
            f"was deducted.", [sid], [expected_fee_total, charged_fee_total]))
    for key, column, name in [("refunds", "refunds", "Refunds"),
                              ("chargebacks", "chargebacks", "Chargebacks"),
                              ("loan", "loan", "Loan repayment")]:
        extra = settlement[column] - deduction(breakdown, key)
        if extra > config.TOLERANCE:
            found.append(_anomaly(
                "deduction_mismatch", extra,
                f"{name} on record total Rs {deduction(breakdown, key):.2f} but the settlement "
                f"deducted Rs {settlement[column]:.2f}.", [sid],
                [deduction(breakdown, key), settlement[column]]))

    # Bank side: did the settlement amount actually arrive?
    net = settlement["net_amount"]
    credit = breakdown["bank_credit"]
    if settlement["status"] == "FAILED":
        found.append(_anomaly("settlement_failed", net,
                              f"Settlement {sid} for Rs {net:.2f} failed.", [sid], [net]))
    elif settlement["status"] == "SETTLED":
        if credit is None:
            found.append(_anomaly("missing_bank_credit", net,
                                  f"Settlement {sid} for Rs {net:.2f} is marked paid, but no "
                                  f"bank credit matches it.", [sid], [net]))
        elif net - credit["amount"] > config.TOLERANCE:
            found.append(_anomaly(
                "short_bank_credit", net - credit["amount"],
                f"Settlement {sid} was for Rs {net:.2f} but bank credit {credit['credit_id']} "
                f"was Rs {credit['amount']:.2f}.", [sid, credit["credit_id"]],
                [net, credit["amount"]]))
    # status PENDING is normal: the money is on its way, so nothing is flagged.
    return found
