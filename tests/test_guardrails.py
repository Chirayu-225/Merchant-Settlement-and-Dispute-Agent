import evaluate
from payouts import anomalies
from product import guardrails


def test_clean_run_has_no_missed_recovery_or_noise(fresh_db):
    evaluate.run_all()
    g = guardrails.payout_guardrails()
    assert g["error_days"] >= 10 and g["clean_days"] > g["error_days"]
    assert g["missed_recoveries"] == 0 and g["ticket_noise_on_clean_days"] == 0
    assert g["wrong_amount_tickets"] == 0


def test_a_blind_agent_shows_up_as_missed_recoveries(fresh_db, monkeypatch):
    """Day type comes from the planted label, so an agent that finds nothing still gets
    counted against the days where something was really wrong."""
    monkeypatch.setattr(anomalies, "detect", lambda breakdown: [])
    evaluate.run_all()
    g = guardrails.payout_guardrails()
    assert g["missed_recoveries"] == g["error_days"] > 0
    assert g["ticket_noise_on_clean_days"] == 0


def test_a_paranoid_agent_shows_up_as_ticket_noise(fresh_db, monkeypatch):
    real = anomalies.detect

    def noisy(breakdown):
        found = real(breakdown)
        if not found and breakdown["gross_sales"] > 0:
            found = [anomalies._anomaly("fee_overcharge", 5.0, "Made-up problem.", ["STL-1"], [5.0])]
        return found
    monkeypatch.setattr(anomalies, "detect", noisy)
    evaluate.run_all()
    g = guardrails.payout_guardrails()
    assert g["ticket_noise_on_clean_days"] > 0
