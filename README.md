# ClearVoice

**Speak naturally. Be understood clearly. Stay in control.**

ClearVoice is a Hermes Agent plugin: a push-to-talk speech-clarity bridge for
people whose speech may be hard for others to understand — aphasia, Parkinson's,
cerebral palsy, ALS, stuttering, a stroke recovery, or a temporary voice
impairment such as after surgery or with a bad cold. It works in **17 languages**,
and both the recognition and the voice run on your own machine.

You hold a big button, speak however you can, and let go. ClearVoice writes down
what it heard, proposes one clear sentence, **shows it to you in large text
before anything is spoken**, and — when you press *Speak it* — says it aloud in a
clear on-device voice.

- **Not** an always-on assistant. The microphone is open only while the button is held.
- **Not** a cloud product. Speech recognition and the voice both run on your machine.
- **Not** a memory. Nothing about you is stored: no profile, no history, no telemetry.

> ClearVoice may help people communicate more clearly. It is not a medical
> device, it does not diagnose or treat anything, and it is not a substitute for
> speech therapy.

---

## The 30-second path

```bash
# 1. install the plugin (from this repo)
hermes plugins install thebangarang/clearvoice-hermes-plugin --enable

# 2. open it
#    Desktop: Sidebar → ClearVoice (or /clearvoice in a chat)
#    First run downloads the on-device voice (~64 MB) and a small STT model (~75 MB).

# 3. hold "Push to talk", speak, release, check the sentence, press "Speak it".
```

Two gates, both opt-in: the Python half loads only when the plugin is enabled
(`hermes plugins enable clearvoice`), and the Desktop half stays **off** in
Capabilities → Plugins until you switch it on. Nothing runs before you say so.

---

## What the user actually sees

```
┌──────────────────────────── ClearVoice ────────────────────────────┐
│  ● Audio processed this session only. Nothing saved.   [Clear session] │
│  Hearing: On-device (faster-whisper)   Voice: On-device (Phonon 31m)   │
│  Network: Offline                                                       │
├────────────────────────────────────────────────────────────────────┤
│                                                                        │
│                    ┌──────────────────────────┐                        │
│                    │      Push to talk        │   ← 148 px tall, huge   │
│                    └──────────────────────────┘                        │
│                                                                        │
│    Could you move the appointment to Tuesday, please?                  │
│                                 ↑ 24 px semibold, never spoken unseen   │
│                                                                        │
│    [ Speak it ]  [ Edit it ]  [ Try again ]  [ Cancel ]                │
└────────────────────────────────────────────────────────────────────────┘
```

