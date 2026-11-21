"""A saved, fully measured copy of the demo database, so the live demo opens instantly.

The snapshot is the offline evaluation result, saved once. It is only used when it is still
true: it stores a fingerprint of every file that can change a result (rules, pipelines, data
generator, thresholds). If any of those files change, the fingerprint no longer matches, the
snapshot is ignored, and the app measures from scratch instead. Nothing stale is ever shown.

Rebuild after changing rules, data or thresholds:   python snapshot.py
Check it is still fresh (also run by the tests):    python snapshot.py --check
"""
import hashlib
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

import config

ROOT = Path(__file__).resolve().parent
SNAPSHOT = ROOT / "snapshot" / "agent.db"
FINGERPRINT_KEY = "snapshot_source_hash"

# Everything that can change a measured number.
SOURCE_DIRS = ["disputes", "payouts", "product"]
SOURCE_FILES = ["generate_data.py", "db.py", "config.py", "llm.py", "evaluate.py"]


def source_hash() -> str:
    """Fingerprint of the code and settings behind the numbers. Line endings are normalised so
    a Windows checkout and a Linux checkout of the same code give the same fingerprint."""
    files = [ROOT / f for f in SOURCE_FILES]
    for folder in SOURCE_DIRS:
        files += sorted((ROOT / folder).glob("*.py"))
    digest = hashlib.sha256()
    for path in files:
        digest.update(path.name.encode())
        digest.update(path.read_bytes().replace(b"\r\n", b"\n"))
    digest.update(f"{config.AMOUNT_LIMIT}|{config.DEADLINE_SLACK_HOURS}".encode())
    return digest.hexdigest()


def _stored_hash(path: Path) -> str | None:
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            row = conn.execute("SELECT value FROM meta WHERE key=?", (FINGERPRINT_KEY,)).fetchone()
        finally:
            conn.close()
        return row[0] if row else None
    except sqlite3.Error:
        return None


def is_fresh() -> bool:
    return SNAPSHOT.exists() and _stored_hash(SNAPSHOT) == source_hash()


def restore() -> bool:
    """Copy the snapshot into place if it is still true. Returns whether it was used."""
    if not is_fresh():
        return False
    Path(config.DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(SNAPSHOT, config.DB_PATH)
    return True


def build() -> dict:
    """Measure everything offline, then save the result with its fingerprint."""
    os.environ["LLM_MODE"] = "offline"
    config.LLM_MODE = "offline"
    work = Path(tempfile.mkdtemp()) / "build.db"
    config.DB_PATH = work
    import db
    import evaluate
    import generate_data
    generate_data.generate()
    result = evaluate.run_all(use_cache=False)
    stamp = result["stamp"]
    if stamp["mode"] not in ("offline", "none") or stamp["failed"]:
        raise SystemExit(f"Refusing to save: the run was not clean offline ({stamp['mode']}).")
    db.set_meta(FINGERPRINT_KEY, source_hash())
    SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
    src = sqlite3.connect(str(work))
    dst = sqlite3.connect(str(SNAPSHOT))
    with dst:
        src.backup(dst)
    src.close()
    dst.close()
    return stamp


if __name__ == "__main__":
    if "--check" in sys.argv:
        if is_fresh():
            print("Snapshot is fresh.")
        else:
            print("Snapshot is missing or stale. Run: python snapshot.py")
            sys.exit(1)
    else:
        built = build()
        print(f"Saved snapshot/agent.db. Measured: {built['mode']} · {built['date']}")
