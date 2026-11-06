# Catalog PR — `plugin-catalog/clearvoice.yaml`

> Draft. Open this PR against `NousResearch/hermes-agent` **after** the plugin
> repository is public and the commit SHA in the entry is a real 40-character
> commit. Title:
>
> `Add clearvoice — privacy-first push-to-talk speech-clarity plugin`

## What it is

ClearVoice is a push-to-talk speech-clarity bridge for people whose speech is
hard for others to understand (aphasia, Parkinson's, cerebral palsy, ALS,
stuttering, temporary voice loss). The user holds a button and speaks naturally;
the plugin transcribes the clip, proposes one clear sentence, **shows it in large
text before speaking anything**, and then voices it with Gradium's on-device
Phonon 31m model.

It is deliberately narrow: it listens only while the button is held, it never
sends messages, and it keeps nothing.

## Hermes surfaces used

- `ctx.register_tool` — three tools: `clearvoice_transcribe`, `clearvoice_speak`, `clearvoice_say_back`.
- `ctx.register_command` — `/clearvoice`.
- Desktop plugin SDK — `panes`, `routes`, `sidebar.nav`, `palette`,
  `statusBar.right`; `ctx.rest` into the plugin's own `/api/plugins/clearvoice`
  namespace.
- Nothing else. No hooks, no middleware, no provider registrations, no core
  access, no `capabilities:`.

## Disclosure (rule 13)

| Item | Detail |
|---|---|
| **Network** | None by default. One-time model download from `huggingface.co` on first use (a weights request — no audio, no text). The Gradium REST API (`api.gradium.ai`) is reachable only when three independent conditions hold: *Allow cloud speech* is on, the backend selector is Gradium, and the user's own key is present. No automatic local→cloud fallback. |
| **Shell** | A single `ffmpeg` invocation with a constant argument vector, audio piped stdin→stdout. No shell, no interpolation, no filenames. |
| **Background processes** | None. No daemon, no timer, no queue worker, no cron. |
| **Stored credentials** | None written. The optional Gradium key is read with `agent.secret_scope.get_secret("CLEARVOICE_GRADIUM_API_KEY")`; it never appears in logs, errors, or the UI. |
| **Filesystem** | Reads and writes exactly one file: `phrases.json` in the plugin's own data directory, and only on an explicit **Save phrase** action. Audio is never written — decoding and synthesis are in-memory, and a CPython audit-hook test asserts it. |
| **Retention** | Session-only and in memory. No telemetry, no account, no profile, history or behavioural memory. |
| **Microphone** | Opened inside the press handler only; tracks stopped on release, cancel, error and unmount. |

## Dependencies

```toml
ptts>=0.6.0,<0.7
faster-whisper>=1.2.1,<1.3
numpy>=1.26,<3
```

All upper-bounded. `ptts` is Gradium's own runtime for the Apache-2.0 Phonon 31m
weights; the CC BY-NC 40m checkpoints are not used or referenced.

## Verification

- `hermes plugins validate . --install-deps` → **Validation passed** (all checks
  green, including `security scan`, `no core override`, `desktop surface`).
- `hermes plugins doctor .` → `3 tool(s), 0 hook(s)`.
- `pytest` → 38 passed, including the no-disk-write audit-hook test and the cloud
  gating tests.
- `python scripts/smoke_test.py` → real Phonon synth → real faster-whisper
  transcript → reframe → real Phonon synth, nothing written to disk.
- `python scripts/api_selftest.py` → every REST route exercised with real
  WebM/Opus audio through an in-process FastAPI `TestClient`.

## Screenshots

The Desktop pane (one screenshot, plus the privacy badge close-up) goes here
after the recording. Both are required by the README-copy rule for
`desktop/` plugins.

## Note on scope

The plugin is CPU-only in 0.7.0, English is the reference language, and ten of the
seventeen languages are polish-only; all of it is stated in the README's
limitations section rather than left for a reviewer to discover. The Gradium cloud
paths are implemented against the published REST contract but are not exercised
in CI (no key exists there) — they fail closed, early, and with a plain message.
