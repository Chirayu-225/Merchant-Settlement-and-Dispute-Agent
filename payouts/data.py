"""Synthetic payout data. Builds two weeks of payments, refunds, chargebacks, settlements
and bank credits for a few shops, and plants known errors on some days. Each day is
labelled with the error planted on it, so the agent's findings can be measured.

Every chargeback also gets a matching dispute case (disputes/data.py) about the same
payment, which is what links the two features.

All data is made up. None of it is Paytm data, and the fee rates are demo values.
"""
from datetime import datetime, timedelta

import config
from disputes import data as dispute_data
from disputes.data import REFERENCE_NOW
from payouts.reconcile import fee_for, money

CHARGEBACK_RATE = 0.15
DAYS = 14

MERCHANTS = [
    ("MID-DEMO", "Lakshmi Stores", "English", 450.0),
    ("MID-2001", "Sri Balaji Kirana", "Tamil", 0.0),
    ("MID-2002", "Gupta General Store", "Hindi", 600.0),
    ("MID-2003", "Annai Tea Stall", "Tamil", 0.0),
    ("MID-2004", "City Mobile Accessories", "English", 900.0),
    ("MID-2005", "Sharma Sweets", "Hindi", 0.0),
]

ERRORS = ["duplicate_refund", "fee_overcharge", "short_bank_credit", "missing_bank_credit",
          "settlement_failed"]

# Fixed days for the demo shop (index 0 = oldest day).
DEMO_PLAN = {5: "duplicate_refund", 8: "fee_overcharge", 10: "missing_bank_credit",
             11: "short_bank_credit"}

# Fixed chargebacks for the demo shop: day index -> (dispute scenario, reason, variant).
# One the agent closes alone, one with missing evidence, one with a planted instruction.
DEMO_CHARGEBACKS = {3: ("clean", "GNR", None),
                    6: ("missing_evidence", "UNAUTH", "no_auth"),
                    9: ("injection", "GNR", dispute_data.INJECTION_STATEMENTS[0])}


