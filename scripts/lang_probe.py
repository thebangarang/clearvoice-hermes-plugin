"""Probe: multi-language support, end to end, with the real engines.

    python scripts/lang_probe.py [--stt]

For each requested language it speaks a real sentence with the on-device engine
and reports the audio. With --stt it also transcribes the French sample back with
the multilingual recogniser, which is the roundtrip that proves both directions.
First run downloads each voice (~60-80 MB) plus, for --stt, a Whisper model.
"""

from __future__ import annotations

import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from clearvoice_engine import intent, stt, tts  # noqa: E402
from clearvoice_engine.settings import Settings  # noqa: E402

SAMPLES = {
    "fr": "Est-ce qu'on pourrait deplacer mon rendez-vous a mardi, s'il vous plait ?",
    "es": "Podemos mover mi cita al martes, por favor?",
    "de": "Konnten wir meinen Termin auf Dienstag verschieben?",
    "ja": "予約を火曜日に変更できますか？",
    "zh": "可以把我的预约改到星期二吗？",
    "ko": "제 예약을 화요일로 옮길 수 있을까요?",
    "hi": "क्या मेरी अपॉइंटमेंट मंगलवार को हो सकती है?",
    "th": "ขอเลื่อนนัดเป็นวันอังคารได้ไหม",
}


def main() -> int:
    wanted = sys.argv[1:] or ["fr", "es", "de", "ja", "zh", "ko", "hi", "th"]
    do_stt = "--stt" in wanted
    wanted = [code for code in wanted if not code.startswith("--")]

    print(f"{'lang':5} {'engine':7} {'voice':28} {'sentence':38} {'audio':>7} {'time':>7}")
    ok = 0
    for code in wanted:
        text = SAMPLES[code]
        settings = Settings.from_mapping({"language": code})
        try:
            started = time.time()
            result = tts.synthesize(text, settings)
            elapsed = time.time() - started
            print(
                f"{code:5} {result.backend:7} {result.voice[:28]:28} {text[:38]:38} "
                f"{result.duration_s:6.2f}s {elapsed:6.2f}s"
            )
            ok += 1
        except Exception as exc:
            print(f"{code:5} FAILED  {type(exc).__name__}: {str(exc)[:90]}")

    print(f"\n{ok}/{len(wanted)} languages spoke.")

    if do_stt:
        print("\nroundtrip: French audio -> multilingual recogniser")
        settings = Settings.from_mapping({"language": "fr"})
        print("  stt model:", settings.stt_model)
        french = tts.synthesize(SAMPLES["fr"], settings)
        started = time.time()
        transcript = stt.transcribe(french.wav, settings)
        print(f"  {time.time() - started:.1f}s -> {transcript.text!r} (model {transcript.model})")
        proposal = intent.reframe(transcript.text, style="courteous")
        print("  proposal:", proposal.message)

    return 0 if ok == len(wanted) else 1


if __name__ == "__main__":
    raise SystemExit(main())
