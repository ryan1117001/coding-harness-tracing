"""Parser for Cursor's chat transcript (SQLite ``store.db``).

Cursor hook payloads carry a ``transcript_path`` (``string | null``). The chat
is stored as a content-addressed SQLite database:

    CREATE TABLE blobs (id TEXT PRIMARY KEY, data BLOB);  -- one JSON message per row
    CREATE TABLE meta  (key TEXT PRIMARY KEY, value TEXT);

Cursor's hooks do NOT expose token usage or cost anywhere (neither in the hook
payload nor in the transcript). The one thing the transcript reliably carries
that the hook payload omits in Auto mode is the resolved model name, stored on
assistant messages as ``providerOptions.cursor.modelName`` (e.g.
``"composer-2.5-fast"``). We extract only that.

Everything here is best-effort and fails soft (returns "") — a hook must never
break because a transcript is missing, locked, or in an unexpected shape.
"""

from __future__ import annotations

import re
import sqlite3
from collections import Counter
from pathlib import Path

# Model values that are selection modes, not resolvable model names.
_MODEL_SENTINELS = frozenset({"default", "auto", ""})

# Matches the resolved model on assistant messages:
#   ...,"providerOptions":{"cursor":{"modelName":"composer-2.5-fast"}},...
# Scanning the raw blob bytes avoids decoding every (potentially large) message.
_MODEL_NAME_RE = re.compile(rb'"modelName"\s*:\s*"([^"]+)"')


def _resolve_store_db(path: str | Path) -> "Path | None":
    """Resolve *path* to a readable ``store.db`` file, or None.

    ``transcript_path`` may point directly at the DB file or at the conversation
    directory that contains it.
    """
    try:
        p = Path(path).expanduser()
    except (TypeError, ValueError):
        return None
    if p.is_file():
        return p
    if p.is_dir():
        candidate = p / "store.db"
        if candidate.is_file():
            return candidate
    return None


def store_db_for_conversation(conversation_id: str) -> "Path | None":
    """Locate a conversation's ``store.db`` by id, without a transcript path.

    Cursor lays chats out as ``~/.cursor/chats/<workspace>/<conversation_id>/store.db``,
    so the conversation id alone (always present on hook payloads) is enough to
    find the transcript even when ``transcript_path`` is absent or null.
    """
    if not conversation_id:
        return None
    try:
        chats = Path.home() / ".cursor" / "chats"
        for db in chats.glob(f"*/{conversation_id}/store.db"):
            if db.is_file():
                return db
    except OSError:
        return None
    return None


def model_from_conversation(conversation_id: str) -> str:
    """Resolve the model from a conversation id via its ``store.db`` (or "")."""
    db = store_db_for_conversation(conversation_id)
    return model_from_transcript(db) if db else ""


def model_from_transcript(path: str | Path) -> str:
    """Return the resolved model name from the transcript, or "".

    Reads ``providerOptions.cursor.modelName`` across all message blobs and
    returns the most frequent real value (a conversation is normally one model).
    Sentinels (``auto``/``default``) are ignored.
    """
    db = _resolve_store_db(path)
    if db is None:
        return ""
    try:
        # Read-only open. (Not immutable: Cursor uses WAL mode, so the newest
        # messages live in the -wal file, which immutable mode would skip.)
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=1.0)
        try:
            rows = con.execute("SELECT data FROM blobs").fetchall()
        finally:
            con.close()
    except sqlite3.Error:
        return ""

    counts: Counter = Counter()
    for (data,) in rows:
        if not isinstance(data, (bytes, bytearray)):
            continue
        for match in _MODEL_NAME_RE.findall(data):
            value = match.decode("utf-8", "replace")
            if value.strip().lower() not in _MODEL_SENTINELS:
                counts[value] += 1
    if not counts:
        return ""
    return counts.most_common(1)[0][0]
