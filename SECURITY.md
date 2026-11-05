# ClearVoice security disclosure

Tier: **High** (business/assistive automation with a microphone, a model runtime,
and an optional paid API). This document is the disclosure a reviewer or a
customer security team should be able to check against the code.

## 1. Attack surface inventory

| Surface | Exists? | Detail |
|---|---|---|
| Network listener / open port | **No** | The backend is a `APIRouter` mounted inside Hermes's gateway at `/api/plugins/clearvoice`. It binds nothing. |
| Background process / daemon | **No** | No threads outliving a request, no timers, no queue workers. |
| Cron / scheduled job | **No** | — |
| Subprocess | **One** | `ffmpeg` with a constant argv, audio on stdin, PCM on stdout. No shell, no filename, no interpolation of any external string. |
| Filesystem reads | **Two kinds** | `phrases.json` in the plugin's own data directory, and the voice/model files inside that same directory (plus Hugging Face's own cache for recognisers). No other path is read. |
| Filesystem writes | **Its own data directory only** | `phrases.json` (explicit save only) and downloaded voice models under `models/piper/`, written to a `.part` sibling and renamed atomically. |
| Outbound network | **Three hosts, all weight downloads or opt-in** | `huggingface.co` (models/voices), `github.com/r9y9/open_jtalk` (the Japanese dictionary, only if that extra is installed), `api.gradium.ai` only when cloud speech is enabled *and* selected *and* a key is present. |
| Credentials | **Read-only, scoped** | `CLEARVOICE_GRADIUM_API_KEY` through `agent.secret_scope.get_secret`. Never logged, never echoed, never stored, never displayed. |
| Hermes core modification | **None** | Only public `ctx.register_tool` / `register_command`. `hermes plugins validate` "no core override" passes. |
| Privileged capabilities | **None requested** | No `tools.override`, no `llm.*`, no platform actions. The manifest declares no `capabilities:` block at all. |

## 2. The microphone

The microphone is the sensitive part of this plugin, so its lifecycle is bounded
by construction:

1. `getUserMedia` is called **inside the press handler** — there is no other call
   site in `desktop/plugin.js`.
2. `MediaRecorder.start()` immediately follows; `recorder.stop()` fires on
   pointer-up, pointer-cancel, pointer-leave-with-no-button, or keyboard key-up.
3. `onstop` stops every `MediaStreamTrack` **before** the clip is sent, so the
   stream object is dead even if the rest of the flow fails.
4. Unmounting the pane, disabling the plugin, or an error all call the same
   `stopTracks()` cleanup.

Consequence: there is no state in which audio is captured without continuous user
intent, and no path where a stream leaks past the turn. Holding a key does not
create a latch: the release path is the only path.

Electron grants the app's renderer microphone permission through Hermes's own
media-capture handler; the OS-level permission (macOS TCC, Windows privacy
settings, PipeWire/PulseAudio) is the user's, and the plugin never asks Chromium
to bypass it. A denied permission surfaces as one plain sentence with the fix.

## 3. The approval gate (why a model cannot speak for you)

`clearvoice_speak` is the only path from the agent to a speaker, and it refuses
by default:

- `confirm_required` defaults to `true` → the handler returns the sentence in a
  `needs_confirmation` payload and does not synthesize anything.
- `POST /speak` independently requires `"approved": true` → a 409 otherwise.
- Only the pane sets that flag, and only in the click handler of **Speak it**,
  on a sentence the user can read and edit.

So there are two independent guards — the tool's `confirm_required` and the
route's `approved` — and neither is reachable from model output alone.

## 4. Input handling

| Input | Bound | Handling |
|---|---|---|
| Audio clip | ~12 MB / 60 s | Base64 decoded with `validate=True`; oversized requests get 413 |
| Sentence | 600 characters | Refused beyond the cap, before any model work |
| Saved phrase | 300 characters | Truncated on write, stored as JSON |
| Transcript text | — | Rendered as a React text node; never `innerHTML`, never a URL, never a shell argument |
| Settings values | — | Coerced to an allow-list; an unknown backend name falls back to the **local** one, never to cloud |
| Gradium responses | — | Parsed as NDJSON line by line; unknown message types ignored; `error` becomes a user-facing message, never an exception relayed raw |

## 5. Failure behaviour (fail closed, loudly)

| Condition | Behaviour |
|---|---|
| Microphone denied / missing / busy | Named state + the specific fix; nothing recorded |
| No speech in the clip | Plain "I didn't catch that" and a fresh turn; no model call at all (energy gate first) |
| Model not installed | Actionable message naming `--install-deps`; the pane offers the retry |
| Cloud selected but cloud off | Refused before any socket is opened |
| Cloud selected, no key | Refused with instructions |
| Cloud unreachable / 401 / 429 | One plain sentence; no credential, no URL, no body in the message |
| ffmpeg missing | WAV still works; other formats say exactly what is missing |
| Any unexpected exception | Caught at the tool boundary and at every route: JSON `{"error": …}` or an HTTP detail, never a traceback to the user |

## 6. Dependency posture

Declared with upper bounds in `pyproject.toml`:

```
ptts>=0.6.0,<0.7
piper-tts>=1.8,<2
faster-whisper>=1.2.1,<1.3
numpy>=1.26,<3
```

`ptts` is a Rust extension (`pyo3`) shipped as a wheel; it executes no shell and
downloads weights only from the documented Hugging Face repo. `piper-tts` runs
ONNX locally and phonemises through **espeak-ng**, which is GPL-3.0 — it is a
separately installed dependency, never vendored into this MIT repository, and the
disclosure is here because a downstream redistributor needs it. Piper voice
models are downloaded per language from `rhasspy/piper-voices` and carry their
own per-voice licence (CC BY 4.0, MIT, …); the plugin ships only the index, not
the weights. Optional phonemizers extend that chain and are never installed
implicitly: `pyopenjtalk` (Japanese, wraps Open JTalk — modified BSD — and
downloads its dictionary from a GitHub release on first use) and `tltk` (Thai,
whose published metadata omits `pandas`, `requests` and `unicode-rbnf`).
`faster-whisper` runs `ctranslate2` locally. None of them opens a listening
socket during normal use, and every download is HTTPS.

## 7. Verifiable claims

```bash
hermes plugins validate ~/.hermes/plugins/clearvoice --install-deps   # catalog gate
hermes plugins doctor   ~/.hermes/plugins/clearvoice                  # real loader
pytest                                                                # 58 tests
python scripts/smoke_test.py                                          # real models, in memory
python scripts/api_selftest.py                                        # every REST route, real audio
```

`tests/test_privacy.py` covers: no disk write during a full pipeline run (audit
hook), no transcript after clear, cloud refused when disabled *with the HTTP
layer instrumented to fail the test if it is touched*, unknown backend values
degrading to local, and the manifest declaring no broad capability.

## 8. Out of scope / known gaps

- The Gradium cloud paths are written against the published REST contract but are
  **not exercised by CI** — no key exists in the test environment. They fail
  early and loudly rather than silently; treat them as user-verified on first use.
- The reframer is heuristic. A confidently wrong sentence is possible; that is
  why the sentence is always shown before it is spoken, and why consequential
  vocabulary forces the confirmation question.
- Local model weights are ~140 MB combined on first download. They are cached by
  Hugging Face in the user's own cache directory, outside the plugin.
- This plugin is not a medical device and makes no clinical claim of any kind.

## 9. Reporting

Open an issue on the repository, or contact the author directly for anything
sensitive. Please do not include audio, transcripts, or API keys in a report.

---

Last reviewed: 2026-11-05 · Version 0.1.0
