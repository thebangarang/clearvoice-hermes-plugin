"""Generate the bundled Piper voice index (`clearvoice_engine/data/piper_voices.json`).

Run once when the voice list needs refreshing:

    python scripts/build_piper_index.py

The file ships with the plugin so the voice picker works offline; downloading a
voice later is the only network call, and only for the voice the user picks.
"""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path

URL = "https://huggingface.co/rhasspy/piper-voices/resolve/main/voices.json"
OUT = Path(__file__).resolve().parent.parent / "clearvoice_engine" / "data" / "piper_voices.json"

#: Languages ClearVoice offers in its picker. Everything Piper ships for those
#: families is included; the map value is the shipped default voice.
FAMILIES = {
    "en": "en_US-lessac-medium", "fr": "fr_FR-siwis-medium", "de": "de_DE-thorsten-medium",
    "es": "es_ES-davefx-medium", "pt": "pt_BR-faber-medium", "it": "it_IT-paola-medium",
    "nl": "nl_NL-ronnie-medium", "pl": "pl_PL-gosia-medium", "ru": "ru_RU-irina-medium",
    "tr": "tr_TR-dfki-medium", "ar": "ar_JO-kareem-medium", "hi": "hi_IN-priyamvada-medium",
    "ja": "ja_JP-hi_fi_captain-medium", "zh": "zh_CN-huayan-medium", "ko": "ko_KR-kss-medium",
    "th": "th_TH-tsync2-medium", "vi": "vi_VN-vais1000-medium",
}


def main() -> int:
    with urllib.request.urlopen(URL, timeout=60) as response:
        raw = json.loads(response.read().decode())

    voices = []
    for key, meta in raw.items():
        family = meta["language"]["family"]
        if family not in FAMILIES:
            continue
        onnx = next(iter(meta["files"]))
        voices.append(
            {
                "key": key,
                "family": family,
                "region": meta["language"]["code"],
                "name": meta["name"],
                "quality": meta["quality"],
                "speakers": meta.get("num_speakers", 1),
                "size_mb": round(meta["files"][onnx]["size_bytes"] / 1e6),
                "native": meta["language"].get("name_native", ""),
            }
        )

    voices.sort(key=lambda v: (v["family"], {"x_low": 0, "low": 1, "medium": 2, "high": 3}[v["quality"]], v["key"]))
    payload = {"source": URL, "licence": "per voice (CC BY 4.0, MIT, …) - see rhasspy/piper-voices", "defaults": FAMILIES, "voices": voices}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {OUT.relative_to(OUT.parents[2])}: {len(voices)} voices across {len(FAMILIES)} languages")
    for family in FAMILIES:
        count = sum(1 for v in voices if v["family"] == family)
        print(f"  {family}: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
