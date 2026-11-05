# Worklog

## 2026-11-05 — Built, validated, verified end to end

**Started from:** `clearvoice_hermes_hackathon_build_brief.md` (hackathon build
brief, deadline 2026-11-11).

**Environment checked first:** Hermes Agent v0.22.7+195.g1fcc57e (2026.9.24),
Python 3.14.9, Linux. Read the Desktop SDK docs, the plugin admission rules and
the catalog entry schema before writing code, because the brief's proposed
structure (`.tsx` UI files, `plugin_data_dir` for everything) does not match what
the loader actually accepts.

**Verified before building:**

- Phonon 31m is real: Apache-2.0, 64 MB, via `gradium-ai/xn-ptts`. `pip install
  ptts` works; in-memory synthesis at 24 kHz works (`TTS(lang='en').synth()`).
- The desktop renderer may open the microphone: Hermes's Electron
  `media-capture-permission.ts` allows `audioCapture` for renderer features
  including desktop plugins.
- A local STT path exists: faster-whisper + ffmpeg over pipes, 1.4 s for a 3 s
  clip on CPU.
- Gradium's REST contract (TTS `POST /api/post/speech/tts` with
  `x-api-key`, ASR `POST /api/post/speech/asr` returning NDJSON) is public and
  documented, so the optional path could be implemented against facts rather than
  guesses.

**Built:**

- `clearvoice_engine/` — audio, stt, tts, intent, privacy, cloud, settings,
  runtime. Hermes-free, fully unit testable.
- `__init__.py` — `clearvoice_speak` (two-step approval) + `/clearvoice`.
- `dashboard/plugin_api.py` — nine routes, in-memory audio, approval gate on
  `/speak`, explicit-consent gate on `/phrases`.
- `desktop/plugin.js` — pane, full page, sidebar row, palette entry, status chip;
  push-to-talk with pointer capture and keyboard hold; captions; privacy badge;
  saved phrases; six named states.
- Docs: README, PRIVACY, SECURITY, HACKATHON_SUBMISSION, catalog entry + PR body
  draft, AGENTS/project-context/decisions.

**Verified (real output, not assumptions):**

- `hermes plugins validate . --install-deps` → Validation passed (all 16 checks).
- `hermes plugins doctor .` → `1 tool(s), 0 hook(s)`.
- `pytest` → 38 passed.
- `scripts/smoke_test.py` → Phonon 1.31 s → whisper 1.47 s →
  "Could you move the appointment to Tuesday, please?" → Phonon 0.83 s; data
  directory never created.
- `scripts/api_selftest.py` → every route with real WebM/Opus: transcribe,
  refuse unapproved speak (409), speak approved (142 KB WAV), phrases consent
  gate, clear session.
- Installed via symlink into `~/.hermes/plugins/clearvoice`, enabled, Python deps
  installed into a new environment by Hermes's package manager.
- `hermes chat -q "..."` → the model found and called `clearvoice_speak`, and the
  call reached the handler. It failed at that moment with
  `No module named 'numpy'` because the **running gateway** (PID 11230, started
  04:36) still holds the pre-install environment. The plugin is fine; the process
  is stale.

**Open / next:**

1. `hermes gateway restart` (must be run by the operator — blocked from inside the
   gateway by design), then repeat the tool call to see it complete, and enable
   the Desktop half in Capabilities → Plugins to see the pane.
2. Publish the repository (owner decision; SSH `thebangarang` is configured),
   then pin `catalog/clearvoice.yaml` to the real 40-char SHA.
3. Open the catalog PR with `catalog/PR_BODY.md`.
4. Record the 90-second demo from the shot list in HACKATHON_SUBMISSION.md.
5. Screenshot the pane for the README gallery (needs step 1).

**Lesson worth keeping:** `hermes plugins enable` installs dependencies but a
running gateway never switches environments — and `hermes gateway restart` is
refused from inside the gateway, so the operator has to run it. This was recorded
in the `hermes-plugin-authoring` skill.
