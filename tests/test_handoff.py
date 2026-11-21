"""The link between the two features: a chargeback in a payout goes to the dispute pipeline."""
import json

import db
import evaluate
from disputes import metrics as dispute_metrics
from payouts import explain, handoff, pipeline, reconcile, verify
from payouts import metrics as payout_metrics


def _demo_chargeback(scenario):
    row = db.one("SELECT c.*, d.scenario FROM chargebacks c JOIN disputes d "
                 "ON d.dispute_id = c.dispute_id WHERE c.merchant_id='MID-DEMO' AND d.scenario=?",
                 (scenario,))
    assert row, f"no demo chargeback with scenario {scenario}"
    return row


def _status(dispute_id):
    return db.one("SELECT status FROM disputes WHERE dispute_id=?", (dispute_id,))["status"]


def test_every_chargeback_has_a_dispute_about_the_same_payment(fresh_db):
    chargebacks = db.many("SELECT * FROM chargebacks")
    assert len(chargebacks) >= 3
    for chargeback in chargebacks:
        dispute = db.one("SELECT * FROM disputes WHERE dispute_id=?", (chargeback["dispute_id"],))
        assert dispute and dispute["chargeback_id"] == chargeback["chargeback_id"]
        assert dispute["merchant_id"] == chargeback["merchant_id"]
        sale = db.one("SELECT * FROM transactions WHERE txn_id=?", (chargeback["txn_id"],))
        payment = db.one("SELECT * FROM payments WHERE txn_id=?", (chargeback["txn_id"],))
        assert payment and sale["status"] == "SUCCESS"
        assert payment["paid_at"] == sale["paid_at"] and payment["method"] == sale["method"]
        assert chargeback["amount"] == sale["amount"]
        assert f"INR {sale['amount']:.2f}" in dispute["notice_text"]


def test_clean_chargeback_is_closed_by_the_agent_and_reported_in_the_payout(fresh_db):
    chargeback = _demo_chargeback("clean")
    result = pipeline.run("MID-DEMO", chargeback["settlement_date"])
    assert len(result["handoffs"]) == 1
    item = result["handoffs"][0]
    assert item["dispute_id"] == chargeback["dispute_id"]
    assert item["decision"] == "auto_submit" and item["status"] == "DRY_RUN_READY"
    assert item["processed_in_this_run"] is True
    assert chargeback["dispute_id"] in result["explanation"]
    assert "Dry run" in result["explanation"]
    # A chargeback is a deduction under dispute, not an error: nothing is "owed", no ticket.
    assert result["amount_owed"] == 0.0 and result["ticket_ids"] == []
    assert reconcile.deduction(result["breakdown"], "chargebacks") == chargeback["amount"]


def test_chargeback_with_missing_evidence_is_escalated_with_a_note(fresh_db):
    chargeback = _demo_chargeback("missing_evidence")
    result = pipeline.run("MID-DEMO", chargeback["settlement_date"])
    item = result["handoffs"][0]
    assert item["decision"] == "escalate" and item["status"] == "ESCALATED"
    assert "support agent" in result["explanation"]
    note = db.one("SELECT handoff_note FROM escalations WHERE dispute_id=?",
                  (chargeback["dispute_id"],))
    assert note and "Evidence checklist" in note["handoff_note"]
    assert db.one("SELECT * FROM submissions WHERE dispute_id=?",
                  (chargeback["dispute_id"],)) is None


def test_chargeback_with_planted_instruction_never_reaches_the_llm(fresh_db):
    chargeback = _demo_chargeback("injection")
    result = pipeline.run("MID-DEMO", chargeback["settlement_date"])
    assert result["handoffs"][0]["status"] == "ESCALATED"
    stored = db.one("SELECT llm_providers, assessment FROM dispute_results WHERE dispute_id=?",
                    (chargeback["dispute_id"],))
    assert json.loads(stored["llm_providers"]) == []
    assert json.loads(stored["assessment"]) is None


