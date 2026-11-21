import pytest

import compare_modes
import config


def test_comparing_offline_with_itself_finds_no_differences(fresh_db, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "BASE_DIR", tmp_path)
    first = compare_modes.collect("offline")
    second = compare_modes.collect("offline")
    result = compare_modes.compare(first, second)
    assert result["decisions_that_differ"] == 0 and result["recommendation_differences"] == 0
    assert result["cases"] >= 89


def test_a_mode_without_a_key_refuses_to_run(fresh_db, monkeypatch):
    monkeypatch.setattr(config, "GEMINI_API_KEY", "")
    with pytest.raises(SystemExit):
        compare_modes.collect("gemini")
