"""ClearVoice — the agent half.

Registers exactly one tool (``clearvoice_speak``) and one slash command
(``/clearvoice``). Everything else lives behind the plugin's own REST backend
(``dashboard/plugin_api.py``), which the Desktop pane calls.

Why the tools cannot speak: a speech bridge that can be told "just say something"
by a model is a way to put words in a disabled user's mouth. So neither tool
synthesises anything for the room. They queue a sentence; the pane shows it with a
single-use token, and only the user pressing **Speak it** redeems that token and
produces audio. A prompt-injected turn can queue text — it cannot make the machine
talk.
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
        "This tool NEVER speaks. It queues the sentence and puts it in front of the user in the ClearVoice "
        "pane, where they read it and press Speak it themselves; calling it again cannot force playback. "
        "So there is nothing to confirm here and no way for a model to make the pane say words the user "
        "has not seen. "
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
        "It never speaks by itself: like clearvoice_speak it queues the transcript and the proposed "
        "sentence, and the user decides in the pane. On-device by default; writes nothing."
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


def _propose(ctx, transcript, settings, language=None):
    """Local rule pack first; the user's own model when they turned it on."""
    from clearvoice_engine import propose as _propose_mod

    return _propose_mod.propose(transcript, settings, language=language)


def _read_settings(ctx):
    from clearvoice_engine.settings import Settings

    keys = (
        "stt_backend", "tts_backend", "language", "voice", "rewrite_style",
        "whisper_model", "gradium_voice_id", "allow_cloud",
        # Without these the tool path silently ignored the panes settings:
        # deliver="file" was refused even after the user switched it on.
        "allow_speech_files", "phrases_dir", "learn_from_edits",
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
    """Queue one sentence for the user to speak. Never speaks by itself."""
    try:
        text = " ".join(str((args or {}).get("text") or "").split())
        if not text:
            return _error("No text to speak.")
        if len(text) > 600:
            return _error("That sentence is too long to speak in one go. Shorten it to a line or two.")

        from clearvoice_engine import runtime

        deliver = str((args or {}).get("deliver") or "pane").strip().lower()

        if deliver == "file":
            # The only synthesis a tool can trigger, and it speaks into no room: it
            # writes one WAV that someone has to open. Still refused unless the user
            # switched the setting on, because a prompt-injected turn could otherwise
            # fill the disk with audio.
            from clearvoice_engine import tts

            ctx = kwargs.get("_ctx")
            settings = _read_settings(ctx) if ctx is not None else _fallback_settings()
            if not settings.allow_speech_files:
                return _error(
                    "Writing speech to a file is off. Turn on 'Allow speech files' in "
                    "Settings > Plugins > ClearVoice, then call again with deliver='file'.",
                    written=False,
                )
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
                return _error(str(exc) or "The voice could not speak that sentence.")
            try:
                folder = runtime.data_dir() / "speech"
                folder.mkdir(parents=True, exist_ok=True)
                target = folder / f"clearvoice-{int(time.time())}.wav"
                target.write_bytes(result.wav)
            except OSError as exc:
                return _error(f"Could not write the speech file: {exc}")
            return json.dumps(
                {
                    "spoken": False,
                    "spoken_into_room": False,
                    "file": str(target),
                    "media": f"MEDIA:{target}",
                    "backend": result.backend,
                    "duration_s": round(result.duration_s, 2),
                    "note": (
                        "Written on request; it stays in the plugin data folder until you delete it. "
                        "Nothing was played aloud."
                    ),
                },
                ensure_ascii=False,
            )

        item = runtime.outbox.request(text, kind="speak")
        _broadcast("queued", {"text": text, "id": item.id})
        return json.dumps(
            {
                "queued": True,
                "spoken": False,
                "awaiting_user": True,
                "text": text,
                "instruction": (
                    "ClearVoice is showing this sentence in its pane. Nothing is spoken until the user "
                    "presses Speak it there. Do not call this tool again to try to force playback."
                ),
            },
            ensure_ascii=False,
        )
    except Exception as exc:  # never let a raise eat the tool call
        logger.warning("clearvoice_speak failed: %s", exc)
        return _error(f"ClearVoice could not queue that: {exc}")


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
            payload["proposal"] = _propose(
                ctx, result.text, settings, result.language or settings.language
            ).public()
        return json.dumps(payload, ensure_ascii=False)
    except Exception as exc:
        logger.warning("clearvoice_transcribe failed: %s", exc)
        return _error(f"ClearVoice could not transcribe that: {exc}")


def clearvoice_say_back(args, **kwargs) -> str:
    """Listen to a file and queue the clear sentence. Never speaks by itself."""
    try:
        path_value = (args or {}).get("audio_path")
        if not str(path_value or "").strip():
            return _error("No audio file to listen to.")
        clip = _read_audio_file(path_value)

        ctx = kwargs.get("_ctx")
        language = str((args or {}).get("language") or "").strip().lower()[:2]
        settings = _cli_settings(ctx, language)

        from clearvoice_engine import stt

        try:
            from clearvoice_engine import runtime as _rt

            _lex = _rt.lexicon()
        except Exception:
            _lex = None

        try:
            result = stt.transcribe(clip, settings, get_key=lambda: _get_secret(GRADIUM_KEY_ENV), lexicon=_lex)
        except Exception as exc:
            return _error(str(exc) or "Transcription failed.")

        proposal = _propose(ctx, result.text, settings, result.language or settings.language)

        from clearvoice_engine import runtime

        item = runtime.outbox.request(proposal.message, kind="say_back", transcript=result.text)
        _broadcast("queued", {"text": proposal.message, "id": item.id, "transcript": result.text})
        return json.dumps(
            {
                "queued": True,
                "spoken": False,
                "awaiting_user": True,
                "transcript": result.text,
                "text": proposal.message,
                "confidence": proposal.confidence,
                "candidates": proposal.candidates,
                "instruction": (
                    "The transcript and this sentence are in the ClearVoice pane. The user decides "
                    "whether to hear it; this call cannot play it."
                ),
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
# CLI: `hermes clearvoice ...` — the third-party surface for scripts and cron
# ---------------------------------------------------------------------------


def _cli_setup(parser) -> None:
    parser.description = "ClearVoice: speak text, transcribe audio, or re-voice a clip — locally."
    sub = parser.add_subparsers(dest="action")

    say = sub.add_parser("say", help="Speak text with the on-device voice and write a WAV")
    say.add_argument("text", help="The sentence to speak")
    say.add_argument("--voice", default="", help="Voice name (Phonon catalog name or Piper voice key)")
    say.add_argument("--backend", choices=["phonon", "piper", "gradium"], default="")
    say.add_argument("--language", default="", help="Language code for this call (en, fr, ja, …)")
    say.add_argument("--out", default="", help="Write the WAV here instead of the plugin speech folder")
    say.add_argument("--json", action="store_true", help="Machine-readable output")

    hear = sub.add_parser("hear", help="Transcribe an audio file locally")
    hear.add_argument("path", help="Audio file (WAV, WebM/Opus, OGG, MP3)")
    hear.add_argument("--language", default="", help="Language code for this call")
    hear.add_argument("--reframe", action="store_true", help="Also return the cleaned-up sentence")
    hear.add_argument("--json", action="store_true", help="Machine-readable output")

    back = sub.add_parser("say-back", help="Listen to a clip and speak it clearly")
    back.add_argument("path", help="Audio file to listen to")
    back.add_argument("--language", default="", help="Language code for this call")
    back.add_argument("--voice", default="", help="Voice name to speak with")
    back.add_argument("--out", default="", help="Write the spoken WAV here")
    back.add_argument("--json", action="store_true", help="Machine-readable output")


def _cli_settings(ctx, language: str = ""):
    settings = _read_settings(ctx) if ctx is not None else _fallback_settings()
    if not language:
        return settings
    from clearvoice_engine.settings import Settings

    return Settings.from_mapping(
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


def _cli_write_speech(wav: bytes, out: str) -> "Path":
    from clearvoice_engine import runtime

    if out:
        target = Path(out).expanduser()
        if not target.is_absolute():
            raise ValueError("--out must be an absolute path.")
        target.parent.mkdir(parents=True, exist_ok=True)
    else:
        folder = runtime.data_dir() / "speech"
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / f"clearvoice-{int(time.time())}.wav"
    target.write_bytes(wav)
    return target


def _cli_handler(args, **kwargs) -> int:
    """Handler for `hermes clearvoice …`. Prints, returns an exit code, never raises."""
    import json as _json

    ctx = kwargs.get("_ctx")
    action = getattr(args, "action", None)
    if action is None:
        print("Usage: hermes clearvoice {say|hear|say-back} …  (try --help)")
        return 2

    try:
        settings = _cli_settings(ctx, getattr(args, "language", "") or "")

        if action == "say":
            from clearvoice_engine import tts

            result = tts.synthesize(
                args.text,
                settings,
                backend=(getattr(args, "backend", "") or None),
                voice=(getattr(args, "voice", "") or None),
                get_key=lambda: _get_secret(GRADIUM_KEY_ENV),
            )
            path = _cli_write_speech(result.wav, getattr(args, "out", ""))
            payload = {
                "spoken": False,
                "text": result.text,
                "backend": result.backend,
                "voice": result.voice,
                "duration_s": round(result.duration_s, 2),
                "file": str(path),
            }
            print(_json.dumps(payload, ensure_ascii=False) if args.json else str(path))
            return 0

        if action == "hear":
            from clearvoice_engine import intent, runtime, stt

            clip = _read_audio_file(args.path)
            result = stt.transcribe(
                clip, settings, get_key=lambda: _get_secret(GRADIUM_KEY_ENV), lexicon=runtime.lexicon()
            )
            payload = {
                "transcript": result.text,
                "language": result.language,
                "model": result.model,
                "duration_s": round(result.duration_s, 2),
                "corrections_applied": result.corrections_applied,
            }
            if getattr(args, "reframe", False):
                payload["proposal"] = _propose(
                    ctx, result.text, settings, result.language or settings.language
                ).public()
            if args.json:
                print(_json.dumps(payload, ensure_ascii=False))
            else:
                print(payload["transcript"])
                if "proposal" in payload:
                    print(f"ClearVoice: {payload['proposal']['message']}")
            return 0

        if action == "say-back":
            from clearvoice_engine import intent, runtime, stt, tts

            clip = _read_audio_file(args.path)
            result = stt.transcribe(
                clip, settings, get_key=lambda: _get_secret(GRADIUM_KEY_ENV), lexicon=runtime.lexicon()
            )
            proposal = _propose(ctx, result.text, settings, result.language or settings.language)
            spoken = tts.synthesize(
                proposal.message,
                settings,
                voice=(getattr(args, "voice", "") or None),
                get_key=lambda: _get_secret(GRADIUM_KEY_ENV),
            )
            path = _cli_write_speech(spoken.wav, getattr(args, "out", ""))
            payload = {
                "transcript": result.text,
                "text": proposal.message,
                "backend": spoken.backend,
                "duration_s": round(spoken.duration_s, 2),
                "file": str(path),
            }
            if args.json:
                print(_json.dumps(payload, ensure_ascii=False))
            else:
                print(f"heard:  {payload['transcript']}")
                print(f"spoken: {payload['text']}")
                print(path)
            return 0

        print(f"Unknown action: {action}")
        return 2
    except Exception as exc:
        print(f"ClearVoice: {exc}" if str(exc) else "ClearVoice: that did not work.")
        return 1


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

        settings = _fallback_settings() if ctx is None else _read_settings(ctx)
        proposal = _propose(ctx, text, settings)
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

    # CLI surface for scripts, cron and other tooling: `hermes clearvoice …`
    try:
        ctx.register_cli_command(
            "clearvoice",
            "Local speech: say, hear, say-back",
            _cli_setup,
            _cli_handler,
            description="Speak text, transcribe audio, or re-voice a clip on-device.",
        )
    except Exception as exc:  # older ctx without CLI commands
        logger.debug("clearvoice: CLI command not registered: %s", exc)

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
