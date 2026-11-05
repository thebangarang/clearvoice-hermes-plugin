"""Optional cleanup of a transcript by the user's own model — never a rewrite.

The first version of this module asked a chat model to "make the sentence clear and
polite". It did exactly that: it paraphrased, smoothed, and sometimes invented
content. For a person whose speech is hard to understand, a machine that improves
what they said is not help — it is the machine talking instead of them. That idea is
removed.

What is left is narrow, checkable and useful: drop "euh / um", collapse a stutter,
add a capital and a full stop — the transcript's words, in the transcript's order.

And it is verified mechanically rather than trusted: the reply must be a
**subsequence of the transcript's words**. Any word that was not said — a name, a
day, a "please" — fails, and the on-device sentence is used instead.
"""

from __future__ import annotations

import re
import unicodedata

MAX_CHARS = 240

SYSTEM = (
    "You clean up a speech transcript. You do NOT rewrite it.\n"
    "Rules, in order:\n"
    "1. Keep every word the speaker said, in the order they said it.\n"
    "2. You may only remove hesitation sounds (um, uh, er, euh, heu, äh, hum, hmm) "
    "and an immediately repeated word (\"I I need\" becomes \"I need\").\n"
    "3. You may add capital letters and one final punctuation mark.\n"
    "4. Never add, replace, reorder or infer a word — not a name, number, day, verb, "
    "politeness phrase or detail.\n"
    "5. Never turn a fragment into a different sentence.\n"
    "6. Output the cleaned text only: no quotes, no explanation, no translation."
)

_MARKDOWN = re.compile(r"[*_`#>\[\]|]")
_WORD = re.compile(r"[^\W\d_]+", re.UNICODE)


def build_messages(transcript: str, language_name: str, style: str = "verbatim") -> list[dict[str, str]]:
    """``style`` is accepted and ignored: this module no longer has a voice."""
    return [
        {"role": "system", "content": SYSTEM},
        {
            "role": "user",
            "content": f"Language: {language_name}\nTranscript: {transcript}",
        },
    ]


def tokens(text: str) -> list[str]:
    """Words, accent- and case-folded, so formatting is not counted as a change."""
    decomposed = unicodedata.normalize("NFKD", str(text or "").lower())
    folded = "".join(char for char in decomposed if not unicodedata.combining(char))
    return _WORD.findall(folded)


def _is_subsequence(short: list[str], long: list[str]) -> bool:
    """Does ``short`` appear inside ``long`` in order, allowing gaps?

    A cleanup may only *drop* words (hesitations, stutters). If every word of the
    reply can be matched in order inside the transcript, nothing was invented and
    nothing was moved.
    """
    iterator = iter(long)
    return all(word in iterator for word in short)


def validate(reply: str, transcript: str, language: str) -> tuple[bool, str]:
    """Is this reply still the user's own words? (ok, why-not)."""
    text = " ".join(str(reply or "").split()).strip()
    if not text:
        return False, "empty"
    if len(text) > MAX_CHARS:
        return False, "too_long"
    if _MARKDOWN.search(text):
        return False, "markdown"
    if text.count(".") + text.count("?") + text.count("!") > 2 or "\n" in text:
        return False, "not_one_sentence"
    if text[:1] in "\"'«»“”" or text[-1:] in "\"'«»“”":
        return False, "quoted"
    if not _script_matches(text, language):
        return False, "wrong_script"

    said = tokens(transcript)
    heard = tokens(text)
    if not heard:
        return False, "empty"

    if not _is_subsequence(heard, said):
        return False, "added_or_reordered_words"

    # A cleanup drops hesitations; deleting half the sentence is not a cleanup.
    if said and len(heard) < 0.6 * len(said):
        return False, "dropped_too_much"

    return True, ""


def _script_matches(text: str, language: str) -> bool:
    """Cheap script guard: a Japanese reply must contain Japanese characters."""
    code = (language or "").strip().lower()[:2]
    ranges = {
        "ja": (0x3040, 0x30FF),
        "zh": (0x4E00, 0x9FFF),
        "ko": (0xAC00, 0xD7AF),
        "hi": (0x0900, 0x097F),
        "th": (0x0E00, 0x0E7F),
        "ar": (0x0600, 0x06FF),
        "ru": (0x0400, 0x04FF),
    }
    span = ranges.get(code)
    if span is None:
        return True
    return any(span[0] <= ord(char) <= span[1] for char in text)


def rewrite(
    transcript: str,
    language: str,
    language_name: str,
    style: str,
    complete,
) -> tuple[str | None, dict]:
    """Ask the model for a cleanup. Returns (text or None, meta).

    ``complete`` is the host callable: ``complete(messages, max_tokens=..)`` →
    an object with ``.text`` (and optionally ``.model``/``.usage``). Anything it
    raises is caught: a model outage must never break the pane.
    """
    meta: dict = {"engine": "gateway", "ok": False, "reason": "", "model": "", "cost_usd": None}
    try:
        result = complete(
            build_messages(transcript, language_name),
            temperature=0.0,
            max_tokens=120,
            timeout=20,
            purpose="clearvoice_cleanup",
        )
    except Exception as exc:  # network, auth, quota, host refusal
        meta["reason"] = f"error:{type(exc).__name__}"
        return None, meta

    text = getattr(result, "text", None)
    if text is None:
        text = str(result or "")
    meta["model"] = str(getattr(result, "model", "") or "")

    usage = getattr(result, "usage", None)
    cost = getattr(usage, "cost_usd", None) if usage is not None else None
    meta["cost_usd"] = float(cost) if isinstance(cost, (int, float)) else None

    cleaned = " ".join(str(text).split())
    ok, why = validate(cleaned, transcript, language)
    meta["ok"] = ok
    meta["reason"] = why
    if not ok:
        return None, meta
    return cleaned, meta
