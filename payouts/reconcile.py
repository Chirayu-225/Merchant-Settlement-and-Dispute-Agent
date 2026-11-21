"""Reconciliation engine: match a day's sales to its settlement and bank credit, and break
the difference down into fees, tax, refunds, chargebacks and loan repayment.

Plain Python and SQL only. No LLM touches the arithmetic.
"""
import config
import db


def money(value: float) -> float:
    return round(float(value) + 1e-9, 2)


def fee_for(amount: float, method: str) -> float:
    return money(amount * config.FEE_RATES.get(method, 0.0))


def build_breakdown(merchant_id: str, date: str) -> dict:
    """Everything known about one merchant's settlement day."""
    merchant = db.one("SELECT * FROM merchants WHERE merchant_id=?", (merchant_id,))
    if not merchant:
        raise KeyError(f"Unknown merchant {merchant_id}")

    txns = db.many("SELECT * FROM transactions WHERE merchant_id=? AND settlement_date=? "
                   "ORDER BY txn_id", (merchant_id, date))
    paid = [t for t in txns if t["status"] == "SUCCESS"]
    gross = money(sum(t["amount"] for t in paid))
    fees = money(sum(fee_for(t["amount"], t["method"]) for t in paid))
    gst = money(fees * config.GST_RATE)

    refunds = db.many("SELECT * FROM refunds WHERE merchant_id=? AND settlement_date=? "
                      "ORDER BY refund_id", (merchant_id, date))
    chargebacks = db.many("SELECT * FROM chargebacks WHERE merchant_id=? AND settlement_date=? "
                          "ORDER BY chargeback_id", (merchant_id, date))
    loans = db.many("SELECT * FROM loan_deductions WHERE merchant_id=? AND settlement_date=? "
                    "ORDER BY deduction_id", (merchant_id, date))

    deductions = [
        {"key": "fees", "label": "Payment fees", "amount": fees, "record_ids": []},
        {"key": "gst", "label": "GST on fees", "amount": gst, "record_ids": []},
        {"key": "refunds", "label": "Refunds to customers",
         "amount": money(sum(r["amount"] for r in refunds)),
         "record_ids": [r["refund_id"] for r in refunds]},
        {"key": "chargebacks", "label": "Chargebacks",
         "amount": money(sum(c["amount"] for c in chargebacks)),
         "record_ids": [c["chargeback_id"] for c in chargebacks]},
        {"key": "loan", "label": "Loan repayment",
         "amount": money(sum(l["amount"] for l in loans)),
         "record_ids": [l["deduction_id"] for l in loans]},
    ]
    expected_net = money(gross - sum(d["amount"] for d in deductions))

    settlement = db.one("SELECT * FROM settlements WHERE merchant_id=? AND settlement_date=?",
                        (merchant_id, date))
    bank_credit = None
    if settlement and settlement["utr"]:
        bank_credit = db.one("SELECT * FROM bank_credits WHERE merchant_id=? AND utr=?",
                             (merchant_id, settlement["utr"]))
    received = money(bank_credit["amount"]) if bank_credit else 0.0

    return {
        "merchant_id": merchant_id,
        "merchant_name": merchant["name"],
        "date": date,
        "txn_count": len(paid),
        "failed_txn_count": len(txns) - len(paid),
        "gross_sales": gross,
        "deductions": deductions,
        "expected_net": expected_net,
        "settlement": settlement,
        "bank_credit": bank_credit,
        "received": received,
        "difference_from_sales": money(gross - received),
        "refund_rows": refunds,
        "chargeback_rows": chargebacks,
    }


def deduction(breakdown: dict, key: str) -> float:
    return next(d["amount"] for d in breakdown["deductions"] if d["key"] == key)
