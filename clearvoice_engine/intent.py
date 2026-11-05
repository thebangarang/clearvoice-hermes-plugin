"""Intended-message inference — deterministic, local, and inspectable.

ClearVoice does **not** call a language model here. A fragmented transcript
("I need... appointment... Tuesday... move.") is classified by intent and
rebuilt from a small, auditable rule set. The upside for this audience is the
one that matters: it runs offline, it answers in milliseconds, it gives the same
answer twice, and it can be unit-tested line by line.

When the rules are unsure they say so: ``needs_confirmation`` is set, a plain
confirmation question is returned, and up to three candidate sentences are
offered for the user to pick from.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass, field
from typing import Iterable

from . import intent_fr as _fr
from . import intent_langs as _langs
from . import intent_packs as _packs
from .intent_fr import guess_language

# --------------------------------------------------------------------------
# Vocabulary
# --------------------------------------------------------------------------

FILLERS = {
    "um", "umm", "uh", "uhh", "er", "erm", "ah", "eh", "hmm", "hm",
    "like", "well", "so", "just", "kinda", "sorta", "basically", "actually",
}

REQUEST_VERBS = {
    "move", "reschedule", "postpone", "change", "cancel", "book", "order",
    "bring", "get", "give", "take", "put", "send", "call", "ask", "tell",
    "find", "open", "close", "turn", "wait", "help", "check", "confirm",
    "repeat", "speak", "say", "write", "read", "pay", "fix", "make", "show",
    "come", "go", "start", "stop", "add", "remove", "print", "sign", "fill",
    "drink", "eat", "sit", "stand", "walk", "rest", "wash", "dress", "use",
}

#: Verbs that take "to <time>" rather than "on <time>".
TO_VERBS = {"move", "reschedule", "postpone", "push", "change"}

QUESTION_WORDS = {
    "what", "when", "where", "who", "whom", "whose", "why", "how", "which",
    "is", "are", "was", "were", "do", "does", "did", "can", "could", "will",
    "would", "should", "may", "am",
}

AFFIRMATIONS = {"yes", "yeah", "yep", "yup", "correct", "right", "okay", "ok", "sure", "indeed"}
NEGATIONS = {"no", "nope", "nah", "not", "dont", "don't", "never", "stop", "cancel", "none"}

GREETING_WORDS = {"hello", "hi", "hey", "morning", "afternoon", "evening", "goodbye", "bye"}
THANKS_WORDS = {"thanks", "thank", "please"}

WEEKDAYS = {
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
    "mon", "tue", "tues", "wed", "thu", "thur", "thurs", "fri", "sat", "sun",
}
MONTHS = {
    "january", "february", "march", "april", "may", "june", "july", "august",
    "september", "october", "november", "december",
    "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec",
}
RELATIVE_TIME = {
    "today", "tonight", "tomorrow", "yesterday", "morning", "afternoon",
    "evening", "noon", "midnight", "later", "soon", "now", "weekend",
    "week", "month", "next", "this", "after", "before",
}

#: Words that make a message consequential: ClearVoice always asks first.
CONSEQUENTIAL = {
    "no", "not", "stop", "cancel", "don't", "dont", "never", "yes",
    "help", "emergency", "hospital", "doctor", "nurse", "pain", "hurt",
    "fell", "fall", "sick", "dizzy", "medication", "medicine", "pill",
    "allergic", "allergy", "chest", "breathe", "breathing",
    "money", "pay", "bank", "account", "password", "address", "sign",
    "contract", "agree", "lawyer", "police", "alone", "unsafe",
}

_PUNCT = re.compile(r"[^\w'\s-]", re.UNICODE)
_SPACES = re.compile(r"\s+")

MAX_MESSAGE_CHARS = 240


@dataclass
class Proposal:
    """What ClearVoice thinks the user meant, plus how sure it is."""

    transcript: str
    message: str
    intent: str
    confidence: float
    needs_confirmation: bool
    consequential: bool
    candidates: list[str] = field(default_factory=list)
    confirmation_question: str = ""
    reason: str = ""
    style: str = "courteous"
    engine: str = "local"        # "local" (rule pack) or "gateway" (the user's model)
    cost_usd: float | None = None

    def public(self) -> dict:
        return asdict(self)

    @property
    def confident(self) -> bool:
        return not self.needs_confirmation


# --------------------------------------------------------------------------
# Cleaning
# --------------------------------------------------------------------------


def clean_transcript(transcript: str) -> str:
    """Drop punctuation and filler words, keep every script intact.

    A regex of ``[^\\w'-]`` looks right and is not: ``\\w`` matches Devanagari
    letters but *not* the combining vowel signs, so "मुझे" came back as "म झ" and
    Thai lost its marks the same way. Keep letters, digits and marks (category
    M) from any script, space everything else.
    """
    kept: list[str] = []
    for char in str(transcript or ""):
        if char in "'-":
            kept.append(char)
            continue
        category = unicodedata.category(char)
        if char.isspace() or category[0] in ("L", "N", "M"):
            kept.append(char)
        else:
            kept.append(" ")
    text = _SPACES.sub(" ", "".join(kept)).strip()
    words = [word for word in text.split(" ") if word and word.lower() not in FILLERS]
    return " ".join(words)


def _tokens(cleaned: str) -> list[str]:
    return [w.lower() for w in cleaned.split(" ") if w]


def _capitalise(text: str) -> str:
    text = text.strip()
    if not text:
        return text
    return text[0].upper() + text[1:]


def _dedupe(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        key = item.strip().lower()
        if item.strip() and key not in seen:
            seen.add(key)
            out.append(item.strip())
    return out


# --------------------------------------------------------------------------
# Classification
# --------------------------------------------------------------------------


def classify(tokens: list[str]) -> str:
    if not tokens:
        return "unclear"
    joined = " ".join(tokens)
    first = tokens[0]

    if len(tokens) <= 4 and any(t in NEGATIONS for t in tokens):
        return "negation"
    if len(tokens) <= 4 and any(t in AFFIRMATIONS for t in tokens):
        return "affirmation"
    if first in GREETING_WORDS or first in THANKS_WORDS:
        return "greeting"
    # "can you help me" is a request, not a question about the world.
    if first in {"can", "could", "would", "will", "may"} and any(t in REQUEST_VERBS for t in tokens):
        return "request"
    if first in QUESTION_WORDS:
        return "question"
    if any(t in REQUEST_VERBS for t in tokens) or "please" in tokens:
        return "request"
    if joined.endswith("?"):
        return "question"
    return "statement"


def _time_phrase(tokens: list[str]) -> tuple[list[str], str]:
    """Pull the time expression out of the token list, original order kept."""
    time_words: list[str] = []
    rest: list[str] = []
    for index, token in enumerate(tokens):
        is_time = token in WEEKDAYS or token in MONTHS or token in RELATIVE_TIME
        if token.isdigit() and 0 < len(token) <= 2 and index and tokens[index - 1] in ("at", "on", "by"):
            is_time = True
        if is_time:
            time_words.append(token if token.isdigit() else _capitalise(token))
        else:
            rest.append(token)
    return rest, " ".join(time_words)


_DETERMINERS = {
    "the", "my", "a", "an", "your", "his", "her", "our", "their", "this",
    "that", "these", "those", "some", "any", "another",
}


def _with_article(obj: str) -> str:
    first = obj.split(" ", 1)[0]
    return obj if first in _DETERMINERS else f"the {obj}"


def _request_parts(tokens: list[str]) -> tuple[str, str, str, str]:
    """(verb, object phrase, preposition, time phrase) extracted from a request."""
    rest, time_phrase = _time_phrase(tokens)
    verb = next((t for t in rest if t in REQUEST_VERBS), "")
    content = [t for t in rest if t not in REQUEST_VERBS]
    content = [t for t in content if t not in {"i", "we", "you", "me", "please", "to", "can", "could", "would", "will", "need", "want", "like"}]
    obj = " ".join(content).strip()
    if obj:
        obj = _with_article(obj)
    prep = "to" if verb in TO_VERBS else "on"
    return verb, obj, prep, time_phrase


def _request_message(tokens: list[str]) -> tuple[str, bool, bool]:
    """Build a courteous request. Returns (message, has_verb_object, has_time)."""
    verb, obj, prep, time_phrase = _request_parts(tokens)
    has_time = bool(time_phrase)
    if verb and obj:
        if has_time:
            return f"Could you {verb} {obj} {prep} {time_phrase}, please?", True, has_time
        return f"Could you {verb} {obj}, please?", True, has_time
    if verb and has_time:
        return f"Could you {verb} it {prep} {time_phrase}, please?", False, has_time
    if obj:
        return f"I need {obj}, please.", False, has_time
    if verb:
        return f"Could you {verb}, please?", False, has_time
    return "Could you help me, please?", False, has_time


def _literal_request(tokens: list[str]) -> str:
    """The user's own words in a plain order — no courtesy frame, no "could you"."""
    verb, obj, prep, time_phrase = _request_parts(tokens)
    if verb and obj:
        core = f"{verb} {obj} {prep} {time_phrase}" if time_phrase else f"{verb} {obj}"
        return _capitalise(core) + "."
    if verb:
        return _capitalise(verb) + "."
    if obj:
        return _capitalise(obj) + "."
    return _capitalise(" ".join(tokens)) + "."


def _verbatim(cleaned: str, intent: str) -> str:
    """Exactly the recognised words, tidied only at the edges (case preserved)."""
    text = _capitalise(cleaned).strip()
    if intent == "question":
        return text.rstrip("?.") + "?"
    return text.rstrip(".") + "."



def _candidates(intent: str, primary: str, tokens: list[str]) -> list[str]:
    literal = _capitalise(" ".join(tokens)).strip()
    options = [primary]
    if intent == "request":
        options.append(literal + ".")
        options.append(f"I would like to {literal.lower()}, please.")
    elif intent == "question":
        options.append(primary.rstrip("?") + "?")
        options.append(literal + ".")
    else:
        options.append(literal + ".")
    return [o for o in _dedupe(options) if len(o) <= MAX_MESSAGE_CHARS][:3]


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------


def reframe(transcript: str, style: str = "courteous", language: str | None = None) -> Proposal:
    """Turn a raw transcript into a proposed clear sentence.

    ``style`` decides how much is rebuilt:
    ``courteous`` (default) — reorders into a polite request, the brief's flow;
    ``literal`` — the user's own words in a plain order, no courtesy frame;
    ``verbatim`` — exactly what was recognised, tidied only at the edges.

    ``language`` picks the rule pack. English and French have their own tables,
    because a reframer that only knows English returns French unchanged — which
    reads to a French speaker as "it does nothing". When no language is given the
    text decides, and the caller should pass the recogniser's language when it has
    one.
    """
    cleaned = clean_transcript(transcript)
    tokens = _tokens(cleaned)
    style = style if style in ("courteous", "literal", "verbatim") else "courteous"

    requested = (language or "").strip().lower()[:2]
    resolved = requested if requested in _langs.POLITE else guess_language(cleaned)
    asked = str(transcript or "").strip().endswith(("?", "？", "؟"))

    if resolved == "fr":
        return _reframe_fr(cleaned, tokens, style)

    if resolved != "en":
        pack = _packs.PACKS.get(resolved)
        if pack is not None:
            words = _packs.tokens_of(transcript, lower_first=not pack.capitalises_nouns)
            message, confidence, has_vo = _packs.reframe_with_pack(
                str(transcript or ""), cleaned, words, pack, style
            )
            low = confidence < 0.6 or not has_vo
            return Proposal(
                transcript=cleaned,
                message=message[:MAX_MESSAGE_CHARS],
                intent="request" if has_vo else "statement",
                confidence=confidence,
                needs_confirmation=low,
                consequential=False,
                candidates=[message[:MAX_MESSAGE_CHARS]],
                confirmation_question=_langs.confirm_question(resolved) if low else "",
                reason="low_confidence" if low else "",
                style=style,
            )
        return _reframe_polished(cleaned, tokens, style, resolved, asked)

    if not tokens:
        return Proposal(
            transcript="",
            message="",
            intent="unclear",
            confidence=0.0,
            needs_confirmation=True,
            consequential=False,
            candidates=[],
            confirmation_question="I didn't catch that - try again?",
            reason="no_speech",
            style=style,
        )

    intent = classify(tokens)
    has_verb_object = False
    has_time = False

    if style == "verbatim":
        message = _verbatim(cleaned, intent)
        has_verb_object = intent == "request"
    elif style == "literal":
        if intent == "request":
            message = _literal_request(tokens)
            has_verb_object = True
        else:
            message = _verbatim(cleaned, intent)
    elif intent == "request":
        message, has_verb_object, has_time = _request_message(tokens)
    elif intent == "question":
        message = _capitalise(" ".join(tokens)).rstrip("?") + "?"
    elif intent == "affirmation":
        message = "Yes." if not any(t in ("please", "sure") for t in tokens) else "Yes, please."
    elif intent == "negation":
        message = "No, thank you."
    elif intent == "greeting":
        if any(t in THANKS_WORDS for t in tokens) and not any(t in GREETING_WORDS for t in tokens):
            message = "Thank you."
        elif any(t in GREETING_WORDS for t in tokens) and tokens[0] in ("goodbye", "bye"):
            message = "Goodbye."
        else:
            message = "Hello."
    else:
        message = _capitalise(" ".join(tokens)).rstrip(".") + "."


    message = message[:MAX_MESSAGE_CHARS]

    confidence = _confidence(
        intent,
        tokens,
        has_verb_object,
        has_time,
        stopwords={"i", "a", "the", "to", "my", "me", "you", "is", "it"},
    )

    consequential = any(t in CONSEQUENTIAL for t in tokens)
    low = confidence < 0.6 or intent == "unclear"
    needs_confirmation = low or consequential

    if consequential and not low:
        question = "This one sounds important. Is this what you want to say?"
        reason = "consequential"
    elif low:
        question = "I'm not sure I got that. Is this what you meant?"
        reason = "low_confidence"
    else:
        question = ""
        reason = ""

    return Proposal(
        transcript=cleaned,
        message=message,
        intent=intent,
        confidence=confidence,
        needs_confirmation=needs_confirmation,
        consequential=consequential,
        candidates=_candidates(intent, message, tokens) if (low or consequential) else [message],
        confirmation_question=question,
        reason=reason,
        style=style,
    )


# --------------------------------------------------------------------------
# Shared scoring, and the French entry point
# --------------------------------------------------------------------------


def _confidence(
    intent: str,
    tokens: list[str],
    has_verb_object: bool,
    has_time: bool,
    *,
    stopwords: set[str],
) -> float:
    """How sure the rules are. Language-independent, so both packs agree."""
    content_words = len([t for t in tokens if t not in stopwords])
    confidence = 0.55
    if intent != "unclear":
        confidence += 0.15
    if has_verb_object:
        confidence += 0.15
    if has_time:
        confidence += 0.10
    if content_words >= 3:
        confidence += 0.05
    if content_words <= 1:
        confidence -= 0.20
    # A short, complete utterance ("Yes.", "Bonjour.") is not an uncertain one:
    # the whole message arrived. Consequential single words still ask first.
    if len(tokens) <= 2 and intent != "unclear":
        confidence = max(confidence, 0.8)
    return round(max(0.05, min(0.95, confidence)), 2)


def _reframe_fr(cleaned: str, tokens: list[str], style: str) -> Proposal:
    """French path: same shape as English, French tables."""
    if not tokens:
        return Proposal(
            transcript="",
            message="",
            intent="unclear",
            confidence=0.0,
            needs_confirmation=True,
            consequential=False,
            candidates=[],
            confirmation_question="Je n'ai pas compris. Vous pouvez répéter ?",
            reason="no_speech",
            style=style,
        )

    intent = _fr.classify(tokens)
    tokens = _fr.tokens_of(cleaned) or tokens
    has_verb_object = False
    has_time = False
    if style == "verbatim":
        message = _fr.verbatim(cleaned, intent)
        has_verb_object = intent == "request"
    elif style == "literal":
        if intent == "request":
            message = _fr.literal(tokens)
            has_verb_object = True
        else:
            message = _fr.verbatim(cleaned, intent)
    elif intent == "request":
        message, has_verb_object, has_time = _fr.courteous(tokens)
    elif intent == "question":
        message = _fr.capitalise(" ".join(tokens)).rstrip("? ") + " ?"
    elif intent == "affirmation":
        message = "Oui, volontiers." if "svp" in tokens else "Oui."
    elif intent == "negation":
        message = "Non, merci."
    elif intent == "greeting":
        norms = [_fr._norm(t) for t in tokens]
        if {"revoir", "au", "bye"} & set(norms):
            message = "Au revoir."
        elif "merci" in norms and not ({"bonjour", "salut", "bonsoir"} & set(norms)):
            message = "Merci."
        elif "bonsoir" in norms:
            message = "Bonsoir."
        elif "salut" in norms:
            message = "Salut."
        else:
            message = "Bonjour."
    else:
        message = _fr.capitalise(" ".join(tokens)).rstrip(".") + "."

    message = message[:MAX_MESSAGE_CHARS]

    confidence = _confidence(
        intent,
        tokens,
        has_verb_object,
        has_time,
        stopwords=_fr.FR_FRAME_WORDS,
    )

    consequential = any(_fr._norm(t) in _fr.FR_CONSEQUENTIAL for t in tokens)
    low = confidence < 0.6 or intent == "unclear"
    needs_confirmation = low or consequential

    if consequential and not low:
        question = "Cela semble important. C'est bien ce que vous voulez dire ?"
        reason = "consequential"
    elif low:
        question = "Je ne suis pas sûr d'avoir compris. Est-ce bien ce que vous vouliez dire ?"
        reason = "low_confidence"
    else:
        question = ""
        reason = ""

    return Proposal(
        transcript=cleaned,
        message=message,
        intent=intent,
        confidence=confidence,
        needs_confirmation=needs_confirmation,
        consequential=consequential,
        candidates=_fr.candidates(intent, message, tokens) if (low or consequential) else [message],
        confirmation_question=question,
        reason=reason,
        style=style,
    )


def _reframe_polished(
    cleaned: str, tokens: list[str], style: str, language: str, question: bool = False
) -> Proposal:
    """Languages without a grammar pack: polished, politely addressed, not rebuilt.

    ``reason`` says ``polished_only`` so the pane can tell the user the truth —
    the words are theirs, only the edges and the courtesy are ours.
    """
    if not tokens:
        return Proposal(
            transcript="",
            message="",
            intent="unclear",
            confidence=0.0,
            needs_confirmation=True,
            consequential=False,
            candidates=[],
            confirmation_question=_langs.confirm_question(language),
            reason="no_speech",
            style=style,
        )

    entry = _langs.politeness_for(language)
    if style == "verbatim":
        message = cleaned[:1].upper() + cleaned[1:]
        message = message.rstrip(" .,!?;:") + (entry.question if question else entry.stop)
        intent = "question" if question else "statement"
    else:
        message = _langs.polish(cleaned, language, question=question)
        intent = "question" if question else "request"

    message = message[:MAX_MESSAGE_CHARS]
    return Proposal(
        transcript=cleaned,
        message=message,
        intent=intent,
        confidence=0.60,
        needs_confirmation=True,
        consequential=False,
        candidates=[message],
        confirmation_question=_langs.confirm_question(language),
        reason="polished_only",
        style=style,
    )
