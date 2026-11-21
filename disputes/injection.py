"""Rule check for untrusted text (the customer statement in a chargeback notice).

This is a pattern scan. It catches known phrasings, not every possible attack, which is
why it is only one of several layers: flagged text is never sent to the LLM, the LLM can
never approve a submission, and the gate is code.
"""
import re

PATTERNS = [
    (r"\b(ignore|disregard|forget|bypass|override)\b.{0,40}\b(rules?|instructions?|prompts?|checks?|polic(y|ies)|evidence)\b",
     "asks the reader to ignore rules or instructions"),
    (r"\b(system|assistant|developer)\s*:", "imitates a system or assistant message"),
    (r"\byou are now\b|\bact as\b|\bpretend to be\b", "tries to assign a new role"),
    (r"\bnew instructions?\b|\bprevious instructions?\b", "refers to instructions"),
    (r"</?[a-zA-Z_][a-zA-Z0-9_\-]*>", "contains markup tags"),
    (r"\b(approve|accept|mark|close|submit)\b.{0,40}\b(refund|chargeback|dispute|acceptance)\b",
     "tells the reader what decision to make"),
    (r"\bwithout (any )?(checks?|verification|review)\b", "asks to skip checks"),
    (r"\b(prompt|jailbreak)\b", "mentions prompts"),
]

MAX_LENGTH = 1200


def scan(text: str) -> list[str]:
    """Return a list of findings. Empty list = nothing suspicious found."""
    findings = []
    if not text:
        return findings
    for pattern, reason in PATTERNS:
        if re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL):
            findings.append(reason)
    if len(text) > MAX_LENGTH:
        findings.append(f"statement is unusually long ({len(text)} characters)")
    if re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", text):
        findings.append("contains control characters")
    if re.search(r"[A-Za-z0-9+/]{120,}={0,2}", text):
        findings.append("contains a long encoded-looking block")
    return findings
