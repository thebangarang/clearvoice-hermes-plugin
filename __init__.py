"""ClearVoice — the agent half.

Registers exactly one tool (``clearvoice_speak``) and one slash command
(``/clearvoice``). Everything else lives behind the plugin's own REST backend
(``dashboard/plugin_api.py``), which the Desktop pane calls.

Why the tool refuses by default: a speech bridge that can be told "just say
something" by a model is a way to put words in a disabled user's mouth. So
``clearvoice_speak`` returns a *needs_confirmation* payload carrying the exact
sentence until the caller passes ``confirm_required: false`` — which the pane
does only after the user pressed **Speak it** on a sentence they can see.
"""

from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path

_ROOT = str(Path(__file__).resolve().parent)
if _ROOT not in sys.path:  # both entry points import clearvoice_engine the same way
    sys.path.insert(0, _ROOT)

logger = logging.getLogger(__name__)

PLUGIN_ID = "clearvoice"
GRADIUM_KEY_ENV = "CLEARVOICE_GRADIUM_API_KEY"
MAX_AUDIO_FILE_BYTES = 25 * 1024 * 1024

CLEARVOICE_SPEAK = {
    "name": "clearvoice_speak",
    "description": (
        "Speak one sentence aloud for the user through the ClearVoice pane, using an on-device "
        "voice by default. Use it when the user asks to have something spoken, read out, or repeated, "
        "or after a ClearVoice message has been confirmed. "
        "Confirmation is two-step on purpose: with confirm_required=true (the default) the tool does "
        "NOT speak; it returns the exact sentence plus a needs_confirmation payload so the user can read "
        "it and approve it, and only a second call with confirm_required=false voices it. Never pass "
        "false on your own initiative, and never speak text the user has not seen. "
        "Backends: 'phonon' = on-device Phonon model (default, offline); 'gradium' = cloud, refused unless "
        "the user turned on 'Allow cloud speech'. The audio is delivered to the open ClearVoice pane in "
        "memory and is never written to disk; nothing is sent to any messaging platform."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "The exact sentence to speak. Keep it short and punctuation-clear.",
            },
            "voice_profile": {
                "type": "string",
                "description": "Optional voice name (e.g. 'default', or a Phonon checkpoint voice).",
            },
            "backend": {
                "type": "string",
                "enum": ["phonon", "gradium"],
                "description": "Synthesis backend. Defaults to the user's setting (on-device phonon).",
            },
            "confirm_required": {
                "type": "boolean",
                "description": (
                    "true (default) = return the sentence for the user to approve instead of speaking. "
                    "false = speak it now, only after the user has seen and accepted this exact text."
                ),
            },
            "deliver": {
                "type": "string",
                "enum": ["pane", "file"],
                "description": (
                    "'pane' (default) plays it in the ClearVoice pane and keeps it in memory. "
                    "'file' writes one WAV into the plugin's data directory and returns its path, for a "
                    "video, a podcast or another pipeline — refused unless the user enabled 'Allow speech "
                    "files' in ClearVoice settings."
                ),
            },
        },
        "required": ["text"],
    },
}

CLEARVOICE_TRANSCRIBE = {
    "name": "clearvoice_transcribe",
    "description": (
        "Transcribe one audio file on this machine with the local speech recogniser (no cloud, no "
        "upload) and return the text, plus ClearVoice's cleaned-up sentence when asked. Use it for "
        "dictation, voice notes, meeting snippets, subtitle drafting, or as the first half of a "
        "voice → text → action pipeline. Accepts a path to a WAV/WebM/Opus/MP3 file the user named "
        "explicitly; read-only, and it writes nothing. Language defaults to the plugin setting; pass "
        "'fr', 'en', 'ja', … to override for one call. The audio is never copied, cached or stored."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "audio_path": {
                "type": "string",
                "description": "Absolute path to the audio file to transcribe (WAV, WebM/Opus, OGG, MP3).",
            },
            "language": {
                "type": "string",
                "description": "Optional language code for this call (en, fr, de, es, pt, ja, zh, ko, th, hi, …).",
            },
            "reframe": {
                "type": "boolean",
                "description": "true = also return ClearVoice's rewritten clear sentence. Default false (raw transcript).",
            },
        },
        "required": ["audio_path"],
    },
}

