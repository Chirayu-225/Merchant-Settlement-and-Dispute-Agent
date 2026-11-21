"""LLM gateway: Gemini first, Groq as backup, then an offline stand-in. Responses are cached.

The offline stand-in is rule-based code, not a model. It exists so the pipeline can be
tested and demonstrated with no API key or network.
"""
import hashlib
import json
import re
from collections import Counter

import requests

import config
import db


# Which provider actually answered, and which ones were tried and failed, since the last
# reset. The evaluation stamp is built from this, so a "Measured" label names the mode that
# really produced the numbers, not the mode that was merely configured first.
_answered: Counter = Counter()
_failed: Counter = Counter()


def reset_tally() -> None:
    _answered.clear()
    _failed.clear()


def tally() -> dict:
    return {"answered": dict(_answered), "failed": dict(_failed)}


def provider_order() -> list[str]:
    mode = config.LLM_MODE
    if mode == "offline":
        return ["offline"]
    if mode == "gemini":
        return ["gemini", "offline"]
    if mode == "groq":
        return ["groq", "offline"]
    order = []
    if config.GEMINI_API_KEY:
        order.append("gemini")
    if config.GROQ_API_KEY:
        order.append("groq")
    order.append("offline")
    return order


def provider_status() -> str:
    first = provider_order()[0]
    if first == "gemini":
        return f"Gemini ({config.GEMINI_MODEL})"
    if first == "groq":
        return f"Groq ({config.GROQ_MODEL})"
    return "Offline stand-in (no API key set)"


def _parse_json(text: str) -> dict:
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object in the model response")
    return json.loads(text[start:end + 1])


def _call_gemini(system: str, user: str) -> dict:
    if not config.GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is not set")
    from google import genai
    from google.genai import types
    client = genai.Client(api_key=config.GEMINI_API_KEY)
    response = client.models.generate_content(
        model=config.GEMINI_MODEL,
        contents=user,
        config=types.GenerateContentConfig(
            system_instruction=system, response_mime_type="application/json", temperature=0),
    )
    return _parse_json(response.text)


def _call_groq(system: str, user: str) -> dict:
    if not config.GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY is not set")
    response = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {config.GROQ_API_KEY}"},
        json={"model": config.GROQ_MODEL, "temperature": 0,
              "response_format": {"type": "json_object"},
              "messages": [{"role": "system", "content": system},
                           {"role": "user", "content": user}]},
        timeout=config.LLM_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return _parse_json(response.json()["choices"][0]["message"]["content"])


def call_json(task: str, system: str, user: str, offline_fn, use_cache: bool = True) -> tuple[dict, dict]:
    """Return (parsed JSON, meta). meta says which provider answered and whether it was cached."""
    order = provider_order()
    key = hashlib.sha256(f"{order[0]}|{task}|{system}|{user}".encode("utf-8")).hexdigest()
    if use_cache:
        row = db.one("SELECT provider, response FROM llm_cache WHERE key=?", (key,))
        if row:
            _answered[row["provider"]] += 1
            return json.loads(row["response"]), {"task": task, "provider": row["provider"],
                                                 "cached": True, "errors": []}
    errors = []
    for provider in order:
        try:
            if provider == "gemini":
                result = _call_gemini(system, user)
            elif provider == "groq":
                result = _call_groq(system, user)
            else:
                result = offline_fn()
        except Exception as exc:  # fall through to the next provider
            errors.append(f"{provider}: {type(exc).__name__}: {exc}"[:300])
            _failed[provider] += 1
            continue
        if provider != "offline":
            db.execute(
                "INSERT OR REPLACE INTO llm_cache (key, task, provider, response, created_at) "
                "VALUES (?,?,?,?,?)",
                (key, task, provider, json.dumps(result), db.now().isoformat(timespec="seconds")))
        _answered[provider] += 1
        return result, {"task": task, "provider": provider, "cached": False, "errors": errors}
    raise RuntimeError("No LLM provider produced a result: " + "; ".join(errors))
