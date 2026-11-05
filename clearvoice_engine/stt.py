"""Speech to text: local faster-whisper by default, Gradium cloud on request."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Callable

import numpy as np

from . import audio, cloud
from .lexicon import Lexicon
from .settings import Settings


class TranscriptionError(RuntimeError):
    """Message is safe to show to the user."""


class NoSpeechDetected(TranscriptionError):
    """The clip contained no usable speech."""


@dataclass
class TranscriptionResult:
    text: str
    backend: str
    language: str
    model: str = ""
    duration_s: float = 0.0
    corrections_applied: int = 0


_local_models: dict[tuple[str, str], object] = {}
_local_lock = threading.Lock()


def local_model_available(model_name: str) -> bool:
    try:
        import faster_whisper  # noqa: F401
    except Exception:
        return False
    return bool(model_name)


def _load_local_model(model_name: str, device: str = "cpu", compute_type: str = "int8"):
    """Load (and cache) one faster-whisper model. Never downloads on import."""
    try:
        from faster_whisper import WhisperModel
    except Exception as exc:  # pragma: no cover - depends on install state
        raise TranscriptionError(
            "The on-device speech model isn't installed. Run "
            "`hermes plugins validate <plugin> --install-deps`, then reload ClearVoice."
        ) from exc

    key = (model_name, device)
    with _local_lock:
        model = _local_models.get(key)
        if model is None:
            try:
                model = WhisperModel(model_name, device=device, compute_type=compute_type)
            except Exception as exc:
                raise TranscriptionError(
                    f"The on-device model '{model_name}' could not be loaded. Check the local STT model "
                    "setting, or switch to a smaller model such as tiny.en."
                ) from exc
            _local_models[key] = model
    return model


def reset_local_models() -> None:
    """Drop cached models (tests, and after a settings change)."""
    with _local_lock:
        _local_models.clear()


def transcribe_local(
    samples: np.ndarray,
    settings: Settings,
    *,
    model_name: str | None = None,
    hotwords: str | None = None,
    initial_prompt: str | None = None,
) -> TranscriptionResult:
    model_name = model_name or settings.stt_model
    model = _load_local_model(model_name)
    try:
        segments, info = model.transcribe(
            samples,
            beam_size=1,
            language=settings.language or None,
            vad_filter=True,
            condition_on_previous_text=False,
            hotwords=hotwords or None,
            initial_prompt=initial_prompt or None,
        )
        text = " ".join(segment.text.strip() for segment in segments).strip()
    except Exception as exc:
        raise TranscriptionError("The on-device transcription failed on that clip. Try again.") from exc
    return TranscriptionResult(
        text=text,
        backend="local",
        language=getattr(info, "language", settings.language) or settings.language,
        model=model_name,
        duration_s=float(getattr(info, "duration", 0.0) or 0.0),
    )


def transcribe_with_model(
    clip_or_samples: bytes | np.ndarray,
    settings: Settings,
    *,
    model_name: str | None = None,
    hotwords: str | None = None,
    initial_prompt: str | None = None,
) -> TranscriptionResult:
    """Local transcription with an explicit model / vocabulary bias (bench, dictionary)."""
    samples = (
        audio.decode_to_mono16k(clip_or_samples)
        if isinstance(clip_or_samples, (bytes, bytearray))
        else np.asarray(clip_or_samples, dtype=np.float32)
    )
    if not audio.looks_like_speech(samples):
        raise NoSpeechDetected("I didn't catch that - try again.")
    result = transcribe_local(
        samples,
        settings,
        model_name=model_name,
        hotwords=hotwords,
        initial_prompt=initial_prompt,
    )
    if not result.text:
        raise NoSpeechDetected("I didn't catch that - try again.")
    return result


def transcribe_cloud(samples: np.ndarray, settings: Settings, get_key: Callable[[], str | None]) -> TranscriptionResult:
    wav_bytes = audio.float32_to_wav_bytes(samples, audio.TARGET_RATE)
    text = cloud.transcribe(wav_bytes, api_key=cloud.require_key(get_key()), language=settings.language)
    return TranscriptionResult(
        text=text,
        backend="gradium",
        language=settings.language,
        model="gradium",
        duration_s=samples.size / float(audio.TARGET_RATE),
    )


def transcribe(
    clip_or_samples: bytes | np.ndarray,
    settings: Settings,
    *,
    get_key: Callable[[], str | None] | None = None,
    lexicon: Lexicon | None = None,
) -> TranscriptionResult:
    """Turn a recorded clip into text, or explain in plain language why not.

    The cloud path is refused before any network call unless the user both
    enabled cloud speech *and* selected Gradium for transcription. When a
    personal dictionary is given, its words bias the recogniser (hotwords) and
    its learned corrections are applied to the result.
    """
    samples = (
        audio.decode_to_mono16k(clip_or_samples)
        if isinstance(clip_or_samples, (bytes, bytearray))
        else np.asarray(clip_or_samples, dtype=np.float32)
    )
    hotwords = lexicon.hotwords() if lexicon is not None else None

    if settings.stt_backend == "gradium":
        if not settings.allow_cloud:
            raise cloud.CloudDisabled(
                "Cloud speech is off. Turn on 'Allow cloud speech' in Settings > Plugins > ClearVoice, "
                "or switch the transcript backend to on-device."
            )
        if not audio.looks_like_speech(samples):
            raise NoSpeechDetected("I didn't catch that - try again.")
        result = transcribe_cloud(samples, settings, get_key or (lambda: None))
    else:
        if not audio.looks_like_speech(samples):
            raise NoSpeechDetected("I didn't catch that - try again.")
        result = transcribe_local(samples, settings, hotwords=hotwords)

    if not result.text:
        raise NoSpeechDetected("I didn't catch that - try again.")
    if lexicon is not None:
        corrected, applied = lexicon.apply(result.text)
        result.text = corrected
        result.corrections_applied = len(applied)
    return result
