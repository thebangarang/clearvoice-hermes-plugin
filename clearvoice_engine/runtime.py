"""Process-local runtime state shared by the agent half and the REST backend.

Both entry points (``__init__.py`` and ``dashboard/plugin_api.py``) import this
same module inside the gateway process, so the tool the model calls and the
pane's ``ctx.rest`` routes see one session store and one audio outbox.

Nothing here survives a restart, and nothing here is ever serialized to disk
except the user's explicitly saved phrases (see ``privacy.SavedPhrases``).
"""

from __future__ import annotations

import os
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .privacy import SavedPhrases, SessionStore
from .lexicon import Lexicon

#: Session transcript/caption memory. In RAM, cleared on request.
session = SessionStore()

#: Pending speech request waiting for the user to approve it in the pane.
PENDING_TTL_SECONDS = 120


@dataclass
class PendingSpeech:
    """A sentence a tool asked to speak — text only, never audio.

    The distinguishing property of this object is what it does *not* carry: there
    is no wav here. A model can put a sentence in this queue; only a click in the
    pane can turn it into sound, by redeeming the single-use token.
    """

    id: int
    text: str
    kind: str            # "speak" | "say_back"
    transcript: str
    token: str
    created_at: float


class SpeechQueue:
    """One queued sentence from a tool, redeemable once by the pane.

    ``request`` is what a tool may do. ``consume`` requires the token that the
    pane received with the text, so the audio a user hears is provably the
    sentence they were shown.
    """

    def __init__(self) -> None:
        self._item: PendingSpeech | None = None
        self._counter = 0

    def request(self, text: str, *, kind: str = "speak", transcript: str = "") -> PendingSpeech:
        self._counter += 1
        item = PendingSpeech(
            id=self._counter,
            text=text,
            kind=kind,
            transcript=transcript,
            token=secrets.token_urlsafe(24),
            created_at=time.time(),
        )
        self._item = item
        return item

    def peek(self) -> PendingSpeech | None:
        item = self._item
        if item and time.time() - item.created_at > PENDING_TTL_SECONDS:
            self._item = None
            return None
        return item

    def consume(self, token: str) -> PendingSpeech | None:
        """Redeem a token once. Wrong, missing or expired token → None."""
        item = self.peek()
        if item is None or not token:
            return None
        if not secrets.compare_digest(str(token), item.token):
            return None
        self._item = None
        return item

    def clear(self) -> None:
        self._item = None


outbox = SpeechQueue()

_phrases: SavedPhrases | None = None
_phrases_dir: Path | None = None
_lexicon: Lexicon | None = None
_lexicon_dir: Path | None = None


def data_dir() -> Path:
    """The plugin's own data directory (the only folder it may write to).

    ``CLEARVOICE_DATA_DIR`` wins when set — used by tests and by an operator
    running the engine outside Hermes. Without Hermes (a plain Python import, a
    script, a cron job) the engine falls back to the XDG data directory instead
    of failing, so ``clearvoice_engine`` really is usable as a library.
    """
    override = os.environ.get("CLEARVOICE_DATA_DIR")
    if override:
        return Path(override)
    try:
        from plugins.plugin_storage import plugin_data_dir  # Hermes-owned
    except Exception:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "clearvoice"
        base.mkdir(parents=True, exist_ok=True)
        return base

    return Path(plugin_data_dir("clearvoice"))


def phrases(directory: Path | str | None = None) -> SavedPhrases:
    """The saved-phrase store. A user-chosen folder wins over the data dir."""
    global _phrases, _phrases_dir
    target = Path(directory) if directory is not None else data_dir()
    if _phrases is None or _phrases_dir != target:
        _phrases = SavedPhrases(target)
        _phrases_dir = target
    return _phrases


def lexicon(directory: Path | str | None = None) -> Lexicon:
    """The personal dictionary. Lives beside the saved phrases."""
    global _lexicon, _lexicon_dir
    target = Path(directory) if directory is not None else data_dir()
    if _lexicon is None or _lexicon_dir != target:
        _lexicon = Lexicon(target)
        _lexicon_dir = target
    return _lexicon


def reset_for_tests() -> None:
    global _phrases, _phrases_dir, _lexicon, _lexicon_dir
    session.clear()
    outbox.clear()
    _phrases = None
    _phrases_dir = None
    _lexicon = None
    _lexicon_dir = None


def status_payload() -> dict[str, Any]:
    last = session.last()
    pending = outbox.peek()
    return {
        "session_utterances": len(session),
        "last_message": last.message if last else "",
        "pending_for_pane": bool(pending),
    }
