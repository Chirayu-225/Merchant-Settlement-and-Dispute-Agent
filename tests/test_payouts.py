import json

import pytest

import db
from payouts import anomalies, explain, pipeline, reconcile, tickets, verify
from payouts import metrics as payout_metrics


def _label(merchant_id, date):
    return db.one("SELECT * FROM day_labels WHERE merchant_id=? AND settlement_date=?",
                  (merchant_id, date))


def test_clean_day_reconciles_to_the_rupee(fresh_db, day_with):
    merchant_id, date = day_with("none", "MID-2001")
    breakdown = reconcile.build_breakdown(merchant_id, date)
    assert breakdown["settlement"]["status"] == "SETTLED"
    assert abs(breakdown["expected_net"] - breakdown["settlement"]["net_amount"]) < 0.05
    assert abs(breakdown["received"] - breakdown["expected_net"]) < 0.05
    assert anomalies.detect(breakdown) == []


def test_breakdown_adds_up(fresh_db, day_with):
    merchant_id, date = day_with("none", "MID-DEMO")
    breakdown = reconcile.build_breakdown(merchant_id, date)
    total_deducted = sum(d["amount"] for d in breakdown["deductions"])
    assert abs(breakdown["gross_sales"] - total_deducted - breakdown["expected_net"]) < 0.01
    assert reconcile.deduction(breakdown, "loan") == 450.0


@pytest.mark.parametrize("label", ["duplicate_refund", "fee_overcharge", "short_bank_credit",
                                   "missing_bank_credit"])
def test_each_planted_error_on_the_demo_shop_is_found_with_the_right_amount(fresh_db, day_with, label):
    merchant_id, date = day_with(label, "MID-DEMO")
    found = anomalies.detect(reconcile.build_breakdown(merchant_id, date))
    assert [a["type"] for a in found] == [label]
    assert abs(found[0]["impact"] - _label(merchant_id, date)["gt_impact"]) < 0.05
    assert found[0]["record_ids"]


def test_failed_settlement_is_found(fresh_db, day_with):
    merchant_id, date = day_with("settlement_failed")
    found = anomalies.detect(reconcile.build_breakdown(merchant_id, date))
    assert [a["type"] for a in found] == ["settlement_failed"]


def test_pending_settlement_is_not_flagged(fresh_db):
    row = db.one("SELECT merchant_id, settlement_date FROM settlements WHERE status='PENDING'")
    breakdown = reconcile.build_breakdown(row["merchant_id"], row["settlement_date"])
    assert breakdown["received"] == 0.0
    assert anomalies.detect(breakdown) == []


def test_partial_refunds_within_the_payment_amount_are_not_duplicates(fresh_db):
    txn = db.one("SELECT * FROM transactions WHERE status='SUCCESS' AND txn_id NOT IN "
                 "(SELECT txn_id FROM refunds) AND merchant_id='MID-2001' ORDER BY txn_id")
    date = db.one("SELECT settlement_date FROM day_labels WHERE merchant_id='MID-2001' AND "
                  "gt_anomaly='none' ORDER BY settlement_date DESC")["settlement_date"]
    half = round(txn["amount"] / 2, 2)
    for refund_id in ("RFD-T1", "RFD-T2"):
        db.execute("INSERT INTO refunds VALUES (?,?,?,?,?)",
                   (refund_id, txn["txn_id"], "MID-2001", half, date))
    breakdown = reconcile.build_breakdown("MID-2001", date)
    assert not [a for a in anomalies.detect(breakdown) if a["type"] == "duplicate_refund"]


def test_template_explanation_passes_the_number_check(fresh_db, day_with):
    for label in ("none", "duplicate_refund", "fee_overcharge", "missing_bank_credit"):
        merchant_id, date = day_with(label, "MID-DEMO")
        breakdown = reconcile.build_breakdown(merchant_id, date)
        found = anomalies.detect(breakdown)
        owed = sum(a["impact"] for a in found)
        text = explain.template_explanation(breakdown, found, owed)
        ok, problems = verify.verify_explanation(text, breakdown, found, owed)
        assert ok, problems


def test_number_check_rejects_an_invented_figure_and_an_invented_record(fresh_db, day_with):
    merchant_id, date = day_with("none", "MID-DEMO")
    breakdown = reconcile.build_breakdown(merchant_id, date)
    good = explain.template_explanation(breakdown, [], 0.0)
    ok, _ = verify.verify_explanation(good + " You also paid Rs 77777.77 in extra charges.",
                                      breakdown, [], 0.0)
    assert not ok
    ok, problems = verify.verify_explanation(good + " See refund RFD-99999.", breakdown, [], 0.0)
    assert not ok and "RFD-99999" in problems[0]


