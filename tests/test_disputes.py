import json

import config
import db
from disputes import graph, llm_steps, tools
from disputes import metrics as dispute_metrics


def _failed(state):
    return [check["name"] for check in state["checks"] if check["passed"] is False]


def test_demo_1_clean_case_is_auto_submitted(fresh_db):
    state = graph.process_dispute("DSP-DEMO-1")
    assert state["decision"] == "auto_submit"
    assert all(check["passed"] is True for check in state["checks"])
    assert len(state["checks"]) == 7
    submission = db.one("SELECT * FROM submissions WHERE dispute_id='DSP-DEMO-1'")
    assert submission and submission["dry_run"] == 1


def test_demo_2_missing_evidence_escalates(fresh_db):
    state = graph.process_dispute("DSP-DEMO-2")
    assert state["decision"] == "escalate"
    assert "evidence_complete" in _failed(state)
    assert state.get("draft") is None
    note = db.one("SELECT handoff_note FROM escalations WHERE dispute_id='DSP-DEMO-2'")
    assert "Evidence checklist" in note["handoff_note"]


def test_demo_3_conflicting_records_escalate(fresh_db):
    state = graph.process_dispute("DSP-DEMO-3")
    assert state["decision"] == "escalate"
    assert "records_consistent" in _failed(state)


def test_demo_4_injection_escalates_without_calling_llm(fresh_db):
    state = graph.process_dispute("DSP-DEMO-4")
    assert state["decision"] == "escalate"
    assert "untrusted_text_clean" in _failed(state)
    assert state["llm_calls"] == []
    assert state.get("assessment") is None
    assert db.one("SELECT * FROM submissions WHERE dispute_id='DSP-DEMO-4'") is None


class _BadCitations:
    """An LLM stand-in that always cites a record that does not exist."""
    assess = staticmethod(llm_steps.assess)

    @staticmethod
    def draft(parsed, bundle, feedback=None, use_cache=True):
        return ({"response_text": "The parcel was delivered [DLV-00000].",
                 "claims": [{"record_id": "DLV-00000", "field": "status", "value": "DELIVERED"}]},
                {"task": "draft", "provider": "fake", "cached": False, "errors": []})


def test_hallucinated_citation_is_retried_then_escalated(fresh_db):
    state = graph.process_dispute("DSP-DEMO-1", steps=_BadCitations)
    assert state["decision"] == "escalate"
    assert "citations_valid" in _failed(state)
    assert state["draft_attempts"] == config.MAX_DRAFT_RETRIES + 1
    assert db.one("SELECT * FROM submissions WHERE dispute_id='DSP-DEMO-1'") is None


class _Veto:
    draft = staticmethod(llm_steps.draft)

    @staticmethod
    def assess(parsed, bundle, checklist, contradictions, use_cache=True):
        return ({"recommendation": "review", "veto": True, "veto_reason": "Something looks off.",
                 "contradictions": [], "reasoning": "Unsure."},
                {"task": "assess", "provider": "fake", "cached": False, "errors": []})


def test_llm_veto_blocks_submission(fresh_db):
    state = graph.process_dispute("DSP-DEMO-1", steps=_Veto)
    assert state["decision"] == "escalate"
    assert _failed(state) == ["llm_no_veto"]
    assert state.get("draft") is None


class _EagerApprover:
    """An LLM stand-in that says 'contest, no veto' for everything."""
    draft = staticmethod(llm_steps.draft)

    @staticmethod
    def assess(parsed, bundle, checklist, contradictions, use_cache=True):
        return ({"recommendation": "contest", "veto": False, "veto_reason": "",
                 "contradictions": [], "reasoning": "Looks fine."},
                {"task": "assess", "provider": "fake", "cached": False, "errors": []})


def test_llm_cannot_approve_a_case_the_rules_reject(fresh_db):
    for dispute_id in ("DSP-DEMO-2", "DSP-DEMO-3"):
        state = graph.process_dispute(dispute_id, steps=_EagerApprover)
        assert state["decision"] == "escalate"


def test_amount_limit_and_deadline_are_enforced(fresh_db, monkeypatch):
    monkeypatch.setattr(config, "AMOUNT_LIMIT", 1.0)
    state = graph.process_dispute("DSP-DEMO-1")
    assert state["decision"] == "escalate" and "amount_under_limit" in _failed(state)

    monkeypatch.setattr(config, "AMOUNT_LIMIT", 5000.0)
    monkeypatch.setattr(config, "DEADLINE_SLACK_HOURS", 100000.0)
    state = graph.process_dispute("DSP-DEMO-1")
    assert state["decision"] == "escalate" and "deadline_slack" in _failed(state)


def test_unparseable_notice_escalates(fresh_db):
    db.execute("UPDATE disputes SET notice_text='garbled text' WHERE dispute_id='DSP-DEMO-1'")
    state = graph.process_dispute("DSP-DEMO-1")
    assert state["decision"] == "escalate"
    assert state["llm_calls"] == []


def test_real_submission_is_idempotent(fresh_db):
    first = graph.process_dispute("DSP-DEMO-1", dry_run=False)
    assert first["outcome"]["status"] == "SUBMITTED"
    second = graph.process_dispute("DSP-DEMO-1", dry_run=False)
    assert second["outcome"]["status"] == "ALREADY_SUBMITTED"
    assert second["outcome"]["duplicate"] is True
    again = tools.submit_dispute_response("DSP-DEMO-1", "different text", dry_run=False)
    assert again["duplicate"] is True
    stored = db.one("SELECT COUNT(*) AS n FROM submissions WHERE dispute_id='DSP-DEMO-1'")
    assert stored["n"] == 1


def test_every_step_is_audited(fresh_db):
    graph.process_dispute("DSP-DEMO-1")
    steps = [row["step"] for row in db.many(
        "SELECT step FROM audit_log WHERE feature='dispute' AND ref='DSP-DEMO-1' ORDER BY id")]
    assert steps == ["ingest", "retrieve", "assess", "draft", "verify", "gate", "submit"]


def test_full_evaluation_has_no_wrong_auto_submissions(fresh_db):
    processed = dispute_metrics.run_all()
    metrics = dispute_metrics.compute_metrics()
    main = db.one("SELECT COUNT(*) AS n FROM disputes WHERE suite='main'")["n"]
    assert metrics["processed"] == main >= 64
    assert processed == main + db.one("SELECT COUNT(*) AS n FROM disputes WHERE suite='adversarial'")["n"]
    assert metrics["wrong_auto_submissions"] == 0
    assert metrics["escalation_precision"] == 1.0
    assert metrics["escalation_recall"] == 1.0
    assert metrics["auto_submitted"] > 0 and metrics["escalated"] > 0
    json.dumps(metrics)
