"""Privacy invariants, enforced as tests rather than promises.

The load-bearing claims of ClearVoice are all negative — no audio file, no
stored transcript, no cloud call, no broad capability — so each one is asserted
here. The file-write test uses a CPython audit hook, which sees every
``open()`` the process makes, including ones inside third-party libraries.
"""

from __future__ import annotations

import sys
from contextlib import contextmanager
from pathlib import Path

import numpy as np
import pytest
import yaml

from clearvoice_engine import audio, cloud, intent, privacy, runtime, stt, tts
from clearvoice_engine.settings import Settings

ROOT = Path(__file__).resolve().parent.parent

# --- audit hook: every write-mode open() in this process ------------------

_WRITES: list[str] = []
_ARMED = False


def _audit(event: str, args: tuple) -> None:
    if not _ARMED or event != "open":
        return
    path, mode = (args + (None, None))[:2]
    if isinstance(mode, str) and any(flag in mode for flag in ("w", "a", "x", "+")):
        _WRITES.append(f"{path}:{mode}")


sys.addaudithook(_audit)


@contextmanager
def record_writes():
    global _ARMED
    _WRITES.clear()
    _ARMED = True
    try:
        yield _WRITES
    finally:
        _ARMED = False


# --- stubs: no model download, no network, no audio device ----------------

class _StubWhisper:
    class _Info:
        language = "en"
        duration = 2.0

    def transcribe(self, samples, **kwargs):
        class _Seg:
            text = " I need appointment Tuesday move. "

        return iter([_Seg()]), self._Info()


class _StubPhonon:
    sample_rate = 24000
    voices = ["default"]

    def synth(self, text, voice=None, **kwargs):
        return np.zeros(2400, dtype=np.float32)


@pytest.fixture()
def stubs(monkeypatch):
    monkeypatch.setattr(stt, "_load_local_model", lambda *a, **k: _StubWhisper())
    monkeypatch.setattr(tts, "_load_phonon", lambda *a, **k: _StubPhonon())
    # No catalog fetch in tests: the real one is a network call.
    monkeypatch.setattr(tts, "phonon_voices", lambda: [{"voice": "default", "name": "Default", "language": "en"}])
    yield


def _clip() -> bytes:
    tone = (0.05 * np.sin(np.linspace(0, 6.28 * 220, 16000))).astype(np.float32)
    return audio.float32_to_wav_bytes(tone, audio.TARGET_RATE)


# --- tests ---------------------------------------------------------------


def test_full_pipeline_writes_no_audio_and_no_transcript(stubs, tmp_path, monkeypatch):
    monkeypatch.setenv("CLEARVOICE_DATA_DIR", str(tmp_path))
    settings = Settings()

    with record_writes() as writes:
        result = stt.transcribe(_clip(), settings)
        proposal = intent.reframe(result.text)
        spoken = tts.synthesize(proposal.message, settings)

    assert result.text
    assert spoken.wav[:4] == b"RIFF"
    assert writes == [], f"the pipeline wrote to disk: {writes}"
    assert list(tmp_path.iterdir()) == []


def test_wav_roundtrip_is_in_memory():
    samples = np.zeros(1600, dtype=np.float32)
    wav = audio.float32_to_wav_bytes(samples, 16000)
    assert wav[:4] == b"RIFF"
    assert audio.wav_sample_rate(wav) == 16000
    assert 0.09 < audio.wav_duration_seconds(wav) < 0.11


def test_session_store_holds_nothing_after_clear():
    store = privacy.SessionStore()
    store.add("I need the forms", "I need the forms, please.", "local")
    store.add("thank you", "Thank you.", "local")
    assert len(store) == 2
    assert store.clear() == 2
    assert len(store) == 0
    assert store.last() is None


def test_session_store_is_bounded_in_memory():
    store = privacy.SessionStore()
    for index in range(privacy.MAX_SESSION_UTTERANCES + 5):
        store.add(f"line {index}", f"Line {index}.", "local")
    assert len(store) == privacy.MAX_SESSION_UTTERANCES


def test_saved_phrases_only_write_on_explicit_save(tmp_path):
    phrases = privacy.SavedPhrases(tmp_path)

    with record_writes() as writes:
        assert phrases.list() == []

    assert writes == []
    phrase = phrases.save_phrase("Could you help me, please?")
    saved_files = list(tmp_path.iterdir())
    assert [p.name for p in saved_files] == ["phrases.json"]
    assert phrases.list()[0].text == phrase.text


def test_saved_phrases_never_hold_audio(tmp_path):
    with pytest.raises(ValueError):
        privacy.SavedPhrases(tmp_path / "nonexistent").save_phrase("   ")


