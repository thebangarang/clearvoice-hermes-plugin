"""Session-scoped state and the one thing ClearVoice is allowed to persist.

Two stores, deliberately different in lifetime:

``SessionStore``
    In memory only. Holds the last few utterances of the *current* app session
    so the pane can show captions and offer **Repeat**. ``clear()`` empties it;
    it is also empty after a restart because nothing was ever written.

``SavedPhrases``
    On disk, under the plugin's data directory, and **only** written by an
    explicit ``save_phrase(...)`` call. No audio, no transcripts, no history —
    a short list of sentences the user typed or approved on purpose.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

PRIVACY_LINE = "Audio processed this session only. Nothing saved."
MAX_SESSION_UTTERANCES = 12
MAX_PHRASES = 100
MAX_PHRASE_CHARS = 300


@dataclass
class Utterance:
    """One push-to-talk turn. Never leaves memory while the app runs."""

    transcript: str
    message: str
    backend: str
    created_at: float = field(default_factory=time.time)

    def public(self) -> dict[str, Any]:
        return {
            "transcript": self.transcript,
            "message": self.message,
            "backend": self.backend,
            "created_at": self.created_at,
        }


class SessionStore:
    def __init__(self) -> None:
        self._items: list[Utterance] = []

    def add(self, transcript: str, message: str, backend: str) -> Utterance:
        item = Utterance(transcript=transcript, message=message, backend=backend)
        self._items.append(item)
        del self._items[:-MAX_SESSION_UTTERANCES]
        return item

    def last(self) -> Utterance | None:
        return self._items[-1] if self._items else None

    def all(self) -> list[Utterance]:
        return list(self._items)

    def clear(self) -> int:
        count = len(self._items)
        self._items.clear()
        return count

    def __len__(self) -> int:  # pragma: no cover - trivial
        return len(self._items)


@dataclass
class SavedPhrase:
    id: str
    text: str
    label: str = ""
    created_at: float = field(default_factory=time.time)

    def public(self) -> dict[str, Any]:
        return asdict(self)


class SavedPhrases:
    """Explicit, user-initiated phrase list. The only disk write in the plugin."""

    def __init__(self, directory: Path | str) -> None:
        self.path = Path(directory) / "phrases.json"

    def _read(self) -> list[dict[str, Any]]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        items = raw.get("phrases") if isinstance(raw, dict) else None
        return [p for p in items if isinstance(p, dict) and p.get("text")] if isinstance(items, list) else []

    def _write(self, items: list[dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": 1, "phrases": items}
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def list(self) -> list[SavedPhrase]:
        out = []
        for item in self._read():
            out.append(
                SavedPhrase(
                    id=str(item.get("id") or uuid.uuid4().hex),
                    text=str(item.get("text"))[:MAX_PHRASE_CHARS],
                    label=str(item.get("label") or "")[:80],
                    created_at=float(item.get("created_at") or 0.0),
                )
            )
        return out

    def save_phrase(self, text: str, label: str = "") -> SavedPhrase:
        """Persist one sentence. Callers must have an explicit user action."""
        cleaned = " ".join(str(text or "").split())[:MAX_PHRASE_CHARS]
        if not cleaned:
            raise ValueError("A saved phrase needs some text.")
        phrase = SavedPhrase(id=uuid.uuid4().hex[:12], text=cleaned, label=str(label or "")[:80])
        items = self._read()
        items.append(asdict(phrase))
        self._write(items[-MAX_PHRASES:])
        return phrase

    def delete(self, phrase_id: str) -> bool:
        items = self._read()
        kept = [p for p in items if str(p.get("id")) != phrase_id]
        if len(kept) == len(items):
            return False
        self._write(kept)
        return True

    def clear(self) -> None:
        if self.path.exists():
            self.path.unlink()
