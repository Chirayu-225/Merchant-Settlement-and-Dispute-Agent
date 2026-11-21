"""Run every merchant day through the agent and score its findings against the planted
errors. Also scores the handoff: what happened to each chargeback sent to the dispute
pipeline, against that dispute's ground-truth label."""
import json

import config
import db
from payouts import pipeline


def run_all(use_cache: bool = True) -> int:
    days = db.many("SELECT merchant_id, settlement_date FROM day_labels "
                   "ORDER BY merchant_id, settlement_date")
    for day in days:
        pipeline.run(day["merchant_id"], day["settlement_date"], use_cache=use_cache,
                     dry_run=True)
    return len(days)


def compute_metrics() -> dict:
    rows = db.many(
        "SELECT l.merchant_id, l.settlement_date, l.gt_anomaly, l.gt_impact, r.anomalies, "
        "r.amount_owed, r.handoffs, r.explanation_source, r.duration_seconds "
        "FROM day_labels l JOIN payout_results r ON r.merchant_id = l.merchant_id "
        "AND r.settlement_date = l.settlement_date")
    if not rows:
        return {"processed": 0}

    true_positive = false_positive = false_negative = 0
    impact_right = impact_scored = 0
    clean_days = false_alarm_days = 0
    missed, false_alarms = [], []
    for row in rows:
        found = json.loads(row["anomalies"])
        types = {a["type"] for a in found}
        expected = set() if row["gt_anomaly"] == "none" else {row["gt_anomaly"]}
        true_positive += len(types & expected)
        false_positive += len(types - expected)
        false_negative += len(expected - types)
        key = f"{row['merchant_id']} {row['settlement_date']}"
        if expected - types:
            missed.append(key)
        if types - expected:
            false_alarms.append(key)
        if not expected:
            clean_days += 1
            false_alarm_days += 1 if types else 0
        elif types & expected:
            impact_scored += 1
            if abs(row["amount_owed"] - row["gt_impact"]) <= config.TOLERANCE:
                impact_right += 1

    handed = closed = escalated = handoff_right = 0
    for row in rows:
        for item in json.loads(row["handoffs"] or "[]"):
            if item["decision"] is None:
                continue
            handed += 1
            closed += 1 if item["decision"] == "auto_submit" else 0
            escalated += 1 if item["decision"] == "escalate" else 0
            truth = db.one("SELECT gt_action FROM disputes WHERE dispute_id=?",
                           (item["dispute_id"],))
            handoff_right += 1 if truth and truth["gt_action"] == item["decision"] else 0

    sources = [row["explanation_source"].replace("cache:", "") for row in rows]
    fallbacks = sources.count("template_fallback")

    def share(part, whole):
        return part / whole if whole else None

    return {
        "processed": len(rows),
        "days_with_planted_errors": len(rows) - clean_days,
        "errors_found": true_positive,
        "detection_precision": share(true_positive, true_positive + false_positive),
        "detection_recall": share(true_positive, true_positive + false_negative),
        "false_alarm_rate_on_clean_days": share(false_alarm_days, clean_days),
        "amount_accuracy": share(impact_right, impact_scored),
        "explanations_from_llm": len(rows) - fallbacks - sources.count("offline"),
        "explanations_from_template": fallbacks + sources.count("offline"),
        "llm_text_rejected_by_number_check": fallbacks,
        "avg_seconds_per_day": sum(row["duration_seconds"] for row in rows) / len(rows),
        "explanation_sources": sorted(set(sources)),
        "chargebacks_handed_to_dispute_pipeline": handed,
        "handoffs_closed_by_agent": closed,
        "handoffs_escalated": escalated,
        "handoff_decision_accuracy": share(handoff_right, handed),
        "missed_days": missed,
        "false_alarm_days": false_alarms,
    }


def print_report(metrics: dict) -> None:
    def pct(value) -> str:
        return "n/a" if value is None else f"{value * 100:.1f}%"
    if not metrics.get("processed"):
        print("No payout results yet.")
        return
    print(f"Merchant days processed:          {metrics['processed']}")
    print(f"Days with a planted error:        {metrics['days_with_planted_errors']}")
    print(f"Explanation source(s):            {', '.join(metrics['explanation_sources'])}")
    print("-" * 50)
    print(f"Error detection precision:        {pct(metrics['detection_precision'])}")
    print(f"Error detection recall:           {pct(metrics['detection_recall'])}")
    print(f"False alarms on clean days:       {pct(metrics['false_alarm_rate_on_clean_days'])}")
    print(f"Rupee amount correct:             {pct(metrics['amount_accuracy'])}")
    print(f"Explanations written by an LLM:   {metrics['explanations_from_llm']}")
    print(f"Explanations from the template:   {metrics['explanations_from_template']}")
    print(f"LLM texts rejected by the check:  {metrics['llm_text_rejected_by_number_check']}")
    print(f"Chargebacks handed to disputes:   {metrics['chargebacks_handed_to_dispute_pipeline']} "
          f"({metrics['handoffs_closed_by_agent']} closed by the agent, "
          f"{metrics['handoffs_escalated']} escalated)")
    print(f"Handoff decision correct:         {pct(metrics['handoff_decision_accuracy'])}")
    print(f"Average time per day:             {metrics['avg_seconds_per_day']:.3f} s")
