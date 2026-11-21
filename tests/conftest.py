import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402
import db  # noqa: E402
import generate_data  # noqa: E402


@pytest.fixture()
def fresh_db(tmp_path, monkeypatch):
    """A new synthetic database per test, with the LLM forced to the offline stand-in."""
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(config, "LLM_MODE", "offline")
    monkeypatch.setattr(config, "AMOUNT_LIMIT", 5000.0)
    monkeypatch.setattr(config, "DEADLINE_SLACK_HOURS", 48.0)
    monkeypatch.setattr(config, "DRY_RUN", True)
    generate_data.generate(seed=11, error_rate=0.3, n_random=60)
    return tmp_path / "test.db"


@pytest.fixture()
def day_with():
    """Find a merchant day by its planted error label."""
    def find(label: str, merchant_id: str | None = None) -> tuple[str, str]:
        sql = "SELECT merchant_id, settlement_date FROM day_labels WHERE gt_anomaly=?"
        params: tuple = (label,)
        if merchant_id:
            sql += " AND merchant_id=?"
            params += (merchant_id,)
        row = db.one(sql + " ORDER BY merchant_id, settlement_date", params)
        assert row, f"no day labelled {label}"
        return row["merchant_id"], row["settlement_date"]
    return find
