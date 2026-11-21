"""The saved measurement is used only while it is still true."""
import json
import shutil
import sqlite3

import config
import snapshot


def test_the_committed_snapshot_is_fresh():
    """Fails when rules, data or thresholds changed without rebuilding. Fix: python snapshot.py"""
    assert snapshot.is_fresh(), "snapshot/agent.db is missing or stale. Run: python snapshot.py"


def test_restore_gives_an_offline_measurement_with_every_result(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "restored.db")
    assert snapshot.restore() is True
    conn = sqlite3.connect(str(tmp_path / "restored.db"))
    stamp = json.loads(conn.execute("SELECT value FROM meta WHERE key='last_eval'").fetchone()[0])
    assert stamp["mode"] == "offline" and stamp["failed"] == {}
    assert conn.execute("SELECT COUNT(*) FROM payout_results").fetchone()[0] == stamp["days"] == 84
    assert conn.execute("SELECT COUNT(*) FROM dispute_results").fetchone()[0] == stamp["disputes"] == 89
    assert conn.execute("SELECT COUNT(*) FROM feedback").fetchone()[0] == 0


def test_a_changed_source_makes_the_snapshot_stale_and_unused(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "restored.db")
    monkeypatch.setattr(snapshot, "source_hash", lambda: "a-different-code-fingerprint")
    assert snapshot.is_fresh() is False
    assert snapshot.restore() is False
    assert not (tmp_path / "restored.db").exists()


def test_a_changed_threshold_makes_the_snapshot_stale(monkeypatch):
    monkeypatch.setattr(config, "AMOUNT_LIMIT", config.AMOUNT_LIMIT + 1)
    assert snapshot.is_fresh() is False


def test_fingerprint_ignores_windows_line_endings(tmp_path, monkeypatch):
    """A Windows checkout (CRLF) and a Linux checkout (LF) must agree."""
    copy = tmp_path / "app"
    shutil.copytree(snapshot.ROOT, copy, ignore=shutil.ignore_patterns(
        "__pycache__", "paytm", "backup", "data", "_moved", ".git"))
    for path in list(copy.glob("*.py")) + list(copy.glob("*/*.py")):
        path.write_bytes(path.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
    original = snapshot.source_hash()
    monkeypatch.setattr(snapshot, "ROOT", copy)
    assert snapshot.source_hash() == original
