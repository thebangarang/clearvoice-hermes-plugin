"""ClearVoice REST backend — the Desktop pane's only door.

Mounted by Hermes at ``/api/plugins/clearvoice/`` and reached from the pane with
``ctx.rest('/transcribe')``, so the namespace is scoped by construction.

Route map
---------
``GET  /status``            settings, backend labels, retention line
``POST /transcribe``        clip (base64) -> transcript + proposed sentence
``POST /clarify``           transcript -> proposed sentence
``POST /speak``             sentence -> audio (base64), in memory
``GET  /pending``           audio the agent asked the pane to speak, once
``POST /session/clear``     drop the session's captions and pending audio
``GET  /phrases``           the user's saved phrases
``POST /phrases``           explicitly save one phrase
``DELETE /phrases/{id}``    remove one phrase

Nothing in this module writes audio or transcripts anywhere. The only file it
can touch is ``<plugin data dir>/phrases.json``, and only through an explicit
``POST /phrases``.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import logging
import sys
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

_ROOT = str(Path(__file__).resolve().parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from clearvoice_engine import audio, cloud, intent, langs, piper, runtime, stt, tts  # noqa: E402
from clearvoice_engine.settings import Settings  # noqa: E402

logger = logging.getLogger(__name__)

router = APIRouter()

PLUGIN_ID = "clearvoice"
GRADIUM_KEY_ENV = "CLEARVOICE_GRADIUM_API_KEY"
MAX_B64_CHARS = 20 * 1024 * 1024


# ---------------------------------------------------------------------------
# Settings / secrets
# ---------------------------------------------------------------------------


def _get_secret(name: str) -> str | None:
    try:
        from agent.secret_scope import get_secret

        value = get_secret(name)
        return str(value).strip() if value else None
    except Exception:
        return None


def _settings(overrides: dict[str, Any] | None = None) -> Settings:
    mapping: dict[str, Any] = {}
    try:
        from hermes_cli.config import load_config_readonly

        config = load_config_readonly() or {}
        mapping = (
            (config.get("plugins") or {}).get("entries", {}).get(PLUGIN_ID, {}).get("settings") or {}
        )
    except Exception as exc:  # older core, or config unreadable
        logger.debug("clearvoice: settings unavailable: %s", exc)
    # Per-request choices from the pane (language, voice, rewrite style) win over
    # the saved settings for that one request. The pane persists its own choice in
    # ctx.storage, so the plugin never writes config.yaml.
    if overrides:
        for key in ("language", "voice", "rewrite_style", "stt_backend", "tts_backend", "whisper_model", "phrases_dir"):
            value = overrides.get(key)
            if isinstance(value, str) and value.strip():
                mapping = {**mapping, key: value.strip()}
    return Settings.from_mapping(mapping, has_key=bool(_get_secret(GRADIUM_KEY_ENV)))


def _local_state(settings: Settings) -> dict[str, Any]:
    engine = settings.resolved_tts_engine
    return {
        "local_stt_available": stt.local_model_available(settings.stt_model),
        "local_tts_available": tts.phonon_available() if engine == "phonon" else piper.available(),
        "phonon_available": tts.phonon_available(),
        "piper_available": piper.available(),
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/status")
async def status() -> dict[str, Any]:
    settings = _settings()
    payload = settings.status()
    payload.update(_local_state(settings))
    payload.update(runtime.status_payload())
    folder = settings.phrases_folder()
    payload["phrases_folder"] = str(folder if folder is not None else runtime.data_dir())
    payload["phrases_folder_custom"] = folder is not None
    return payload


@router.get("/languages")
async def languages() -> dict[str, Any]:
    """What the picker offers, and which engine will voice each language."""
    return {"languages": [lang.public() for lang in langs.all_languages()]}


@router.get("/voices")
async def voices(language: str | None = None) -> dict[str, Any]:
    """Every voice available for a language: Phonon catalog (English) or Piper."""
    code = language or _settings().language
    if not language:
        return {"language": code, "voice": _settings().resolved_voice, "voices": tts.voices_for(code)}
    return {"language": langs.get(code).code, "voice": "", "voices": tts.voices_for(code)}


def _decode_clip(payload: dict[str, Any]) -> bytes:
    raw = str(payload.get("audio_b64") or "")
    if not raw:
        raise HTTPException(status_code=400, detail="No audio was sent.")
    if len(raw) > MAX_B64_CHARS:
        raise HTTPException(status_code=413, detail="That recording is too large. Try a shorter sentence.")
    if raw.startswith("data:") and "," in raw:
        raw = raw.split(",", 1)[1]
    try:
        return base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(status_code=400, detail="The recording could not be read.") from None


@router.post("/transcribe")
async def transcribe(payload: dict[str, Any]) -> dict[str, Any]:
    """Clip in, transcript plus proposed sentence out. One round trip."""
    settings = _settings(payload)
    clip = _decode_clip(payload)

    try:
        result = await asyncio.to_thread(
            stt.transcribe,
            clip,
            settings,
            get_key=lambda: _get_secret(GRADIUM_KEY_ENV),
            lexicon=_lexicon(payload),
        )
    except stt.NoSpeechDetected as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except cloud.CloudDisabled as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from None
    except cloud.CloudNotConfigured as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except (cloud.CloudError, stt.TranscriptionError, audio.AudioError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("clearvoice: transcribe failed (%s)", type(exc).__name__)
        raise HTTPException(status_code=500, detail="Transcription failed. Try again.") from None

    proposal = intent.reframe(result.text, settings.rewrite_style)
    runtime.session.add(result.text, proposal.message, result.backend)
    return {
        "transcript": result.text,
        "backend": result.backend,
        "language": result.language,
        "duration_s": round(result.duration_s, 2),
        "corrections_applied": result.corrections_applied,
        "proposal": proposal.public(),
        "status": _settings().status(),
    }


@router.post("/clarify")
async def clarify(payload: dict[str, Any]) -> dict[str, Any]:
    text = str((payload or {}).get("transcript") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Nothing to clarify.")
    proposal = intent.reframe(text, _settings(payload).rewrite_style)
    return {"proposal": proposal.public()}


@router.post("/speak")
async def speak(payload: dict[str, Any]) -> dict[str, Any]:
    """Synthesize one approved sentence. Returns audio as base64, never a file."""
    body = payload or {}
    message = " ".join(str(body.get("message") or "").split())
    if not message:
        raise HTTPException(status_code=400, detail="There is nothing to speak yet.")
    if not body.get("approved", False):
        # The pane must set this after the user presses "Speak it".
        raise HTTPException(status_code=409, detail="Show the sentence and let the user approve it first.")

    settings = _settings(body)
    backend = str(body.get("backend") or settings.tts_backend)
    voice = str(body.get("voice_profile") or body.get("voice") or "") or None

    try:
        result = await asyncio.to_thread(
            tts.synthesize,
            message,
            settings,
            backend=backend,
            voice=voice,
            get_key=lambda: _get_secret(GRADIUM_KEY_ENV),
        )
    except cloud.CloudDisabled as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from None
    except cloud.CloudNotConfigured as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except (cloud.CloudError, tts.SynthesisError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("clearvoice: speak failed (%s)", type(exc).__name__)
        raise HTTPException(status_code=500, detail="The voice failed on that sentence. Try again.") from None

    return {
        "audio_b64": base64.b64encode(result.wav).decode("ascii"),
        "mime": "audio/wav",
        "backend": result.backend,
        "voice": result.voice,
        "sample_rate": result.sample_rate,
        "duration_s": round(result.duration_s, 2),
        "text": result.text,
        "saved": False,
    }


@router.get("/pending")
async def pending() -> dict[str, Any]:
    """Audio the agent queued through ``clearvoice_speak``. Consumed once."""
    item = runtime.outbox.take()
    if item is None:
        return {"pending": False}
    return {
        "pending": True,
        "audio_b64": base64.b64encode(item.wav).decode("ascii"),
        "mime": "audio/wav",
        "text": item.text,
        "backend": item.backend,
    }


@router.post("/session/clear")
async def clear_session() -> dict[str, Any]:
    dropped = runtime.session.clear()
    runtime.outbox.clear()
    return {"cleared": dropped, "retention": "Session only", "message": "Session cleared. Nothing was saved."}


def _phrases(overrides: dict[str, Any] | None = None):
    """The saved-phrase store for the current settings (user folder or data dir)."""
    settings = _settings(overrides)
    folder = settings.phrases_folder()
    return runtime.phrases(folder if folder is not None else runtime.data_dir())


def _lexicon(overrides: dict[str, Any] | None = None):
    """The personal dictionary (hotwords + learned corrections). Local only."""
    settings = _settings(overrides)
    folder = settings.phrases_folder()
    return runtime.lexicon(folder if folder is not None else runtime.data_dir())


@router.get("/dictionary")
async def get_dictionary(phrases_dir: str | None = None) -> dict[str, Any]:
    store = _lexicon({"phrases_dir": phrases_dir} if phrases_dir else None)
    return store.public()


@router.post("/dictionary/terms")
async def add_term(payload: dict[str, Any]) -> dict[str, Any]:
    body = payload or {}
    store = _lexicon(body)
    try:
        added = store.add_term(str(body.get("term") or ""))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    return {"added": added, **store.public()}


@router.delete("/dictionary/terms")
async def remove_term(term: str, phrases_dir: str | None = None) -> dict[str, Any]:
    store = _lexicon({"phrases_dir": phrases_dir} if phrases_dir else None)
    return {"removed": store.remove_term(term), **store.public()}


@router.post("/dictionary/learn")
async def learn_from_edit(payload: dict[str, Any]) -> dict[str, Any]:
    """Learn one heard → meant pair. Refused unless the user enabled learning."""
    body = payload or {}
    if not body.get("learning", False):
        raise HTTPException(status_code=409, detail="Learning from corrections is off. Turn it on in the pane to use it.")
    store = _lexicon(body)
    pairs = store.learn(str(body.get("heard") or ""), str(body.get("said") or ""), enabled=True)
    return {"learned": pairs, **store.public()}


@router.delete("/dictionary/corrections")
async def clear_corrections(phrases_dir: str | None = None) -> dict[str, Any]:
    store = _lexicon({"phrases_dir": phrases_dir} if phrases_dir else None)
    removed = store.clear_corrections()
    return {"removed": removed, **store.public()}


@router.get("/phrases")
async def list_phrases(phrases_dir: str | None = None) -> dict[str, Any]:
    store = _phrases({"phrases_dir": phrases_dir} if phrases_dir else None)
    return {"phrases": [p.public() for p in store.list()], "folder": str(store.path.parent)}


@router.post("/phrases")
async def save_phrase(payload: dict[str, Any]) -> dict[str, Any]:
    body = payload or {}
    if not body.get("explicit", False):
        raise HTTPException(status_code=409, detail="Saving a phrase needs an explicit Save phrase action.")
    store = _phrases(body)
    try:
        phrase = store.save_phrase(str(body.get("text") or ""), str(body.get("label") or ""))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except OSError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Could not write to {store.path.parent}. Check the folder in Settings > Plugins > ClearVoice.",
        ) from exc
    return {"phrase": phrase.public(), "saved_to": str(store.path)}


@router.delete("/phrases/{phrase_id}")
async def delete_phrase(phrase_id: str, phrases_dir: str | None = None) -> dict[str, Any]:
    return {"deleted": _phrases({"phrases_dir": phrases_dir} if phrases_dir else None).delete(phrase_id)}
