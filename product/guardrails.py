"""Guardrail metrics. Day type always comes from the GROUND-TRUTH label in day_labels,
never from what the agent concluded.

  missed recovery  a day with a real planted error where the agent drafted no ticket
  wrong amount     an error day where a ticket was drafted but for the wrong rupee amount
  ticket noise     a day with no error where the agent drafted a ticket anyway

Wrong auto-submissions and missed recoveries are the two ways the product can fail, and
they are reported side by side.
"""
import config
import db


def payout_guardrails() -> dict:
    rows = db.many(
        "SELECT l.merchant_id, l.settlement_date, l.gt_anomaly, l.gt_impact, "
        "(SELECT COUNT(*) FROM tickets t WHERE t.merchant_id = l.merchant_id "
        " AND t.settlement_date = l.settlement_date) AS n_tickets, "
        "(SELECT COALESCE(SUM(t.amount), 0) FROM tickets t WHERE t.merchant_id = l.merchant_id "
        " AND t.settlement_date = l.settlement_date) AS ticket_amount "
        "FROM day_labels l JOIN payout_results r ON r.merchant_id = l.merchant_id "
        "AND r.settlement_date = l.settlement_date")
    error_days = [r for r in rows if r["gt_anomaly"] != "none"]
    clean_days = [r for r in rows if r["gt_anomaly"] == "none"]
    missed = [r for r in error_days if r["n_tickets"] == 0]
    wrong_amount = [r for r in error_days if r["n_tickets"] > 0
                    and abs(r["ticket_amount"] - r["gt_impact"]) > config.TOLERANCE]
    noise = [r for r in clean_days if r["n_tickets"] > 0]
    key = lambda r: f"{r['merchant_id']} {r['settlement_date']}"
    return {
        "error_days": len(error_days), "clean_days": len(clean_days),
        "missed_recoveries": len(missed), "missed_days": [key(r) for r in missed],
        "wrong_amount_tickets": len(wrong_amount), "wrong_amount_days": [key(r) for r in wrong_amount],
        "ticket_noise_on_clean_days": len(noise), "noise_days": [key(r) for r in noise],
    }
