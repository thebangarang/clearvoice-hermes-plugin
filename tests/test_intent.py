"""The intent reframer: deterministic, testable, and honest about doubt."""

from __future__ import annotations

from clearvoice_engine import intent


def test_brief_example_is_rebuilt_as_a_courteous_request():
    proposal = intent.reframe("I need... appointment... Tuesday... move.")
    assert proposal.message == "Could you move the appointment to Tuesday, please?"
    assert proposal.intent == "request"
    assert proposal.confidence >= 0.9
    assert proposal.needs_confirmation is False


def test_fillers_are_removed_without_losing_content():
    proposal = intent.reframe("um I need the uh forms please")
    assert "um" not in proposal.message.lower()
    assert "forms" in proposal.message


def test_empty_transcript_asks_to_try_again():
    proposal = intent.reframe("   ")
    assert proposal.intent == "unclear"
    assert proposal.confidence == 0.0
    assert proposal.needs_confirmation is True
    assert proposal.candidates == []
    assert "try again" in proposal.confirmation_question.lower()


def test_consequential_single_words_always_ask_first():
    for word in ("yes", "no", "help", "stop"):
        proposal = intent.reframe(word)
        assert proposal.needs_confirmation is True, word
        assert proposal.consequential is True
        assert proposal.confirmation_question


def test_ordinary_greeting_does_not_ask():
    proposal = intent.reframe("hello")
    assert proposal.message == "Hello."
    assert proposal.needs_confirmation is False


def test_question_keeps_its_question_mark():
    proposal = intent.reframe("what time is my appointment")
    assert proposal.message.endswith("?")
    assert proposal.intent == "question"


def test_can_you_is_a_request_not_a_question():
    proposal = intent.reframe("can you bring the water")
    assert proposal.intent == "request"


def test_low_information_input_offers_candidates_and_asks():
    proposal = intent.reframe("medicine")
    assert proposal.needs_confirmation is True
    assert len(proposal.candidates) >= 1
    assert proposal.confirmation_question


def test_candidates_are_unique_and_bounded():
    proposal = intent.reframe("stop")
    assert 1 <= len(proposal.candidates) <= 3
    assert len({c.lower() for c in proposal.candidates}) == len(proposal.candidates)


def test_message_length_is_capped():
    proposal = intent.reframe("need " + "word " * 400)
    assert len(proposal.message) <= intent.MAX_MESSAGE_CHARS


def test_reframe_is_deterministic():
    a = intent.reframe("I want to move the meeting to Friday").public()
    b = intent.reframe("I want to move the meeting to Friday").public()
    assert a == b


def test_cleaning_keeps_apostrophes():
    assert intent.clean_transcript("I don't know") == "I don't know"


def test_classification_covers_the_main_intents():
    assert intent.classify(["yes"]) == "affirmation"
    assert intent.classify(["no"]) == "negation"
    assert intent.classify(["hello", "there"]) == "greeting"
    assert intent.classify(["where", "is", "it"]) == "question"
    assert intent.classify(["bring", "water"]) == "request"
    assert intent.classify(["the", "sky", "is", "blue"]) == "statement"
    assert intent.classify([]) == "unclear"
