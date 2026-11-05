"""One place that turns a transcript into a sentence — and it is entirely local.

There is no model in this path and no network call. A transcript becomes one
sentence through the rule packs (`intent.py`, `intent_fr.py`, `intent_packs.py`,
`intent_langs.py`): deterministic, inspectable, testable, offline.

The rule is deliberate: ClearVoice may re-order your words with grammar you can
read, or leave them exactly as heard — it may never ask a model to improve them.
An earlier version did, and the model paraphrased and invented. That path is gone,
not disabled.
"""

from __future__ import annotations

from . import intent, langs
from .settings import Settings


def propose(transcript: str, settings: Settings, *, language: str | None = None) -> intent.Proposal:
    """The sentence ClearVoice will offer. Local rule packs only."""
    code = (language or settings.language or "en").strip().lower()[:2]
    return intent.reframe(transcript, settings.rewrite_style, language=code)
