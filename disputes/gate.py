"""The autonomy gate: seven checks, all code. Auto-submit only if every one passes.

A check's `passed` is True, False, or None (not run because an earlier step stopped the
pipeline). Anything other than True blocks submission.
"""
from datetime import datetime

import config

CHECK_LABELS = {
    "evidence_complete": "Evidence checklist",
    "amount_under_limit": "Amount",
    "deadline_slack": "Deadline slack",
    "records_consistent": "Record consistency",
    "citations_valid": "Citations",
    "untrusted_text_clean": "Untrusted text",
    "llm_no_veto": "LLM veto",
}


def _check(name: str, passed, detail: str) -> dict:
    return {"name": name, "label": CHECK_LABELS[name], "passed": passed, "detail": detail}


def evaluate(state: dict, now: datetime) -> list[dict]:
    parsed = state.get("parsed")
    if not parsed:
        reason = state.get("parse_error", "notice could not be read")
        checks = [_check("evidence_complete", False, f"Notice could not be parsed: {reason}")]
        checks += [_check(name, None, "Not run") for name in list(CHECK_LABELS)[1:]]
        return checks

    checks = []

    checklist = state.get("checklist") or []
    missing = [row["description"] for row in checklist if not row["present"]]
    checks.append(_check("evidence_complete", bool(checklist) and not missing,
                         "All required evidence is present" if checklist and not missing
                         else "Missing: " + "; ".join(missing or ["evidence was not retrieved"])))

    amount = parsed["amount"]
    checks.append(_check("amount_under_limit", amount < config.AMOUNT_LIMIT,
                         f"INR {amount:,.2f} against a limit of INR {config.AMOUNT_LIMIT:,.2f}"))

    hours_left = (datetime.fromisoformat(parsed["respond_by"]) - now).total_seconds() / 3600
    checks.append(_check("deadline_slack", hours_left > config.DEADLINE_SLACK_HOURS,
                         f"{hours_left:.0f} hours left; more than "
                         f"{config.DEADLINE_SLACK_HOURS:.0f} needed to act alone"))

    contradictions = state.get("contradictions") or []
    checks.append(_check("records_consistent", not contradictions,
                         "Records agree with each other and the dispute" if not contradictions
                         else "; ".join(contradictions)))

    if state.get("draft") is None:
        checks.append(_check("citations_valid", None, "Not run: no draft was written"))
    else:
        problems = state.get("verify_problems") or []
        checks.append(_check("citations_valid", bool(state.get("verify_ok")),
                             "Every claim cites a record that exists and matches"
                             if state.get("verify_ok") else "; ".join(problems)))

    findings = state.get("injection_findings") or []
    checks.append(_check("untrusted_text_clean", not findings,
                         "Nothing suspicious in the customer statement" if not findings
                         else "Customer statement " + "; ".join(findings)))

    assessment = state.get("assessment")
    if assessment is None:
        checks.append(_check("llm_no_veto", None, "Not run: the LLM was not called"))
    else:
        checks.append(_check("llm_no_veto", not assessment["veto"],
                             "No objection raised" if not assessment["veto"]
                             else assessment["veto_reason"]))
    return checks


def decide(checks: list[dict]) -> str:
    return "auto_submit" if all(check["passed"] is True for check in checks) else "escalate"


def failed(checks: list[dict]) -> list[dict]:
    return [check for check in checks if check["passed"] is False]
