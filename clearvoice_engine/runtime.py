"""Process-local runtime state shared by the agent half and the REST backend.

Both entry points (``__init__.py`` and ``dashboard/plugin_api.py``) import this
same module inside the gateway process, so the tool the model calls and the
pane's ``ctx.rest`` routes see one session store and one audio outbox.

Nothing here survives a restart, and nothing here is ever serialized to disk
except the user's explicitly saved phrases (see ``privacy.SavedPhrases``).
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .privacy import SavedPhrases, SessionStore

#: Session transcript/caption memory. In RAM, cleared on request.
session = SessionStore()

#: Pending spoken audio waiting to be collected by the Desktop pane.
PENDING_TTL_SECONDS = 120


@dataclass
class PendingAudio:
    token: int
    wav: bytes
    text: str
    backend: str
    created_at: float


class AudioOutbox:
    """Single slot: the newest utterance the agent asked the pane to speak."""

    def __init__(self) -> None:
        self._item: PendingAudio | None = None
        self._counter = 0

    def put(self, wav: bytes, text: str, backend: str) -> PendingAudio:
        self._counter += 1
        self._item = PendingAudio(self._counter, wav, text, backend, time.time())
        return self._item

    def take(self) -> PendingAudio | None:
        item, self._item = self._item, None
        if item and time.time() - item.created_at > PENDING_TTL_SECONDS:
            return None
        return item

    def peek(self) -> PendingAudio | None:
        item = self._item
        if item and time.time() - item.created_at > PENDING_TTL_SECONDS:
            self._item = None
            return None
        return item

    def clear(self) -> None:
        self._item = None


outbox = AudioOutbox()

_phrases: SavedPhrases | None = None
_phrases_dir: Path | None = None


def data_dir() -> Path:
    """The plugin's own data directory (the only folder it may write to).

    ``CLEARVOICE_DATA_DIR`` wins when set — used by tests and by an operator
    running the engine outside Hermes.
    """
    override = os.environ.get("CLEARVOICE_DATA_DIR")
    if override:
        return Path(override)
    from plugins.plugin_storage import plugin_data_dir  # Hermes-owned

    return Path(plugin_data_dir("clearvoice"))


def phrases(directory: Path | str | None = None) -> SavedPhrases:
    """The saved-phrase store. A user-chosen folder wins over the data dir."""
    global _phrases, _phrases_dir
    target = Path(directory) if directory is not None else data_dir()
    if _phrases is None or _phrases_dir != target:
        _phrases = SavedPhrases(target)
        _phrases_dir = target
    return _phrases


def reset_for_tests() -> None:
    global _phrases
    session.clear()
    outbox.clear()
    _phrases = None


def status_payload() -> dict[str, Any]:
    last = session.last()
    pending = outbox.peek()
    return {
        "session_utterances": len(session),
        "last_message": last.message if last else "",
        "pending_for_pane": bool(pending),
    }
