"""Optional Gradium cloud speech — off unless the user turns it on.

Endpoints are the public, documented Gradium REST API:

    POST https://api.gradium.ai/api/post/speech/tts   (raw audio back)
    POST https://api.gradium.ai/api/post/speech/asr   (NDJSON transcript)

Transport is the standard library's ``urllib`` so the plugin adds no HTTP
dependency, and every call is a single request/response with a timeout — no
sockets, no keep-alive, no background work. The API key is read per call from
the caller's secret getter and is never logged, echoed in an error, or written
anywhere.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

GRADIUM_TTS_URL = "https://api.gradium.ai/api/post/speech/tts"
GRADIUM_STT_URL = "https://api.gradium.ai/api/post/speech/asr"
DEFAULT_VOICE_ID = "YTpq7expH9539ERJ"
USER_AGENT = "ClearVoice/0.1.0 (+hermes-plugin)"


class CloudDisabled(RuntimeError):
    """The user has not enabled cloud speech."""


class CloudNotConfigured(RuntimeError):
    """Cloud speech is enabled/selected but there is no API key."""


class CloudError(RuntimeError):
    """The cloud call failed. Message is safe to show to the user."""


def require_key(api_key: str | None) -> str:
    key = (api_key or "").strip()
    if not key:
        raise CloudNotConfigured(
            "Gradium is selected but no API key is set. Add one in "
            "Settings > Plugins > ClearVoice, or switch the backend to on-device."
        )
    return key


def _http_url(url: str) -> str:
    """The endpoint proven to be http(s) before urllib opens it.

    ``urlopen`` reads a ``file://`` URL as happily as an ``https://`` one. The URLs here are built by this
    module from a constant, so nothing today can pass another scheme — but this is the one place an
    utterance and its transcript leave the machine, and a read that became a local-file read would send the
    wrong bytes to a paid API. The scheme is therefore checked at the choke point, and bandit's B310 is
    silenced there with this guard as its reason rather than in a baseline.
    """
    if urllib.parse.urlsplit(url).scheme not in ("http", "https"):
        raise CloudError("The speech endpoint was not an http(s) address, so nothing was sent.")
    return url


def _post(url: str, *, key: str, body: bytes, content_type: str, timeout: float) -> bytes:
    request = urllib.request.Request(_http_url(url), data=body, method="POST")
    request.add_header("x-api-key", key)
    request.add_header("Content-Type", content_type)
    request.add_header("Accept", "*/*")
    request.add_header("User-Agent", USER_AGENT)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # nosec B310 — _http_url() refuses any scheme but http/https
            return response.read()
    except urllib.error.HTTPError as exc:
        status = exc.code
        if status in (401, 403):
            raise CloudError("Gradium refused the API key. Check the key in Settings > Plugins > ClearVoice.") from None
        if status == 429:
            raise CloudError("Gradium is rate-limiting this key. Try again in a moment.") from None
        raise CloudError(f"Gradium returned an error ({status}). Nothing was played or saved.") from None
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        raise CloudError(f"Could not reach Gradium ({reason}). Switch to the on-device backend to keep working.") from None
    except TimeoutError:
        raise CloudError("Gradium did not answer in time. Switch to the on-device backend to keep working.") from None


def synthesize(text: str, *, api_key: str, voice_id: str = "", language: str = "en", timeout: float = 25.0) -> bytes:
    """Return WAV bytes for ``text``. Nothing is written to disk."""
    key = require_key(api_key)
    payload = {
        "text": text,
        "voice_id": (voice_id or DEFAULT_VOICE_ID),
        "output_format": "wav",
        "only_audio": True,
    }
    data = json.dumps(payload).encode("utf-8")
    audio = _post(GRADIUM_TTS_URL, key=key, body=data, content_type="application/json", timeout=timeout)
    if not audio:
        raise CloudError("Gradium returned no audio. Nothing was played or saved.")
    return audio


def transcribe(wav_bytes: bytes, *, api_key: str, language: str = "en", timeout: float = 30.0) -> str:
    """Return the transcript of a WAV clip. The clip is not stored anywhere."""
    key = require_key(api_key)
    config = urllib.parse.quote(json.dumps({"language": language or "en"}))
    url = f"{GRADIUM_STT_URL}?json_config={config}"
    raw = _post(url, key=key, body=wav_bytes, content_type="audio/wav", timeout=timeout)

    parts: list[str] = []
    for line in raw.decode("utf-8", "replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except ValueError:
            continue
        kind = message.get("type")
        if kind in ("text", "end_text") and message.get("text"):
            parts.append(str(message["text"]).strip())
        elif kind == "error":
            raise CloudError("Gradium could not transcribe that clip. Try again, or use the on-device backend.")
    return " ".join(p for p in parts if p).strip()
