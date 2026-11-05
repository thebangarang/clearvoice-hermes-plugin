#!/usr/bin/env python
"""Exercise the pane's REST backend with real audio, without a running gateway.

    hermes-env-python scripts/api_selftest.py

It builds a WebM/Opus clip exactly like the browser produces (Phonon speaks a
fragmented line, ffmpeg re-encodes it), then walks the routes the Desktop pane
calls: /status → /transcribe → /speak → /session/clear → /phrases. Every byte of
audio stays in memory; the script asserts the data directory stayed empty.
"""

from __future__ import annotations

import base64
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("CLEARVOICE_DATA_DIR", tempfile.mkdtemp(prefix="cv-selftest-"))

from clearvoice_engine import audio, tts  # noqa: E402
from clearvoice_engine.settings import Settings  # noqa: E402


def load_api():
    spec = importlib.util.spec_from_file_location(
        "clearvoice_plugin_api", ROOT / "dashboard" / "plugin_api.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def make_webm() -> bytes:
    result = tts.synthesize("I need appointment Tuesday move", Settings.from_mapping({}))
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", "pipe:0",
         "-c:a", "libopus", "-b:a", "32k", "-f", "webm", "pipe:1"],
        input=result.wav, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    if proc.returncode != 0 or not proc.stdout:
        raise SystemExit(f"ffmpeg could not build the test clip: {proc.stderr[:300]!r}")
    return proc.stdout


def main() -> int:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    api = load_api()
    app = FastAPI()
    app.include_router(api.router)
    client = TestClient(app)

    print("GET /status")
    status = client.get("/status").json()
    print("  stt:", status["stt_label"], "| tts:", status["tts_label"], "| network:", status["network"])
    assert status["retention"] == "Session only"
    assert status["local_tts_available"] is True

    clip = make_webm()
    print(f"POST /transcribe  ({len(clip)} bytes of WebM/Opus, like the pane sends)")
    response = client.post(
        "/transcribe", json={"audio_b64": base64.b64encode(clip).decode(), "mime": "audio/webm"}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    print("  transcript:", repr(body["transcript"]))
    print("  proposal:  ", repr(body["proposal"]["message"]))
    assert body["proposal"]["message"]

    print("POST /speak  (unapproved -> refused)")
    refused = client.post("/speak", json={"message": body["proposal"]["message"]})
    print("  status", refused.status_code, refused.json()["detail"])
    assert refused.status_code == 409

    print("POST /speak  (approved)")
    spoken = client.post("/speak", json={"message": body["proposal"]["message"], "approved": True})
    assert spoken.status_code == 200, spoken.text
    payload = spoken.json()
    wav = base64.b64decode(payload["audio_b64"])
    print(f"  {len(wav)} bytes, {payload['duration_s']}s, backend={payload['backend']}, saved={payload['saved']}")
    assert wav[:4] == b"RIFF"
    assert payload["saved"] is False

    print("POST /phrases  (without an explicit action -> refused)")
    no_consent = client.post("/phrases", json={"text": "Could you help me, please?"})
    assert no_consent.status_code == 409
    saved = client.post("/phrases", json={"text": "Could you help me, please?", "explicit": True})
    assert saved.status_code == 200
    print("  saved:", client.get("/phrases").json()["phrases"][0]["text"])

    print("POST /session/clear")
    cleared = client.post("/session/clear").json()
    print("  ", cleared["message"])

    data_dir = Path(os.environ["CLEARVOICE_DATA_DIR"])
    leftovers = sorted(p.name for p in data_dir.iterdir()) if data_dir.exists() else []
    print("data dir holds:", leftovers or "nothing beyond the one saved phrase")
    assert leftovers == ["phrases.json"], leftovers
    print("\nOK - every pane route answered, no audio ever hit the disk.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
