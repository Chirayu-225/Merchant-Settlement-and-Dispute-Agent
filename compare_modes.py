"""Run the same synthetic cases through two LLM modes and list where the answers differ.

Usage:
    python compare_modes.py                  offline versus whichever keys are in .env
    python compare_modes.py offline offline  sanity check: must report zero differences

Each mode gets its own database (data/compare_<mode>.db), the same seed, and no cache, so
nothing is shared except the cases. Results go to data/mode_comparison.json, which the app's
Needs testing tab reads. This is the only way to learn whether Gemini behaves differently
from the offline stand-in, which is what the adversarial results currently cannot say.
"""
import json
import sys
from datetime import date
from pathlib import Path

import config
import db
import evaluate
import generate_data
from disputes import metrics as dispute_metrics
from payouts import metrics as payout_metrics

OUT = config.BASE_DIR / "data" / "mode_comparison.json"


def _have_keys(mode: str) -> bool:
    return {"offline": True, "gemini": bool(config.GEMINI_API_KEY),
            "groq": bool(config.GROQ_API_KEY)}.get(mode, False)


def collect(mode: str) -> dict:
    if not _have_keys(mode):
        raise SystemExit(f"No API key for mode '{mode}'. Set it in .env first.")
    config.LLM_MODE = mode
    config.DB_PATH = Path(config.BASE_DIR / "data" / f"compare_{mode}.db")
    generate_data.generate()
    evaluate.run_all(use_cache=False)
    rows = db.many("SELECT d.dispute_id, d.suite, d.scenario, r.decision, r.assessment, r.llm_providers "
                   "FROM disputes d JOIN dispute_results r ON r.dispute_id = d.dispute_id "
                   "ORDER BY d.dispute_id")
    payouts = payout_metrics.compute_metrics()
    return {
        "mode": mode, "date": date.today().isoformat(),
        "decisions": {r["dispute_id"]: r["decision"] for r in rows},
        "recommendations": {r["dispute_id"]: (json.loads(r["assessment"] or "null") or {}).get("recommendation")
                            for r in rows},
        "scenario": {r["dispute_id"]: r["scenario"] for r in rows},
        "adversarial": dispute_metrics.adversarial_report(),
        "main": dispute_metrics.compute_metrics(),
        "payout_llm_texts": payouts["explanations_from_llm"],
        "payout_llm_texts_rejected": payouts["llm_text_rejected_by_number_check"],
    }


def compare(a: dict, b: dict) -> dict:
    differing = [d for d in a["decisions"] if a["decisions"][d] != b["decisions"].get(d)]
    by_type: dict[str, int] = {}
    for dispute_id in differing:
        by_type[a["scenario"][dispute_id]] = by_type.get(a["scenario"][dispute_id], 0) + 1
    return {"modes": [a["mode"], b["mode"]], "date": date.today().isoformat(),
            "cases": len(a["decisions"]), "decisions_that_differ": len(differing),
            "differing_ids": differing, "differing_by_scenario": by_type,
            "recommendation_differences": sum(1 for d in a["recommendations"]
                                              if a["recommendations"][d] != b["recommendations"].get(d)),
            "adversarial": {a["mode"]: [{k: r[k] for k in ("type", "cases", "auto_submitted", "escalated")}
                                        for r in a["adversarial"]],
                            b["mode"]: [{k: r[k] for k in ("type", "cases", "auto_submitted", "escalated")}
                                        for r in b["adversarial"]]},
            "payout_llm_texts": {a["mode"]: a["payout_llm_texts"], b["mode"]: b["payout_llm_texts"]},
            "payout_llm_texts_rejected": {a["mode"]: a["payout_llm_texts_rejected"],
                                          b["mode"]: b["payout_llm_texts_rejected"]}}


def default_modes() -> tuple[str, str]:
    other = "gemini" if config.GEMINI_API_KEY else ("groq" if config.GROQ_API_KEY else None)
    if other is None:
        raise SystemExit("No GEMINI_API_KEY or GROQ_API_KEY in .env. Nothing to compare offline against.")
    return "offline", other


if __name__ == "__main__":
    first, second = (sys.argv[1], sys.argv[2]) if len(sys.argv) == 3 else default_modes()
    result = compare(collect(first), collect(second))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=2))
    print(f"{result['cases']} cases. Decisions that differ between {first} and {second}: "
          f"{result['decisions_that_differ']}")
    for scenario, count in sorted(result["differing_by_scenario"].items()):
        print(f"  {scenario}: {count}")
    print(f"Payout LLM texts rejected by the number check: {result['payout_llm_texts_rejected']}")
    print(f"Wrote {OUT}")
