# Worklog

## 2026-11-05 (v0.3.0) — three tools, a personal dictionary, learning off by default

**Trigger:** two questions from the user — "how do we improve accuracy, and can
it learn?" and "this is just a panel, where are the functions?" — plus three UI
bugs from a real session (unreadable pickers, a voice dropdown that would not
open, no way to choose where phrases are saved).

**Accuracy, measured before deciding** (`scripts/accuracy_bench.py`, French,
real voice, 3 runs per condition): `base` 11–15% WER, `small` 5.6% at 3–5×
latency, `base` + dictionary 0–4%. The lexicon wins on accuracy *and* speed, so
that is what got built rather than a model upgrade or fine-tuning.

**Built:**

- `clearvoice_engine/lexicon.py` — `dictionary.json`: user terms, learned
  heard→said pairs, `hotwords()` for the recogniser, `apply()` for corrections,
  word-level diff learning. Caps, dedupe, accent-insensitive matching.
- Tools: `clearvoice_transcribe` (audio file → text), `clearvoice_speak`
  (text → speech, `deliver: pane|file`), `clearvoice_say_back`
  (listen → propose → speak). Bundled skill `skills/clearvoice/SKILL.md`.
- `deliver: file` is gated behind a new `allow_speech_files` setting (off by
  default) so the "nothing written" promise survives by default.
- Pane: readable pickers (app's own Select, OS-colour fallback), voices scoped to
  the language and ordered best-first, a Personal dictionary panel, a
  "Learn from my corrections" switch (off by default), and a choosable saved-
  phrases folder with "Open folder".
- Docs: README accuracy section, PRIVACY (dictionary + "no community, ever"),
  SECURITY (writes), decisions D-012/D-013.

**Verified:** 75 tests; `validate` green with three declared tools; `doctor`
`3 tool(s), 0 hook(s)`.

**Open:** the pane needs one gateway restart to see the new routes; then the
multilingual demo.

---

## 2026-11-05 (later) — v0.2.0: 17 languages, voice picker, rewrite styles

**Trigger:** the plugin worked in English but did nothing in French; the user
asked for all languages, including Japanese/Chinese/Korean/Thai/Hindi, plus more
"speak it" voices, and pushed back on the courteous rewrite changing his sentence.

**Root cause of the French failure (three separate causes, only one of them
architectural):**

1. STT defaulted to `tiny.en`, an English-only model. A `.en` model does not
   error on French — it returns fluent nonsense.
2. `ptts.TTS(lang='fr')` loads the **same English checkpoint** (verified:
   `model.languages == ['en']`, warning *"text is normalized as fr, but the model
   was trained for en"*).
3. Phonon's actual multilingual checkpoint (40m) is CC BY-NC, so it is not
   shippable in an MIT plugin.

**Built:**

- `clearvoice_engine/langs.py` — 17 languages, each mapped to an STT model and a
  voice engine; `whisper_model_for()` swaps a `.en` model for a multilingual one.
- `clearvoice_engine/piper.py` — Piper engine (MIT), atomic voice download into
  the plugin data dir, in-memory load, cached per voice.
- `clearvoice_engine/data/piper_voices.json` — 108 voices across the 17
  languages, generated once by `scripts/build_piper_index.py` so the picker works
  offline.
- `tts.py` — engine routing (Phonon for English, Piper elsewhere, Gradium on
  request), catalog voices with an in-process cache, and a refusal when someone
  forces Phonon at a non-English language.
- `intent.py` — three rewrite styles (`courteous`, `literal`, `verbatim`).
- `dashboard/plugin_api.py` — `/languages`, `/voices`, per-request overrides.
- `desktop/plugin.js` — language + voice + rewrite selectors, persisted in
  `ctx.storage`, never in `config.yaml`.
- 17 new tests (`tests/test_languages.py`), README/PRIVACY/SECURITY/SUBMISSION
  updated, version 0.2.0.

**Verified:** 58 tests pass; `validate --install-deps` passes; `doctor` reports
`1 tool(s), 0 hook(s)`.

**Language verification, real synthesis on this machine (`scripts/lang_probe.py`):**

```
fr  piper  fr_FR-siwis-medium      3.10s of audio   OK after 4.6s cold
es  piper  es_ES-davefx-medium     2.01s            OK
de  piper  de_DE-thorsten-medium   2.35s            OK
zh  piper  zh_CN-huayan-medium     2.65s            OK
ko  piper  ko_KR-kss-medium        2.86s            OK
hi  piper  hi_IN-priyamvada-medium 3.34s            OK
vi  piper  vi_VN-vais1000-medium   1.86s            OK
it  piper  it_IT-paola-medium      2.23s            OK
ar  piper  ar_JO-kareem-medium     3.48s            OK
pt / ru / pl / tr / nl                              OK
th  piper  th_TH-tsync2-medium     3.02s            OK after installing tltk's undeclared deps
ja  piper  ja_JP-hi_fi_captain-medium 2.94s         OK once pyopenjtalk had cmake to build with
```

Japanese is the one that needed a build: Piper's Japanese voice phonemises with
`pyopenjtalk`, which ships no wheel, so it needs `cmake` + a C++ compiler. It was
then measured at **0.51 s warm** for 2.87 s of audio. The first run also fetches
the Open JTalk dictionary (~23 MB) from a GitHub release — disclosed in PRIVACY.
Rather than leave a cryptic "the voice failed", a missing phonemizer is now
mapped to the exact install line, each language reports `ready: true/false`, and
the pane prints the hint before you record. Thai had the same shape of problem
(tltk's metadata omits pandas/requests/unicode-rbnf) and is fixed by one
documented install line.

**Open:** `hermes gateway restart` again (the dependency set changed, so the
running gateway is stale a second time), then record the multilingual demo.

---

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
