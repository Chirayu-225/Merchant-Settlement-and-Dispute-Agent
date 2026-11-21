"""Settings for the settlement and chargeback dispute agent. Values come from .env when present."""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def _bool(name: str, default: str) -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


def _default_db_path() -> Path:
    """data/agent.db next to the code, or the system temp folder if that is not writable
    (some hosts mount the app folder read-only)."""
    preferred = BASE_DIR / "data"
    try:
        preferred.mkdir(parents=True, exist_ok=True)
        probe = preferred / ".write_test"
        probe.write_text("ok")
        probe.unlink()
        return preferred / "agent.db"
    except OSError:
        import tempfile
        return Path(tempfile.gettempdir()) / "settlement_dispute_agent.db"


DB_PATH = Path(os.getenv("DB_PATH") or _default_db_path())

# ---- Feature 1: payout explanation
# Fee model. These are DEMO VALUES for synthetic data, not real Paytm pricing.
FEE_RATES = {"UPI": 0.0, "CARD": 0.018, "WALLET": 0.015}
GST_RATE = 0.18  # GST charged on the fee
TOLERANCE = 0.05  # amounts within this many rupees are treated as equal
LANGUAGES = ["English", "Hindi", "Tamil"]
MAX_EXPLANATION_RETRIES = 1

# ---- Feature 2: chargeback dispute resolution
# Gate thresholds (demo values, change in .env)
AMOUNT_LIMIT = float(os.getenv("AMOUNT_LIMIT", "5000"))
DEADLINE_SLACK_HOURS = float(os.getenv("DEADLINE_SLACK_HOURS", "48"))
DRY_RUN = _bool("DRY_RUN", "true")
MAX_DRAFT_RETRIES = 1

# ---- LLM gateway (shared by both features)
LLM_MODE = os.getenv("LLM_MODE", "auto").strip().lower()  # auto | gemini | groq | offline
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-flash-latest").strip()
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile").strip()
LLM_TIMEOUT_SECONDS = 40
