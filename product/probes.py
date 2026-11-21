"""Probe the number check with legitimate wording.

The number check rejects any digit string that is not a figure the reconciliation produced.
That protects merchants from invented numbers, but it can also reject honest sentences. This
file measures that on a probe set I wrote by hand: each probe is a sentence I judge to be
legitimate, appended to a template explanation that is known to pass.

It measures the check, not Gemini. Whether real model text trips the check at a similar rate
is on the needs-testing list and cannot be answered offline.
"""
from payouts import explain, reconcile, verify

DEVANAGARI = str.maketrans("0123456789", "०१२३४५६७८९")
TAMIL = str.maketrans("0123456789", "௦௧௨௩௪௫௬௭௮௯")


def _probe_set(breakdown: dict) -> list[dict]:
    gross = breakdown["gross_sales"]
    n = breakdown["txn_count"]
    year, month, day = breakdown["date"].split("-")
    probes = [
        ("Rs with commas and paise", f"You sold Rs {gross:,.2f} today."),
        ("Rs. with a full stop", f"You sold Rs. {gross:,.2f} today."),
        ("rupee symbol", f"You sold ₹{gross:,.2f} today."),
        ("INR prefix", f"You sold INR {gross:,.2f} today."),
        ("amount then 'rupees'", f"You sold {gross:,.2f} rupees today."),
        ("no commas", f"You sold Rs {gross:.2f} today."),
        ("Devanagari digits", f"You sold Rs {gross:,.2f} today.".translate(DEVANAGARI)),
        ("Tamil digits", f"You sold Rs {gross:,.2f} today.".translate(TAMIL)),
        ("payment count", f"There were {n} successful payments."),
        ("day of month", f"This is for the {int(day)}th."),
        ("year", f"This covers {year}."),
        # Sentences below are legitimate by my judgment, but quote a figure code never produced.
        ("GST rate as a percentage", "GST at 18% is charged on the fee."),
        ("rounded amount", f"You sold about Rs {round(gross, -2):,.0f} today."),
        ("share of sales as a percentage", f"Deductions were {5 + n % 7}% of your sales."),
        ("count of deduction lines", "Three items were deducted from your sales."
         .replace("Three", str(len([d for d in breakdown["deductions"] if d["amount"] > 0]) + 7))),
        ("amount in lakhs", f"That is {gross / 100000:.3f} lakh rupees."),
    ]
    return [{"label": label, "text": text} for label, text in probes]


def run_probes(merchant_id: str = "MID-DEMO", date: str | None = None) -> dict:
    import db
    if date is None:
        date = db.one("SELECT settlement_date FROM day_labels WHERE merchant_id=? AND gt_anomaly='none' "
                      "ORDER BY settlement_date LIMIT 1", (merchant_id,))["settlement_date"]
    breakdown = reconcile.build_breakdown(merchant_id, date)
    base = explain.template_explanation(breakdown, [], 0.0, [])
    base_ok, _ = verify.verify_explanation(base, breakdown, [], 0.0, [])
    results = []
    for probe in _probe_set(breakdown):
        ok, problems = verify.verify_explanation(base + " " + probe["text"], breakdown, [], 0.0, [])
        results.append({**probe, "accepted": ok, "problems": problems})
    rejected = [r for r in results if not r["accepted"]]
    return {"base_text_passes": base_ok, "probes": len(results), "rejected": len(rejected),
            "false_rejection_rate": len(rejected) / len(results), "results": results}