CLEARVOICE_SAY_BACK = {
    "name": "clearvoice_say_back",
    "description": (
        "The ClearVoice round trip on a file: listen to an audio clip, work out the clear sentence, and "
        "speak it back — 'say it again, but understood'. Use it to repeat an unclear recording, to read "
        "an impaired-speech voice note aloud, or as listen → clarify → speak inside a bigger pipeline. "
        "Same approval rule as clearvoice_speak: with confirm_required=true (default) it returns the "
        "transcript and the proposed sentence WITHOUT speaking, so the user can approve or edit it; only "
        "confirm_required=false voices it. On-device by default; writes nothing."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "audio_path": {
                "type": "string",
                "description": "Absolute path to the audio file to listen to.",
            },
            "language": {
                "type": "string",
                "description": "Optional language code for this call.",
            },
            "voice_profile": {
                "type": "string",
                "description": "Optional voice name to speak with.",
            },
            "confirm_required": {
                "type": "boolean",
                "description": "true (default) = propose only, do not speak. false = speak the proposal.",
            },
        },
        "required": ["audio_path"],
    },
}


# ---------------------------------------------------------------------------
# Settings and secrets
# ---------------------------------------------------------------------------


def _get_secret(name: str) -> str | None:
    try:
        from agent.secret_scope import get_secret

        value = get_secret(name)
        return str(value).strip() if value else None
    except Exception:  # missing secret store is not an error here
        return None


def _read_settings(ctx):
    from clearvoice_engine.settings import Settings

    keys = (
        "stt_backend", "tts_backend", "language", "voice", "rewrite_style",
        "whisper_model", "gradium_voice_id", "allow_cloud",
    )
    mapping = {}
    for key in keys:
        try:
            mapping[key] = ctx.get_config(key)
        except Exception:
            mapping[key] = None
    return Settings.from_mapping(mapping, has_key=bool(_get_secret(GRADIUM_KEY_ENV)))


