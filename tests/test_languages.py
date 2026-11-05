"""Languages, voice routing and the three rewrite styles."""

from __future__ import annotations

import pytest

from clearvoice_engine import intent, langs
from clearvoice_engine.settings import Settings

SAMPLE = "I need... appointment... Tuesday... move."


# --- language routing ------------------------------------------------------


def test_every_language_resolves_and_is_ordered():
    listed = langs.all_languages()
    assert len(listed) == len(langs.ORDER) == 17
    assert listed[0].code == "en"
    codes = [lang.code for lang in listed]
    assert codes == list(langs.ORDER)


def test_the_requested_languages_are_present():
    for code in ("fr", "ja", "zh", "ko", "th", "hi", "ar", "ru", "tr", "vi"):
        language = langs.get(code)
        assert language.code == code
        assert language.tts_engine == "piper"
        assert language.default_voice


def test_english_is_voiced_by_phonon_and_others_by_piper():
    assert Settings.from_mapping({"language": "en"}).resolved_tts_engine == "phonon"
    for code in ("fr", "de", "es", "ja", "th"):
        assert Settings.from_mapping({"language": code}).resolved_tts_engine == "piper"


def test_language_codes_tolerate_region_suffixes():
    assert langs.get("fr-FR").code == "fr"
    assert langs.get("pt_BR").code == "pt"
    assert langs.get("klingon").code == "en"


def test_an_english_only_recogniser_is_never_used_for_another_language():
    assert langs.whisper_model_for(langs.get("fr"), "tiny.en") == "tiny"
    assert langs.whisper_model_for(langs.get("ja"), "base.en") == "base"
    assert langs.whisper_model_for(langs.get("en"), "tiny.en") == "tiny.en"
    assert langs.whisper_model_for(langs.get("en"), "small") == "small"


def test_default_stt_model_is_multilingual_for_non_english():
    for code in ("fr", "de", "es", "pt", "ja", "zh"):
        assert not langs.get(code).stt_model.endswith(".en")


def test_explicit_phonon_for_a_non_english_language_is_refused():
    import pytest

    from clearvoice_engine import tts

    settings = Settings.from_mapping({"language": "fr", "tts_backend": "phonon"})
    with pytest.raises(tts.SynthesisError) as excinfo:
        tts.synthesize("Bonjour", settings)
    assert "only speaks English" in str(excinfo.value)


# --- voice index -----------------------------------------------------------


def test_every_language_default_voice_is_in_the_bundled_index():
    for language in langs.all_languages():
        if language.tts_engine != "piper":
            continue
        voice = langs.piper_voice(language.default_voice)
        assert voice is not None, language.code
        assert voice["family"] == language.code


def test_voice_index_covers_all_offered_piper_languages():
    for language in langs.all_languages():
        if language.tts_engine != "piper":
            continue
        assert langs.piper_voices(language.code), language.code


def test_voice_keys_map_to_hugging_face_paths():
    assert (
        langs.piper_url("fr_FR-siwis-medium")
        == "https://huggingface.co/rhasspy/piper-voices/resolve/main/fr/fr_FR/siwis/medium/fr_FR-siwis-medium.onnx"
    )
    assert (
        langs.piper_url("en_GB-alan-low")
        == "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_GB/alan/low/en_GB-alan-low.onnx"
    )


def test_status_exposes_the_language_list_and_engine_labels():
    status = Settings.from_mapping({"language": "ja"}).status()
    assert status["language_label"] == "Japanese"
    assert status["tts_label"] == "Piper (local)"
    assert len(status["languages"]) == 17
    assert status["network"] == "Offline"


# --- rewrite styles --------------------------------------------------------


def test_courteous_style_rebuilds_a_request():
    proposal = intent.reframe(SAMPLE, "courteous")
    assert proposal.message == "Could you move the appointment to Tuesday, please?"
    assert proposal.style == "courteous"


def test_literal_style_keeps_the_users_words_in_a_plain_order():
    proposal = intent.reframe(SAMPLE, "literal")
    assert proposal.message == "Move the appointment to Tuesday."
    assert "Could you" not in proposal.message
    assert "please" not in proposal.message.lower()


def test_verbatim_style_changes_nothing_but_the_edges():
    proposal = intent.reframe("I need appointment Tuesday move", "verbatim")
    assert proposal.message == "I need appointment Tuesday move."


def test_verbatim_question_keeps_the_question_mark():
    assert intent.reframe("what time is my appointment", "verbatim").message.endswith("?")


def test_unknown_style_falls_back_to_courteous():
    assert intent.reframe(SAMPLE, "shakespearean").message == intent.reframe(SAMPLE).message


def test_rewrite_style_comes_from_settings():
    settings = Settings.from_mapping({"rewrite_style": "literal"})
    assert settings.rewrite_style == "literal"
    assert Settings.from_mapping({"rewrite_style": "nonsense"}).rewrite_style == "courteous"


# --- optional phonemizers --------------------------------------------------


def test_readiness_matches_the_installed_phonemizer():
    import importlib.util

    for code, module in (("ja", "pyopenjtalk"), ("th", "tltk")):
        installed = importlib.util.find_spec(module) is not None
        assert langs.get(code).ready is installed, code
        assert langs.get(code).public()["ready"] is installed


def test_a_missing_phonemizer_names_the_package_to_install():
    from clearvoice_engine import piper

    for module, expected in (
        ("pyopenjtalk", "pip install pyopenjtalk"),
        ("tltk", "pip install tltk"),
        ("unicode_rbnf", "pip install tltk"),
    ):
        exc = ModuleNotFoundError(f"No module named '{module}'", name=module)
        message = piper._missing_phonemizer(exc)
        assert message and expected in message, module


def test_an_unrelated_error_is_not_explained_away():
    from clearvoice_engine import piper

    assert piper._missing_phonemizer(RuntimeError("boom")) is None
    assert piper._missing_phonemizer(ModuleNotFoundError("numpy", name="numpy")) is None


# --- voice choices and the saved-phrase folder -----------------------------


def test_voice_choices_are_scoped_to_one_language_and_best_first():
    french = langs.piper_voices("fr")
    assert french, "French voices missing from the index"
    assert all(v["family"] == "fr" for v in french)
    # The default voice opens the picker, then higher quality before lower.
    assert french[0]["key"] == "fr_FR-siwis-medium"
    ranks = [{"high": 3, "medium": 2, "low": 1, "x_low": 0}[v["quality"]] for v in french[1:]]
    assert ranks == sorted(ranks, reverse=True)


def test_english_voice_choices_exclude_other_languages():
    from clearvoice_engine import tts

    if not tts.phonon_available():
        pytest.skip("ptts not installed")
    english = tts.voices_for("en")
    assert english
    assert all(v.get("language") in (None, "", "en") for v in english)


def test_phrases_folder_needs_an_existing_absolute_directory(tmp_path):
    assert Settings.from_mapping({"phrases_dir": str(tmp_path)}).phrases_folder() == tmp_path
    assert Settings.from_mapping({"phrases_dir": "relative/dir"}).phrases_folder() is None
    assert Settings.from_mapping({"phrases_dir": "/no/such/folder/here"}).phrases_folder() is None
    assert Settings.from_mapping({}).phrases_folder() is None
