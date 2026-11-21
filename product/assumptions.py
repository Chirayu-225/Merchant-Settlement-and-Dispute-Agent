"""Every assumption in the project, in one place, each with where it came from.

A figure shown anywhere in the app is one of three things:
  Measured       computed by running the code on the synthetic data (shows mode and date)
  Assumption     an input defined in THIS file, with a source or the word "guess"
  Needs testing  nothing can honestly be said yet, so no number is shown

Low / base / high were fixed before any result was computed and were not tuned to make a
chart look better. Where the source is "guess", that is exactly what it is.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Assumption:
    key: str
    label: str
    unit: str
    low: float
    base: float
    high: float
    source: str          # a real source, or the word "guess"
    note: str = ""
    needs_testing: bool = True


ASSUMPTIONS = {a.key: a for a in [
    Assumption("disputes_per_day", "Chargeback disputes arriving per day", "disputes/day",
               20, 60, 150, "guess",
               "Replace with the support team's real intake. This scales every per-day figure."),
    Assumption("win_rate", "Share of contested disputes that are won", "share",
               0.30, 0.50, 0.70, "guess",
               "Real outcomes arrive weeks after submission, so this cannot be measured here."),
    Assumption("minutes_per_manual_case", "Support minutes to handle one dispute by hand", "minutes",
               10, 15, 25, "guess",
               "Used only for hours saved on cases the agent closes with no human."),
    Assumption("support_capacity_per_day", "Escalations the support team clears per day", "cases/day",
               8, 16, 32, "guess",
               "Drives deadline misses. Escalations are worked in deadline order."),
]}

# Policy choices, not facts. They are set in .env.
POLICY_DEFAULTS = {
    "amount_limit": "INR 5,000. A demo choice, not a Paytm rule.",
    "deadline_slack_hours": "48 hours. A demo choice, not a Paytm rule.",
}

# Properties of the synthetic data, not of the world.
SYNTHETIC_DATA_NOTES = [
    "Scenario mix (40% clean, 15% missing evidence, and so on) is chosen by the generator.",
    "Fee rates (UPI 0%, card 1.8%, wallet 1.5%, GST 18%) are demo values, not Paytm pricing.",
    "Ground-truth labels come from the scenario that built each case.",
]


def get(key: str) -> Assumption:
    return ASSUMPTIONS[key]


def table() -> list[dict]:
    return [{"Assumption": a.label, "Low": a.low, "Base": a.base, "High": a.high,
             "Unit": a.unit, "Source": a.source, "Note": a.note} for a in ASSUMPTIONS.values()]
