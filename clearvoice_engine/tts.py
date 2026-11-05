"""Text to speech: on-device Phonon 31m by default, Gradium cloud on request.

Phonon (Gradium's Apache-2.0 31m English model, run through the ``ptts``
runtime) synthesizes into a NumPy array that is turned into WAV bytes in
memory. The CC BY-NC 40m models are never loaded, never referenced.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Callable

from . import audio, cloud
from .settings import Settings

PHONON_DEFAULT_VOICE = "default"


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


def phonon_available() -> bool:
    try:
        import ptts  # noqa: F401
    except Exception:
        return False
    return True


def _load_phonon(language: str = "en"):
    try:
        import ptts
    except Exception as exc:  # pragma: no cover - depends on install state
        raise SynthesisError(
            "The on-device voice model isn't installed. Run "
            "`hermes plugins validate <plugin> --install-deps`, then reload ClearVoice."
        ) from exc

    lang = language if language in ("en", "fr", "de", "es", "pt") else "en"
    with _phonon_lock:
        model = _phonon_models.get(lang)
        if model is None:
            try:
                model = ptts.TTS(lang=lang)
            except Exception as exc:
                raise SynthesisError(
                    "The on-device Phonon model could not be loaded. It is downloaded once "
                    "on first use - check the connection, then try again."
                ) from exc
            _phonon_models[lang] = model
    return model


def reset_phonon_models() -> None:
    with _phonon_lock:
        _phonon_models.clear()


def phonon_voices(language: str = "en") -> list[str]:
    model = _load_phonon(language)
    try:
        return [str(v) for v in model.voices]
    except Exception:  # pragma: no cover - defensive
        return [PHONON_DEFAULT_VOICE]


def synthesize_phonon(text: str, settings: Settings, voice: str | None = None) -> SynthesisResult:
    model = _load_phonon(settings.language)
    voices = phonon_voices(settings.language)
    wanted = (voice or settings.phonon_voice or PHONON_DEFAULT_VOICE).strip()
    chosen = wanted if wanted in voices else (PHONON_DEFAULT_VOICE if PHONON_DEFAULT_VOICE in voices else voices[0])
    try:
        samples = model.synth(text, voice=chosen)
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


def synthesize(
    text: str,
    settings: Settings,
    *,
    backend: str | None = None,
    voice: str | None = None,
    get_key: Callable[[], str | None] | None = None,
) -> SynthesisResult:
    """Speak ``text`` and return the audio bytes. Nothing is written to disk."""
    spoken = " ".join(str(text or "").split())
    if not spoken:
        raise SynthesisError("There is nothing to speak yet.")
    if len(spoken) > 600:
        raise SynthesisError("That message is too long to speak in one go. Shorten it a little.")

    chosen = (backend or settings.tts_backend or "phonon").strip().lower()
    if chosen not in ("phonon", "gradium"):
        chosen = "phonon"

    if chosen == "gradium":
        if not settings.allow_cloud:
            raise cloud.CloudDisabled(
                "Cloud speech is off. Turn on 'Allow cloud speech' in Settings > Plugins > ClearVoice, "
                "or switch the voice backend to on-device."
            )
        return synthesize_cloud(spoken, settings, get_key or (lambda: None), voice)

    return synthesize_phonon(spoken, settings, voice)
