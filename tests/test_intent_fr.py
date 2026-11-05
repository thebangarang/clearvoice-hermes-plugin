"""French reframing — the defects a French speaker actually reported.

The English reframer rebuilt sentences; the French path returned the transcript
with a capital and a full stop ("in french it's literally the exact thing I
said"). These tests hold the fix in place.
"""

from __future__ import annotations

from clearvoice_engine import intent, intent_fr


def fr(transcript: str, style: str = "courteous"):
    return intent.reframe(transcript, style, language="fr")


# --- the sentence is rebuilt, not echoed ----------------------------------


def test_fragmented_french_becomes_a_courteous_request():
    proposal = fr("j'ai besoin... rendez-vous... mardi... déplacer.")
    assert proposal.intent == "request"
    assert proposal.message == "Pourriez-vous déplacer le rendez-vous pour mardi, s'il vous plaît ?"
    assert proposal.confidence >= 0.9


def test_the_frame_never_leaks_into_the_object():
    # "j'ai" used to survive as literal object content: "le j'ai rendez-vous".
    message = fr("j'ai besoin rendez-vous mardi déplacer").message
    assert "j'ai" not in message
    assert "besoin" not in message


def test_a_french_sentence_is_not_the_english_sentence():
    english = intent.reframe("I need... appointment... Tuesday... move.", language="en")
    french = fr("j'ai besoin... rendez-vous... mardi... déplacer.")
    assert english.message.startswith("Could you")
    assert french.message.startswith("Pourriez-vous")
    assert french.message != french.transcript


# --- the pieces that used to be lost --------------------------------------


def test_a_range_of_days_is_kept_whole():
    proposal = fr("il faut déplacer mon rendez-vous de mardi à jeudi")
    assert proposal.message == (
        "Pourriez-vous déplacer mon rendez-vous de mardi à jeudi, s'il vous plaît ?"
    )


def test_a_proper_noun_keeps_its_capital():
    message = fr("pouvez-vous rappeler le docteur Lefèvre à propos des ordonnances").message
    assert "Lefèvre" in message


def test_a_topic_phrase_survives_the_rebuild():
    # "à" was stripped as a frame word, leaving "propos des ordonnances".
    message = fr("pouvez-vous rappeler le docteur Lefèvre à propos des ordonnances").message
    assert "à propos des ordonnances" in message


def test_a_possessive_object_is_not_double_determined():
    message = fr("je voudrais changer mon rendez-vous chez le dentiste pour vendredi").message
    assert "mon rendez-vous" in message
    assert "le mon rendez-vous" not in message


def test_a_bare_noun_gets_an_article():
    assert "le rendez-vous" in fr("rendez-vous mardi déplacer").message
    # Elision matters: "le ordonnance" is the kind of thing that betrays a robot.
    assert "l'ordonnance" in fr("envoyer ordonnance demain").message


# --- the three styles ------------------------------------------------------


def test_literal_keeps_the_users_words_in_a_plain_order():
    proposal = fr("il faut déplacer mon rendez-vous de mardi à jeudi", "literal")
    assert proposal.message == "Déplacer mon rendez-vous de mardi à jeudi."


def test_verbatim_is_exactly_what_was_said():
    proposal = fr("il faut déplacer mon rendez-vous de mardi à jeudi", "verbatim")
    assert proposal.message == "Il faut déplacer mon rendez-vous de mardi à jeudi."


# --- classification --------------------------------------------------------


def test_classification_of_the_common_utterances():
    assert intent_fr.classify(["bonjour"]) == "greeting"
    assert intent_fr.classify(["merci"]) == "greeting"
    assert intent_fr.classify(["non"]) == "negation"
    assert intent_fr.classify(["oui"]) == "affirmation"
    assert intent_fr.classify(["pouvez", "vous", "rappeler"]) == "question"
    assert intent_fr.classify(["déplacer", "rendez-vous"]) == "request"


def test_greetings_and_negations_are_answered_in_french():
    assert fr("bonjour").message == "Bonjour."
    assert fr("au revoir").message == "Au revoir."
    assert fr("non").message == "Non, merci."


def test_empty_input_asks_in_french():
    proposal = fr("")
    assert proposal.reason == "no_speech"
    assert "répéter" in proposal.confirmation_question


def test_a_consequential_word_asks_first():
    proposal = fr("annuler ordonnance demain")
    assert proposal.needs_confirmation is True
    assert proposal.reason in ("consequential", "low_confidence")


# --- language routing ------------------------------------------------------


def test_english_is_never_mistaken_for_french():
    for text in ("yes", "no", "help", "stop", "medicine", "hello"):
        assert intent_fr.guess_language(text) == "en", text


def test_french_is_recognised_from_its_words():
    assert intent_fr.guess_language("j'ai besoin rendez-vous mardi déplacer") == "fr"
    assert intent_fr.guess_language("Déplacer mon rendez-vous") == "fr"


def test_an_explicit_language_wins_over_guessing():
    # A short English-looking utterance handled with French rules on request.
    proposal = intent.reframe("oui merci", language="fr")
    assert proposal.intent == "greeting"
    assert proposal.message == "Merci."


def test_without_a_language_english_still_takes_the_english_path():
    proposal = intent.reframe("I need... appointment... Tuesday... move.")
    assert proposal.message == "Could you move the appointment to Tuesday, please?"
