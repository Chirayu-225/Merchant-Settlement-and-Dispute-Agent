"""Citation check: every claim in a draft must point at a real record and match its value."""
import re

CITATION = re.compile(r"\[((?:ORD|TXN|DLV)-[A-Za-z0-9\-]+)\]")

_TRUE = {"1", "true", "yes", "verified"}
_FALSE = {"0", "false", "no"}


def _same(record_value, claimed_value) -> bool:
    a, b = str(record_value).strip().casefold(), str(claimed_value).strip().casefold()
    if a == b:
        return True
    if (a in _TRUE and b in _TRUE) or (a in _FALSE and b in _FALSE):
        return True
    try:
        return abs(float(a.replace(",", "")) - float(b.replace(",", "").replace("inr", ""))) < 0.01
    except ValueError:
        return False


def verify_draft(draft: dict, records: dict) -> tuple[bool, list[str]]:
    """Return (ok, problems). `records` maps record ID to the record."""
    problems = []
    text = draft.get("response_text", "")
    claims = draft.get("claims", [])

    if not text.strip():
        problems.append("The draft has no response text.")
    if not claims:
        problems.append("The draft lists no claims.")

    cited = CITATION.findall(text)
    if not cited:
        problems.append("The response text cites no record IDs in square brackets.")
    for record_id in sorted(set(cited)):
        if record_id not in records:
            problems.append(f"The text cites {record_id}, which is not in the evidence.")

    for claim in claims:
        record_id, field = claim.get("record_id"), claim.get("field")
        if record_id not in records:
            problems.append(f"Claim cites {record_id}, which is not in the evidence.")
            continue
        if field not in records[record_id]:
            problems.append(f"Claim cites field '{field}', which {record_id} does not have.")
            continue
        if not _same(records[record_id][field], claim.get("value")):
            problems.append(f"Claim says {record_id}.{field} is '{claim.get('value')}', but the "
                            f"record says '{records[record_id][field]}'.")
    return (len(problems) == 0, problems)
