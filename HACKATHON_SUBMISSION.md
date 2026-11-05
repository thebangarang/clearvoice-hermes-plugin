# ClearVoice — Hermes Agent Plugin Hackathon submission

> **The first Hermes plugin to bring Gradium/Phonon real-time voice to the agent
> ecosystem — and the first to use it to help people be understood.**

| | |
|---|---|
| **Plugin name** | `clearvoice` |
| **Version** | 0.2.0 |
| **Licence** | MIT |
| **Languages** | 17 — English, French, German, Spanish, Portuguese, Italian, Dutch, Polish, Russian, Turkish, Arabic, Hindi, Japanese, Mandarin, Korean, Thai, Vietnamese |
| **Category** | accessibility / speech |
| **Hermes surfaces used** | `ctx.register_tool`, `ctx.register_command`, Desktop SDK (pane, route, sidebar nav, palette, status bar), `ctx.rest` → `dashboard/plugin_api.py` |
| **Capabilities requested** | none |
| **Tools** | 1 (`clearvoice_speak`) · **Hooks** 0 · **Middleware** 0 |
| **Requires** | Hermes >= 0.22.0 · `ptts`, `faster-whisper`, `numpy` (all bounded) |

## One-sentence pitch

ClearVoice is a push-to-talk speech-clarity bridge for people whose speech is
hard to understand: you speak naturally, it shows you one clear sentence to
check, and only then speaks it — on-device, in memory, never saved.

## Problem statement

Roughly one in fifty people lives with a speech difference that strangers
misunderstand: aphasia after a stroke, hypophonia in Parkinson's, dysarthria in
cerebral palsy or ALS, a stutter, or a temporary loss of voice after surgery.
The assistive-tech market answers this with dedicated hardware costing hundreds
to thousands of euros, tied to one device and one vendor.

The software that *could* help — text-to-speech with a clear voice — exists and
is now small enough to run on a laptop: Gradium released **Phonon 31m** under
Apache-2.0, 64 MB, speaking in milliseconds on a CPU. What was missing is a
bridge with the right defaults.

Three failure modes kill the obvious implementations:

1. **Always-on listening.** Convenient for a demo, unacceptable in a bedroom, a
   bathroom, a hospice, a workplace. A voice assistant that listens all the time
   is a surveillance device the user cannot audit.
2. **Autonomy.** If the model speaks first and the user corrects it afterwards,
   the tool has put words in the mouth of the person it claims to help. For a
   population where "yes" and "no" carry weight, that is the wrong direction.
3. **The cloud.** Sending a recording of an impaired voice to a vendor is a
   medical-adjacent data transfer. It should be a choice, made three times over,
   not a default.

ClearVoice is the version that refuses all three: hold to talk, see it before
it is spoken, local by default, nothing stored.

## What it does

```
hold ──▶ capture ──▶ transcribe ──▶ propose ──▶ [you check it] ──▶ speak
          (RAM)        (local)      (rules)      Speak it / Edit / Try again / Cancel
```

The pane shows six named states (Ready, Listening, Understanding, Ready to
speak, Speaking, Error) and a permanent privacy line: **"Audio processed this
session only. Nothing saved."**

## Architecture

```
┌──────────────────────── Hermes Desktop (renderer) ────────────────────────┐
│  desktop/plugin.js  —  pane · page · sidebar row · palette · status chip  │
│    PushToTalkButton   CaptionPanel   PrivacyBadge   MyPhrases             │
│    getUserMedia() on press → MediaRecorder → tracks stopped on release    │
│    audio → base64 → ctx.rest('/transcribe')        audio ← base64 ← play  │
└───────────────────────────────┬──────────────────────────────────────────┘
                                │  /api/plugins/clearvoice/*   (loopback, in-process)
┌───────────────────────────────▼──────────────────────────────────────────┐
│  dashboard/plugin_api.py — FastAPI router inside the Hermes gateway       │
│    /status /transcribe /clarify /speak /pending /session/clear /phrases   │
└───────────────────────────────┬──────────────────────────────────────────┘
                                │
┌───────────────────────────────▼──────────────────────────────────────────┐
│  clearvoice_engine/  (Hermes-free, unit-testable)                        │
│    audio.py   bytes → float32 @16 kHz → WAV bytes      (never a file)    │
│    stt.py     faster-whisper local  │  Gradium ASR cloud (gated)         │
│    intent.py  classify → slot fill → confidence → candidates             │
│    tts.py     Phonon 31m local      │  Gradium TTS cloud (gated)         │
│    privacy.py session store (RAM) · saved phrases (explicit only)        │
└──────────────────────────────────────────────────────────────────────────┘
                                │
┌───────────────────────────────▼──────────────────────────────────────────┐
│  __init__.py — agent half: tool `clearvoice_speak`, command `/clearvoice`│
└──────────────────────────────────────────────────────────────────────────┘
```

