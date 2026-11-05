# AGENTS.md — ClearVoice

Local rules for this project. The global `~/AGENTS.md` still applies.

## What this is

A Hermes Agent plugin built for the Hermes Agent Plugin Hackathon (deadline
2026-11-11). Public-good assistive tool, not a client engagement. No customer
data is used or stored here.

## Facts that break the build if you forget them

- The Desktop half is **one ESM file** (`desktop/plugin.js`), loaded
  **uncompiled**: `jsx()` calls only, and the only importable specifiers are
  `@hermes/plugin-sdk`, `react`, `react/jsx-runtime`.
- The plugin directory name (`Clearvoice-hermes-plugin`) is not a Python
  identifier, so `__init__.py` inserts its own directory on `sys.path` and both
  entry points import the engine as the top-level package `clearvoice_engine`.
  Do not nest an engine package under a directory with the same name.
- Register area strings, not constants: `panes`, `routes`, `sidebar.nav`
  (yes, dotted), `palette`, `statusBar.right`.
- A running gateway never switches dependency environments. After changing
  `pyproject.toml` and re-enabling, `hermes gateway restart` is required — and it
  cannot be run from inside the gateway (the command is blocked by design).
- The `python3` on this shell resolves to the *old* Hermes environment. Use the
  enabled plugin's environment explicitly when testing the backend:
  `/home/hermes/.hermes/installs/*/environments/<current>/venv/bin/python`.

## Gates before claiming anything works

```bash
.venv/bin/python -m pytest
hermes plugins validate . --install-deps
hermes plugins doctor .
python scripts/smoke_test.py        # real models
python scripts/api_selftest.py      # every REST route, real audio
```

## Hard rules for this codebase

1. **Never** add a second call site for `getUserMedia`. One press handler, one
   release path.
2. **Never** write audio, transcripts or generated speech to disk. If a change
   needs a temp file, the change is wrong.
3. **Never** let the cloud path become automatic. Three conditions or refuse.
4. **Never** let the tool speak text the user has not seen. Two gates:
   `confirm_required` on the tool, `approved` on the route.
5. Roadmap items that add continuous listening, conversation history or a user
   profile are out of scope permanently — that is the product, not a phase.