def test_real_submission_through_the_handoff_happens_once(fresh_db):
    chargeback = _demo_chargeback("clean")
    first = pipeline.run("MID-DEMO", chargeback["settlement_date"], dry_run=False)
    assert first["handoffs"][0]["status"] == "AUTO_SUBMITTED"
    assert "sent a reply" in first["explanation"]
    second = pipeline.run("MID-DEMO", chargeback["settlement_date"], dry_run=False)
    assert second["handoffs"][0]["status"] == "AUTO_SUBMITTED"
    assert second["handoffs"][0]["processed_in_this_run"] is False
    count = db.one("SELECT COUNT(*) AS n FROM submissions WHERE dispute_id=?",
                   (chargeback["dispute_id"],))
    assert count["n"] == 1


def test_dry_run_reply_is_sent_for_real_when_dry_run_is_switched_off(fresh_db):
    chargeback = _demo_chargeback("clean")
    pipeline.run("MID-DEMO", chargeback["settlement_date"], dry_run=True)
    assert _status(chargeback["dispute_id"]) == "DRY_RUN_READY"
    pipeline.run("MID-DEMO", chargeback["settlement_date"], dry_run=False)
    assert _status(chargeback["dispute_id"]) == "AUTO_SUBMITTED"


def test_handoff_can_be_switched_off(fresh_db):
    chargeback = _demo_chargeback("clean")
    result = pipeline.run("MID-DEMO", chargeback["settlement_date"], resolve_disputes=False)
    assert result["handoffs"][0]["status"] == "PENDING"
    assert result["handoffs"][0]["decision"] is None
    assert _status(chargeback["dispute_id"]) == "PENDING"
    assert "still open" in result["explanation"]


def test_handoff_is_in_the_shared_audit_log_for_both_features(fresh_db):
    chargeback = _demo_chargeback("clean")
    pipeline.run("MID-DEMO", chargeback["settlement_date"])
    payout_steps = [row["step"] for row in db.many(
        "SELECT step FROM audit_log WHERE feature='payout' AND ref=? ORDER BY id",
        (db.payout_ref("MID-DEMO", chargeback["settlement_date"]),))]
    assert payout_steps == ["reconcile", "handoff", "flag", "explain", "tickets"]
    dispute_steps = [row["step"] for row in db.many(
        "SELECT step FROM audit_log WHERE feature='dispute' AND ref=? ORDER BY id",
        (chargeback["dispute_id"],))]
    assert dispute_steps == ["ingest", "retrieve", "assess", "draft", "verify", "gate", "submit"]


def test_explanation_that_leaves_out_the_dispute_fails_the_check(fresh_db):
    chargeback = _demo_chargeback("clean")
    breakdown = reconcile.build_breakdown("MID-DEMO", chargeback["settlement_date"])
    handoffs = handoff.resolve_chargebacks(breakdown, dry_run=True)
    good = explain.template_explanation(breakdown, [], 0.0, handoffs)
    assert verify.verify_explanation(good, breakdown, [], 0.0, handoffs)[0]
    without = explain.template_explanation(breakdown, [], 0.0, [])
    ok, problems = verify.verify_explanation(without, breakdown, [], 0.0, handoffs)
    assert not ok and chargeback["dispute_id"] in problems[-1]
    ok, _ = verify.verify_explanation(good + " See also DSP-CB-9999.", breakdown, [], 0.0, handoffs)
    assert not ok


def test_full_evaluation_scores_both_features_and_the_handoff(fresh_db):
    counts = evaluate.run_all()
    payouts = payout_metrics.compute_metrics()
    disputes = dispute_metrics.compute_metrics()
    assert counts["days"] == payouts["processed"] == 84
    assert counts["disputes"] == disputes["processed"] + db.one(
        "SELECT COUNT(*) AS n FROM disputes WHERE suite='adversarial'")["n"]
    linked = db.one("SELECT COUNT(*) AS n FROM chargebacks")["n"]
    assert payouts["chargebacks_handed_to_dispute_pipeline"] == linked
    assert payouts["handoffs_closed_by_agent"] >= 1 and payouts["handoffs_escalated"] >= 1
    assert payouts["handoff_decision_accuracy"] == 1.0
    assert payouts["detection_recall"] == 1.0 and payouts["false_alarm_rate_on_clean_days"] == 0.0
    assert disputes["wrong_auto_submissions"] == 0
    json.dumps([payouts, disputes])
