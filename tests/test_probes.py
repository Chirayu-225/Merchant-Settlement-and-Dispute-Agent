import evaluate
from product import probes


def test_probe_base_text_passes_and_probes_are_run(fresh_db):
    evaluate.run_all()
    result = probes.run_probes()
    assert result["base_text_passes"] is True
    assert result["probes"] >= 12
    assert 0 <= result["false_rejection_rate"] <= 1


def test_ordinary_amount_formats_are_accepted(fresh_db):
    evaluate.run_all()
    accepted = {r["label"] for r in probes.run_probes()["results"] if r["accepted"]}
    assert {"Rs with commas and paise", "rupee symbol", "INR prefix", "no commas"} <= accepted


def test_known_false_rejections_are_documented_not_hidden(fresh_db):
    """Honest sentences the check rejects. If someone fixes the check, update this test."""
    evaluate.run_all()
    rejected = {r["label"] for r in probes.run_probes()["results"] if not r["accepted"]}
    assert "GST rate as a percentage" in rejected
    assert "rounded amount" in rejected
