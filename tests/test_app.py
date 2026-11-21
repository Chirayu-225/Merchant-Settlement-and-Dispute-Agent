"""The app boots from a fresh folder with no keys, shows four tabs, and the main journeys work."""
from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parent.parent / "app.py")


def _fresh_app(tmp_path, monkeypatch):
    for key in ("GEMINI_API_KEY", "GROQ_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("LLM_MODE", "auto")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "boot.db"))
    import config
    monkeypatch.setattr(config, "GEMINI_API_KEY", "")
    monkeypatch.setattr(config, "GROQ_API_KEY", "")
    monkeypatch.setattr(config, "LLM_MODE", "auto")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "boot.db")
    return AppTest.from_file(APP, default_timeout=300)


def _all_html(at) -> str:
    return " ".join(e.proto.body for e in at.get("html"))


def test_no_keys_boot_shows_four_tabs_and_all_three_labels(tmp_path, monkeypatch):
    at = _fresh_app(tmp_path, monkeypatch).run()
    assert not at.exception
    assert [t.label for t in at.tabs] == ["Payout check", "Disputes", "Results", "Audit log"]
    text = _all_html(at)
    assert "MEASURED" in text and "offline stand-in" in text
    assert "ASSUMPTION" in text and "NEEDS TESTING" in text
    assert "gemini" not in text.split("MEASURED", 1)[1][:80].lower()


def test_developer_settings_stay_in_the_sidebar(tmp_path, monkeypatch):
    at = _fresh_app(tmp_path, monkeypatch).run()
    assert [c.label for c in at.sidebar.checkbox] == ["Dry run", "Reuse saved AI answers"]
    assert {b.label for b in at.sidebar.button} == {"Reset demo data", "Run evaluation"}


def test_payout_journey_feedback_and_ticket(tmp_path, monkeypatch):
    at = _fresh_app(tmp_path, monkeypatch).run()
    import db
    error_day = db.one("SELECT settlement_date FROM day_labels WHERE merchant_id='MID-DEMO' "
                       "AND gt_anomaly != 'none' ORDER BY settlement_date")["settlement_date"]
    [s for s in at.selectbox if s.label == "Day"][0].select(error_day).run()
    [b for b in at.button if b.label == "Check this day"][0].click().run()
    assert not at.exception
    assert "may be owed to you" in _all_html(at)
    [b for b in at.button if b.label == "No"][0].click().run()
    [b for b in at.button if b.label == "Send"][0].click().run()
    [b for b in at.button if b.label == "Raise this ticket"][0].click().run()
    assert not at.exception
    assert db.one("SELECT COUNT(*) AS n FROM feedback")["n"] == 1
    assert db.one("SELECT COUNT(*) AS n FROM events WHERE event='ticket_raised'")["n"] == 1


def test_pending_day_does_not_look_like_lost_money(tmp_path, monkeypatch):
    at = _fresh_app(tmp_path, monkeypatch).run()
    import db
    day = db.one("SELECT settlement_date FROM settlements WHERE merchant_id='MID-DEMO' "
                 "AND status='PENDING'")
    if day:
        [s for s in at.selectbox if s.label == "Day"][0].select(day["settlement_date"]).run()
        assert "Not settled yet. Nothing is wrong." in _all_html(at)


def test_dispute_detail_shows_seven_checks_in_words(tmp_path, monkeypatch):
    at = _fresh_app(tmp_path, monkeypatch).run()
    text = _all_html(at)
    assert "Goods not received" in text or "Unauthorised payment" in text
    assert "GNR</td>" not in text
    assert text.count('class="check"') >= 7


def test_results_report_trick_cases_per_type(tmp_path, monkeypatch):
    at = _fresh_app(tmp_path, monkeypatch).run()
    frames = [d.value for d in at.dataframe]
    trick = next(f for f in frames if "Situation" in f.columns)
    assert len(trick) == 8 and set(trick["Type"]) == {"Gap", "Control"}


def test_audit_log_lists_steps(tmp_path, monkeypatch):
    at = _fresh_app(tmp_path, monkeypatch).run()
    assert "steps logged" in " ".join(c.value for c in at.caption)
