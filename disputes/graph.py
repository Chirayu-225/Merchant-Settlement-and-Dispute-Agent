"""The dispute pipeline as a LangGraph graph.

ingest -> retrieve -> assess -> draft -> verify -> gate -> submit | escalate

Branches:
- a notice that cannot be parsed goes straight to the gate (and escalates)
- a suspicious customer statement skips the LLM entirely
- a failed rule check or an LLM veto skips drafting
- a draft that fails the citation check is retried once, then escalates
"""
import json
import time
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

import config
import db
from disputes import gate, injection, llm_steps, rules, tools, verify
from product import events


class State(TypedDict, total=False):
    dispute_id: str
    notice_text: str
    dry_run: bool
    use_cache: bool
    parsed: dict
    parse_error: str
    bundle: dict
    checklist: list
    contradictions: list
    injection_findings: list
    assessment: dict
    draft: dict
    draft_attempts: int
    verify_ok: bool
    verify_problems: list
    checks: list
    decision: str
    outcome: dict
    llm_calls: list


def audit(dispute_id: str, step: str, detail: dict) -> None:
    db.audit("dispute", dispute_id, step, detail)


def build_handoff_note(state: dict) -> str:
    """The note a human support agent reads when a case is escalated."""
    parsed = state.get("parsed")
    checks = state["checks"]
    lines = [f"HANDOFF NOTE - {state['dispute_id']}"]
    if parsed:
        label = rules.REASON_CODES.get(parsed["reason_code"], {}).get("label", "unknown reason")
        lines.append(f"Order {parsed['order_id']} | {parsed['reason_code']} ({label}) | "
                     f"INR {parsed['amount']:,.2f} | respond by {parsed['respond_by']}")
    lines.append("")
    lines.append("Why this was escalated:")
    for check in gate.failed(checks):
        lines.append(f"  - {check['label']}: {check['detail']}")
    passed = [check["label"] for check in checks if check["passed"] is True]
    skipped = [check["label"] for check in checks if check["passed"] is None]
    lines.append("")
    lines.append("What was verified: " + (", ".join(passed) if passed else "nothing"))
    if skipped:
        lines.append("Not checked: " + ", ".join(skipped))

    names = {check["name"] for check in gate.failed(checks)}
    assessment = state.get("assessment")
    lines.append("")
    if not parsed:
        action = "Read the notice by hand; the agent could not parse it."
    elif "untrusted_text_clean" in names:
        action = ("Read the customer statement yourself. The agent did not send it to the LLM "
                  "and submitted nothing.")
    elif "evidence_complete" in names:
        action = ("Ask the merchant for the missing evidence. If it cannot be produced before "
                  "the deadline, accept the dispute.")
    elif "records_consistent" in names:
        action = "Resolve the conflicting records before replying."
    elif "deadline_slack" in names:
        action = "Deadline is close. Handle this case first."
    elif "amount_under_limit" in names:
        action = "High-value case. Review the evidence and submit by hand."
    elif "citations_valid" in names:
        action = "The draft could not be verified against the records. Write the reply by hand."
    else:
        action = "Review the LLM's objection, then decide."
    lines.append("Recommended action: " + action)
    if assessment:
        lines.append(f"LLM view: {assessment['recommendation']} - {assessment['reasoning']}")
    return "\n".join(lines)


