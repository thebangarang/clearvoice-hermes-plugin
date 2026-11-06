# Catalog entry: `clearvoice`

**Suggested PR title:** `catalog: add clearvoice (local push-to-talk speech bridge)`

**Pinned tree:** `874657a61250ca94df01b36cc1b800c865022fe4` · version 0.7.1

---

## What it is

ClearVoice is a push-to-talk speech bridge for people whose speech is hard for
others to understand (aphasia, Parkinson's, cerebral palsy, ALS, stuttering, a
tracheostomy, post-surgery voice loss) — and for anyone who wants their own agent
to hear them without shipping their voice to a vendor.

You hold one button. Your words appear large and editable in the pane. Nothing is
spoken until you press **Speak it**, and then a voice on your own machine says the
sentence, in one of seventeen languages. No account, no cloud, no audio on disk,
and no language model anywhere in the pipeline.

## Hermes surfaces used

| Surface | Detail |
|---|---|
| Tools | `clearvoice_transcribe`, `clearvoice_speak`, `clearvoice_say_back` |
| Slash command | `/clearvoice` (opens the pane, or proposes a sentence from text) |
| CLI command | `hermes clearvoice say \| hear \| say-back`, with `--json` for scripts |
| Desktop | pane, `routes`, `sidebar.nav`, `palette`, `statusBar.right` |
| Backend | `APIRouter` mounted at `/api/plugins/clearvoice/` (binds no port) |
| Skill | bundled `skills/clearvoice/SKILL.md`, teaching when to use each tool |

## Capabilities declared

`provides_tools`: the three tools above. `provides_hooks`: none.
`provides_middleware`: none. `requires_env`: none — the optional Gradium key is read
through `agent.secret_scope`, never required. No `tools.override`, no core override,
no desktop SDK escape: `hermes plugins validate` reports `security scan — safe`,
`no core override`, `desktop surface — stays inside the plugin SDK surface`.

## Rule 13 disclosure

- **Network.** Nothing while you use it. Two opt-in paths only: a one-time model
  download from `huggingface.co` on first use (no audio, no text), and the Gradium
  REST API when *Allow cloud speech* is on **and** the Gradium backend is selected
  **and** the user's own key is present. Any one missing → a plain refusal, never a
  silent upload. There is **no** language-model path: an earlier version could send
  a transcript to a model to "make it clearer"; it paraphrased and invented, so the
  code was deleted rather than disabled.
- **Shell.** One `ffmpeg` invocation with a constant argument vector; audio over
  stdin/stdout. No shell, no filename, no user string in the command line.
- **Background processes.** None — no thread outliving a request, no timer, no
  daemon, no cron.
- **Stored credentials.** None written. The optional Gradium key is read via
  `agent.secret_scope.get_secret("CLEARVOICE_GRADIUM_API_KEY")` and is never logged,
  echoed or displayed.
- **Filesystem.** Writes only inside its own plugin data directory: `phrases.json`
  (explicit **Save phrase**) and `dictionary.json` (words the user adds, plus
  corrections only while learning is switched on).
- **Retention.** Audio, transcripts and generated speech are session-only and in
  memory. Audio is never written anywhere, so there is nothing to retain, leak or
  upload. No telemetry, no account, no profile, no history.
- **Microphone.** Opened inside the press handler only; every track stopped on
  release, cancel, error and unmount.

## Dependencies

```toml
ptts>=0.6.0,<0.7
faster-whisper>=1.2.1,<1.3
numpy>=1.26,<3
piper-tts>=1.8,<2
```

All upper-bounded. `ptts` is Gradium's own runtime for the Apache-2.0 Phonon 31m
English weights; `piper-tts` (MIT runtime) voices the other sixteen languages. The
CC BY-NC Phonon 40m checkpoints are not used, downloaded or referenced.

## Verification at the pinned commit

```
hermes plugins validate . --install-deps
  ✓ manifest · requires_hermes · config schema · requires_env · loadable
  ✓ python dependencies (4, bounded)
  ✓ capability probe · declared tools / hooks / middleware match registrations
  ✓ no built-in tool collisions · security scan — safe
  ✓ no core override · desktop surface — stays inside the plugin SDK surface
  Validation passed.

hermes plugins doctor .
  registrations: 3 tool(s), 0 hook(s)

python -m pytest -q
  160 passed
```

Behaviour is verified by tests rather than claims: `tests/test_privacy.py` runs the
real pipeline under a CPython audit hook and asserts **zero** write-mode `open()`
calls; the cloud tests fail if the HTTP layer is even *called* while cloud is off;
each approval gate (`confirm_required` on the tool, `approved` on the route) has a
test that the refusal happens before any synthesis.

## Screenshots

Banner `docs/banner.png` (1200×600); pane screenshots `docs/shot-verbatim.png` and
`docs/shot-courteous.png`; 7-second loop `demo/preview.gif`; 80-second demo
`demo/clearvoice-demo.mp4`. All pinned to the entry's commit.

## Honest limitations (also in the README, the pane and `known_issues`)

- **Recognition is not adapted to the speaker.** Voiceitt (50–200 recorded phrases)
  and Google's Project Relate (500 phrases, per-user model) recognise atypical
  speech better than a general Whisper. The dictionary here is a cheap local
  approximation of that, and the README says so plainly.
- **7 of 17 languages rebuild a sentence** — en, fr, de, es, it, pt, nl, each with a
  checked grammar pack. The other ten are polished: punctuation, capitalisation, the
  language's own politeness word, and a confirmation question in that language, with
  word order untouched. The pane states which happened.
- **CPU only** in this version; ~2.8 s from release to sentence.

## Note on scope

The plugin is deliberately narrow: it listens only while a button is held, it speaks
only what the user has approved, it stores nothing, and it asks no capabilities. That
is the design argument, not a phase — the audience is people for whom being
understood is not a convenience.
