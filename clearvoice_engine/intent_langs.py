"""Polite wrapping for the languages that have no full reframing pack.

Full sentence rebuilding needs per-language grammar (verbs, time expressions,
determiners, elision) — that exists for English and French, and pretending
otherwise for fifteen more languages would mean shipping grammar nobody native
has checked. What *is* safe and language-independent:

* tidy the edges (spaces, capital letter, one sentence-ending mark);
* say it politely, using the language's own politeness word;
* ask for confirmation in the same language.

So a German or Japanese user gets: their sentence, clean, addressed politely,
with a check question they can actually read — and no claim that ClearVoice
reordered their words. That distinction is the honest one to put in the UI:
"polished" versus "rebuilt".

A language pack is code, not data: anyone who speaks the language can extend
`POLITE` or write a full pack, and no user's speech is involved.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Politeness:
    """How one language ends a request politely."""

    code: str
    please: str            # ", bitte." — appended whole, including punctuation
    joiner: str            # what goes before it ("" for CJK, ", " for latin)
    stop: str              # sentence end
    question: str          # sentence end for questions
    confirm: str           # "Is this what you meant?"
    uppercase_first: bool = True


POLITE: dict[str, Politeness] = {
    "en": Politeness("en", "please.", ", ", ".", "?", "Is this what you meant?"),
    "fr": Politeness("fr", "s'il vous plaît.", ", ", ".", " ?", "Est-ce bien ce que vous voulez dire ?"),
    "de": Politeness("de", "bitte.", ", ", ".", "?", "Ist das, was Sie sagen wollten?"),
    "es": Politeness("es", "por favor.", ", ", ".", "?", "¿Es esto lo que querías decir?"),
    "pt": Politeness("pt", "por favor.", ", ", ".", "?", "É isto que queria dizer?"),
    "it": Politeness("it", "per favore.", ", ", ".", "?", "È questo che volevi dire?"),
    "nl": Politeness("nl", "alstublieft.", ", ", ".", "?", "Is dit wat je bedoelde?"),
    "pl": Politeness("pl", "proszę.", ", ", ".", "?", "Czy to jest to, co chciałeś powiedzieć?"),
    "ru": Politeness("ru", "пожалуйста.", ", ", ".", "?", "Это то, что вы хотели сказать?"),
    "tr": Politeness("tr", "lütfen.", ", ", ".", "?", "Bunu mu söylemek istediniz?"),
    "ar": Politeness("ar", "من فضلك.", "، ", ".", "؟", "هل هذا ما أردت قوله؟"),
    "hi": Politeness("hi", "कृपया।", " ", "।", "?", "क्या आप यही कहना चाहते थे?"),
    "ja": Politeness("ja", "お願いします。", "、", "。", "？", "これで合っていますか？"),
    "zh": Politeness("zh", "谢谢。", "，", "。", "？", "这是您想说的吗？"),
    "ko": Politeness("ko", "부탁드립니다.", ", ", ".", "?", "이 말씀하신 게 맞나요?"),
    "th": Politeness("th", "กรุณา", " ", "", "?", "นี่คือสิ่งที่คุณต้องการจะพูดหรือไม่"),
    "vi": Politeness("vi", "làm ơn.", ", ", ".", "?", "Đây có phải điều bạn muốn nói không?"),
}

_TRAILING = " .,!?;:…。、،؟।"


def politeness_for(language: str) -> Politeness:
    """The table entry for a language, English when we have nothing better."""
    code = (language or "").strip().lower()[:2]
    return POLITE.get(code) or POLITE["en"]


def _already_polite(text: str, entry: Politeness) -> bool:
    stripped = entry.please.rstrip(" .。、،؟।")
    return bool(stripped) and stripped.lower() in text.lower()


def polish(text: str, language: str, *, question: bool = False) -> str:
    """Tidy and address politely, without touching the word order.

    The distinction matters: this is not a rewrite, and the pane must not claim
    it was one. Nothing is added but a politeness word and punctuation.

    ``question`` must be decided on the *raw* transcript: the caller cleans
    punctuation off before this point, so a trailing "?" is already gone by here.
    """
    entry = politeness_for(language)
    body = " ".join(str(text or "").split()).strip(_TRAILING)
    if not body:
        return ""

    if entry.uppercase_first:
        body = body[:1].upper() + body[1:]

    if question:
        return f"{body}{entry.question}"

    if _already_polite(body, entry):
        return f"{body}{entry.stop}"

    return f"{body}{entry.joiner}{entry.please}"


def confirm_question(language: str) -> str:
    return politeness_for(language).confirm


def supports_full_rebuild(language: str) -> bool:
    """True only where a real rule pack exists — the UI and the README use this."""
    return (language or "").strip().lower()[:2] in {"en", "fr"}