def build_graph(steps=llm_steps):
    """`steps` supplies assess() and draft(); tests pass a fake to exercise failure paths."""

    def n_ingest(state: State) -> dict:
        try:
            parsed = rules.parse_notice(state["notice_text"])
        except rules.NoticeError as exc:
            audit(state["dispute_id"], "ingest", {"parse_error": str(exc)})
            return {"parse_error": str(exc)}
        findings = injection.scan(parsed["customer_statement"])
        audit(state["dispute_id"], "ingest",
              {"order_id": parsed["order_id"], "reason_code": parsed["reason_code"],
               "amount": parsed["amount"], "respond_by": parsed["respond_by"],
               "injection_findings": findings})
        return {"parsed": parsed, "injection_findings": findings}

    def n_retrieve(state: State) -> dict:
        bundle = tools.collect_evidence(state["parsed"])
        checklist = rules.check_evidence(state["parsed"], bundle)
        contradictions = rules.check_consistency(state["parsed"], bundle)
        audit(state["dispute_id"], "retrieve",
              {"records": sorted(tools.records_by_id(bundle)), "checklist": checklist,
               "contradictions": contradictions})
        return {"bundle": bundle, "checklist": checklist, "contradictions": contradictions}

    def n_assess(state: State) -> dict:
        assessment, meta = steps.assess(state["parsed"], state["bundle"], state["checklist"],
                                        state["contradictions"], state.get("use_cache", True))
        audit(state["dispute_id"], "assess", {"assessment": assessment, "llm": meta})
        return {"assessment": assessment, "llm_calls": state.get("llm_calls", []) + [meta]}

    def n_draft(state: State) -> dict:
        feedback = state.get("verify_problems") if state.get("draft_attempts", 0) else None
        draft, meta = steps.draft(state["parsed"], state["bundle"], feedback,
                                  state.get("use_cache", True))
        attempts = state.get("draft_attempts", 0) + 1
        audit(state["dispute_id"], "draft", {"attempt": attempts, "draft": draft, "llm": meta})
        return {"draft": draft, "draft_attempts": attempts,
                "llm_calls": state.get("llm_calls", []) + [meta]}

    def n_verify(state: State) -> dict:
        ok, problems = verify.verify_draft(state["draft"], tools.records_by_id(state["bundle"]))
        audit(state["dispute_id"], "verify", {"ok": ok, "problems": problems})
        return {"verify_ok": ok, "verify_problems": problems}

    def n_gate(state: State) -> dict:
        checks = gate.evaluate(state, db.now())
        decision = gate.decide(checks)
        audit(state["dispute_id"], "gate", {"decision": decision, "checks": checks})
        return {"checks": checks, "decision": decision}

    def n_submit(state: State) -> dict:
        outcome = tools.submit_dispute_response(state["dispute_id"],
                                                state["draft"]["response_text"],
                                                state.get("dry_run", True))
        status = "DRY_RUN_READY" if outcome["dry_run"] else "AUTO_SUBMITTED"
        db.execute("UPDATE disputes SET status=? WHERE dispute_id=?", (status, state["dispute_id"]))
        db.execute("DELETE FROM escalations WHERE dispute_id=?", (state["dispute_id"],))
        audit(state["dispute_id"], "submit", outcome)
        return {"outcome": outcome}

    def n_escalate(state: State) -> dict:
        note = build_handoff_note(state)
        names = [check["name"] for check in gate.failed(state["checks"])]
        db.execute("INSERT OR REPLACE INTO escalations (dispute_id, failed_checks, handoff_note, "
                   "created_at) VALUES (?,?,?,?)",
                   (state["dispute_id"], json.dumps(names), note,
                    db.now().isoformat(timespec="seconds")))
        db.execute("UPDATE disputes SET status='ESCALATED' WHERE dispute_id=?",
                   (state["dispute_id"],))
        # A dry-run draft from an earlier run is no longer valid; a real submission is kept.
        db.execute("DELETE FROM submissions WHERE dispute_id=? AND dry_run=1",
                   (state["dispute_id"],))
        outcome = {"status": "ESCALATED", "failed_checks": names, "handoff_note": note}
        audit(state["dispute_id"], "escalate", {"failed_checks": names})
        return {"outcome": outcome}

    def after_ingest(state: State) -> str:
        return "gate" if state.get("parse_error") else "retrieve"

    def after_retrieve(state: State) -> str:
        # Suspicious text is never sent to the LLM.
        return "gate" if state.get("injection_findings") else "assess"

    def after_assess(state: State) -> str:
        rules_ok = (all(row["present"] for row in state["checklist"])
                    and not state["contradictions"])
        return "draft" if rules_ok and not state["assessment"]["veto"] else "gate"

    def after_verify(state: State) -> str:
        if state["verify_ok"]:
            return "gate"
        return "draft" if state["draft_attempts"] <= config.MAX_DRAFT_RETRIES else "gate"

    def after_gate(state: State) -> str:
        return "submit" if state["decision"] == "auto_submit" else "escalate"

    graph = StateGraph(State)
    for name, node in [("ingest", n_ingest), ("retrieve", n_retrieve), ("assess", n_assess),
                       ("draft", n_draft), ("verify", n_verify), ("gate", n_gate),
                       ("submit", n_submit), ("escalate", n_escalate)]:
        graph.add_node(name, node)
    graph.add_edge(START, "ingest")
    graph.add_conditional_edges("ingest", after_ingest, {"gate": "gate", "retrieve": "retrieve"})
    graph.add_conditional_edges("retrieve", after_retrieve, {"gate": "gate", "assess": "assess"})
    graph.add_conditional_edges("assess", after_assess, {"draft": "draft", "gate": "gate"})
    graph.add_edge("draft", "verify")
    graph.add_conditional_edges("verify", after_verify, {"gate": "gate", "draft": "draft"})
    graph.add_conditional_edges("gate", after_gate, {"submit": "submit", "escalate": "escalate"})
    graph.add_edge("submit", END)
    graph.add_edge("escalate", END)
    return graph.compile()


def process_dispute(dispute_id: str, dry_run: bool | None = None, use_cache: bool = True,
                    steps=llm_steps) -> dict:
    """Run one dispute through the pipeline and store the result."""
    row = db.one("SELECT * FROM disputes WHERE dispute_id=?", (dispute_id,))
    if not row:
        raise KeyError(f"Unknown dispute {dispute_id}")
    started = time.perf_counter()
    state = build_graph(steps).invoke({
        "dispute_id": dispute_id, "notice_text": row["notice_text"],
        "dry_run": config.DRY_RUN if dry_run is None else dry_run,
        "use_cache": use_cache, "draft_attempts": 0, "llm_calls": [],
    })
    duration = time.perf_counter() - started
    providers = [("cache:" if call["cached"] else "") + call["provider"]
                 for call in state.get("llm_calls", [])]
    db.execute(
        "INSERT OR REPLACE INTO dispute_results (dispute_id, decision, checks, assessment, draft, "
        "llm_providers, duration_seconds, processed_at) VALUES (?,?,?,?,?,?,?,?)",
        (dispute_id, state["decision"], json.dumps(state["checks"]),
         json.dumps(state.get("assessment")), json.dumps(state.get("draft")),
         json.dumps(providers), duration, db.now().isoformat(timespec="seconds")))
    state["duration_seconds"] = duration
    events.log_event("dispute_decided", persona="system", ref=dispute_id,
                     props={"decision": state["decision"]})
    return state
