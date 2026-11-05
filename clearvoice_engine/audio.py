"""In-memory audio plumbing.

Every function in this module takes bytes and returns bytes/arrays. Nothing is
written to disk: no WAV cache, no temp recording, no logging of audio. That is
the load-bearing privacy property of ClearVoice, so it is enforced here (the
only place allowed to touch audio bytes) rather than at the call sites.
"""

from __future__ import annotations

import io
import shutil
import subprocess
import wave

import numpy as np

#: Sample rate every STT backend expects.
TARGET_RATE = 16000

#: A held push-to-talk clip longer than this is truncated, not stored.
MAX_UTTERANCE_SECONDS = 60
MAX_INPUT_BYTES = 12 * 1024 * 1024  # ~12 MB of opus is minutes of speech

#: Below this RMS the clip is treated as silence (no model call at all).
SILENCE_RMS = 0.004


class AudioError(RuntimeError):
    """Raised when a clip cannot be decoded. Message is user-facing."""


def _as_float32(samples: np.ndarray) -> np.ndarray:
    arr = np.asarray(samples)
    if arr.dtype == np.float32:
        return arr.reshape(-1)
    if arr.dtype == np.int16:
        return (arr.astype(np.float32) / 32768.0).reshape(-1)
    raise AudioError("Unsupported audio sample format.")


def _decode_wav(data: bytes) -> tuple[np.ndarray, int]:
    with wave.open(io.BytesIO(data), "rb") as handle:
        channels = handle.getnchannels()
        width = handle.getsampwidth()
        rate = handle.getframerate()
        frames = handle.readframes(handle.getnframes())
    if width == 2:
        arr = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0
    elif width == 4:
        # 32-bit WAV is almost always float32; 24-bit is not supported.
        arr = np.frombuffer(frames, dtype="<f4").astype(np.float32)
    elif width == 1:
        arr = (np.frombuffer(frames, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    else:
        raise AudioError("Unsupported WAV sample width.")
    if channels > 1:
        arr = arr.reshape(-1, channels).mean(axis=1)
    return arr.reshape(-1), rate


def _resample(samples: np.ndarray, src_rate: int, dst_rate: int) -> np.ndarray:
    """Linear resampling — adequate for speech at 16 kHz, no dependency."""
    if src_rate == dst_rate or samples.size == 0:
        return samples
    duration = samples.size / float(src_rate)
    count = max(1, int(round(duration * dst_rate)))
    src_idx = np.linspace(0.0, samples.size - 1, count, dtype=np.float64)
    return np.interp(src_idx, np.arange(samples.size, dtype=np.float64), samples).astype(np.float32)


def decode_to_mono16k(data: bytes, *, ffmpeg: str | None = None) -> np.ndarray:
    """Decode any browser-recorded clip into mono float32 at 16 kHz.

    WAV is decoded with the standard library so the pipeline works on machines
    without ffmpeg; Opus/WebM/Ogg (what ``MediaRecorder`` produces) goes through
    ffmpeg over pipes — stdin in, stdout out, no temporary file anywhere.
    """
    if not data:
        raise AudioError("The recording was empty. Hold the button while you speak.")
    if len(data) > MAX_INPUT_BYTES:
        raise AudioError("That recording was too long. Try a shorter sentence.")

    if data[:4] == b"RIFF":
        samples, rate = _decode_wav(data)
        return _resample(samples, rate, TARGET_RATE)

    binary = ffmpeg or shutil.which("ffmpeg")
    if not binary:
        raise AudioError(
            "ClearVoice needs ffmpeg to read this recording format. "
            "Install ffmpeg, or use a browser build that records WAV."
        )
    try:
        proc = subprocess.run(
            [
                binary, "-hide_banner", "-loglevel", "error",
                "-i", "pipe:0",
                "-f", "f32le", "-acodec", "pcm_f32le",
                "-ac", "1", "-ar", str(TARGET_RATE), "pipe:1",
            ],
            input=data,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise AudioError(f"Could not read the recording: {exc}") from exc
    if proc.returncode != 0 or not proc.stdout:
        raise AudioError("I couldn't read that recording. Try again, a little closer to the microphone.")
    return np.frombuffer(proc.stdout, dtype="<f4").astype(np.float32)


def rms(samples: np.ndarray) -> float:
    if samples.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(samples, dtype=np.float64))))


def looks_like_speech(samples: np.ndarray) -> bool:
    """Cheap energy gate so silence never reaches a model."""
    if samples.size < TARGET_RATE // 10:  # under 100 ms
        return False
    return rms(samples) >= SILENCE_RMS


def float32_to_wav_bytes(samples: np.ndarray, sample_rate: int) -> bytes:
    """Package synthesized speech as WAV bytes held in memory."""
    arr = np.clip(_as_float32(samples), -1.0, 1.0)
    pcm = (arr * 32767.0).astype("<i2").tobytes()
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(int(sample_rate))
        handle.writeframes(pcm)
    return buffer.getvalue()


def wav_duration_seconds(wav_bytes: bytes) -> float:
    try:
        with wave.open(io.BytesIO(wav_bytes), "rb") as handle:
            rate = handle.getframerate() or 1
            return handle.getnframes() / float(rate)
    except (wave.Error, EOFError):
        return 0.0


def wav_sample_rate(wav_bytes: bytes) -> int:
    try:
        with wave.open(io.BytesIO(wav_bytes), "rb") as handle:
            return int(handle.getframerate() or 0)
    except (wave.Error, EOFError):
        return 0
