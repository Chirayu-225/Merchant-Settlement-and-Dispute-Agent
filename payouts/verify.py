"""Checks an explanation before a merchant sees it.

Every number in the text must be a number the reconciliation engine produced, every
record ID must be a real record for that day, and every chargeback dispute must be named. A model cannot slip in its own arithmetic.
"""
import re

RECORD_ID = re.compile(r"\b(?:TXN|RFD|CBK|LND|STL|CRD|DSP)-[A-Z0-9\-]+\b")
ISO_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


def allowed_numbers(breakdown: dict, anomalies: list[dict], amount_owed: float,
                    handoffs: list[dict] | None = None) -> set[float]:
    values = {breakdown["gross_sales"], breakdown["expected_net"], breakdown["received"],
              breakdown["difference_from_sales"], amount_owed,
              float(breakdown["txn_count"]), float(breakdown["failed_txn_count"]),
              float(len(anomalies))}
    for item in breakdown["deductions"]:
        values.add(item["amount"])
        values.add(float(len(item["record_ids"])))
    if breakdown["settlement"]:
        values.add(breakdown["settlement"]["net_amount"])
    for anomaly in anomalies:
        values.add(anomaly["impact"])
        values.update(anomaly.get("figures", []))
    for handoff in handoffs or []:
        values.add(handoff["amount"])
    values.add(float(len(handoffs or [])))
    year, month, day = breakdown["date"].split("-")
    values.update({float(year), float(month), float(day)})
    return {round(v, 2) for v in values}


def known_ids(breakdown: dict, anomalies: list[dict],
              handoffs: list[dict] | None = None) -> set[str]:
    ids = set()
    for handoff in handoffs or []:
        ids.update({handoff["chargeback_id"], handoff["dispute_id"]})
    for item in breakdown["deductions"]:
        ids.update(item["record_ids"])
    if breakdown["settlement"]:
        ids.add(breakdown["settlement"]["settlement_id"])
    if breakdown["bank_credit"]:
        ids.add(breakdown["bank_credit"]["credit_id"])
    for anomaly in anomalies:
        ids.update(anomaly["record_ids"])
    return ids


def verify_explanation(text: str, breakdown: dict, anomalies: list[dict], amount_owed: float,
                       handoffs: list[dict] | None = None) -> tuple[bool, list[str]]:
    """Return (ok, problems)."""
    problems = []
    if not text or len(text.strip()) < 40:
        return False, ["The explanation is empty or too short."]

    ids = known_ids(breakdown, anomalies, handoffs)
    for record_id in sorted(set(RECORD_ID.findall(text))):
        if record_id not in ids:
            problems.append(f"The text mentions {record_id}, which is not a record for this day.")

    stripped = ISO_DATE.sub(" ", RECORD_ID.sub(" ", text))
    allowed = allowed_numbers(breakdown, anomalies, amount_owed, handoffs)
    allowed_whole = {float(round(v)) for v in allowed}
    for raw in NUMBER.findall(stripped):
        try:
            value = round(float(raw.replace(",", "")), 2)
        except ValueError:
            continue
        if value in allowed or ("." not in raw and value in allowed_whole):
            continue
        problems.append(f"The number {raw} does not come from the reconciliation.")

    for anomaly in anomalies:
        if not any(record_id in text for record_id in anomaly["record_ids"]) and anomaly["record_ids"]:
            problems.append(f"The text does not cite a record for the problem '{anomaly['type']}'.")
    for handoff in handoffs or []:
        if handoff["dispute_id"] not in text:
            problems.append(f"The text does not mention dispute {handoff['dispute_id']}.")
    return (len(problems) == 0, problems)
