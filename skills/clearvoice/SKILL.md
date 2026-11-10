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
| Something said out loud | `clearvoice_speak` | Queues the sentence; the user presses Speak it in the pane |
| An unclear clip repeated clearly | `clearvoice_say_back` | Listen → propose → queue, same rule |
| A voice-over or audio file to use elsewhere | `clearvoice_speak` with `deliver: "file"` | Only works if the user enabled *Allow speech files*; returns a `MEDIA:` path |

## You cannot make ClearVoice speak

There is no flag for it. `clearvoice_speak` and `clearvoice_say_back` return
`{"queued": true, "spoken": false, "awaiting_user": true}` and put the sentence in
front of the user in the pane. That is the end of your part: only the user pressing
**Speak it** produces audio, because only that click redeems the single-use token
the pane was given.

So do not call the tool twice hoping the second call plays it, do not claim in your
reply that it "has been spoken", and do not treat "the user asked for speech" as
approval of wording you invented afterwards. Say what you queued, and let them press
the button.

`deliver: "file"` is different: it writes a WAV and plays nothing. It needs the user
to have enabled *Allow speech files*.

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
