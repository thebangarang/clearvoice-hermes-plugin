# Worklog

## 2026-11-05 (v0.5.0) — a table per language, and the local model measured and rejected

**Trigger:** "I really think we should try to deliver the most universal and multi
language support plugin… Is it really that long and complex to get a good batch of
rule packs for all these languages?"

**Measured first, twice.**

1. *What a rule pack cost as it was.* French was 379 lines + 140 test lines and 84
   verb forms — because it re-implemented the whole algorithm. That is not a table,
   it is a second engine.
2. *What the alternative costs.* `llama-cpp-python` + Qwen2.5-1.5B-Instruct Q4 on
   this CPU: loads in 2.1 s, median 2.7 s per sentence few-shot, 19.7 s worst case.
   On fragmented input it concatenates instead of restructuring ("I need an
   appointment for Tuesday and move."), French came back ungrammatical, and
   Vietnamese mixed Chinese characters. A 7B would fix the quality and be ~10×
   slower here. Rejected on evidence.

**Built instead:** `intent_packs.py` — one shared pipeline (strip the frame, find the
verb, lift the time span, keep the object with its article) plus one `Pack` per
language: verbs, time words, frame words, determiners, courtesy template. Verb-final
languages are just a different template. Packs for de/es/it/pt/nl join en and fr:
**7 rebuilt, 10 polished and labelled.** A new language is ~80 lines, reviewable by
a native speaker without reading the engine.

```
de  Könnten Sie meinen Termin von Dienstag auf Donnerstag bitte verschieben?
es  ¿Podría cambiar mi cita del martes al jueves, por favor?
it  Potrebbe spostare il mio appuntamento da martedì a giovedì, per favore?
pt  Poderia mudar a minha consulta de terça para quinta, por favor?
nl  Kunt u mijn afspraak van dinsdag naar donderdag verplaatsen, alstublieft?
```

Bugs the tests caught while building it:
- umlauts: "können" never matched "konnen", so the German frame leaked ("Könnten
  Sie können das Rezept…"). Frame and filler sets are normalised now.
- articles vs frame words: `mi`, `il`, `a`, `mijn` were in both lists, so objects
  lost their article ("Podría cambiar cita"). A test now forbids the overlap.
- time spans swallowed the following preposition, so "morgen an die Apotheke"
  became the time phrase and the pharmacy vanished from the request.
- "danke" became "danke, bitte": gratitude and greetings are exempt now.

**Verified:** 160 tests, `validate` green, `doctor` 3 tools / 0 hooks, v0.5.0.

---

## 2026-11-05 (v0.3.2) — the reframer learns French, and the demo speaks one language

**Trigger:** "in english, it will guess the sentence and put words in order and
add more words if needed. In french it's literally the exact thing I said." Plus:
"why should I do a demo on the french part that's not working if we don't show
the progression with the learning function."

The first report was a real defect, reproduced in one line:

```
en | request | 0.95 | Could you move the appointment to Tuesday, please?
fr | statement | 0.75 | J'ai besoin rendez-vous mardi déplacer.
```

The reframer was English-only — English verb list, English time words, English
"Could you…" frame — so on French it matched nothing and returned the transcript
with a capital letter. Fixed with `clearvoice_engine/intent_fr.py`: French verb
forms (infinitive + spoken inflections), day/month/relative time spans including
"de mardi à jeudi", frame-word stripping that survives elision ("j'ai" → "j"),
an article guesser with elision ("l'ordonnance", "la facture", "le rendez-vous"),
French classification (request/question/affirmation/negation/greeting), and a
"Pourriez-vous … s'il vous plaît ?" frame. `reframe(..., language=)` dispatches;
`guess_language()` decides when the caller has no language, and defaults to
English on a tie.

Live proof through the real pipeline (Piper fr → Whisper base fr):
"J'ai besoin de déplacer mon rendez-vous de mardi à jeudi s'il vous plaît."
→ **"Pourriez-vous déplacer mon rendez-vous de mardi à jeudi, s'il vous plaît ?"**

Bugs found on the way:
- "à" normalises to "a" (avoir) and was stripped as a frame word, turning "à
  propos des ordonnances" into "propos des ordonnances".
- Proper nouns were lowercased ("Lefèvre" → "lefèvre").
- `guess_language("yes")` returned French, which put English single words on the
  French pack; English is now the default on a tie.
- `runtime.data_dir()` imported Hermes' storage module unconditionally, so the
  engine crashed on a plain Python import — the exact claim INTEGRATION.md makes.
  It now falls back to the XDG data directory.

Demo: one language, English, with the dictionary progression as the last beat
(miss a name → add the word → say it again). French is out of the video: without
showing the learning fix, a French failure is a bug on camera.

**Verified:** 103 tests (18 new French ones), the live pipeline above.

---

## 2026-11-05 (v0.3.1) — the demo now follows the take instead of the other way round

**Trigger:** "the audio is only 1:04 and the video is supposed to be 1:30 …
how do you expect me to make the video synced with all this? It's almost
impossible for me to shoot it."

That was a design fault, not a shooting problem: a fixed 64-second narration plus
a ten-beat cue sheet assumed a performer. Replaced with `scripts/cut_demo.py`:

- `silencedetect` on the take's audio → active moments; short gaps merged so a
  sentence is never split.
- Moments kept in order until 86 s of screen; dead air and the leftover tail
  dropped. Fumble at the start, three-minute take: both fine.
- Title card (3 s) + moments + end card (4 s), captions burned onto the beats
  **it** found, `+faststart`, 1080p30.
- `--narration` mixes the on-device voice-over *under* the take, never instead
  of it. Default off: the voice in the demo should be the app's.
- `docs/DEMO.md` states the protocol: record once, naturally, stop when done.

Bugs found and fixed while proving it on a stand-in take (82.4 s → 70.7 s):
- SRT stamps written as `MM:SS.mmm` → libass refused the file with a misleading
  "Unable to open"; now `HH:MM:SS,mmm`.
- Unlabelled `subtitles` filter could not bind in a multi-input graph; now
  `[0:v]…[vout]` and explicit maps.
- 19 micro-segments from per-breath detection → merged to 5 real moments.

**Verified:** 85 tests (6 new, on the cutter's pure functions), the build run end
to end, and a frame inspected to confirm the captions render at the bottom.

---

## 2026-11-05 (v0.3.0) — three tools, a personal dictionary, learning off by default

**Trigger:** two questions from the user — "how do we improve accuracy, and can
it learn?" and "this is just a panel, where are the functions?" — plus three UI
bugs from a real session (unreadable pickers, a voice dropdown that would not
open, no way to choose where phrases are saved).

**Accuracy, measured before deciding** (`scripts/accuracy_bench.py`, French,
real voice, 6 runs per condition): `base` 22.6% WER at 1.15 s, `small` 5.6% at
2.80 s, `base` + hotword list 5.6% at 0.99 s, `base` + dictionary 3.8% at
0.89 s. The lexicon wins on accuracy *and* speed, so that is what got built
rather than a model upgrade or fine-tuning.

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
