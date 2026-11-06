# Project context — ClearVoice

## Identity

- **Plugin id:** `clearvoice`
- **Version:** 0.7.0
- **Type:** Hermes Agent plugin (agent half + Desktop half + REST backend)
- **Purpose:** privacy-first push-to-talk speech-clarity bridge
- **Audience:** people whose speech is hard for others to understand, and the
  people who support them
- **Event:** Hermes Agent Plugin Hackathon, deadline 5 PM EST 2026-11-11
- **Public promise:** "Speak naturally. Be understood clearly. Stay in control."

## Stack

| Layer | Technology |
|---|---|
| Agent half | `__init__.py` — `ctx.register_tool`, `ctx.register_command` |
| Desktop half | ESM `desktop/plugin.js` against `@hermes/plugin-sdk` (no build step) |
| Backend | FastAPI router in `dashboard/plugin_api.py`, mounted at `/api/plugins/clearvoice` |
| Engine | `clearvoice_engine/` — Hermes-free Python, unit-testable |
| STT | faster-whisper `small` (local, MIT) · Gradium ASR (cloud, opt-in) |
| TTS | Phonon 31m via ptts for English (Apache-2.0) · Piper for 16 languages (MIT) · Gradium (cloud, opt-in) |
| Audio | ffmpeg over pipes for decode; NumPy + `wave` for encode; nothing on disk |

## Commands

```bash
.venv/bin/python -m pytest            # unit tests (no models, no network)
python scripts/smoke_test.py          # real models end to end
python scripts/api_selftest.py        # REST surface, real audio
hermes plugins validate . --install-deps
hermes plugins doctor .
```

## Constraints that shape every decision

1. **Privacy is the product**, not a feature. Any change that stores audio or
   transcripts is out of scope.
2. **The user is the authority.** Nothing is spoken before it is shown.
3. **Local by default.** Cloud is a triple-gated opt-in.
4. **Accessibility first.** Large targets, high contrast, full keyboard path, no
   timeouts, no dark patterns.
5. **Narrow manifest.** Three tools, no hooks, no capabilities, no background work.
6. **No language model in the pipeline.** A transcript becomes a sentence through
   rule tables only. An earlier model-assisted path paraphrased and was deleted.

## State of play (2026-11-06)

Working end to end and validated: 160 tests, `validate` and `doctor` green, public
repository published, 80-second demo recorded (`demo/clearvoice-demo.mp4`).
Remaining before submission: pin the catalog entry to a real SHA and open the
catalog PR.
