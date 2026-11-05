"""Why do the Japanese and Thai Piper voices fail? Print the real exception."""

from __future__ import annotations

import os
import sys
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from clearvoice_engine import piper  # noqa: E402

CASES = {
    "ja": ("ja_JP-hi_fi_captain-medium", "予約を火曜日に変更できますか？"),
    "th": ("th_TH-tsync2-medium", "ขอเลื่อนนัดเป็นวันอังคารได้ไหม"),
    "zh": ("zh_CN-huayan-medium", "可以把我的预约改到星期二吗？"),
}

for code, (key, text) in CASES.items():
    print(f"--- {code} {key}")
    try:
        model, config = piper.ensure_voice(key)
        print("   files:", model.stat().st_size, "config:", config.stat().st_size)
        from piper import PiperVoice

        voice = PiperVoice.load(str(model))
        print("   loaded, rate:", voice.config.sample_rate, "| espeak voice:", getattr(voice.config, "espeak", None))
        chunks = [chunk.audio_int16_bytes for chunk in voice.synthesize(text)]
        print("   OK", sum(len(c) for c in chunks), "bytes")
    except Exception:
        print("   FAILED:")
        traceback.print_exc()
