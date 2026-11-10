"""The agent half: registration contract and the approval gate.

The tool is the only way a model can make ClearVoice speak, so the tests that
matter most are the ones proving it will not speak on its own initiative and
that it never raises into the tool call.
"""

from __future__ import annotations

import json

import pytest

from clearvoice_engine import runtime, stt, tts

SCHEMA_KEYS = {"text", "voice_profile", "backend", "deliver"}


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


def test_the_tool_cannot_speak_it_only_queues(plugin, fake_ctx, monkeypatch):
    """The blocking review item: a model cannot make the pane talk."""
    ctx = _register(plugin, fake_ctx)
    _schema, handler = ctx.tools["clearvoice_speak"]

    def must_not_synthesise(*_args, **_kwargs):
        raise AssertionError("the tool synthesised audio; only the pane may do that")

    monkeypatch.setattr(tts, "synthesize", must_not_synthesise)

    # Even a caller that passes the old override, and one that passes nonsense,
    # gets the same answer: queued, not spoken.
    for args in ({"text": "Please sit down."}, {"text": "Please sit down.", "confirm_required": False}):
        runtime.outbox.clear()
        payload = json.loads(handler(args))
        assert payload["queued"] is True
        assert payload["spoken"] is False
        assert payload["awaiting_user"] is True
        assert payload["text"] == "Please sit down."
        pending = runtime.outbox.peek()
        assert pending is not None and pending.text == "Please sit down."
        assert pending.token and len(pending.token) >= 16


def test_a_queued_sentence_can_only_be_redeemed_with_its_token(plugin, fake_ctx):
    ctx = _register(plugin, fake_ctx)
    _schema, handler = ctx.tools["clearvoice_speak"]
    runtime.outbox.clear()
    handler({"text": "The pharmacy closes at six."})
    pending = runtime.outbox.peek()

    assert runtime.outbox.consume("not-the-token") is None
    assert runtime.outbox.peek() is not None, "a wrong token must not consume the request"
    redeemed = runtime.outbox.consume(pending.token)
    assert redeemed is not None and redeemed.text == "The pharmacy closes at six."
    assert runtime.outbox.consume(pending.token) is None, "a token is single-use"


def test_say_back_queues_and_does_not_speak(plugin, fake_ctx, monkeypatch, tmp_path):
    ctx = _register(plugin, fake_ctx)
    _schema, handler = ctx.tools["clearvoice_say_back"]

    clip = tmp_path / "note.webm"
    clip.write_bytes(b"RIFFfake-audio")

    class _Heard:
        text = "i need appointment tuesday move"
        language = "en"
        model = "small"
        duration_s = 2.0
        corrections_applied = 0

    monkeypatch.setattr("__init__._read_audio_file", lambda _p: b"RIFFfake-audio")
    monkeypatch.setattr(stt, "transcribe", lambda *a, **k: _Heard())

    def must_not_synthesise(*_args, **_kwargs):
        raise AssertionError("say_back synthesised audio; only the pane may do that")

    monkeypatch.setattr(tts, "synthesize", must_not_synthesise)

    runtime.outbox.clear()
    payload = json.loads(handler({"audio_path": str(clip)}))
    assert payload["queued"] is True
    assert payload["spoken"] is False
    assert payload["transcript"] == "i need appointment tuesday move"
    assert runtime.outbox.peek() is not None


def test_file_delivery_is_the_only_tool_synthesis_and_is_off_by_default(plugin, fake_ctx):
    ctx = _register(plugin, fake_ctx)
    _schema, handler = ctx.tools["clearvoice_speak"]

    payload = json.loads(handler({"text": "Hello.", "deliver": "file"}))
    assert payload["spoken"] is False
    assert "Allow speech files" in payload["error"]


def test_tool_never_raises_on_bad_input(plugin, fake_ctx):
    ctx = _register(plugin, fake_ctx)
    _schema, handler = ctx.tools["clearvoice_speak"]

    for args in ({}, {"text": "   "}, {"text": "x" * 900}, None):
        payload = json.loads(handler(args or {}))
        assert payload["spoken"] is False
        assert payload["error"]


def test_file_delivery_reports_a_voice_failure_in_plain_language(plugin, fake_ctx, monkeypatch):
    fake_ctx.config = {"allow_speech_files": True}
    ctx = _register(plugin, fake_ctx)
    _schema, handler = ctx.tools["clearvoice_speak"]

    def boom(*_args, **_kwargs):
        raise tts.SynthesisError("The on-device voice could not speak that sentence.")

    monkeypatch.setattr(tts, "synthesize", boom)
    payload = json.loads(handler({"text": "Hello.", "deliver": "file"}))
    assert payload["spoken"] is False
    assert "could not speak" in payload["error"]

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