def test_number_check_requires_a_record_for_each_problem(fresh_db, day_with):
    merchant_id, date = day_with("missing_bank_credit", "MID-DEMO")
    breakdown = reconcile.build_breakdown(merchant_id, date)
    found = anomalies.detect(breakdown)
    owed = found[0]["impact"]
    vague = (f"On {date} you sold Rs {breakdown['gross_sales']:.2f}. Something went wrong with "
             f"your bank credit and you may be owed Rs {owed:.2f}.")
    ok, problems = verify.verify_explanation(vague, breakdown, found, owed)
    assert not ok


class _WrongNumbers:
    """An LLM stand-in that always invents a figure."""
    calls = 0

    @classmethod
    def generate(cls, breakdown, found, owed, language, feedback=None, use_cache=True,
                 handoffs=None):
        cls.calls += 1
        return ("You sold a lot today and roughly Rs 123456.78 reached your bank after about "
                "12.5 percent in charges.",
                {"task": "explain", "provider": "fake", "cached": False, "errors": []})


def test_bad_llm_text_is_retried_then_replaced_by_the_template(fresh_db, day_with):
    merchant_id, date = day_with("none", "MID-DEMO")
    _WrongNumbers.calls = 0
    result = pipeline.run(merchant_id, date, explainer=_WrongNumbers)
    assert _WrongNumbers.calls == 2
    assert result["explanation_source"] == "template_fallback"
    assert "123456.78" not in result["explanation"]
    assert f"₹{result['breakdown']['gross_sales']:,.2f}" in result["explanation"]


def test_template_in_rupee_format_passes_the_number_check_on_every_day(fresh_db):
    from payouts import anomalies as find, reconcile, verify
    from payouts.explain import template_explanation
    for day in db.many("SELECT merchant_id, settlement_date FROM day_labels"):
        breakdown = reconcile.build_breakdown(day["merchant_id"], day["settlement_date"])
        found = find.detect(breakdown)
        owed = sum(a["impact"] for a in found)
        text = template_explanation(breakdown, found, owed)
        ok, problems = verify.verify_explanation(text, breakdown, found, owed)
        assert ok, (day, problems)
        assert "₹" in text and "Rs " not in text


def test_pipeline_drafts_one_ticket_and_raising_is_idempotent(fresh_db, day_with):
    merchant_id, date = day_with("duplicate_refund", "MID-DEMO")
    first = pipeline.run(merchant_id, date)
    second = pipeline.run(merchant_id, date)
    assert first["ticket_ids"] == second["ticket_ids"] and len(first["ticket_ids"]) == 1
    ticket_id = first["ticket_ids"][0]
    assert db.one("SELECT status FROM tickets WHERE ticket_id=?", (ticket_id,))["status"] == "DRAFT"
    assert tickets.raise_ticket(ticket_id)["duplicate"] is False
    assert tickets.raise_ticket(ticket_id)["duplicate"] is True
    pipeline.run(merchant_id, date)  # a re-run must not reset a raised ticket
    assert db.one("SELECT status FROM tickets WHERE ticket_id=?", (ticket_id,))["status"] == "RAISED"
    assert db.one("SELECT COUNT(*) AS n FROM tickets WHERE merchant_id=? AND settlement_date=?",
                  (merchant_id, date))["n"] == 1


def test_clean_day_drafts_no_ticket_and_is_audited(fresh_db, day_with):
    merchant_id, date = day_with("none", "MID-2003")
    result = pipeline.run(merchant_id, date)
    assert result["ticket_ids"] == [] and result["amount_owed"] == 0.0
    steps = [row["step"] for row in db.many(
        "SELECT step FROM audit_log WHERE feature='payout' AND ref=? ORDER BY id",
        (db.payout_ref(merchant_id, date),))]
    assert steps == ["reconcile", "flag", "explain", "tickets"]


def test_full_evaluation_finds_every_planted_error_with_no_false_alarms(fresh_db):
    processed = payout_metrics.run_all()
    metrics = payout_metrics.compute_metrics()
    assert processed == metrics["processed"] == 84
    assert metrics["days_with_planted_errors"] >= 10
    assert metrics["detection_recall"] == 1.0
    assert metrics["detection_precision"] == 1.0
    assert metrics["false_alarm_rate_on_clean_days"] == 0.0
    assert metrics["amount_accuracy"] == 1.0
    json.dumps(metrics)
