"""The Measured label must name the mode that actually produced the numbers."""
import config
import evaluate
import llm


def _boom(*_args, **_kwargs):
    raise RuntimeError("simulated 404")


def test_stamp_names_the_provider_that_answered_not_the_one_configured(fresh_db, monkeypatch):
    # Gemini is configured first but every call fails, so every answer is the offline stand-in.
    monkeypatch.setattr(config, "LLM_MODE", "gemini")
    monkeypatch.setattr(llm, "_call_gemini", _boom)
    stamp = evaluate.run_all(use_cache=False)["stamp"]
    assert stamp["configured_first"] == "gemini"
    assert stamp["mode"] == "offline"
    assert stamp["failed"].get("gemini", 0) > 0
    text = evaluate.stamp_text(stamp)
    assert text.startswith("offline stand-in")
    assert "fell back after failed calls: gemini" in text


def test_clean_offline_run_has_no_fallback_note(fresh_db):
    stamp = evaluate.run_all(use_cache=False)["stamp"]
    assert stamp["mode"] == "offline" and stamp["failed"] == {}
    assert "fell back" not in evaluate.stamp_text(stamp)


def test_old_stamp_without_tally_is_read_from_providers_used():
    old = {"mode": "gemini", "providers_used": ["offline"], "date": "2026-11-20"}
    assert evaluate.stamp_text(old).startswith("offline stand-in")


def test_mixed_and_no_call_modes():
    assert evaluate.actual_mode({"gemini": 3, "offline": 2}) == "mixed"
    assert evaluate.actual_mode({}) == "none"