One installable folder carries both halves; the agent half is gated by
`plugins.enabled`, the Desktop half by its own switch in Capabilities → Plugins,
and both default to **off**.

## Privacy guarantees (each one enforced by a test)

| Guarantee | How it is enforced |
|---|---|
| No always-on microphone | `getUserMedia` has exactly one call site, inside the press handler; tracks stopped on release, cancel, error and unmount |
| Audio buffer exists only during a held turn | one local variable; no module-level buffer, no cache, no queue that outlives the request |
| No audio file, ever | `clearvoice_engine/audio.py` has no filesystem API in it; `test_full_pipeline_writes_no_audio_and_no_transcript` runs the real pipeline under a CPython audit hook and asserts **zero** write-mode `open()` calls |
| No transcript persisted | transcripts live in a 12-slot in-memory ring; `test_session_store_holds_nothing_after_clear` |
| Cloud disabled unless enabled | `test_cloud_stt_is_refused_when_not_enabled` / `…_tts_…` instrument the HTTP layer and fail if it is even *called* while cloud is off |
| No filesystem / mail / calendar / contacts / messaging capability | manifest declares no `capabilities` and one tool; `test_manifest_declares_one_tool_and_no_broad_capabilities` |
| No saved audio on an implicit action | `/phrases` returns 409 without `explicit: true`; `/speak` returns 409 without `approved: true` |

## Technical implementation notes

- **Speech to text.** `faster-whisper` (MIT) with `tiny.en` by default. Browser
  audio is Opus/WebM; it is decoded by `ffmpeg` over **pipes** (stdin → stdout),
  so the recording never touches a temporary file. WAV is decoded with the
  standard library. An RMS energy gate runs first, so silence never costs a model
  call and "I didn't catch that — try again" comes back instantly.
- **Understanding.** A deterministic reframer: filler removal, intent
  classification (request / question / affirmation / negation / greeting /
  statement), slot extraction (verb, object, time expression) and courteous
  reconstruction, plus a confidence score. Consequential vocabulary (`no`,
  `stop`, `help`, `medication`, `money`, `sign`, …) forces the confirmation
  question regardless of confidence. No LLM, no network, identical output twice,
  fully unit-tested — and when it is unsure it shows up to three candidates
  instead of guessing.
- **Speech out.** Phonon 31m via `ptts`, running on CPU, ~0.8 s for a sentence
  after the model is warm. Audio is a NumPy array turned into WAV bytes in
  memory and played from a `data:` URL in the pane. The CC BY-NC 40m checkpoints
  are never referenced.
- **Seventeen languages, two local engines, one rule.** English is voiced by
  Phonon 31m (Apache-2.0) with 37 catalog voices. Every other language is voiced
  by Piper (MIT runtime) with a per-language model — 108 voices indexed, bundled
  offline so the picker works without a network. Phonon's multilingual checkpoint
  is CC BY-NC, so it is not used: the licence decides the architecture, not the
  other way round. Recognition is multilingual Whisper, and an `.en` model is
  swapped out automatically for any non-English language, because a `.en` model
  does not fail on French — it invents fluent nonsense, the worst possible
  failure for someone whose speech is already misunderstood.
- **The rewrite is a choice, not a policy.** `courteous` (default) rebuilds a
  polite request, `literal` keeps your words in a plain order, `verbatim` changes
  nothing but the edges. The user picks; the pane shows "You said: …" underneath
  either way, so the transformation is never hidden.
