"""Text to speech: Phonon for English, Piper for everything else, cloud on request.

* **English** — Phonon 31m (Gradium, Apache-2.0) via ``ptts``, any of the ~37
  catalog voices, synthesised into a NumPy array and wrapped as WAV in memory.
* **Every other language** — Piper (MIT runtime) with a per-language voice model.
  Phonon's multilingual checkpoint is CC BY-NC, so it is never used here.
* **Cloud** — Gradium, only when the user enabled it *and* selected it.

The CC BY-NC 40m Phonon models are not loaded, not downloaded, not referenced.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Callable

from . import audio, cloud, langs, piper
from .settings import Settings

PHONON_DEFAULT_VOICE = "default"

#: Phonon catalog voices are grouped by these language codes.
PHONON_LANGUAGES = ("en", "fr", "de", "es", "pt")


class SynthesisError(RuntimeError):
    """Message is safe to show to the user."""


@dataclass
class SynthesisResult:
    wav: bytes
    backend: str
    voice: str
    sample_rate: int
    duration_s: float
    text: str


_phonon_models: dict[str, object] = {}
_phonon_lock = threading.Lock()
_catalog: list[dict] = []
_catalog_at = 0.0
CATALOG_TTL_SECONDS = 600


def phonon_voices() -> list[dict]:
    """Catalog voices usable on-device, with their language.

    The catalog is fetched once (it is a small JSON) and cached in-process; a
    failure degrades to the checkpoint's own default voice rather than an error.
    """
    global _catalog, _catalog_at
    import time

    if _catalog and time.time() - _catalog_at < CATALOG_TTL_SECONDS:
        return list(_catalog)
    try:
        import ptts

        catalog = ptts.catalog_voices()
    except Exception:
        return [{"voice": PHONON_DEFAULT_VOICE, "name": "Default", "language": "en", "engine": "phonon"}]
    out = []
    for entry in catalog:
        out.append(
            {
                "voice": entry.get("name") or entry.get("voice_id"),
                "voice_id": entry.get("voice_id", ""),
                "name": entry.get("name", ""),
                "language": entry.get("language", "en"),
                "description": entry.get("description", ""),
                "engine": "phonon",
            }
        )
    _catalog = out
    _catalog_at = time.time()
    return list(out)


def phonon_available() -> bool:
    try:
        import ptts  # noqa: F401
    except Exception:
        return False
    return True


def _load_phonon():
    """Load the English Phonon checkpoint (the only permissive one).

    ``ptts.TTS(lang=…)`` does **not** select a language model — it loads this
    same checkpoint and only changes text normalisation — so the language is a
    normalisation hint here, never a promise that the voice speaks it.
    """
    try:
        import ptts
    except Exception as exc:  # pragma: no cover - depends on install state
        raise SynthesisError(
            "The on-device voice model isn't installed. Run "
            "`hermes plugins validate <plugin> --install-deps`, then reload ClearVoice."
        ) from exc

    with _phonon_lock:
        model = _phonon_models.get("en")
        if model is None:
            try:
                model = ptts.TTS(lang="en")
            except Exception as exc:
                raise SynthesisError(
                    "The on-device Phonon model could not be loaded. It is downloaded once "
                    "on first use - check the connection, then try again."
                ) from exc
            _phonon_models["en"] = model
    return model


def reset_phonon_models() -> None:
    with _phonon_lock:
        _phonon_models.clear()


def voices_for(language_code: str) -> list[dict]:
    """Every voice available for a language, on-device first."""
    language = langs.get(language_code)
    if language.code == "en" and phonon_available():
        # The catalog lists voices for several languages; Phonon 31m is the
        # English checkpoint, so offer only the ones that belong to it.
        english = [v for v in phonon_voices() if v.get("language") in (None, "", "en")]
        if english:
            return english
    return piper.voices(language.code)


def synthesize_phonon(text: str, settings: Settings, voice: str | None = None, seed: int | None = None) -> SynthesisResult:
    model = _load_phonon()
    available = {v["voice"] for v in phonon_voices()}
    wanted = (voice or settings.voice or PHONON_DEFAULT_VOICE).strip()
    chosen = wanted if wanted in available else PHONON_DEFAULT_VOICE
    try:
        samples = model.synth(text, voice=chosen, seed=seed)
        sample_rate = int(model.sample_rate)
    except Exception as exc:
        raise SynthesisError("The on-device voice could not speak that sentence. Try again, or edit the text.") from exc
    wav = audio.float32_to_wav_bytes(samples, sample_rate)
    return SynthesisResult(
        wav=wav,
        backend="phonon",
        voice=chosen,
        sample_rate=sample_rate,
        duration_s=audio.wav_duration_seconds(wav),
        text=text,
    )


def synthesize_piper(text: str, settings: Settings, voice: str | None = None) -> SynthesisResult:
    key = (voice or settings.voice or settings.language_info.default_voice).strip()
    try:
        wav, sample_rate, chosen = piper.synthesize(text, key, settings.language)
    except piper.PiperError as exc:
        raise SynthesisError(str(exc)) from exc
    return SynthesisResult(
        wav=wav,
        backend="piper",
        voice=chosen,
        sample_rate=sample_rate,
        duration_s=audio.wav_duration_seconds(wav),
        text=text,
    )


def synthesize_cloud(
    text: str,
    settings: Settings,
    get_key: Callable[[], str | None],
    voice: str | None = None,
) -> SynthesisResult:
    wav = cloud.synthesize(
        text,
        api_key=cloud.require_key(get_key()),
        voice_id=voice or settings.gradium_voice_id,
        language=settings.language,
    )
    return SynthesisResult(
        wav=wav,
        backend="gradium",
        voice=voice or settings.gradium_voice_id or cloud.DEFAULT_VOICE_ID,
        sample_rate=audio.wav_sample_rate(wav),
        duration_s=audio.wav_duration_seconds(wav),
        text=text,
    )


MAX_SPEECH_CHARS = 4000
CHUNK_CHARS = 280


def _chunk_text(text: str, limit: int = CHUNK_CHARS) -> list[str]:
    """Split at sentence boundaries so a paragraph can be read aloud."""
    import re

    sentences = re.split(r"(?<=[.!?;:])\s+", text)
    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        while len(sentence) > limit:
            cut = sentence.rfind(" ", 0, limit) or limit
            if current:
                chunks.append(current)
                current = ""
            chunks.append(sentence[:cut].strip())
            sentence = sentence[cut:].strip()
        if not sentence:
            continue
        if current and len(current) + 1 + len(sentence) > limit:
            chunks.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        chunks.append(current)
    return [c for c in chunks if c]


def synthesize(
    text: str,
    settings: Settings,
    *,
    backend: str | None = None,
    voice: str | None = None,
    get_key: Callable[[], str | None] | None = None,
    seed: int | None = None,
) -> SynthesisResult:
    """Speak ``text`` and return the audio bytes. Nothing is written to disk."""
    spoken = " ".join(str(text or "").split())
    if not spoken:
        raise SynthesisError("There is nothing to speak yet.")
    if len(spoken) > MAX_SPEECH_CHARS:
        raise SynthesisError("That is too long to speak in one go. Shorten it to a few paragraphs.")

    if len(spoken) > CHUNK_CHARS:
        parts = [
            synthesize(chunk, settings, backend=backend, voice=voice, get_key=get_key, seed=seed)
            for chunk in _chunk_text(spoken)
        ]
        if not parts:
            raise SynthesisError("There is nothing to speak yet.")
        wav = audio.concat_wavs([part.wav for part in parts])
        return SynthesisResult(
            wav=wav,
            backend=parts[0].backend,
            voice=parts[0].voice,
            sample_rate=parts[0].sample_rate,
            duration_s=audio.wav_duration_seconds(wav),
            text=spoken,
        )

    chosen = (backend or settings.resolved_tts_engine or "auto").strip().lower()
    if chosen not in ("phonon", "piper", "gradium"):
        chosen = settings.resolved_tts_engine

    if chosen == "phonon" and settings.language != "en":
        # An English checkpoint reading French is worse than saying so.
        raise SynthesisError(
            f"Phonon only speaks English. Choose 'auto' or the Piper voice for "
            f"{settings.language_info.label}, or switch the voice backend to Gradium cloud."
        )

    if chosen == "gradium":
        if not settings.allow_cloud:
            raise cloud.CloudDisabled(
                "Cloud speech is off. Turn on 'Allow cloud speech' in Settings > Plugins > ClearVoice, "
                "or switch the voice backend to on-device."
            )
        return synthesize_cloud(spoken, settings, get_key or (lambda: None), voice)

    if chosen == "piper":
        return synthesize_piper(spoken, settings, voice)

    return synthesize_phonon(spoken, settings, voice, seed=seed)
