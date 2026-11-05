"""The languages ClearVoice offers, and how each one is voiced.

English is synthesised by the Apache-2.0 Phonon 31m checkpoint (voice names come
from its catalog). Every other language is synthesised by Piper, whose runtime is
MIT and whose per-language voice models are individually licensed. Recognition is
faster-whisper in every case — but a `.en` model can only hear English, so the
model is chosen from the language, never left to a stale setting.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

_DATA = Path(__file__).resolve().parent / "data" / "piper_voices.json"

#: Display order in the picker.
ORDER = ("en", "fr", "de", "es", "pt", "it", "nl", "pl", "ru", "tr", "ar", "hi", "ja", "zh", "ko", "th", "vi")


@dataclass(frozen=True)
class Language:
    code: str
    label: str
    native: str
    tts_engine: str  # 'phonon' | 'piper'
    default_voice: str
    stt_model: str  # multilingual unless the language is English
    extra: str = ""  # optional phonemizer package(s) this voice needs
    extra_module: str = ""  # the module to probe for that extra

    def public(self) -> dict:
        return {**asdict(self), "ready": self.ready}

    @property
    def ready(self) -> bool:
        """True when its voice can be synthesised on this machine right now."""
        if self.tts_engine != "piper" or not self.extra_module:
            return True
        import importlib.util

        return importlib.util.find_spec(self.extra_module) is not None


_LANGUAGES: dict[str, Language] = {
    "en": Language("en", "English", "English", "phonon", "default", "small"),
    "fr": Language("fr", "French", "Français", "piper", "fr_FR-siwis-medium", "small"),
    "de": Language("de", "German", "Deutsch", "piper", "de_DE-thorsten-medium", "small"),
    "es": Language("es", "Spanish", "Español", "piper", "es_ES-davefx-medium", "small"),
    "pt": Language("pt", "Portuguese", "Português", "piper", "pt_BR-faber-medium", "small"),
    "it": Language("it", "Italian", "Italiano", "piper", "it_IT-paola-medium", "small"),
    "nl": Language("nl", "Dutch", "Nederlands", "piper", "nl_NL-ronnie-medium", "small"),
    "pl": Language("pl", "Polish", "Polski", "piper", "pl_PL-gosia-medium", "small"),
    "ru": Language("ru", "Russian", "Русский", "piper", "ru_RU-irina-medium", "small"),
    "tr": Language("tr", "Turkish", "Türkçe", "piper", "tr_TR-dfki-medium", "small"),
    "ar": Language("ar", "Arabic", "العربية", "piper", "ar_JO-kareem-medium", "small"),
    "hi": Language("hi", "Hindi", "हिन्दी", "piper", "hi_IN-priyamvada-medium", "small"),
    "ja": Language(
        "ja", "Japanese", "日本語", "piper", "ja_JP-hi_fi_captain-medium", "small",
        extra="pyopenjtalk", extra_module="pyopenjtalk",
    ),
    "zh": Language("zh", "Chinese (Mandarin)", "中文", "piper", "zh_CN-huayan-medium", "small"),
    "ko": Language("ko", "Korean", "한국어", "piper", "ko_KR-kss-medium", "small"),
    "th": Language(
        "th", "Thai", "ไทย", "piper", "th_TH-tsync2-medium", "small",
        extra="tltk pandas requests unicode-rbnf", extra_module="tltk",
    ),
    "vi": Language("vi", "Vietnamese", "Tiếng Việt", "piper", "vi_VN-vais1000-medium", "small"),
}


def get(code: str | None) -> Language:
    """Resolve a language code, tolerating 'fr-FR', 'fr_FR' and empty input."""
    raw = str(code or "").strip().lower().replace("_", "-")
    base = raw.split("-")[0]
    return _LANGUAGES.get(base, _LANGUAGES["en"])


def all_languages() -> list[Language]:
    return [_LANGUAGES[code] for code in ORDER if code in _LANGUAGES]


def codes() -> list[str]:
    return [code for code in ORDER if code in _LANGUAGES]


def whisper_model_for(language: Language, configured: str | None) -> str:
    """Never hand a `.en` model a non-English utterance.

    faster-whisper does not error on the mismatch: it returns fluent nonsense,
    which is the worst possible failure for someone being misunderstood.
    """
    model = (configured or "").strip() or language.stt_model
    if language.code != "en" and model.endswith(".en"):
        model = model[: -len(".en")] or language.stt_model
    if language.code == "en" and not model.endswith(".en") and model in ("tiny", "base", "small"):
        # A multilingual model still hears English correctly; leave the choice alone.
        return model
    return model


# ---------------------------------------------------------------------------
# Piper voice index (bundled, offline)
# ---------------------------------------------------------------------------


def _load_index() -> dict:
    try:
        return json.loads(_DATA.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"voices": [], "defaults": {}}


def piper_voices(language_code: str | None = None) -> list[dict]:
    """Every Piper voice for a language (or every voice, when no language is given).

    Best first: the language's default voice, then higher quality before lower,
    so the picker does not open on a `low` model.
    """
    index = _load_index()
    voices = index.get("voices", [])
    if not language_code:
        return list(voices)
    language = get(language_code)
    rank = {"high": 3, "medium": 2, "low": 1, "x_low": 0}
    family = [v for v in voices if v.get("family") == language.code]
    return sorted(
        family,
        key=lambda v: (v.get("key") != language.default_voice, -rank.get(v.get("quality", ""), 0)),
    )


def piper_voice(key: str) -> dict | None:
    for voice in _load_index().get("voices", []):
        if voice.get("key") == key:
            return voice
    return None


def piper_url(key: str) -> str:
    """Hugging Face URL of a voice's ONNX file, derived from its key.

    ``fr_FR-siwis-medium`` -> ``fr/fr_FR/siwis/medium/fr_FR-siwis-medium.onnx``
    """
    region, _, rest = key.partition("-")
    quality = rest.rsplit("-", 1)[-1]
    name = rest[: -(len(quality) + 1)]
    family = region.split("_")[0]
    return f"https://huggingface.co/rhasspy/piper-voices/resolve/main/{family}/{region}/{name}/{quality}/{key}.onnx"
