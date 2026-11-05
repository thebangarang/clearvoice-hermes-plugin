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
from pathlib import Path

_ROOT = str(Path(__file__).resolve().parent)
if _ROOT not in sys.path:  # both entry points import clearvoice_engine the same way
    sys.path.insert(0, _ROOT)

logger = logging.getLogger(__name__)

PLUGIN_ID = "clearvoice"
GRADIUM_KEY_ENV = "CLEARVOICE_GRADIUM_API_KEY"

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
        },
        "required": ["text"],
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
        return json.dumps(
            {
                "spoken": True,
                "text": text,
                "backend": result.backend,
                "voice": result.voice,
                "duration_s": round(result.duration_s, 2),
                "delivered_to": "clearvoice pane (in memory)",
                "saved": False,
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
    """Wire the tool and slash command. Imports stay lazy (see plugin docs)."""
    generator = clearvoice_speak

    def handler(args: dict, **kwargs) -> str:
        return generator(args, _ctx=ctx, **kwargs)

    ctx.register_tool(
        name="clearvoice_speak",
        toolset="clearvoice",
        schema=CLEARVOICE_SPEAK,
        handler=handler,
    )

    ctx.register_command(
        "clearvoice",
        lambda raw: _handle_command(raw, ctx=ctx),
        description="Open the ClearVoice push-to-talk pane",
    )
