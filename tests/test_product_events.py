from datetime import datetime, timedelta

import pytest

import db
from product import events


def _clean_and_error_day():
    clean = db.one("SELECT merchant_id, settlement_date FROM day_labels WHERE gt_anomaly='none' LIMIT 1")
    error = db.one("SELECT merchant_id, settlement_date, gt_impact FROM day_labels "
                   "WHERE gt_anomaly<>'none' LIMIT 1")
    return clean, error


def test_unknown_events_are_rejected(fresh_db):
    with pytest.raises(ValueError):
        events.log_event("made_up_event")


def test_logged_event_is_stored_with_props(fresh_db):
    events.log_event("why_clicked", "merchant", "MID-DEMO", "2026-11-05", {"x": 1})
    row = db.one("SELECT * FROM events WHERE event='why_clicked'")
    assert row["persona"] == "merchant" and row["ref"] == "2026-11-05"


def test_a_no_answer_must_give_a_reason(fresh_db):
    with pytest.raises(ValueError):
        events.record_feedback("MID-DEMO", "2026-11-05", helpful=False)
    with pytest.raises(ValueError):
        events.record_feedback("MID-DEMO", "2026-11-05", helpful=False, reason="because")
    events.record_feedback("MID-DEMO", "2026-11-05", helpful=False, reason="too_long")
    events.record_feedback("MID-DEMO", "2026-11-06", helpful=True)
    rows = db.many("SELECT helpful, reason FROM feedback ORDER BY id")
    assert rows == [{"helpful": 0, "reason": "too_long"}, {"helpful": 1, "reason": None}]


def test_deflection_uses_ground_truth_day_type_and_a_48_hour_window(fresh_db):
    clean, error = _clean_and_error_day()
    t0 = datetime(2026, 11, 20, 9, 0)
    # clean day, clicked, no ticket: deflected
    events.log_event("why_clicked", "merchant", clean["merchant_id"], clean["settlement_date"], ts=t0)
    # error day, clicked and ticket raised: excluded from deflection (not a clean day)
    events.log_event("why_clicked", "merchant", error["merchant_id"], error["settlement_date"], ts=t0)
    events.log_event("ticket_raised", "merchant", error["merchant_id"], error["settlement_date"],
                     {"amount": error["gt_impact"]}, ts=t0 + timedelta(hours=1))
    result = events.deflection_on_clean_days()
    assert result == {"eligible": 1, "deflected": 1, "rate": 1.0}
    # a ticket on the clean day inside 48h is not deflection; one after 48h is
    events.log_event("ticket_raised", "merchant", clean["merchant_id"], clean["settlement_date"],
                     {"amount": 1.0}, ts=t0 + timedelta(hours=49))
    assert events.deflection_on_clean_days()["deflected"] == 1
    events.log_event("ticket_raised", "merchant", clean["merchant_id"], clean["settlement_date"],
                     {"amount": 1.0}, ts=t0 + timedelta(hours=47))
    assert events.deflection_on_clean_days()["deflected"] == 0


def test_recovery_capture_needs_the_right_amount_on_an_error_day(fresh_db):
    clean, error = _clean_and_error_day()
    t0 = datetime(2026, 11, 20, 9, 0)
    events.log_event("why_clicked", "merchant", error["merchant_id"], error["settlement_date"], ts=t0)
    assert events.recovery_capture_on_error_days() == {"eligible": 1, "captured": 0, "rate": 0.0}
    events.log_event("ticket_raised", "merchant", error["merchant_id"], error["settlement_date"],
                     {"amount": error["gt_impact"] + 50}, ts=t0)
    assert events.recovery_capture_on_error_days()["captured"] == 0
    events.log_event("ticket_raised", "merchant", error["merchant_id"], error["settlement_date"],
                     {"amount": error["gt_impact"]}, ts=t0)
    assert events.recovery_capture_on_error_days()["captured"] == 1


def test_no_events_means_no_rate_not_a_zero(fresh_db):
    assert events.deflection_on_clean_days()["rate"] is None
    assert events.recovery_capture_on_error_days()["rate"] is None


def test_every_metric_action_names_events_that_exist(fresh_db):
    for item in events.METRIC_ACTIONS:
        assert item["if_it_drops"] and item["then_we"]
        named = [e.strip().split(" ")[0].strip(",") for e in item["events"].split("(")[0].split(",")]
        for name in named:
            assert name in events.EVENT_SCHEMA, (item["metric"], name)
