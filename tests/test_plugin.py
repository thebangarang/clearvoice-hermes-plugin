"""The agent half: registration contract and the approval gate.

The tool is the only way a model can make ClearVoice speak, so the tests that
matter most are the ones proving it will not speak on its own initiative and
that it never raises into the tool call.
"""

from __future__ import annotations

import json

import pytest

from clearvoice_engine import runtime, tts

SCHEMA_KEYS = {"text", "voice_profile", "backend", "confirm_required", "deliver"}


def _register(plugin, ctx):
    plugin.register(ctx)
    return ctx


def test_register_exposes_three_tools_and_one_command(plugin, fake_ctx):
    ctx = _register(plugin, fake_ctx)
    assert set(ctx.tools) == {"clearvoice_speak", "clearvoice_transcribe", "clearvoice_say_back"}
    assert set(ctx.commands) == {"clearvoice"}
    assert ctx.hooks == []
    schema, _handler = ctx.tools["clearvoice_speak"]
    assert schema["name"] == "clearvoice_speak"
    assert set(schema["parameters"]["properties"]) == SCHEMA_KEYS
    assert "on-device" in schema["description"]
    transcribe_schema, _ = ctx.tools["clearvoice_transcribe"]
    assert transcribe_schema["parameters"]["required"] == ["audio_path"]
    say_back_schema, _ = ctx.tools["clearvoice_say_back"]
    assert say_back_schema["parameters"]["required"] == ["audio_path"]


def test_tool_refuses_to_speak_without_confirmation(plugin, fake_ctx):
    ctx = _register(plugin, fake_ctx)
    _schema, handler = ctx.tools["clearvoice_speak"]

    payload = json.loads(handler({"text": "Could you sit down, please?"}))
    assert payload["spoken"] is False
    assert payload["needs_confirmation"] is True
    assert payload["text"] == "Could you sit down, please?"
    assert "confirm_required=false" in payload["then"]


def test_tool_speaks_only_when_confirmation_is_passed_as_false(plugin, fake_ctx, monkeypatch):
    ctx = _register(plugin, fake_ctx)
    _schema, handler = ctx.tools["clearvoice_speak"]

    class _Result:
        wav = b"RIFFfake"
        backend = "phonon"
        voice = "default"
        duration_s = 1.0

    monkeypatch.setattr(tts, "synthesize", lambda *a, **k: _Result())

    payload = json.loads(handler({"text": "Thank you.", "confirm_required": False}))
    assert payload["spoken"] is True
    assert payload["backend"] == "phonon"
    assert payload["saved"] is False
    assert runtime.outbox.peek() is not None, "the pane was never handed the audio"


def test_tool_reports_cloud_refusal_as_a_plain_message(plugin, fake_ctx, monkeypatch):
    fake_ctx.config = {"tts_backend": "gradium", "allow_cloud": False}
    ctx = _register(plugin, fake_ctx)
    _schema, handler = ctx.tools["clearvoice_speak"]

    payload = json.loads(handler({"text": "Hello.", "confirm_required": False}))
    assert payload["spoken"] is False
    assert "Cloud speech is off" in payload["error"]


def test_tool_never_raises_on_bad_input(plugin, fake_ctx):
    ctx = _register(plugin, fake_ctx)
    _schema, handler = ctx.tools["clearvoice_speak"]

    for args in ({}, {"text": "   "}, {"text": "x" * 900}, None):
        payload = json.loads(handler(args or {}))
        assert payload["spoken"] is False
        assert payload["error"]


def test_tool_returns_error_when_the_voice_fails(plugin, fake_ctx, monkeypatch):
    ctx = _register(plugin, fake_ctx)
    _schema, handler = ctx.tools["clearvoice_speak"]

    def boom(*_args, **_kwargs):
        raise tts.SynthesisError("The on-device voice could not speak that sentence.")

    monkeypatch.setattr(tts, "synthesize", boom)
    payload = json.loads(handler({"text": "Hello.", "confirm_required": False}))
    assert payload["spoken"] is False
    assert "could not speak" in payload["error"]


def test_slash_command_without_text_opens_the_pane(plugin, fake_ctx):
    ctx = _register(plugin, fake_ctx)
    message = ctx.commands["clearvoice"]("")
    assert "Push to Talk" in message
    assert "Confirm" in message or "pane" in message


def test_slash_command_with_text_proposes_but_does_not_speak(plugin, fake_ctx):
    ctx = _register(plugin, fake_ctx)
    message = ctx.commands["clearvoice"]("I need... appointment... Tuesday... move.")
    assert "Could you move the appointment to Tuesday, please?" in message
    assert "nothing is spoken" in message.lower()


def test_slash_command_survives_odd_input(plugin, fake_ctx):
    ctx = _register(plugin, fake_ctx)
    assert ctx.commands["clearvoice"](None)


def test_settings_are_read_through_the_plugin_context(plugin, fake_ctx):
    fake_ctx.config = {"whisper_model": "base.en", "language": "fr"}
    ctx = _register(plugin, fake_ctx)
    settings = plugin._read_settings(ctx)
    assert settings.whisper_model == "base.en"
    assert settings.language == "fr"
    assert settings.tts_backend == "auto"
    # French: Piper voices it, and a `.en` recogniser is swapped for a
    # multilingual one rather than silently mis-hearing.
    assert settings.resolved_tts_engine == "piper"
    assert settings.stt_model == "base"


def test_fallback_settings_are_local(plugin):
    settings = plugin._fallback_settings()
    assert settings.tts_backend == "auto"
    assert settings.resolved_tts_engine == "phonon"
    assert settings.allow_cloud is False


# --- CLI surface -----------------------------------------------------------


class _Args:
    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)


def test_cli_without_an_action_prints_usage(plugin, capsys):
    code = plugin._cli_handler(_Args(action=None))
    assert code == 2
    assert "hermes clearvoice" in capsys.readouterr().out


def test_cli_say_writes_a_wav_and_reports_it(plugin, tmp_path, monkeypatch, capsys):
    from clearvoice_engine import tts

    class _Result:
        wav = b"RIFFfake"
        backend = "phonon"
        voice = "default"
        duration_s = 1.0
        text = "Hello."

    monkeypatch.setattr(tts, "synthesize", lambda *a, **k: _Result())
    out = tmp_path / "speech.wav"
    code = plugin._cli_handler(
        _Args(action="say", text="Hello.", voice="", backend="", language="", out=str(out), json=True)
    )
    assert code == 0
    assert out.read_bytes() == b"RIFFfake"
    assert '"file"' in capsys.readouterr().out


def test_cli_hear_reports_a_missing_file_in_plain_language(plugin, capsys):
    code = plugin._cli_handler(
        _Args(action="hear", path="/no/such/file.webm", language="", reframe=False, json=False)
    )
    assert code == 1
    assert "No file at" in capsys.readouterr().out


def test_cli_refuses_a_relative_out_path(plugin, capsys):
    code = plugin._cli_handler(
        _Args(action="say", text="Hello.", voice="", backend="", language="", out="relative.wav", json=False)
    )
    assert code == 1
    assert "absolute" in capsys.readouterr().out