Six states, always named on screen: **Ready · Listening · Understanding · Ready
to speak · Speaking · Error**. A failure never dead-ends — every error message is
one plain sentence plus the action that fixes it ("The microphone is blocked.
Allow microphone access for Hermes in your system settings, then try again.").

A static rendering of the three main states, drawn from the same tokens as
`desktop/plugin.js`, is in [`docs/pane-mockup.html`](docs/pane-mockup.html).

---

## How it works

```
        hold button                 release
             │                         │
   ┌─────────▼─────────┐     ┌─────────▼─────────┐      ┌──────────────────┐
   │ microphone open   │────▶│ clip in memory    │─────▶│ transcribe       │
   │ (only while held) │     │ (never a file)    │      │ local · Gradium  │
   └───────────────────┘     └───────────────────┘      └────────┬─────────┘
                                                                  │ text
                                                     ┌────────────▼─────────┐
                                                     │ intent reframer      │
                                                     │ deterministic, local │
                                                     └────────────┬─────────┘
                                                                  │ proposal
                   ┌──────────────────────────────────────────────▼─────────┐
                   │ shown in large text · edit · candidates if it is unsure │
                   └──────────────────────────────┬─────────────────────────┘
                                                  │ "Speak it"
                                     ┌────────────▼─────────────┐
                                     │ Phonon 31m synth (local) │──▶ audio in RAM ──▶ speaker
                                     └──────────────────────────┘
```

Nothing but the audio ever crosses a process boundary, and the audio is a
base64 blob in a request body — not a file, not a URL, not a cache entry.

**The "understanding" step is rules, not a language model.** A fragmented
transcript is classified (request, question, affirmation, negation, greeting,
statement) and rebuilt from a small, auditable rule set. That is a deliberate
trade: it runs offline, answers in milliseconds, gives the same answer twice,
and can be unit-tested line by line. When the rules are unsure they say so,
offer up to three candidate sentences, and ask before speaking.

```
"I need... appointment... Tuesday... move."
   → "Could you move the appointment to Tuesday, please?"      (confidence 0.95)
"medicine"                                                       (confidence 0.35)
   → asks: "I'm not sure I got that. Is this what you meant?"
```

Certain words always trigger the confirmation question regardless of confidence:
`no`, `stop`, `yes`, `help`, `hurt`, `fall`, `medication`, `money`, `sign`,
`address`, `emergency` and similar. A speech bridge must never sound confident
on the sentence where confidence is dangerous.

---

## Privacy model

| Question | Answer |
|---|---|
| Is the microphone ever always-on? | No. It is opened on press and every track is stopped on release; the pane tears the stream down on unmount too. |
| Where does the audio live? | In memory, for the seconds between release and transcription. |
| Is audio written to disk? | Never. No WAV, no temp recording, no cache. (This is asserted by tests using a CPython audit hook.) |
| Are transcripts stored? | Only in RAM, for the current app session, so you can re-read or repeat the last sentence. **Clear session** empties it; a restart starts empty. |
| Is anything sent off-device? | Not by default. The on-device path makes **no network call at all**. Gradium cloud is opt-in, off by default, needs your own key, and is selected per backend. |
| Telemetry / accounts / profiles? | None of the three. There is no analytics endpoint in the code, no login, and no behavioural memory. |
| What *is* on disk? | Only what you explicitly save: the sentences you add with **Save phrase**, in `phrases.json` inside the plugin's data directory. |
| Can it send messages? | No. It speaks into the room. It has no access to email, calendar, files, contacts or messaging, and no capability to reach them. |

The full statement is in [PRIVACY.md](PRIVACY.md).

---

## Accuracy: your own words beat a bigger model

Measured on this machine with `scripts/accuracy_bench.py` (French audio, real
voice, three runs per condition):

| Setup | mean word-error-rate | mean time |
|---|---|---|
| `base` (default) | **22.6%** (22.2–23.1%) | 1.15 s |
| `small` | **5.6%** (0.0–11.1%) | 2.80 s |
| `base` + hotword list | **5.6%** (0.0–11.1%) | 0.99 s |
| `base` + **personal dictionary** (shipped path) | **3.8%** | 0.89 s |

Six runs per condition, French, the on-device voice synthesising the test audio.
The spread is real — quantised CPU inference wobbles on borderline words — so
treat these as orders of magnitude, not a benchmark ranking. The shape is what
matters: **the dictionary cut errors by 6× and made the slowest option
unnecessary.**

A short word list — the names, streets, medications and phrases *you* use — passed
to the recogniser as a prompt fixes repeated errors and costs nothing in latency.
That is the **Personal dictionary** in the pane:

- **Add words** you say often (a name, a street, a treatment). They bias the
  recogniser toward them.
- **Learn from my corrections** (off by default). When you fix a proposed
  sentence, the pair "what it heard → what you meant" is stored locally and
  applied to later transcripts.
- Everything is visible in the pane, deletable in one click, and kept in
  `dictionary.json` in the plugin's data folder. **Nothing is shared, ever** — no
  community packs, no upload, no telemetry.

If accuracy feels unreliable, that is the first thing to turn on: a dozen words
usually does more than a model three times slower.

---

## Languages and voices

ClearVoice speaks and understands **17 languages**, all on-device:

| | |
|---|---|
| **Languages** | English, French, German, Spanish, Portuguese, Italian, Dutch, Polish, Russian, Turkish, Arabic, Hindi, Japanese, Mandarin Chinese, Korean, Thai, Vietnamese |
| **Recognition** | faster-whisper, multilingual (`tiny`/`base`/`small`). An `.en`-only model is never left in place for a non-English language — it would return fluent nonsense instead of an error, which is the worst possible failure here |
| **Voice, English** | Phonon 31m (Apache-2.0), **37 catalog voices** — Zoey, Juniper, Everly, Harper, Hadley, Delia … downloaded once per voice |
| **Voice, other 16** | **Piper** (MIT runtime). 108 voice models in the bundled index: 7 French, 10 German, 9 Spanish, 4 Chinese, 3 Hindi, 3 Vietnamese, and one each for Japanese, Korean and Thai |
| **Voice picker** | In the pane: pick a language, then any voice for it. The choice is remembered (`ctx.storage`), never written into `config.yaml` |
| **Out of the box** | All 17 voice a sentence, verified by real synthesis on this machine. **Thai** needs `pip install tltk pandas requests unicode-rbnf` and **Japanese** needs `pyopenjtalk` (declared as optional extras `clearvoice[th]` / `clearvoice[ja]`; `pyopenjtalk` may build from source, so have `cmake` and a C++ compiler). The pane flags a language whose voice is not installed yet and prints the exact command |
| **Sentence rewriting** | Full rebuilding in **English and French**. The other 15 are **polished**: punctuation tidied, capitalised, and closed with the language's own politeness word, with the confirmation question in that language — but the word order is untouched, and the pane says so |

"J'ai besoin… rendez-vous… mardi… déplacer." becomes *"Pourriez-vous déplacer le
rendez-vous pour mardi, s'il vous plaît ?"* — the same reordering as English, from
a French rule pack (`clearvoice_engine/intent_fr.py`), not from a model.

German gets *"Ich muss meinen Termin verschieben, bitte."* — its own words, made
polite, and *"Ist das, was Sie sagen wollten?"* as the check. That distinction
("rebuilt" vs "polished") is shown in the pane rather than hidden.

Why two engines: Gradium's only permissively-licensed Phonon checkpoint is
English — the multilingual 40m model is **CC BY-NC**, which a commercial plugin
cannot ship. Piper fills every other language under MIT. Neither makes a network
call while you speak; each engine downloads a model once, on first use, and
says so in the privacy badge.

Measured on a small desktop CPU, no GPU: French sentence → **0.26 s** of
synthesis at 22 kHz (Piper), Japanese/Thai/Korean the same engine and order of
magnitude. First use of a language downloads its voice (~60–80 MB) and the first
utterance in that language pays a one-time model load.

Fair warning on quality: English (Phonon) is noticeably more natural than the
non-English Piper voices, and the single-voice languages (Japanese, Korean, Thai)
are the weakest of the set. They are intelligible; they are not premium. That is
a limitation of the permissive-licence landscape, not a configuration mistake,
and it is stated here rather than discovered in a demo.

### Local Phonon — default, on-device

ClearVoice uses **Phonon 31m English**, Gradium's 31-million-parameter TTS model
released under **Apache 2.0**, through `ptts`, its official runtime
([gradium-ai/xn-ptts](https://github.com/gradium-ai/xn-ptts)). Inference runs on
your CPU. On a small desktop-class machine a short sentence synthesizes in about
0.8–1.3 s including model load, at 24 kHz mono.

The first synthesis downloads the checkpoint (~64 MB) from Hugging Face. After
that the voice works with the network unplugged.

The **CC BY-NC** Phonon 40m models are not used, not downloaded, and not
referenced by this plugin — a commercial-use plugin has no business near a
non-commercial licence.

### Local speech-to-text — default, on-device

`faster-whisper` (MIT) with a small English model (`tiny.en` by default,
~75 MB, downloaded on first use). Decoding is done with `ffmpeg` over pipes —
stdin in, stdout out — so the recording never touches a temporary file. WAV is
decoded with the standard library, so a machine without ffmpeg still works for
WAV input.

Accuracy note: `tiny.en` is fast and forgiving; it is not perfect. `base.en` or
`small.en` in Settings → Plugins → ClearVoice are meaningfully better and
noticeably slower. Because ClearVoice always shows the sentence before speaking
it, a transcription error costs you an edit — not a wrong thing said out loud.

### Gradium cloud — optional, off by default

Select `gradium` as a backend, turn on **Allow cloud speech**, and paste your
own API key in Settings → Plugins → ClearVoice. Three separate consents have to
line up before a byte leaves the machine: the switch, the backend choice, and
the key.

| Use | Endpoint |
|---|---|
| Voice | `POST https://api.gradium.ai/api/post/speech/tts` (`output_format: wav`) |
| Transcript | `POST https://api.gradium.ai/api/post/speech/asr` (NDJSON) |

The key is stored in `.env` as `CLEARVOICE_GRADIUM_API_KEY`, read through
Hermes's secret scope, and never logged, echoed in an error, or shown in the UI,
which only ever reports whether one is set. When the cloud backend is active the
pane says so in the privacy badge (`Network: Cloud optional`) — there is no
silent fallback from local to cloud, ever.

---

## Installation

### From Git (recommended)

```bash
hermes plugins install thebangarang/clearvoice-hermes-plugin
hermes plugins enable clearvoice       # consent to the two Python deps
```

Then, in Hermes Desktop: **Capabilities → Plugins → ClearVoice → enable**, and
**Rescan** if the ClearVoice row does not appear in the sidebar. The Desktop half
is a separate, deliberate switch; the pane will not appear until you flip it.

Dependencies are declared in `pyproject.toml` with upper bounds:
`ptts>=0.6.0,<0.7`, `faster-whisper>=1.2.1,<1.3`, `numpy>=1.26,<3`.

### From a local checkout (development)

```bash
git clone https://github.com/thebangarang/clearvoice-hermes-plugin
ln -s "$PWD/clearvoice-hermes-plugin" ~/.hermes/plugins/clearvoice
hermes plugins enable clearvoice
```

A symlinked package is hot-reloaded: saving `desktop/plugin.js` re-syncs the copy
the app runs.

### Requirements

- Hermes Agent **>= 0.22.0** (Desktop app for the pane; the tool and slash command work in the CLI too).
- Python 3.10+ with the plugin's two dependencies (installed for you).
- `ffmpeg` on `PATH` for Opus/WebM input (that is what the browser records). Without it, WAV input still works.
- A working microphone. On macOS, Hermes must have microphone permission.

### Verify your install

```bash
hermes plugins validate ~/.hermes/plugins/clearvoice --install-deps
hermes plugins doctor ~/.hermes/plugins/clearvoice
python scripts/smoke_test.py    # real Phonon + real whisper, end to end, no mic needed
```

`smoke_test.py` synthesizes a sentence, transcribes it back, reframes it, speaks
the result, and asserts that nothing was written to disk. It is the fastest way
to know the pipeline works on your machine before you trust it with your voice.

---

## Using it

| Action | How |
|---|---|
| Talk | Hold **Push to talk** (mouse, touch, or hold Space/Enter while focused) |
| Talk without holding | Not supported on purpose — a stuck key must not become an open microphone |
| Change the sentence | **Edit it** → type → **Done editing** → **Speak it** |
| Hear it again | **Speak it** again; the sentence stays until you cancel |
| Start over | **Try again**, or **Cancel** (which also clears the session) |
| Save a sentence you use often | Type or approve it, then **Save phrase** in *My phrases* |
| Insert a saved phrase | Tap it in *My phrases* — it becomes the sentence, unspoken until you say so |
| Use it from a chat | `/clearvoice` opens the pane; `/clearvoice <words>` proposes a sentence in the transcript |
| Let the agent speak | The tool `clearvoice_speak` (see below), always through the pane, never on its own |
| Transcribe a recording | `clearvoice_transcribe` — audio file in, text out |
| "Say it again, clearly" on a file | `clearvoice_say_back` — listen, propose, speak |

### The tools — for the agent, and for your own pipelines

ClearVoice is not only a pane. Three tools are registered for the model, and the
same code is importable, so a workflow can use whichever half it needs:

| Tool | Input → output | Use it for |
|---|---|---|
| `clearvoice_transcribe` | `audio_path` → transcript (+ optional reframed sentence) | dictation, voice notes, meeting snippets, subtitles |
| `clearvoice_speak` | `text` → speech in the pane, or one WAV with `deliver: "file"` | reading something aloud, voice-over, an agent that speaks |
| `clearvoice_say_back` | `audio_path` → transcript → clear sentence → spoken | repeating an unclear recording so someone else understands it |

`clearvoice_speak` is deliberately two-step:

```jsonc
// confirm_required: true (the default) — refuses, and returns the sentence
{"spoken": false, "needs_confirmation": true,
 "text": "Could you move the appointment to Tuesday, please?",
 "then": "call clearvoice_speak again with confirm_required=false once the user accepts it"}

// confirm_required: false — speaks it, in memory, into the open pane
{"spoken": true, "backend": "phonon", "voice": "default", "duration_s": 2.9,
 "delivered_to": "clearvoice pane (in memory)", "saved": false}
```

A model cannot make this plugin say something the user has not seen: the pane
sets `confirm_required: false` only after the user pressed **Speak it** on a
sentence on screen. If the pane is closed the audio is discarded after 120 s and
nothing lands on disk.

`deliver: "file"` is the one way speech reaches the disk, it writes exactly one
WAV into the plugin's `speech/` folder, and it stays **off** until you enable
*Allow speech files* in settings. That is what a video, podcast or another agent
pipeline uses.

A bundled skill (`clearvoice`) teaches the agent when to reach for each tool and
that the approval gate is not optional.

### Using it from outside Hermes

Four surfaces, in increasing order of coupling — a shell command with `--json`,
the plugin's local HTTP routes, a plain Python import of `clearvoice_engine`, or
the three agent tools. Recipes and the full route table are in
[docs/INTEGRATION.md](docs/INTEGRATION.md).

```bash
hermes clearvoice say "The pharmacy closes at six." --json
hermes clearvoice hear ~/notes/voice-note.webm --json --reframe
hermes clearvoice say-back ~/notes/mum.webm --out ~/notes/clear.wav
```

---

## Accessibility notes

- **148 px** push-to-talk target, **24 px** proposed sentence, **18–20 px** body
  and buttons — well above WCAG AA minimums.
- **High contrast** by construction: text and panels use the app's own theme
  tokens, so the pane follows light/dark mode and every theme instead of
  hardcoding a palette that fails one of them.
- **Full keyboard path**: Tab to the button, hold Space or Enter to talk, release
  to stop. Every action is a real `<button>`, focus rings are never removed.
- **Screen readers**: the proposed sentence is an `aria-live="polite"` status
  region, errors are `role="alert"`, and the button reports `aria-pressed` while
  listening.
- **No time limits anywhere**: no countdown, no auto-dismiss, no auto-speak. You
  can stare at the sentence as long as you like before committing to it.
- **No dark patterns**: no pre-ticked cloud toggle, no "recommended" upsell, no
  modal that traps focus, and no confirmation that is easier to accept than to
  decline.
- **One decision per screen**: the pane shows a single sentence and four buttons.
  It is an assistive device, not a dashboard.

---

## Limitations (read these)

- **17 languages, uneven quality.** English (Phonon) is the best voice here.
  French, German, Spanish, Portuguese, Italian, Dutch, Polish, Russian, Turkish,
  Arabic, Hindi, Chinese, Korean, Vietnamese and Thai use Piper `medium` voices
  and are good for clear speech. Japanese, Korean and Thai have exactly one voice
  each and are the weakest — intelligible, not premium. Japanese and Thai need an
  extra phonemizer package (`pyopenjtalk` / `tltk`), declared as optional extras.
  Recognition uses multilingual Whisper: `base` by default for non-English,
  `small` for the scripts Whisper handles worst, both selectable.
- **The reframer is not an LLM.** It handles fragmented, telegraphic speech well
  and long meandering sentences poorly. It reorders known slot patterns (verb,
  object, time) rather than understanding arbitrary meaning. When it is unsure it
  asks instead of guessing — expect that to happen on unusual sentences.
- **Single utterance at a time.** There is no conversation mode, no wake word, no
  continuous dictation, and none is planned: those are exactly the behaviours
  this plugin exists to avoid.
- **CPU only in this version.** No GPU path, no streaming TTS. Time-to-first-word
  is roughly half a second to a second and a half on a small desktop.
- **Voices are chosen, not cloned.** 37 English Phonon voices and 108 Piper
  voices across 16 languages, but no voice cloning and no custom voice training:
  Gradium's cloning runs in the cloud and needs an account, which is the opposite
  of this plugin's defaults.
- **No conversation history**, so no "what did I say yesterday". That is the
  privacy promise, and it has a real cost.
- **Cloud speech is not exercised by the test suite.** The Gradium paths are
  implemented against the documented REST contract and fail loudly and early
  (never silently), but they cannot be tested without a key. Treat them as
  unverified until you have run them once with your own account.

---

## Security and data handling

- **No secrets in code.** The Gradium key lives in `.env` via Hermes's secret
  scope; the plugin never reads `.env`, `auth.json`, or another tool's credential
  file, and never writes a credential.
- **Loopback only.** The backend is a router mounted inside Hermes's own gateway
  (`/api/plugins/clearvoice`). It opens no port, binds no socket, and runs no
  background process.
- **No shell, except one fixed call.** The only subprocess is `ffmpeg` with a
  constant argument vector and audio piped through stdin/stdout — no filename, no
  user string, no shell.
- **Bounded input.** Clips over ~12 MB are refused, sentences over 600 characters
  are refused, and saved phrases are capped at 300 characters.
- **Untrusted text is text.** The proposed sentence comes from your microphone; it
  is rendered as a text node in React, never as HTML, and never executed,
  fetched, or interpolated into a URL.
- **Least privilege.** The manifest requests no capabilities at all: no
  `tools.override`, no filesystem/email/calendar capabilities, no shell tool, one
  process-wide hook — none.
- **Verifiable.** `tests/test_privacy.py` enforces the negative claims (audit-hook
  write detection, cloud gating, manifest capability checks); `hermes plugins
  validate` and `hermes plugins doctor` both pass. Full disclosure in
  [SECURITY.md](SECURITY.md).

---

## Development

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
pytest                        # 58 tests, no model download, no network
python scripts/smoke_test.py  # real models, real audio, in memory
hermes plugins validate . --install-deps
hermes plugins doctor .
```

### Structure

```
clearvoice-hermes-plugin/
├── plugin.yaml                 # manifest: 1 tool, 0 hooks, 0 capabilities
├── __init__.py                 # agent half: clearvoice_speak + /clearvoice
├── pyproject.toml              # ptts, faster-whisper, numpy (bounded)
├── clearvoice_engine/          # the pipeline, Hermes-free and importable
│   ├── audio.py                # bytes in, arrays out — never a file
│   ├── stt.py                  # local faster-whisper · Gradium cloud
│   ├── tts.py                  # engine routing: Phonon (en) · Piper (others) · Gradium
│   ├── langs.py                # the 17 languages, voice index, Whisper-model mapping
│   ├── piper.py                # MIT local engine for every non-English language
│   ├── intent.py               # deterministic reframer (3 styles), shared scoring
│   ├── intent_fr.py            # French rule pack: verb forms, time spans, "Pourriez-vous…"
│   ├── privacy.py              # session store, saved phrases
│   ├── cloud.py                # Gradium REST, gated and key-safe
│   ├── settings.py             # validated settings view
│   ├── runtime.py              # in-process session state + audio outbox
│   └── data/piper_voices.json  # 108 voices, bundled so the picker works offline
├── dashboard/
│   ├── manifest.json           # {"name": "clearvoice", "api": "plugin_api.py"}
│   └── plugin_api.py           # the pane's REST backend
├── desktop/
│   └── plugin.js               # pane, page, nav, palette, status chip
├── assets/icon.svg
├── scripts/smoke_test.py
└── tests/                      # intent · privacy · plugin
```

Two deviations from the original build brief, both forced by the platform, both
documented rather than hidden:

1. **The Desktop UI is one ESM `plugin.js`, not four `.tsx` files.** Hermes
   Desktop loads a disk plugin uncompiled — JSX cannot be parsed, and the only
   importable specifiers are `@hermes/plugin-sdk`, `react` and
   `react/jsx-runtime`. The four components named in the brief (`ClearVoicePane`,
   `PushToTalkButton`, `CaptionPanel`, `PrivacyBadge`) exist as separate
   components in that file, written with `jsx()` calls.
2. **The engine is `clearvoice_engine/` at the plugin root**, not
   `clearvoice/clearvoice/`. A nested package of the same name as its parent
   directory breaks path-based imports; the flat, uniquely named package is
   importable from both entry points (the agent half and the REST backend) and
   from the tests.

---

## Hackathon submission checklist

- [x] Installs cleanly into Hermes (`hermes plugins install` / linked checkout)
- [x] Desktop pane works (pane, full page, sidebar row, palette command, status chip)
- [x] Push-to-talk capture works (press/release, keyboard, pointer-capture safe)
- [x] STT works on at least one backend (local faster-whisper, verified end to end)
- [x] Intent clarification works (rules, confidence, candidates, confirmation)
- [x] Phonon local TTS works (Apache-2.0 31m, on CPU, verified end to end)
- [x] Optional Gradium backend implemented, **disabled by default**, triple-gated
- [x] No audio or transcript persisted during normal use (audit-hook tested)
- [x] `hermes plugins validate . --install-deps` passes
- [x] `README.md`, `PRIVACY.md`, `LICENSE`, `tests/`, `HACKATHON_SUBMISSION.md` complete
- [ ] Public repository published
- [ ] Catalog pull request opened
- [ ] 90-second demo video recorded

See [HACKATHON_SUBMISSION.md](HACKATHON_SUBMISSION.md) for the pitch, the demo
script, and the submission state.

## Licence

MIT — see [LICENSE](LICENSE). Model and runtime licences are listed there too.