- **The agent tool is deliberately two-step.** `clearvoice_speak` returns a
  `needs_confirmation` payload instead of speaking unless
  `confirm_required: false`, and `POST /speak` separately requires
  `approved: true`. A model cannot make this plugin say something the user has
  not read.
- **Verification, not vibes.** `hermes plugins validate --install-deps` and
  `hermes plugins doctor` both pass; 38 unit tests; `scripts/smoke_test.py`
  exercises real Phonon + real Whisper end to end; `scripts/api_selftest.py`
  walks every REST route with real WebM/Opus audio.

Measured on the development machine (small desktop CPU, no GPU):

| Step | Time |
|---|---|
| Phonon synth (cold) | 1.2–1.3 s |
| Phonon synth (warm) | 0.8 s |
| faster-whisper `tiny.en` on a 3 s clip | 1.4 s |
| Reframe | < 1 ms |
| Round trip in the pane | ~3 s for a 3 s sentence to become clear speech |

## Demo video script (≤ 90 s)

| Time | Shot | What is on screen |
|---|---|---|
| 0–5 s | Title card | **"ClearVoice — speak naturally. Be understood clearly."** (white on dark, the pane's own type) |
| 5–15 s | A person at a laptop, holding the big button, speaking with effort: *"I need… appointment… Tuesday… move."* | Pane reads **Listening**, the button filled with the accent colour, privacy line already visible at the top |
| 15–30 s | Release. **Understanding** for ~2 s, then the sentence lands | Large text: **"Could you move the appointment to Tuesday, please?"** and below it, small: *You said: "I need appointment Tuesday move."* |
| 30–45 s | Finger hits **Speak it** | **Speaking**, then a clear voice says the sentence. Caption stays on screen. |
| 45–60 s | Slow push-in on the privacy badge | **"Audio processed this session only. Nothing saved."** · Hearing: On-device · Voice: On-device (Phonon 31m) · Network: Offline |
| 60–75 s | Deliberate failure: hold, say nothing (or a noisy room) | **"I didn't catch that — try again."** then **Start over** → back to Ready. Shows the recovery, not a crash |
| 75–90 s | End card | **"No background listening. No saved audio. Built with Hermes + Phonon."** · `github.com/thebangarang/clearvoice-hermes-plugin` |

Voice-over, in the same order: *"She speaks. ClearVoice listens only while the
button is held. It writes down what it heard, shows her one clear sentence — she
can change it, or throw it away. She taps Speak it. The voice is on her machine,
the audio was never saved, and nothing left the laptop. ClearVoice may help
people be understood more clearly. It is not a medical device."*

Rules for the recording: no medical claims, no "treatment", no "cure", no
"restores speech". Show the failure and the recovery — that is what makes the
privacy and the error handling believable.

## Validation output

`hermes plugins validate . --install-deps` on the pinned tree:

```
✓ manifest — plugin.yaml parses
✓ manifest fields — name, version, description present
✓ requires_hermes — spec '>=0.22.0' parses
✓ config schema — shape valid
✓ requires_env — all entries UPPER_SNAKE
✓ oauth — not declared
✓ loadable — entry: __init__.py, desktop/plugin.js
✓ python dependencies — 3 requirements from pyproject
✓ capability probe — register() ran in isolation
✓ declared tools — matches registrations
✓ declared hooks — matches registrations
✓ declared middleware — matches registrations
✓ built-in tool collisions — no collisions
✓ security scan — safe
✓ no core override — no runtime rebinds of Hermes core
✓ desktop surface — stays inside the plugin SDK surface
◆ Isolation — runs in the plugin host (plugins.isolation: host)
  · dashboard backend API is served through the plugin host (buffered responses)

Validation passed.
```

`hermes plugins doctor .`:

```
Plugin Doctor: /home/hermes/projects/Clearvoice-hermes-plugin
  manifest: clearvoice 0.2.0 (standalone)
  OK: runtime discovery, manifest parsing, import, and registration passed
  registrations: 1 tool(s), 0 hook(s)
```

Unit tests: `58 passed`. End-to-end smoke test (real models, no microphone):

```
1. synthesizing with on-device Phonon ... 138284 bytes, 2.88s of speech, 1310 ms
2. transcribing with local faster-whisper ... 1465 ms -> 'Could we move my appointment to Tuesday please?'
3. inferring ... 'Could you move my appointment to Tuesday, please?' (confidence 0.95)
4. speaking the proposal ... 142124 bytes, 2.96s, 834 ms
5. plugin data dir: not created (nothing was written)
OK - end to end, on-device, nothing saved.
```

REST surface, real WebM/Opus audio (the same bytes the pane sends):

```
POST /transcribe  -> 'I need appointment Tuesday move.' -> 'Could you move the appointment to Tuesday, please?'
POST /speak (no approved flag) -> 409 "Show the sentence and let the user approve it first."
POST /speak (approved)         -> 142124 bytes of WAV, backend=phonon, saved=False
data dir holds: ['phrases.json']   (the one phrase the test saved on purpose)
```

## Catalog submission

- **Entry:** [`catalog/clearvoice.yaml`](catalog/clearvoice.yaml) — one file,
  `plugin-catalog/<name>.yaml`, owner-submitted, community tier, pinned to a full
  40-character SHA.
- **PR body draft:** [`catalog/PR_BODY.md`](catalog/PR_BODY.md), including the
  rule-13 disclosure block (network, shell, background, stored credentials).
- **Catalog PR link:** _pending — opened after the repository is published and
  the commit SHA exists._
- **Public repository:** _pending — `github.com/thebangarang/clearvoice-hermes-plugin`._
- **X demo video:** _pending — recorded from the shot list above._

Nothing above is marked done until the link exists. The plugin is not submitted
to the catalog before validation passes; it passes.

## Disclosure summary (rule 13)

- **Network.** No network access by default. Two opt-in paths: a one-time model
  download from Hugging Face on first use, and the Gradium REST API when cloud
  speech is enabled **and** the Gradium backend is selected **and** a key is set.
- **Shell.** One `ffmpeg` invocation with a constant argument vector, audio over
  stdin/stdout. No user data in the command line, no shell.
- **Background processes.** None. No threads outliving a request, no timers, no
  daemons, no cron.
- **Stored credentials.** None written by the plugin. The optional Gradium key is
  read through `agent.secret_scope.get_secret("CLEARVOICE_GRADIUM_API_KEY")`.
- **Filesystem.** Reads and writes exactly one file: `phrases.json` in the
  plugin's own data directory, and only on an explicit **Save phrase** action.
- **Data retention.** Audio, transcripts and generated speech are session-only
  and in memory. No telemetry, no account, no profile, no history.

## Hackathon checklist

| Requirement | State |
|---|---|
| Installs cleanly into Hermes | ✅ enabled and loaded, `plugins list` shows `clearvoice` |
| Desktop pane works | ✅ pane + page + nav + palette + status chip registered |
| Push-to-talk capture works | ✅ `getUserMedia` on press, tracks stopped on release |
| STT works on ≥ 1 backend | ✅ local faster-whisper, verified end to end |
| Intent clarification works | ✅ rules, confidence, candidates, forced confirmation on consequential words |
| Phonon local TTS works | ✅ Apache-2.0 31m on CPU, verified end to end |
| Multilingual works | ✅ all 17 languages voice a sentence — verified by real synthesis, including Japanese (0.51 s warm) and Thai |
| Voice picker works | ✅ 37 English Phonon voices + 108 Piper voices, indexed offline |
| Gradium backend implemented, off by default | ✅ triple-gated (switch + backend + key), refuses before any socket |
| No audio/transcript persisted | ✅ audit-hook test |
| `validate --install-deps` passes | ✅ output above |
| Docs complete | ✅ README, PRIVACY, SECURITY, LICENSE, this file |
| Public repo / catalog PR / demo video | ⏳ pending publication |

## Positioning

A voice plugin for Hermes could have been a convenience: talk to your agent.
ClearVoice is aimed at the opposite end of the same technology — the person for
whom being understood is not convenient but necessary — and it uses the strictest
version of every default to get there: hold to talk, show before speaking,
process on the device, store nothing.
