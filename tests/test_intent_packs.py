"""The five data-driven packs: a table per language, one shared pipeline.

These tests are deliberately about *structure*, not poetry: the verb is found,
the object keeps its article, the frame words do not leak into the sentence, the
verb lands at the end where the language wants it, and a language with no verb
found degrades to a polite sentence instead of a guess.
"""

from __future__ import annotations

import pytest

from clearvoice_engine import intent, intent_langs, intent_packs, langs

PACKED = sorted(intent_packs.PACKS)


# --- the tables agree with what the plugin offers ---------------------------


def test_every_pack_is_a_language_we_ship():
    offered = {language.code for language in langs.all_languages()}
    for code in PACKED:
        assert code in offered, code


def test_every_pack_can_say_please_and_ask_a_question():
    for code in PACKED:
        assert code in intent_langs.POLITE
        assert intent_langs.politeness_for(code).confirm.strip()


@pytest.mark.parametrize("code", PACKED)
def test_a_pack_has_the_pieces_the_engine_needs(code):
    pack = intent_packs.PACKS[code]
    assert len(pack.verbs) >= 20, code
    assert pack.days and pack.months and pack.relatives, code
    assert pack.frame_words and pack.determiners and pack.links, code
    assert "{verb}" in pack.courteous and "{object}" in pack.courteous, code


@pytest.mark.parametrize("code", PACKED)
def test_no_determiner_is_also_a_frame_word(code):
    """If they collide the article vanishes: "Podría cambiar cita" for "mi cita"."""
    pack = intent_packs.PACKS[code]
    overlap = {word for word in pack.determiners if word in pack.frame_words}
    assert overlap == set(), (code, sorted(overlap))


# --- the pipeline ----------------------------------------------------------


@pytest.mark.parametrize(
    "code,text,expected_fragment",
    [
        ("de", "ich muss meinen Termin von Dienstag auf Donnerstag verschieben",
         "meinen Termin von Dienstag auf Donnerstag"),
        ("es", "necesito cambiar mi cita del martes al jueves", "mi cita del martes al jueves"),
        ("it", "devo spostare il mio appuntamento da martedì a giovedì", "il mio appuntamento"),
        ("pt", "preciso mudar a minha consulta de terça para quinta", "a minha consulta"),
        ("nl", "ik moet mijn afspraak van dinsdag naar donderdag verplaatsen",
         "mijn afspraak van dinsdag naar donderdag"),
    ],
)
def test_the_object_survives_with_its_article(code, text, expected_fragment):
    message = intent.reframe(text, "courteous", language=code).message
    assert expected_fragment.lower() in message.lower(), message


@pytest.mark.parametrize(
    "code,text,banned",
    [
        ("de", "ich muss meinen Termin verschieben", ["muss", "ich"]),
        ("es", "necesito cambiar mi cita", ["necesito"]),
        ("it", "devo spostare il mio appuntamento", ["devo"]),
        ("pt", "preciso mudar a minha consulta", ["preciso"]),
        ("nl", "ik moet mijn afspraak verplaatsen", ["moet"]),
    ],
)
def test_the_frame_does_not_leak_into_the_sentence(code, text, banned):
    message = intent.reframe(text, "courteous", language=code).message.lower()
    for word in banned:
        assert word not in message, (code, word, message)


@pytest.mark.parametrize("code", ["de", "nl"])
def test_verb_closing_languages_end_with_the_verb(code):
    pack = intent_packs.PACKS[code]
    samples = {
        "de": "ich muss meinen Termin von Dienstag auf Donnerstag verschieben",
        "nl": "ik moet mijn afspraak van dinsdag naar donderdag verplaatsen",
    }
    message = intent.reframe(samples[code], "courteous", language=code).message
    # "…verplaatsen, alstublieft?": the courtesy can follow, the verb still closes.
    courtesy = intent_langs.politeness_for(code).please.rstrip(" .?")
    without_courtesy = message.replace(courtesy, " ").replace(",", " ").strip(" ?.!")
    last_word = without_courtesy.split(" ")[-1]
    assert last_word in set(pack.verbs.values()), (code, message)


@pytest.mark.parametrize("code", ["es", "it", "pt"])
def test_verb_early_languages_start_with_their_courtesy(code):
    sample = {
        "es": "cambiar mi cita",
        "it": "spostare il mio appuntamento",
        "pt": "mudar a minha consulta",
    }[code]
    message = intent.reframe(sample, "courteous", language=code).message
    assert message.lower().startswith(("¿podría", "potrebbe", "poderia")), message


def test_an_unknown_verb_degrades_to_a_polite_sentence():
    proposal = intent.reframe("mein Termin am Dienstag", "courteous", language="de")
    assert proposal.message.rstrip(".").endswith("bitte")
    assert proposal.needs_confirmation is True


def test_thanks_do_not_get_a_please():
    assert intent.reframe("danke", "courteous", language="de").message == "Danke."
    assert intent.reframe("gracias", "courteous", language="es").message == "Gracias."


def test_verbatim_never_rewrites_a_packed_language():
    text = "ich muss meinen Termin verschieben"
    assert intent.reframe(text, "verbatim", language="de").message == (
        "Ich muss meinen Termin verschieben."
    )


def test_a_packed_language_is_marked_as_rebuilt():
    proposal = intent.reframe("ich muss meinen Termin verschieben", "courteous", language="de")
    assert proposal.reason == ""
    assert proposal.intent == "request"


def test_languages_without_a_pack_still_say_so():
    for code in ("ja", "zh", "ar", "hi", "ko", "th", "vi", "ru", "pl", "tr"):
        proposal = intent.reframe("test phrase", "courteous", language=code)
        assert proposal.reason == "polished_only", code
        assert intent_packs.has_pack(code) is False
