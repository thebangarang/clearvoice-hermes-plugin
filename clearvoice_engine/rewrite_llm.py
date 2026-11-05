"""Optional rewrite by the user's own model, through Hermes — text only.

What this is for: the rule packs rebuild sentences in seven languages. A frontier
model rebuilds them in all seventeen, and Hermes already holds the user's model and
credentials, so the plugin never sees a key.

What this deliberately is **not**: speech recognition. No model here hears audio;
recognition stays on-device. In this mode the *transcript text* leaves the machine
and nothing else — no audio, no phrases, no dictionary contents.

Two rules make it safe to offer to this audience:

1. **Off by default.** ``reframe_backend: local`` is the shipped setting.
2. **Validated, then discarded on doubt.** A reply that invents a number, changes
   language, exceeds the length or loses every word of the original is thrown
   away and the local sentence is used instead. A model that guesses at what an
   unclear speaker meant is the one failure this product must not have.
"""

from __future__ import annotations

import re

MAX_CHARS = 240

SYSTEM = (
    "You rewrite speech that may be fragmented, agrammatical or hard to understand "
    "into ONE clear, polite sentence.\n"
    "Rules, in order:\n"
    "1. Keep the speaker's meaning exactly. Invent nothing: no new facts, names, "
    "numbers, dates, places or reasons.\n"
    "2. Keep every detail that was given, and only what was given.\n"
    "3. Write in the language given to you, even if the input is mixed.\n"
    "4. Output the sentence only: no quotes, no markdown, no explanation, no "
    "translations.\n"
    "5. If a detail is unclear, leave it out rather than guessing it.\n"
    "6. Maximum 40 words."
)

STYLE_HINT = {
    "courteous": "Make it a polite request or statement, as one would say it aloud.",
    "literal": "Keep the speaker's own wording; only fix the order enough to be a sentence.",
    "verbatim": "Do not rephrase at all; only add capitalisation and final punctuation.",
}

_MARKDOWN = re.compile(r"[*_`#>\[\]|]")
_NUMBER = re.compile(r"\d+")


def build_messages(transcript: str, language_name: str, style: str) -> list[dict[str, str]]:
    hint = STYLE_HINT.get(style, STYLE_HINT["courteous"])
    return [
        {"role": "system", "content": SYSTEM},
        {
            "role": "user",
            "content": f"Language: {language_name}\nStyle: {hint}\nSpeech: {transcript}",
        },
    ]


def _units(text: str) -> set[str]:
    """What "the same meaning" means for a script: words in Latin, characters in CJK.

    Japanese and Thai are written without spaces, so a whole reply arrives as one
    "word" and any word-overlap test would reject every correct answer.
    """
    words = {word for word in re.findall(r"\w+", text.lower()) if len(word) > 2}
    characters = {char for char in text if ord(char) >= 0x2E80 and char.isalnum()}
    return words | characters


def validate(reply: str, transcript: str, language: str) -> tuple[bool, str]:
    """Is this reply safe to show as the user's sentence? (ok, why-not)."""
    text = " ".join(str(reply or "").split()).strip()
    if not text:
        return False, "empty"
    if len(text) > MAX_CHARS:
        return False, "too_long"
    if _MARKDOWN.search(text):
        return False, "markdown"
    if text.count(".") > 2 or "\n" in text:
        return False, "not_one_sentence"

    stripped = text.strip("\"'«»“” \t")
    if stripped != text and (text.startswith(("\"", "«", "“")) or text.endswith(("\"", "»", "”"))):
        return False, "quoted"

    # Invented numbers are the most damaging hallucination here: a wrong day or a
    # wrong dose. Every digit in the reply must exist in what was said.
    if not _NUMBER.findall(text) <= _NUMBER.findall(transcript):
        return False, "invented_number"

    # Wrong script is the more specific diagnosis, so it is checked first:
    # a Latin reply to a Japanese transcript is a language swap, not a paraphrase.
    if not _script_matches(text, language):
        return False, "wrong_script"

    # The reply must still be about what was said.
    given = _units(transcript)
    if given and not (_units(text) & given):
        return False, "loss_of_meaning"

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
    """Ask the model for one sentence. Returns (sentence or None, meta).

    ``complete`` is the host callable: ``complete(messages, max_tokens=..)`` →
    an object with ``.text`` (and optionally ``.model``/``.usage``). Anything it
    raises is caught: a model outage must never break the pane.
    """
    meta: dict = {"engine": "gateway", "ok": False, "reason": "", "model": "", "cost_usd": None}
    try:
        result = complete(
            build_messages(transcript, language_name, style),
            temperature=0.0,
            max_tokens=120,
            timeout=20,
            purpose="clearvoice_reframe",
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
    return cleaned.strip("\"'«»“” "), meta