def add_shops(conn, rng, error_rate: float = 0.2) -> None:
    """Fill the payout tables (and one linked dispute per chargeback) on an open connection."""
    last_day = REFERENCE_NOW.date() - timedelta(days=1)
    days = [last_day - timedelta(days=DAYS - 1 - n) for n in range(DAYS)]
    counter = {"txn": 100000, "rfd": 20000, "cbk": 3000, "lnd": 4000, "stl": 60000, "crd": 80000}

    def next_id(kind: str, prefix: str) -> str:
        counter[kind] += 1
        return f"{prefix}-{counter[kind]}"

    for merchant_id, name, language, loan_daily in MERCHANTS:
        conn.execute("INSERT INTO merchants VALUES (?,?,?,?)",
                     (merchant_id, name, language, loan_daily))
        history: list[dict] = []   # earlier successful payments, for refunds
        refunded: set[str] = set()
        charged_back: set[str] = set()

        for index, day in enumerate(days):
            iso = day.isoformat()
            is_last = index == DAYS - 1

            # --- payments
            todays = []
            for _ in range(rng.randint(10, 24)):
                txn = {"txn_id": next_id("txn", "TXN"),
                       "amount": float(rng.randint(40, 2400)),
                       "method": rng.choices(["UPI", "CARD", "WALLET"], [0.7, 0.2, 0.1])[0],
                       "status": "SUCCESS" if rng.random() > 0.05 else "FAILED"}
                paid_at = datetime.combine(day, datetime.min.time()) + timedelta(
                    hours=rng.randint(8, 21), minutes=rng.randint(0, 59))
                txn["paid_at"] = paid_at
                conn.execute("INSERT INTO transactions VALUES (?,?,?,?,?,?,?)",
                             (txn["txn_id"], merchant_id, txn["amount"], txn["method"],
                              txn["status"], paid_at.isoformat(timespec="seconds"), iso))
                if txn["status"] == "SUCCESS":
                    todays.append(txn)
            gross = money(sum(t["amount"] for t in todays))
            fees = money(sum(fee_for(t["amount"], t["method"]) for t in todays))
            gst = money(fees * config.GST_RATE)

            # --- which error, if any, is planted today
            if merchant_id == "MID-DEMO":
                error = DEMO_PLAN.get(index)
            elif not is_last and index > 0 and rng.random() < error_rate:
                error = rng.choice(ERRORS)
            else:
                error = None
            impact = 0.0

            # --- refunds (genuine)
            refund_total = 0.0
            candidates = [t for t in history + todays
                          if t["txn_id"] not in refunded and t["txn_id"] not in charged_back]
            if candidates and rng.random() < 0.35:
                for txn in rng.sample(candidates, k=min(len(candidates), rng.randint(1, 2))):
                    amount = txn["amount"] if rng.random() < 0.7 else money(txn["amount"] / 2)
                    conn.execute("INSERT INTO refunds VALUES (?,?,?,?,?)",
                                 (next_id("rfd", "RFD"), txn["txn_id"], merchant_id, amount, iso))
                    refunded.add(txn["txn_id"])
                    refund_total += amount

            if error == "duplicate_refund":
                pool = [t for t in history + todays
                        if t["txn_id"] not in refunded and t["txn_id"] not in charged_back]
                txn = rng.choice(pool)
                for _ in range(2):  # the same payment refunded in full, twice
                    conn.execute("INSERT INTO refunds VALUES (?,?,?,?,?)",
                                 (next_id("rfd", "RFD"), txn["txn_id"], merchant_id,
                                  txn["amount"], iso))
                refunded.add(txn["txn_id"])
                refund_total += 2 * txn["amount"]
                impact = txn["amount"]
            refund_total = money(refund_total)

            # --- chargebacks, each with a linked dispute about the same payment
            chargeback_total = 0.0
            pool = [t for t in history
                    if t["txn_id"] not in refunded and t["txn_id"] not in charged_back]
            if merchant_id == "MID-DEMO":
                planned = DEMO_CHARGEBACKS.get(index)
            else:
                planned = (None, None, None) if rng.random() < CHARGEBACK_RATE else None
            if planned and pool:
                txn = rng.choice(pool)
                chargeback_id = next_id("cbk", "CBK")
                raised_at = datetime.combine(day, datetime.min.time()) + timedelta(hours=18)
                dispute_id = dispute_data.add_linked_case(
                    conn, rng, chargeback_id,
                    {"merchant_id": merchant_id, "txn_id": txn["txn_id"],
                     "amount": txn["amount"], "method": txn["method"],
                     "paid_at": txn["paid_at"], "raised_at": raised_at},
                    scenario=planned[0], reason=planned[1], variant=planned[2],
                    is_demo=1 if merchant_id == "MID-DEMO" else 0)
                conn.execute("INSERT INTO chargebacks VALUES (?,?,?,?,?,?)",
                             (chargeback_id, txn["txn_id"], merchant_id, txn["amount"], iso,
                              dispute_id))
                charged_back.add(txn["txn_id"])
                chargeback_total = txn["amount"]

            # --- loan repayment
            loan_total = 0.0
            if loan_daily > 0:
                conn.execute("INSERT INTO loan_deductions VALUES (?,?,?,?)",
                             (next_id("lnd", "LND"), merchant_id, loan_daily, iso))
                loan_total = loan_daily

            # --- settlement
            charged_fees, charged_gst = fees, gst
            if error == "fee_overcharge":
                charged_fees = money(fees + rng.randint(20, 200))
                charged_gst = money(charged_fees * config.GST_RATE)
                impact = money((charged_fees + charged_gst) - (fees + gst))
            net = money(gross - charged_fees - charged_gst - refund_total - chargeback_total
                        - loan_total)

            status = "SETTLED"
            if error == "settlement_failed":
                status, impact = "FAILED", net
            elif is_last and merchant_id in ("MID-DEMO", "MID-2002", "MID-2004"):
                status = "PENDING"
            utr = f"UTR{rng.randint(10**11, 10**12 - 1)}" if status == "SETTLED" else None
            conn.execute("INSERT INTO settlements VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                         (next_id("stl", "STL"), merchant_id, iso, gross, charged_fees,
                          charged_gst, refund_total, chargeback_total, loan_total, net,
                          status, utr))

            # --- bank credit
            if status == "SETTLED":
                if error == "missing_bank_credit":
                    impact = net
                else:
                    credited = net
                    if error == "short_bank_credit":
                        short = float(rng.randint(50, 500))
                        credited, impact = money(net - short), short
                    credited_at = datetime.combine(day + timedelta(days=1),
                                                   datetime.min.time()) + timedelta(hours=11)
                    conn.execute("INSERT INTO bank_credits VALUES (?,?,?,?,?)",
                                 (next_id("crd", "CRD"), merchant_id, utr, credited,
                                  credited_at.isoformat(timespec="seconds")))

            conn.execute("INSERT INTO day_labels VALUES (?,?,?,?)",
                         (merchant_id, iso, error or "none", money(impact)))
            history.extend(todays)
