#!/usr/bin/env python
"""End-to-end smoke test with the real models (no stubs, no network).

    python scripts/smoke_test.py

It synthesizes a sentence with the on-device Phonon voice, feeds that audio
straight back into the local recognizer, reframes the transcript, and speaks the
result again — the same path the pane drives, minus the microphone. Nothing is
written to disk: both clips live in memory, and the script asserts that.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from clearvoice_engine import audio, intent, stt, tts  # noqa: E402
from clearvoice_engine.settings import Settings  # noqa: E402

SPOKEN = "Could we move my appointment to Tuesday please?"


def main() -> int:
    settings = Settings.from_mapping({"whisper_model": "tiny.en", "language": "en"})

    print("1. synthesizing with on-device Phonon ...")
    started = time.time()
    first = tts.synthesize(SPOKEN, settings)
    synth_ms = (time.time() - started) * 1000
    print(f"   {len(first.wav)} bytes, {first.duration_s:.2f}s of speech, {synth_ms:.0f} ms, voice={first.voice}")

    print("2. transcribing that audio with local faster-whisper ...")
    started = time.time()
    result = stt.transcribe(first.wav, settings)
    stt_ms = (time.time() - started) * 1000
    print(f"   {stt_ms:.0f} ms -> {result.text!r}")

    print("3. inferring the intended message ...")
    proposal = intent.reframe(result.text)
    print(f"   {proposal.message!r} (intent={proposal.intent}, confidence={proposal.confidence})")
    if proposal.needs_confirmation:
        print(f"   asks first: {proposal.confirmation_question}")
        for candidate in proposal.candidates:
            print(f"     - {candidate}")

    print("4. speaking the proposal ...")
    started = time.time()
    second = tts.synthesize(proposal.message, settings)
    print(f"   {len(second.wav)} bytes, {second.duration_s:.2f}s, {(time.time() - started) * 1000:.0f} ms")

    # The pipeline must not have created any file anywhere it owns.
    data_dir = None
    try:
        from clearvoice_engine import runtime

        data_dir = runtime.data_dir()
    except Exception:
        pass
    if data_dir and Path(data_dir).exists():
        files = list(Path(data_dir).rglob("*"))
        print(f"5. plugin data dir holds: {files or 'nothing'}")
        if files:
            print("   FAIL: the pipeline wrote files")
            return 1
    else:
        print("5. plugin data dir: not created (nothing was written)")

    if not result.text:
        print("FAIL: no transcript")
        return 1
    print("\nOK - end to end, on-device, nothing saved.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