def _broadcast(event: str, payload: dict) -> bool:
    """Push an event to the Desktop half. Best-effort, never raises."""
    try:
        from hermes_cli.plugin_events import broadcast_plugin_event

        broadcast_plugin_event(PLUGIN_ID, event, payload)
        return True
    except Exception as exc:  # pragma: no cover - version dependent
        logger.debug("clearvoice: event broadcast unavailable: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Tool handler
# ---------------------------------------------------------------------------


def _error(message: str, **extra) -> str:
    payload = {"spoken": False, "error": message}
    payload.update(extra)
    return json.dumps(payload, ensure_ascii=False)


def clearvoice_speak(args: dict, **kwargs) -> str:
    """Speak one sentence through the ClearVoice pane. Never raises."""
    try:
        text = " ".join(str((args or {}).get("text") or "").split())
        if not text:
            return _error("No text to speak.")
        if len(text) > 600:
            return _error("That sentence is too long to speak in one go. Shorten it to a line or two.")

        confirm_required = (args or {}).get("confirm_required", True)
        if confirm_required is None:
            confirm_required = True
        confirmed = confirm_required is False

        if not confirmed:
            return json.dumps(
                {
                    "spoken": False,
                    "needs_confirmation": True,
                    "text": text,
                    "instruction": (
                        "Show this exact sentence to the user and let them approve it - the ClearVoice "
                        "pane is the place to do that. Do not speak it yet."
                    ),
                    "then": "call clearvoice_speak again with confirm_required=false once the user accepts it",
                },
                ensure_ascii=False,
            )

        from clearvoice_engine import runtime, tts

        ctx = kwargs.get("_ctx")
        settings = _read_settings(ctx) if ctx is not None else _fallback_settings()
        backend = (args or {}).get("backend") or settings.tts_backend
        voice = (args or {}).get("voice_profile") or None

        try:
            result = tts.synthesize(
                text,
                settings,
                backend=backend,
                voice=voice,
                get_key=lambda: _get_secret(GRADIUM_KEY_ENV),
            )
        except Exception as exc:
            # Plain-language, actionable failure — the pane shows the same string.
            return _error(str(exc) or "The voice could not speak that sentence.")

        runtime.outbox.put(result.wav, text, result.backend)
        _broadcast("speak", {
            "text": text,
            "backend": result.backend,
            "duration_s": round(result.duration_s, 2),
        })

        deliver = str((args or {}).get("deliver") or "pane").strip().lower()
        file_payload: dict = {}
        if deliver == "file":
            if not settings.allow_speech_files:
                return _error(
                    "Writing speech to a file is off. Turn on 'Allow speech files' in "
                    "Settings > Plugins > ClearVoice, then call again with deliver='file'.",
                    spoken=True,
                    delivered_to="clearvoice pane (in memory)",
                )
            try:
                folder = runtime.data_dir() / "speech"
                folder.mkdir(parents=True, exist_ok=True)
                target = folder / f"clearvoice-{int(time.time())}.wav"
                target.write_bytes(result.wav)
                file_payload = {
                    "file": str(target),
                    "media": f"MEDIA:{target}",
                    "note": "Generated speech written on request; it stays in the plugin data folder until you delete it.",
                }
            except OSError as exc:
                return _error(f"Could not write the speech file: {exc}", spoken=True)

        return json.dumps(
            {
                "spoken": True,
                "text": text,
                "backend": result.backend,
                "voice": result.voice,
                "duration_s": round(result.duration_s, 2),
                "delivered_to": "clearvoice pane (in memory)",
                "saved": bool(file_payload),
                **file_payload,
                "note": (
                    "Playback happens in the ClearVoice pane. If the pane is closed the audio is "
                    "dropped after 120 s and nothing is written to disk."
                ),
            },
            ensure_ascii=False,
        )
    except Exception as exc:  # never let a raise eat the tool call
        logger.warning("clearvoice_speak failed: %s", exc)
        return _error(f"ClearVoice could not speak that: {exc}")


def _read_audio_file(path_value: str) -> bytes:
    """Read an audio file the user named. Read-only; nothing is copied anywhere."""
    path = Path(str(path_value or "")).expanduser()
    if not str(path_value or "").strip():
        raise ValueError("No audio_path given.")
    if not path.is_absolute():
        raise ValueError("audio_path must be absolute (e.g. /home/you/note.webm).")
    if not path.is_file():
        raise ValueError(f"No file at {path}.")
    size = path.stat().st_size
    if size == 0:
        raise ValueError(f"{path.name} is empty.")
    if size > MAX_AUDIO_FILE_BYTES:
        raise ValueError(f"{path.name} is larger than {MAX_AUDIO_FILE_BYTES // (1024 * 1024)} MB.")
    return path.read_bytes()


def clearvoice_transcribe(args, **kwargs) -> str:
    """Audio file in, text out. Nothing is written, nothing is uploaded."""
    try:
        ctx = kwargs.get("_ctx")
        settings = _read_settings(ctx) if ctx is not None else _fallback_settings()
        language = str((args or {}).get("language") or "").strip()
        if language:
            from clearvoice_engine.settings import Settings

            settings = Settings.from_mapping(
                {
                    "language": language,
                    "tts_backend": settings.tts_backend,
                    "stt_backend": settings.stt_backend,
                    "whisper_model": settings.whisper_model,
                    "allow_cloud": settings.allow_cloud,
                },
                has_key=settings.has_gradium_key,
            )
        clip = _read_audio_file((args or {}).get("audio_path", ""))

        from clearvoice_engine import intent, stt

        lexicon = None
        try:
            from clearvoice_engine import runtime as _runtime

            lexicon = _runtime.lexicon()
        except Exception:
            lexicon = None

        try:
            result = stt.transcribe(clip, settings, get_key=lambda: _get_secret(GRADIUM_KEY_ENV), lexicon=lexicon)
        except Exception as exc:
            return _error(str(exc) or "Transcription failed.")

        payload = {
            "transcript": result.text,
            "language": result.language,
            "model": result.model,
            "backend": result.backend,
            "duration_s": round(result.duration_s, 2),
            "corrections_applied": result.corrections_applied,
            "saved": False,
        }
        if (args or {}).get("reframe"):
            payload["proposal"] = intent.reframe(result.text, settings.rewrite_style).public()
        return json.dumps(payload, ensure_ascii=False)
    except Exception as exc:
        logger.warning("clearvoice_transcribe failed: %s", exc)
        return _error(f"ClearVoice could not transcribe that: {exc}")


def clearvoice_say_back(args, **kwargs) -> str:
    """Listen to a clip, propose the clear sentence, and speak it on approval."""
    try:
        ctx = kwargs.get("_ctx")
        settings = _read_settings(ctx) if ctx is not None else _fallback_settings()
        language = str((args or {}).get("language") or "").strip()
        if language:
            settings = settings.__class__.from_mapping(
                {
                    "language": language,
                    "tts_backend": settings.tts_backend,
                    "stt_backend": settings.stt_backend,
                    "whisper_model": settings.whisper_model,
                    "voice": settings.voice,
                    "rewrite_style": settings.rewrite_style,
                    "allow_cloud": settings.allow_cloud,
                },
                has_key=settings.has_gradium_key,
            )
        clip = _read_audio_file((args or {}).get("audio_path", ""))

        from clearvoice_engine import intent, stt

        try:
            from clearvoice_engine import runtime as _rt

            _lex = _rt.lexicon()
        except Exception:
            _lex = None

        try:
            result = stt.transcribe(clip, settings, get_key=lambda: _get_secret(GRADIUM_KEY_ENV), lexicon=_lex)
        except Exception as exc:
            return _error(str(exc) or "Transcription failed.")

        proposal = intent.reframe(result.text, settings.rewrite_style)
        confirmed = (args or {}).get("confirm_required", True) is False
        if not confirmed:
            return json.dumps(
                {
                    "spoken": False,
                    "needs_confirmation": True,
                    "transcript": result.text,
                    "text": proposal.message,
                    "confidence": proposal.confidence,
                    "candidates": proposal.candidates,
                    "instruction": "Show the transcript and this sentence to the user, then ask whether to speak it.",
                    "then": "call clearvoice_say_back again with confirm_required=false once the user accepts it",
                },
                ensure_ascii=False,
            )

        from clearvoice_engine import runtime, tts

        try:
            spoken = tts.synthesize(
                proposal.message,
                settings,
                voice=(args or {}).get("voice_profile") or None,
                get_key=lambda: _get_secret(GRADIUM_KEY_ENV),
            )
        except Exception as exc:
            return _error(str(exc) or "The voice could not speak that sentence.", transcript=result.text)

        runtime.outbox.put(spoken.wav, proposal.message, spoken.backend)
        _broadcast("speak", {"text": proposal.message, "backend": spoken.backend})
        return json.dumps(
            {
                "spoken": True,
                "transcript": result.text,
                "text": proposal.message,
                "backend": spoken.backend,
                "duration_s": round(spoken.duration_s, 2),
                "delivered_to": "clearvoice pane (in memory)",
                "saved": False,
            },
            ensure_ascii=False,
        )
    except Exception as exc:
        logger.warning("clearvoice_say_back failed: %s", exc)
        return _error(f"ClearVoice could not do that: {exc}")


def _fallback_settings():
    """Settings when the tool runs without a plugin context (tests, CLI)."""
    from clearvoice_engine.settings import Settings

    return Settings.from_mapping({}, has_key=bool(_get_secret(GRADIUM_KEY_ENV)))


# ---------------------------------------------------------------------------
# Slash command
# ---------------------------------------------------------------------------


def _handle_command(raw_args: str, *, ctx=None, **kwargs) -> str:
    try:
        text = " ".join(str(raw_args or "").split())
        opened = _broadcast("open", {"reason": "slash-command"})
        if not text:
            return (
                "ClearVoice: the pane is opening on your Desktop.\n"
                "Press and hold Push to Talk, speak, then approve the sentence before it is spoken."
                + ("" if opened else "\n(No Desktop window answered - open ClearVoice from Capabilities > Plugins.)")
            )

        from clearvoice_engine import intent

        style = "courteous"
        if ctx is not None:
            try:
                style = _read_settings(ctx).rewrite_style
            except Exception:
                style = "courteous"
        proposal = intent.reframe(text, style)
        lines = [f"Proposed: {proposal.message}"]
        if proposal.needs_confirmation:
            lines.append(f"Needs a check: {proposal.confirmation_question}")
            for index, candidate in enumerate(proposal.candidates[1:], start=2):
                lines.append(f"  {index}. {candidate}")
        lines.append("Confirm it in the ClearVoice pane - nothing is spoken from here.")
        return "\n".join(lines)
    except Exception as exc:
        logger.warning("clearvoice command failed: %s", exc)
        return f"ClearVoice hit a problem: {exc}"


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register(ctx) -> None:
    """Wire the tools, the slash command and the bundled skill."""
    generator = clearvoice_speak

    def speak_handler(args: dict, **kwargs) -> str:
        return generator(args, _ctx=ctx, **kwargs)

    def transcribe_handler(args: dict, **kwargs) -> str:
        return clearvoice_transcribe(args, _ctx=ctx, **kwargs)

    def say_back_handler(args: dict, **kwargs) -> str:
        return clearvoice_say_back(args, _ctx=ctx, **kwargs)

    ctx.register_tool(
        name="clearvoice_speak",
        toolset="clearvoice",
        schema=CLEARVOICE_SPEAK,
        handler=speak_handler,
    )
    ctx.register_tool(
        name="clearvoice_transcribe",
        toolset="clearvoice",
        schema=CLEARVOICE_TRANSCRIBE,
        handler=transcribe_handler,
    )
    ctx.register_tool(
        name="clearvoice_say_back",
        toolset="clearvoice",
        schema=CLEARVOICE_SAY_BACK,
        handler=say_back_handler,
    )

    ctx.register_command(
        "clearvoice",
        lambda raw: _handle_command(raw, ctx=ctx),
        description="Open the ClearVoice push-to-talk pane",
    )

    skill_dir = Path(_ROOT) / "skills" / "clearvoice"
    skill_md = skill_dir / "SKILL.md"
    if skill_md.is_file():
        try:
            ctx.register_skill(
                "clearvoice",
                skill_md,
                description="Use ClearVoice for local speech: transcribe audio, speak text, or play back a clip clearly.",
            )
        except TypeError:  # older ctx without the description kwarg
            ctx.register_skill("clearvoice", skill_md)
        except Exception as exc:  # never fail the plugin over a bundled skill
            logger.warning("clearvoice: bundled skill not registered: %s", exc)
