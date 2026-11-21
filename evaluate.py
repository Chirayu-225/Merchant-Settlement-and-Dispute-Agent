"""Score both features against the ground truth in the synthetic data. Always dry-run.

Run:  python evaluate.py

Every run records a stamp (mode and date). The app shows that stamp next to every figure
labelled Measured, so a number is always tied to how and when it was produced.
"""
import json
from datetime import date

import db
import generate_data
import llm
from disputes import metrics as dispute_metrics
from payouts import metrics as payout_metrics


def run_all(use_cache: bool = True) -> dict:
    """Payout days first (which hands their chargebacks to the dispute pipeline), then
    every dispute, including the adversarial suite."""
    llm.reset_tally()
    days = payout_metrics.run_all(use_cache=use_cache)
    disputes = dispute_metrics.run_all(use_cache=use_cache)
    t = llm.tally()
    stamp = {"mode": actual_mode(t["answered"]), "answered": t["answered"], "failed": t["failed"],
             "configured_first": llm.provider_order()[0],
             "date": date.today().isoformat(), "days": days, "disputes": disputes,
             "data_source": "synthetic"}
    db.set_meta("last_eval", json.dumps(stamp))
    return {"days": days, "disputes": disputes, "stamp": stamp}


def actual_mode(answered: dict) -> str:
    """The mode that really produced the results: one provider, "mixed", or no LLM calls."""
    used = [p for p, n in answered.items() if n]
    if not used:
        return "none"
    return used[0] if len(used) == 1 else "mixed"


_NAMES = {"offline": "offline stand-in, no LLM", "gemini": "Gemini", "groq": "Groq",
          "none": "rules only, no LLM calls"}


def last_stamp() -> dict | None:
    raw = db.get_meta("last_eval")
    return json.loads(raw) if raw else None


def stamp_text(stamp: dict | None = None) -> str:
    stamp = stamp or last_stamp()
    if not stamp:
        return "not measured yet"
    if "answered" not in stamp:  # stamp written before this fix: trust what was used, not configured
        used = stamp.get("providers_used") or []
        stamp = {**stamp, "answered": {p: 1 for p in used}, "failed": {}}
        stamp["mode"] = actual_mode(stamp["answered"])
    answered = stamp["answered"]
    if stamp["mode"] == "mixed":
        mode = "mixed: " + ", ".join(f"{_NAMES.get(p, p)} {n}" for p, n in sorted(answered.items()))
    else:
        mode = _NAMES.get(stamp["mode"], stamp["mode"])
    text = f"{mode} · {stamp['date']} · synthetic data"
    failed = {p: n for p, n in stamp.get("failed", {}).items() if n}
    if failed:
        text += " · fell back after failed calls: " + ", ".join(f"{p} {n}" for p, n in sorted(failed.items()))
    return text


if __name__ == "__main__":
    if not db.exists():
        generate_data.generate()
    run_all()
    print(f"Measured: {stamp_text()}\n")
    print("FEATURE 1: PAYOUT EXPLANATION")
    payout_metrics.print_report(payout_metrics.compute_metrics())
    print()
    print("FEATURE 2: CHARGEBACK DISPUTE RESOLUTION (main suite)")
    dispute_metrics.print_report(dispute_metrics.compute_metrics())
    print()
    print("ADVERSARIAL SUITE (per case type; counts, not a blended rate)")
    dispute_metrics.print_adversarial(dispute_metrics.adversarial_report())
