"""Piper — the MIT-licensed local voice engine for every non-English language.

Phonon's only permissively-licensed checkpoint is English, so ClearVoice voices
French, German, Japanese, Thai and the rest with Piper: an ONNX runtime (MIT)
plus one voice model per language (~60–120 MB, downloaded once, cached next to
the plugin's data directory).

The download is the single network call this engine makes, it fetches weights
only, and it happens the first time a voice is used.
"""

from __future__ import annotations

import hashlib
import os
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from . import audio, langs


class PiperError(RuntimeError):
    """Message is safe to show to the user."""


#: Some Piper voices phonemise with an optional package. Name it precisely
#: instead of saying "the voice failed" — the user can then fix it in one line.
MISSING_PHONEMIZER_HINTS = {
    "pyopenjtalk": (
        "Japanese needs the 'pyopenjtalk' phonemizer, and it has no prebuilt wheel: "
        "run `pip install pyopenjtalk` (it compiles from source, so it needs cmake and a C++ compiler)."
    ),
    "tltk": "Thai needs its phonemizer: run `pip install tltk pandas requests unicode-rbnf`.",
    "unicode_rbnf": "Thai needs its phonemizer: run `pip install tltk pandas requests unicode-rbnf`.",
    "pandas": "Thai needs its phonemizer: run `pip install tltk pandas requests unicode-rbnf`.",
    "requests": "Thai needs its phonemizer: run `pip install tltk pandas requests unicode-rbnf`.",
}


def _missing_phonemizer(exc: BaseException) -> str | None:
    """Find a ModuleNotFoundError in the chain and explain what to install."""
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, ModuleNotFoundError):
            name = (getattr(current, "name", "") or str(current)).split(".")[0]
            if name in MISSING_PHONEMIZER_HINTS:
                return MISSING_PHONEMIZER_HINTS[name]
        current = current.__cause__ or current.__context__
    return None


_lock = threading.Lock()
_loaded: dict[str, object] = {}


def models_dir() -> Path:
    from . import runtime

    path = runtime.data_dir() / "models" / "piper"
    path.mkdir(parents=True, exist_ok=True)
    return path


def available() -> bool:
    try:
        import piper  # noqa: F401
    except Exception:
        return False
    return True


_SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")


def _http_url(url: str) -> str:
    """The voice URL proven to be http(s) before urllib opens it.

    ``urlopen`` reads a ``file://`` URL as happily as an ``https://`` one, and this download writes what it
    read into the model cache — a substituted scheme would install a local file as a voice model, or copy a
    local file into a place the runtime loads. The guard is cheap and sits at the one call that fetches
    anything; bandit's B310 is silenced there with this guard as the reason.
    """
    if urllib.parse.urlsplit(url).scheme not in ("http", "https"):
        raise PiperError("The voice URL was not an http(s) address, so nothing was downloaded.")
    return url


def _download(url: str, target: Path) -> None:
    """Stream one file to a temp sibling, verify it, then rename.

    Verification: the pinned revision fixes *which* files, and Hugging Face
    publishes the sha256 of every LFS object in ``x-linked-etag``. When that
    header is a digest we compare it with what actually arrived, so a corrupted
    or substituted download is refused instead of loaded by the model runtime.
    Config JSON files are not LFS objects and arrive without a digest; those are
    covered by the revision pin alone.
    """
    if target.exists() and target.stat().st_size > 0:
        return
    tmp = target.with_suffix(target.suffix + ".part")
    request = urllib.request.Request(_http_url(url), headers={"User-Agent": "ClearVoice/0.3.0"})
    digest = hashlib.sha256()
    expected = ""
    expected_size = 0
    try:
        with urllib.request.urlopen(request, timeout=120) as response:  # nosec B310 — _http_url() refuses any scheme but http/https
            etag = str(response.headers.get("x-linked-etag") or "").strip().strip('"').lower()
            if _SHA256_HEX.match(etag):
                expected = etag
            size_header = str(response.headers.get("x-linked-size") or "").strip()
            if size_header.isdigit():
                expected_size = int(size_header)
            with open(tmp, "wb") as handle:
                while True:
                    chunk = response.read(1 << 20)
                    if not chunk:
                        break
                    digest.update(chunk)
                    handle.write(chunk)
    except (urllib.error.URLError, TimeoutError) as exc:
        tmp.unlink(missing_ok=True)
        raise PiperError(
            "The voice file could not be downloaded. Check the connection, then try again."
        ) from exc
    size = tmp.stat().st_size
    if size < 1024:
        tmp.unlink(missing_ok=True)
        raise PiperError("The voice download was incomplete. Try again.")
    if expected_size and size != expected_size:
        tmp.unlink(missing_ok=True)
        raise PiperError(
            f"The voice file arrived incomplete ({size} of {expected_size} bytes). Try again."
        )
    if expected and digest.hexdigest() != expected:
        tmp.unlink(missing_ok=True)
        raise PiperError(
            "The voice file did not match the published checksum, so it was discarded. "
            "Nothing was installed from it."
        )
    os.replace(tmp, target)


def ensure_voice(key: str) -> tuple[Path, Path]:
    """Download (once) and return the ONNX model and its config."""
    meta = langs.piper_voice(key)
    if meta is None:
        raise PiperError(f"Unknown voice '{key}'.")
    base = models_dir()
    model = base / f"{key}.onnx"
    config = base / f"{key}.onnx.json"
    url = langs.piper_url(key)
    _download(url, model)
    _download(url + ".json", config)
    return model, config


def _load(key: str):
    cached = _loaded.get(key)
    if cached is not None:
        return cached
    try:
        from piper import PiperVoice
    except Exception as exc:  # pragma: no cover - install dependent
        raise PiperError(
            "The on-device non-English voice engine is not installed. Run "
            "`hermes plugins validate <plugin> --install-deps`, then reload ClearVoice."
        ) from exc
    model, _config = ensure_voice(key)
    try:
        voice = PiperVoice.load(str(model))
    except Exception as exc:
        raise PiperError("The voice file could not be loaded. Remove it from the plugin's models folder and try again.") from exc
    with _lock:
        _loaded[key] = voice
    return voice


def voices(language_code: str | None = None) -> list[dict]:
    """The picker's list: key, label, quality, size, speakers."""
    out = []
    for meta in langs.piper_voices(language_code):
        label = f"{meta['name']} ({meta['region']}, {meta['quality']})"
        out.append({**meta, "engine": "piper", "label": label})
    return out


def synthesize(text: str, key: str, language_code: str | None = None) -> tuple[bytes, int, str]:
    """Synthesize into WAV bytes. Returns (wav, sample_rate, voice_key)."""
    from . import langs as _langs

    language = _langs.get(language_code)
    meta = _langs.piper_voice(key)
    if meta is None or meta.get("family") != language.code:
        # Fall back to that language's default voice rather than speaking French
        # with a Japanese model.
        key = language.default_voice
        meta = _langs.piper_voice(key)
    voice = _load(key)
    try:
        chunks = [chunk.audio_int16_bytes for chunk in voice.synthesize(text)]
    except Exception as exc:
        hint = _missing_phonemizer(exc)
        if hint:
            raise PiperError(hint) from exc
        raise PiperError("The voice could not speak that sentence. Try again, or edit the text.") from exc
    pcm = b"".join(chunks)
    if not pcm:
        raise PiperError("The voice produced no audio. Try again.")
    sample_rate = int(getattr(voice.config, "sample_rate", 22050))
    wav = audio.pcm16_to_wav_bytes(pcm, sample_rate)
    return wav, sample_rate, key


def reset() -> None:
    with _lock:
        _loaded.clear()
