"""Run every dispute through the agent in dry-run mode and score it against ground truth."""
import json

import db
from disputes import graph


def run_all(use_cache: bool = True, only_pending: bool = False) -> int:
    sql = "SELECT dispute_id FROM disputes"
    if only_pending:
        sql += " WHERE status='PENDING'"
    ids = [row["dispute_id"] for row in db.many(sql + " ORDER BY dispute_id")]
    for dispute_id in ids:
        graph.process_dispute(dispute_id, dry_run=True, use_cache=use_cache)
    return len(ids)


def compute_metrics() -> dict:
    """Score stored results against the ground-truth labels."""
    rows = db.many("SELECT d.dispute_id, d.scenario, d.gt_action, d.gt_decision, d.gt_reason, "
                   "r.decision, r.checks, r.assessment, r.duration_seconds, r.llm_providers "
                   "FROM disputes d JOIN dispute_results r ON r.dispute_id = d.dispute_id "
                   "WHERE d.suite='main'")
    if not rows:
        return {"processed": 0}

    auto = [row for row in rows if row["decision"] == "auto_submit"]
    escalated = [row for row in rows if row["decision"] == "escalate"]
    should_escalate = [row for row in rows if row["gt_action"] == "escalate"]
    wrong_auto = [row for row in auto if row["gt_action"] == "escalate"]
    right_escalations = [row for row in escalated if row["gt_action"] == "escalate"]

    reason_hits = 0
    for row in right_escalations:
        failed = [c["name"] for c in json.loads(row["checks"]) if c["passed"] is False]
        if row["gt_reason"] in failed:
            reason_hits += 1

    assessed = [row for row in rows if json.loads(row["assessment"] or "null")]
    recommendation_hits = sum(
        1 for row in assessed
        if json.loads(row["assessment"])["recommendation"] == row["gt_decision"])

    providers = set()
    calls = model_calls = 0
    for row in rows:
        used = [p.replace("cache:", "") for p in json.loads(row["llm_providers"] or "[]")]
        providers.update(used)
        calls += len(used)
        model_calls += sum(1 for p in used if p != "offline")

    def share(part, whole):
        return (len(part) if isinstance(part, list) else part) / whole if whole else None

    return {
        "processed": len(rows),
        "auto_submitted": len(auto),
        "escalated": len(escalated),
        "wrong_auto_submissions": len(wrong_auto),
        "wrong_auto_submission_ids": [row["dispute_id"] for row in wrong_auto],
        "wrong_auto_submission_rate": share(wrong_auto, len(auto)),
        "escalation_precision": share(right_escalations, len(escalated)),
        "escalation_recall": share(right_escalations, len(should_escalate)),
        "escalation_reason_match": share(reason_hits, len(right_escalations)),
        "recommendation_accuracy": share(recommendation_hits, len(assessed)),
        "recommendations_scored": len(assessed),
        "auto_resolution_rate": share(auto, len(rows)),
        "avg_seconds_per_dispute": sum(row["duration_seconds"] for row in rows) / len(rows),
        "llm_providers_used": sorted(providers) or ["none"],
        "avg_calls_per_case": calls / len(rows),
        "avg_model_calls_per_case": model_calls / len(rows),
    }


def adversarial_report() -> list[dict]:
    """One row per adversarial case type. No blended rate: the types are different questions.

    A 'wrong auto-submission' here is a case whose truth label is escalate that the agent
    submitted on its own. 'matched_expectation' compares the agent with the prediction that
    was written in disputes/adversarial.py before the first run.
    """
    from disputes import adversarial
    rows = db.many(
        "SELECT d.dispute_id, d.scenario, r.decision, r.checks FROM disputes d "
        "JOIN dispute_results r ON r.dispute_id = d.dispute_id WHERE d.suite='adversarial' "
        "ORDER BY d.dispute_id")
    report = []
    for case_type in adversarial.CASE_TYPES:
        mine = [r for r in rows if r["scenario"] == f"adv:{case_type['name']}"]
        auto = [r for r in mine if r["decision"] == "auto_submit"]
        failed = sorted({c["name"] for r in mine for c in json.loads(r["checks"])
                         if c["passed"] is False})
        report.append({
            "type": case_type["name"], "kind": case_type["kind"], "title": case_type["title"],
            "cases": len(mine), "auto_submitted": len(auto),
            "escalated": len(mine) - len(auto),
            "wrong_auto_submissions": len(auto) if case_type["truth"] == "escalate" else 0,
            "expected_agent": case_type["expected_agent"],
            "matched_expectation": sum(1 for r in mine if r["decision"] == case_type["expected_agent"]),
            "checks_that_fired": failed, "why": case_type["why"],
            "case_ids": [r["dispute_id"] for r in mine],
        })
    return report


def print_adversarial(report: list[dict]) -> None:
    print(f"{'Case type':38} {'kind':8} {'cases':>5} {'auto':>5} {'esc':>4} "
          f"{'wrong':>5} {'matched prediction':>19}")
    for row in report:
        print(f"{row['type']:38} {row['kind']:8} {row['cases']:>5} {row['auto_submitted']:>5} "
              f"{row['escalated']:>4} {row['wrong_auto_submissions']:>5} "
              f"{row['matched_expectation']:>10} of {row['cases']}")


def print_report(metrics: dict) -> None:
    def pct(value) -> str:
        return "n/a" if value is None else f"{value * 100:.1f}%"
    if not metrics.get("processed"):
        print("No dispute results yet.")
        return
    print(f"Disputes processed:          {metrics['processed']}")
    print(f"LLM provider(s) used:        {', '.join(metrics['llm_providers_used'])}")
    print("-" * 50)
    print(f"Wrong auto-submission rate:  {pct(metrics['wrong_auto_submission_rate'])} "
          f"({metrics['wrong_auto_submissions']} of {metrics['auto_submitted']})")
    print(f"Escalation precision:        {pct(metrics['escalation_precision'])}")
    print(f"Escalation recall:           {pct(metrics['escalation_recall'])}")
    print(f"Escalation reason match:     {pct(metrics['escalation_reason_match'])}")
    print(f"Recommendation accuracy:     {pct(metrics['recommendation_accuracy'])} "
          f"(on {metrics['recommendations_scored']} assessed cases)")
    print(f"Auto-resolution rate:        {pct(metrics['auto_resolution_rate'])}")
    print(f"Average time per dispute:    {metrics['avg_seconds_per_dispute']:.3f} s")
