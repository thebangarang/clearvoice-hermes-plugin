# CLAUDE.md — ClearVoice

Loaded at the start of every session here. The plugin's own README carries the product story; this file
carries the conventions and the traps.

## What this is

A Hermes plugin: push-to-talk speech bridge, on-device, 17 languages, no account, no audio on disk. Merged
into the Hermes catalogue at **`d4bc366` (v0.7.2)** — that pin is the code people install, and it only moves
through a NEW catalogue PR bumping `sha` + `version` together (never a force-push of a pinned commit).

## Surface

`clearvoice_transcribe` · `clearvoice_speak` · `clearvoice_say_back` · `/clearvoice` · `hermes clearvoice say|hear|say-back`
· pane + `routes` + `sidebar.nav` + `palette` · `APIRouter` at `/api/plugins/clearvoice/` (binds no port).

## Commands

```bash
python3 -m pytest -q                     # 163 tests
python3 scripts/api_selftest.py          # walks the real routes: transcribe → propose → token → speak
hermes plugins validate . && hermes plugins doctor .
```

## Rules that cost us something when forgotten

- **The accuracy comes from the personal dictionary, not a bigger model**: `base` 22.6 % WER → 3.8 % with the
  dictionary, and a bigger model would mean keeping recordings of an impaired voice (decision D-013).
- **`polished_only` is a real outcome**: 10 of the 17 languages polish punctuation only; the pane must say so
  rather than imply a grammar pack exists (D-016).
- **One token per use**, wrong token refused — the route is cheap to keep strict and expensive to re-audit.
