"""The personal dictionary: learning from edits, and what it does to a transcript."""

from __future__ import annotations

import sys
from contextlib import contextmanager

import numpy as np
import pytest

from clearvoice_engine import audio, stt
from clearvoice_engine.lexicon import Lexicon
from clearvoice_engine.settings import Settings

_WRITES: list[str] = []
_ARMED = False


def _audit(event: str, args: tuple) -> None:
    if not _ARMED or event != "open":
        return
    path, mode = (args + (None, None))[:2]
    if isinstance(mode, str) and any(flag in mode for flag in ("w", "a", "x", "+")):
        _WRITES.append(f"{path}:{mode}")


sys.addaudithook(_audit)


@contextmanager
def record_writes():
    global _ARMED
    _WRITES.clear()
    _ARMED = True
    try:
        yield _WRITES
    finally:
        _ARMED = False


@pytest.fixture()
def lexicon(tmp_path):
    return Lexicon(tmp_path)


# --- learning is opt-in ----------------------------------------------------


def test_learning_does_nothing_while_it_is_off(lexicon):
    assert lexicon.learn("le faire", "Lefèvre", enabled=False) == []
    assert lexicon.corrections() == []
    assert not lexicon.path.exists()


def test_learning_stores_the_pair_the_user_meant(lexicon):
    pairs = lexicon.learn("Rappelez le docteur le faire", "Rappelez le docteur Lefèvre", enabled=True)
    assert pairs, "nothing was learned"
    heard_said = {(p["heard"], p["said"]) for p in pairs}
    assert ("le faire", "Lefèvre") in heard_said
    assert lexicon.path.exists()


def test_the_same_correction_counts_up_instead_of_duplicating(lexicon):
    lexicon.learn("le faire", "Lefèvre", enabled=True)
    lexicon.learn("le faire", "Lefèvre", enabled=True)
    corrections = lexicon.corrections()
    assert len(corrections) == 1
    assert corrections[0]["count"] == 2


def test_a_case_or_accent_only_change_is_not_learned(lexicon):
    assert lexicon.learn("lefevre", "Lefèvre", enabled=True) == []
    assert lexicon.corrections() == []


def test_learning_ignores_a_huge_rewrite(lexicon):
    long_a = " ".join(["mot"] * 12)
    long_b = " ".join(["autre"] * 12)
    assert lexicon.learn(long_a, long_b, enabled=True) == []


# --- applying what was learned ---------------------------------------------


def test_corrections_are_applied_to_a_transcript(lexicon):
    lexicon.learn("le faire", "Lefèvre", enabled=True)
    corrected, applied = lexicon.apply("Rappelez le docteur le faire, merci.")
    assert corrected == "Rappelez le docteur Lefèvre, merci."
    assert applied


def test_correction_matching_ignores_case_but_keeps_the_users_spelling(lexicon):
    lexicon.learn("le faire", "Lefèvre", enabled=True)
    corrected, _ = lexicon.apply("rappelez LE FAIRE a propos des ordonnances")
    assert "Lefèvre" in corrected


def test_corrections_do_not_fire_inside_other_words(lexicon):
    lexicon.learn("aire", "hier", enabled=True)
    corrected, applied = lexicon.apply("la mairie est fermee")
    assert corrected == "la mairie est fermee"
    assert applied == []


def test_terms_and_corrections_both_reach_the_recogniser(lexicon):
    lexicon.add_term("kinésithérapeute")
    lexicon.learn("le faire", "Lefèvre", enabled=True)
    hotwords = lexicon.hotwords()
    assert "kinésithérapeute" in hotwords
    assert "Lefèvre" in hotwords


def test_terms_are_unique_and_removable(lexicon):
    assert lexicon.add_term("ordonnances") is True
    assert lexicon.add_term("Ordonnances") is False  # same word, other case
    assert lexicon.terms() == ["ordonnances"]
    assert lexicon.remove_term("ORDONNANCES") is True
    assert lexicon.terms() == []


def test_an_empty_term_is_refused(lexicon):
    with pytest.raises(ValueError):
        lexicon.add_term("   ")


# --- French compounds: the spelling the recogniser invents ------------------


def test_a_hyphenated_term_survives_a_space_or_no_separator(lexicon):
    lexicon.add_term("rendez-vous")
    assert lexicon.apply("rendez vous de mardi")[0] == "rendez-vous de mardi"
    assert lexicon.apply("RENDEZVOUS de mardi")[0] == "rendez-vous de mardi"
    assert lexicon.apply("Rendez-Vous de mardi")[0] == "rendez-vous de mardi"


def test_a_hyphenated_phrase_is_learned_as_one_correction(lexicon):
    lexicon.learn("rendez vous", "rendez-vous", enabled=True)
    corrected, applied = lexicon.apply("mon rendez vous de mardi")
    assert corrected == "mon rendez-vous de mardi"
    assert applied


def test_separator_variants_are_one_dictionary_entry(lexicon):
    assert lexicon.add_term("après-midi") is True
    assert lexicon.add_term("apres midi") is False
    assert lexicon.add_term("APRES-MIDI") is False
    assert lexicon.terms() == ["après-midi"]


def test_a_short_term_is_never_rewritten_behind_the_users_back(lexicon):
    # Rewriting "de" or "à" inside a sentence would be vandalism, not correction.
    lexicon.add_term("de")
    text = "il faut deplacer le rendez-vous"
    assert lexicon.apply(text)[0] == text


def test_clearing_corrections_keeps_the_terms(lexicon):
    lexicon.add_term("mutuelle")
    lexicon.learn("le faire", "Lefèvre", enabled=True)
    removed = lexicon.clear_corrections()
    assert removed == 1
    assert lexicon.corrections() == []
    assert lexicon.terms() == ["mutuelle"]


# --- wiring into the pipeline ----------------------------------------------


class _StubWhisper:
    class _Info:
        language = "fr"
        duration = 2.0

    def transcribe(self, samples, **kwargs):
        class _Seg:
            text = " Rappelez le docteur le faire a propos des ordonnances. "

        return iter([_Seg()]), self._Info()


def test_transcription_uses_the_dictionary(lexicon, monkeypatch):
    seen: dict = {}

    def fake_load(model_name, device="cpu", compute_type="int8"):
        seen["model"] = model_name
        return _StubWhisper()

    monkeypatch.setattr(stt, "_load_local_model", fake_load)
    lexicon.add_term("ordonnances")
    lexicon.learn("le faire", "Lefèvre", enabled=True)

    tone = (0.05 * np.sin(np.linspace(0, 6.28 * 220, 16000))).astype(np.float32)
    result = stt.transcribe(audio.float32_to_wav_bytes(tone, 16000), Settings.from_mapping({"language": "fr"}), lexicon=lexicon)

    assert "Lefèvre" in result.text
    assert result.corrections_applied == 1


def test_the_dictionary_only_ever_writes_its_own_file(tmp_path):
    store = Lexicon(tmp_path)
    with record_writes() as writes:
        store.add_term("Lefèvre")
        store.learn("le faire", "Lefèvre", enabled=True)
        store.apply("le faire")
        store.public()

    names = {w.split(":")[0].rsplit("/", 1)[-1] for w in writes}
    assert names <= {"dictionary.json", "dictionary.json.tmp"}, names
