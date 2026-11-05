---
name: clearvoice
description: Use ClearVoice for local speech — transcribe an audio file, speak text aloud, or play a clip back clearly.
---

# ClearVoice — speech in, speech out, nothing stored

Three tools, one privacy rule: audio is processed in memory on this machine and
is never written, uploaded or kept (the one exception is a speech file the user
explicitly asked for).

Reach for them instead of hand-rolling `ffmpeg` + a model: the plugin already
picks the right local engine per language, gates cloud use, and returns
plain-language errors instead of tracebacks.

## Which tool

| The user wants… | Use | Notes |
|---|---|---|
| To know what an audio file says | `clearvoice_transcribe` | `audio_path` (absolute), optional `language`, `reframe: true` for a cleaned sentence |
| Something said out loud | `clearvoice_speak` | Two-step: propose, then speak |
| An unclear clip repeated clearly | `clearvoice_say_back` | Listen → propose → speak, same two-step gate |
| A voice-over or audio file to use elsewhere | `clearvoice_speak` with `deliver: "file"` | Only works if the user enabled *Allow speech files*; returns a `MEDIA:` path |

## The approval gate is not optional

`clearvoice_speak` and `clearvoice_say_back` default to `confirm_required: true`,
which returns the exact sentence with `needs_confirmation: true` and speaks
nothing. Show that sentence to the user, let them approve or edit it, then call
again with `confirm_required: false`.

Never pass `confirm_required: false` on your own initiative, never speak text the
user has not seen, and never treat "the user asked for speech" as approval of
*wording* you invented afterwards.

## Rules

- **Absolute paths only** for `audio_path`. Read the file the user named; do not
  go looking for other recordings.
- **Language**: pass `language` for a one-off; otherwise the plugin setting wins.
  A `.en` recogniser is never used for another language — the plugin swaps it.
- **Cloud**: never enabled by you. If a call returns 403/400 with "cloud is off",
  relay it and offer the on-device path; do not retry with a key.
- **Do not loop**: one clip per call, ≤25 MB. For a long recording, ask the user
  to split it rather than transcribing it a fragment at a time.
- **Never claim a file was produced** unless the tool result carries a `file`
  path — with speech files off, the audio only played in the pane.