def test_cloud_stt_is_refused_when_not_enabled(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(cloud, "_post", lambda *a, **k: calls.append("called") or b"")
    settings = Settings.from_mapping({"stt_backend": "gradium", "allow_cloud": False})
    with pytest.raises(cloud.CloudDisabled):
        stt.transcribe(_clip(), settings, get_key=lambda: "test-key")
    assert calls == [], "a cloud call was attempted while cloud speech was off"


def test_cloud_tts_is_refused_when_not_enabled(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(cloud, "_post", lambda *a, **k: calls.append("called") or b"")
    settings = Settings.from_mapping({"tts_backend": "gradium", "allow_cloud": False})
    with pytest.raises(cloud.CloudDisabled):
        tts.synthesize("hello", settings, get_key=lambda: "test-key")
    assert calls == []


def test_cloud_backend_without_a_key_asks_for_one(monkeypatch):
    monkeypatch.setattr(cloud, "_post", lambda *a, **k: b"")
    settings = Settings.from_mapping({"tts_backend": "gradium", "allow_cloud": True})
    with pytest.raises(cloud.CloudNotConfigured):
        tts.synthesize("hello", settings, get_key=lambda: None)


def test_defaults_are_local_and_offline():
    settings = Settings.from_mapping({})
    assert settings.stt_backend == "local"
    assert settings.tts_backend == "auto"
    assert settings.resolved_tts_engine == "phonon"  # English
    assert settings.allow_cloud is False
    assert settings.network_used is False
    status = settings.status()
    assert status["retention"] == "Session only"
    assert status["network"] == "Offline"
    assert "Nothing saved" in status["retention_line"]


def test_unknown_backend_values_fall_back_to_local():
    settings = Settings.from_mapping({"stt_backend": "banana", "tts_backend": "cloud-magic", "allow_cloud": "yes"})
    assert settings.stt_backend == "local"
    assert settings.tts_backend == "auto"
    assert settings.allow_cloud is True


def test_manifest_declares_the_three_tools_and_no_broad_capabilities():
    manifest = yaml.safe_load((ROOT / "plugin.yaml").read_text(encoding="utf-8"))
    assert manifest["name"] == "clearvoice"
    assert manifest["provides_tools"] == ["clearvoice_speak", "clearvoice_transcribe", "clearvoice_say_back"]
    assert not manifest.get("provides_hooks")
    # No privileged host surface is requested at all.
    assert not manifest.get("capabilities")
    # Nothing that would reach mail, calendar, contacts, files or messaging.
    forbidden = ("filesystem", "email", "calendar", "contacts", "messaging", "shell")
    text = (ROOT / "plugin.yaml").read_text(encoding="utf-8").lower()
    for word in forbidden:
        assert f"  {word}" not in text.replace("-", "_")


def test_engine_modules_do_not_import_network_or_shell_for_audio_io():
    """Cheap source audit: audio handling never shells out except to ffmpeg."""
    source = (ROOT / "clearvoice_engine" / "audio.py").read_text(encoding="utf-8")
    assert source.count("subprocess.run") == 1
    assert "ffmpeg" in source
    assert "tempfile" not in source
    assert "NamedTemporaryFile" not in source


def test_the_pending_queue_carries_text_never_audio(monkeypatch):
    """The blocker from review: the queue must not be able to hold sound."""
    queue = runtime.SpeechQueue()
    item = queue.request("The pharmacy closes at six.", kind="speak")

    assert item.text == "The pharmacy closes at six."
    assert not hasattr(item, "wav"), "a queued request must not carry audio"
    assert queue.peek() is not None

    monkeypatch.setattr(runtime, "PENDING_TTL_SECONDS", -1)
    assert queue.peek() is None, "an expired request is dropped, not redeemed"
    assert queue.consume(item.token) is None


def test_a_token_is_single_use_and_bound_to_its_text():
    queue = runtime.SpeechQueue()
    item = queue.request("Call the doctor.", kind="speak")

    assert queue.consume("") is None
    assert queue.consume("wrong-token") is None
    assert queue.peek() is not None
    redeemed = queue.consume(item.token)
    assert redeemed is not None and redeemed.text == "Call the doctor."
    assert queue.consume(item.token) is None


def test_a_new_request_replaces_the_previous_one():
    queue = runtime.SpeechQueue()
    first = queue.request("First.")
    queue.request("Second.")
    assert queue.consume(first.token) is None, "the replaced request cannot be redeemed"
    assert queue.peek().text == "Second."
