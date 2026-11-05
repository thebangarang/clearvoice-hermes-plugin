"""Every language gets a polite sentence; only two get their words rebuilt.

The distinction is the product's honesty line: "rebuilt" is a claim about grammar,
"polished" is a claim about punctuation and courtesy. These tests keep the two
apart, and keep non-Latin scripts intact.
"""

from __future__ import annotations

import pytest

from clearvoice_engine import intent, intent_langs, langs

CODES = [language.code for language in langs.all_languages()]


# --- the table must cover exactly what the plugin offers --------------------


def test_every_offered_language_has_a_politeness_entry():
    missing = [code for code in CODES if code not in intent_langs.POLITE]
    assert missing == []


def test_no_politeness_entry_for_a_language_we_do_not_offer():
    extra = [code for code in intent_langs.POLITE if code not in CODES]
    assert extra == []


def test_every_entry_is_complete():
    for code, entry in intent_langs.POLITE.items():
        assert entry.please.strip(), code
        assert entry.confirm.strip(), code
        assert entry.confirm != intent_langs.POLITE["en"].confirm or code == "en", code


def test_only_english_and_french_claim_a_full_rebuild():
    assert intent_langs.supports_full_rebuild("en") is True
    assert intent_langs.supports_full_rebuild("fr") is True
    for code in ("de", "es", "ja", "zh", "hi", "th"):
        assert intent_langs.supports_full_rebuild(code) is False, code


# --- polishing never mangles a script --------------------------------------


@pytest.mark.parametrize(
    "code,text",
    [
        ("hi", "मुझे अपना अपॉइंटमेंट बदलना है"),
        ("th", "ฉันต้องการเลื่อนนัดหมายเป็นวันพฤหัสบดี"),
        ("ja", "火曜日から木曜日にかえてください"),
        ("zh", "我想把预约改到星期四"),
        ("ko", "예약을 목요일로 바꾸고 싶어요"),
        ("ar", "أريد تغيير موعدي إلى الخميس"),
        ("ru", "мне нужно перенести встречу на четверг"),
        ("vi", "tôi muốn đổi lịch hẹn sang thứ năm"),
    ],
)
def test_the_words_survive_polishing(code, text):
    proposal = intent.reframe(text, "courteous", language=code)
    # Every word the recogniser produced is still there, in the same order —
    # the first letter may be capitalised, which is the only edit allowed here.
    assert proposal.message.lower().startswith(text.lower()[:12])
    for word in text.split():
        assert word.lower() in proposal.message.lower(), (code, word, proposal.message)


def test_devanagari_combining_marks_are_not_stripped():
    # "मुझे" was coming back as "म झ": \w matches letters, not vowel signs.
    polished = intent.reframe("मुझे अपना अपॉइंटमेंट बदलना है", "courteous", language="hi").message
    assert "मुझे" in polished
    assert "म झ" not in polished


# --- politeness rules ------------------------------------------------------


def test_a_question_is_not_given_a_politeness_closer():
    proposal = intent.reframe("¿puede cambiar mi cita?", "courteous", language="es")
    assert proposal.message.endswith("?")
    assert "por favor" not in proposal.message.lower()


def test_the_closer_is_not_added_twice():
    proposal = intent.reframe("bitte meinen Termin verschieben, bitte", "courteous", language="de")
    assert proposal.message.lower().count("bitte") == 2  # the user's own two, no third
    assert proposal.message.count("bitte.") == 1


def test_cjk_sentences_end_with_their_own_full_stop():
    assert intent.reframe("我想把预约改到星期四", "courteous", language="zh").message.endswith("。")
    assert intent.reframe("火曜日にかえてください", "courteous", language="ja").message.endswith("。")


def test_the_confirmation_question_is_in_the_users_language():
    assert "合って" in intent.reframe("火曜日にかえて", "courteous", language="ja").confirmation_question
    assert "sagen" in intent.reframe("Termin verschieben", "courteous", language="de").confirmation_question


def test_polished_output_says_it_was_not_rebuilt():
    proposal = intent.reframe("ich muss meinen Termin verschieben", "courteous", language="de")
    assert proposal.reason == "polished_only"
    assert proposal.needs_confirmation is True


def test_verbatim_in_a_polished_language_keeps_the_words_untouched():
    text = "ich muss meinen Termin verschieben"
    proposal = intent.reframe(text, "verbatim", language="de")
    assert proposal.message == "Ich muss meinen Termin verschieben."


# --- English and French are untouched by all of this -----------------------


def test_english_still_rebuilds_with_its_own_rules():
    proposal = intent.reframe("I need... appointment... Tuesday... move.", language="en")
    assert proposal.message == "Could you move the appointment to Tuesday, please?"
    assert proposal.reason == ""


def test_french_still_rebuilds_with_its_own_rules():
    proposal = intent.reframe("j'ai besoin... rendez-vous... mardi... déplacer.", language="fr")
    assert proposal.message == "Pourriez-vous déplacer le rendez-vous pour mardi, s'il vous plaît ?"
    assert proposal.reason == ""
