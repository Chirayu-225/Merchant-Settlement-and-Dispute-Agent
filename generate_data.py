"""Synthetic data generator for both features.

Builds two weeks of payouts for six shops (with planted errors), one dispute case for every
chargeback in those payouts, and a queue of standalone disputes from other merchants.

Run:  python generate_data.py
All data is made up. None of it is Paytm data.
"""
import random

import db
from disputes import data as dispute_data
from payouts import data as payout_data


def generate(seed: int = 7, error_rate: float = 0.2, n_random: int = 40) -> dict:
    """Rebuild the database. Returns counts."""
    rng = random.Random(seed)
    db.reset_schema()
    with db.connect() as conn:
        conn.execute("DELETE FROM meta WHERE key='last_eval'")
        conn.execute("INSERT OR REPLACE INTO meta VALUES ('reference_now', ?)",
                     (dispute_data.REFERENCE_NOW.isoformat(timespec="seconds"),))
        payout_data.add_shops(conn, rng, error_rate)
        dispute_data.add_standalone_cases(conn, rng, n_random)
        dispute_data.add_adversarial_cases(conn, rng)

        def count(sql: str) -> int:
            return conn.execute(sql).fetchone()[0]
        counts = {
            "shops": count("SELECT COUNT(*) FROM merchants"),
            "days": count("SELECT COUNT(*) FROM day_labels"),
            "days_with_planted_errors": count(
                "SELECT COUNT(*) FROM day_labels WHERE gt_anomaly<>'none'"),
            "disputes": count("SELECT COUNT(*) FROM disputes WHERE suite='main'"),
            "adversarial_disputes": count("SELECT COUNT(*) FROM disputes WHERE suite='adversarial'"),
            "disputes_linked_to_a_payout": count(
                "SELECT COUNT(*) FROM disputes WHERE chargeback_id IS NOT NULL"),
        }
    return counts


if __name__ == "__main__":
    c = generate()
    print(f"Generated {c['days']} merchant days for {c['shops']} shops, "
          f"{c['days_with_planted_errors']} with a planted error.")
    print(f"Generated {c['disputes']} disputes, {c['disputes_linked_to_a_payout']} of them "
          f"linked to a chargeback in a payout, plus {c['adversarial_disputes']} adversarial cases.")
