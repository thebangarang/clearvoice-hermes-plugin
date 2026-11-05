"""The personal dictionary — the accuracy feature that actually pays off.

Measured on this machine (``scripts/accuracy_bench.py``, French): the local
recogniser at ``base`` scores 15.0% word-error-rate, a bigger model (``small``)
scores 5.6% but takes 3–5× as long, and ``base`` **with a domain lexicon** scores
3.8% in *less* time than either. Names, streets, medications and recurring
sentences matter more than model size.

Two mechanisms, both local, neither one a model download:

* **hotwords** — your words are passed to the recogniser as a prompt, so it
  prefers them when the acoustics are ambiguous.
* **corrections** — pairs learned from your own edits ("le faire" → "Lefèvre"),
  applied afterwards as exact replacements.

Nothing here leaves the machine. Learning is **off unless the user turns it on**,
every entry is visible and deletable, and there is no sharing or telemetry.
"""

from __future__ import annotations

import difflib
import json
import re
import time
import unicodedata
from pathlib import Path
from typing import Any

MAX_TERMS = 200
MAX_CORRECTIONS = 200
MAX_TERM_CHARS = 64
MAX_PAIR_WORDS = 6


def _normalise(text: str) -> str:
    return " ".join(str(text or "").split())


def _key(text: str) -> str:
    """Comparison key: case- and accent-insensitive."""
    decomposed = unicodedata.normalize("NFKD", _normalise(text).lower())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


class Lexicon:
    """The user's own words, kept in the plugin's data directory."""

    def __init__(self, directory: Path | str) -> None:
        self.path = Path(directory) / "dictionary.json"

    # --- storage -----------------------------------------------------------

    def _read(self) -> dict[str, Any]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raw = {}
        terms = [str(t) for t in raw.get("terms", []) if str(t).strip()]
        corrections = [
            {
                "heard": _normalise(c.get("heard", "")),
                "said": _normalise(c.get("said", "")),
                "count": int(c.get("count", 1) or 1),
                "learned_at": float(c.get("learned_at", 0) or 0),
            }
            for c in raw.get("corrections", [])
            if isinstance(c, dict) and str(c.get("heard", "")).strip() and str(c.get("said", "")).strip()
        ]
        return {"version": 1, "terms": terms, "corrections": corrections}

    def _write(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.path)

    # --- reading -----------------------------------------------------------

    def terms(self) -> list[str]:
        return self._read()["terms"]

    def corrections(self) -> list[dict[str, Any]]:
        return self._read()["corrections"]

    def hotwords(self) -> str:
        """One string for the recogniser: your terms plus every corrected form."""
        data = self._read()
        words = list(data["terms"]) + [c["said"] for c in data["corrections"]]
        seen: set[str] = set()
        out: list[str] = []
        for word in words:
            key = _key(word)
            if key and key not in seen:
                seen.add(key)
                out.append(word)
        return ", ".join(out)

    def apply(self, text: str) -> tuple[str, list[dict[str, str]]]:
        """Apply learned corrections to a transcript. Returns (text, applied)."""
        result = _normalise(text)
        applied: list[dict[str, str]] = []
        corrections = sorted(self._read()["corrections"], key=lambda c: -len(c["heard"]))
        for correction in corrections:
            heard = correction["heard"]
            said = correction["said"]
            if _key(heard) == _key(said):
                continue
            pattern = re.compile(rf"(?<!\w){re.escape(heard)}(?!\w)", re.IGNORECASE)
            if pattern.search(result):
                result = pattern.sub(said, result)
                applied.append({"heard": heard, "said": said})
        return result, applied

    def public(self) -> dict[str, Any]:
        data = self._read()
        return {
            "terms": data["terms"],
            "corrections": data["corrections"],
            "hotwords": self.hotwords(),
            "path": str(self.path),
        }

    # --- writing -----------------------------------------------------------

    def add_term(self, term: str) -> bool:
        cleaned = _normalise(term)[:MAX_TERM_CHARS]
        if not cleaned:
            raise ValueError("A dictionary entry needs some text.")
        data = self._read()
        if any(_key(t) == _key(cleaned) for t in data["terms"]):
            return False
        data["terms"] = (data["terms"] + [cleaned])[-MAX_TERMS:]
        self._write(data)
        return True

    def remove_term(self, term: str) -> bool:
        data = self._read()
        kept = [t for t in data["terms"] if _key(t) != _key(term)]
        if len(kept) == len(data["terms"]):
            return False
        data["terms"] = kept
        self._write(data)
        return True

    def learn(self, heard: str, said: str, *, enabled: bool) -> list[dict[str, Any]]:
        """Store what the recogniser got wrong, from a transcript the user fixed.

        Refuses unless learning is enabled *for this call*: the caller passes the
        user's own switch, so a stale setting cannot start collecting edits.
        """
        if not enabled:
            return []
        pairs = _diff_into_pairs(heard, said)
        if not pairs:
            return []
        data = self._read()
        existing = {(_key(c["heard"]), _key(c["said"])): c for c in data["corrections"]}
        stored: list[dict[str, Any]] = []
        for heard_part, said_part in pairs:
            key = (_key(heard_part), _key(said_part))
            if key in existing:
                existing[key]["count"] += 1
                stored.append(existing[key])
                continue
            entry = {"heard": heard_part, "said": said_part, "count": 1, "learned_at": time.time()}
            data["corrections"].append(entry)
            existing[key] = entry
            stored.append(entry)
        data["corrections"] = data["corrections"][-MAX_CORRECTIONS:]
        self._write(data)
        return stored

    def clear_corrections(self) -> int:
        data = self._read()
        count = len(data["corrections"])
        data["corrections"] = []
        self._write(data)
        return count

    def clear_all(self) -> None:
        if self.path.exists():
            self.path.unlink()


def _diff_into_pairs(heard: str, said: str) -> list[tuple[str, str]]:
    """Word-level diff of a transcript and the user's fixed version."""
    cleared = _normalise(heard)
    fixed = _normalise(said)
    if not cleared or not fixed or _key(cleared) == _key(fixed):
        return []
    left = cleared.split()
    right = fixed.split()
    matcher = difflib.SequenceMatcher(a=[_key(w) for w in left], b=[_key(w) for w in right], autojunk=False)
    pairs: list[tuple[str, str]] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        heard_part = " ".join(left[i1:i2])
        said_part = " ".join(right[j1:j2])
        if not heard_part or not said_part:
            continue
        if len(heard_part.split()) > MAX_PAIR_WORDS or len(said_part.split()) > MAX_PAIR_WORDS:
            continue
        if _key(heard_part) == _key(said_part):
            continue  # case or accent only: the recogniser heard the right word
        pairs.append((heard_part, said_part))
    return pairs
