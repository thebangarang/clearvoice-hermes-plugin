# ClearVoice privacy statement

**Short version: your voice is used for one sentence and then gone. Nothing is
recorded, nothing is kept, and by default nothing leaves your machine.**

This page is the complete statement — what is processed, what is stored, what is
sent, when a network connection happens at all, how to clear everything, and why
there is no memory.

---

## 1. What is processed

| Data | Where it exists | For how long |
|---|---|---|
| Microphone audio | RAM, inside the Desktop app window and in the request that carries it to the local backend | From the moment you press the button until the transcript comes back — seconds |
| The transcript | RAM, inside the Hermes gateway process | Until you clear the session, close the app, or the plugin unloads |
| The proposed sentence | RAM, in the same place | Same |
| Synthesized speech | RAM, returned to the pane and played through your speakers | Until playback finishes |
| Saved phrases | Disk, `phrases.json` in the plugin's data directory | Until you delete them |

The microphone is opened on **press** and every track is stopped on **release**.
There is no background listening path in the plugin: no wake word, no voice
activity detection outside a held clip, no timer that re-opens the stream. The
pane also tears the stream down if it is unmounted mid-recording.

## 2. What is stored

- **Audio: never.** Not a WAV, not a temporary file, not a cache entry, not a
  backup. The audio is decoded from bytes into an array in memory and the bytes
  go out of scope. `tests/test_privacy.py` asserts this with a CPython audit
  hook that observes every `open()` in the process, including calls made by
  third-party libraries.
- **Transcripts: only in RAM**, capped at the last 12 utterances, so the pane can
  show "You said: …" and offer *Speak it* again. **Clear session** empties it. A
  restart starts empty, because there is nowhere for it to have been written.
- **Generated speech: never**, same as audio.
- **Your saved phrases: yes, on purpose.** Only sentences you add with the
  **Save phrase** button, and only that text — never the recording it came from,
  never a history of when you used it. Stored at
  `<hermes home>/plugin-data/clearvoice/phrases.json` (mode-restricted by your
  user account). Delete them one by one in *My phrases*, or delete the file.

There is no analytics, no crash-reporting endpoint, no "anonymous usage
statistics" option, and no identifier of any kind tied to you.

## 3. What is sent off-device

**By default: nothing.** The default configuration (local speech recognition +
Phonon on-device voice) makes **zero network calls while you use it**. The only
traffic is the one-time model download the first time each model is used:

| When | What goes out | Where |
|---|---|---|
| First transcription ever | A model download request (no audio, no text) | Hugging Face (`huggingface.co`) via faster-whisper |
| First synthesis ever | A model download request (no audio, no text) | Hugging Face (`huggingface.co`) via ptts |

After that, unplug the network and ClearVoice keeps working.

**If you opt in to Gradium cloud**, and only then, and only for the backend you
selected:

- Cloud **transcription** sends the WAV of that one clip to
  `https://api.gradium.ai/api/post/speech/asr`.
- Cloud **voice** sends the final sentence text (already approved by you) to
  `https://api.gradium.ai/api/post/speech/tts`.

Three independent things must all be true for that to happen: **Allow cloud
speech** is on, the backend selector is set to Gradium, and a key is present.
Any one missing and the plugin refuses with a plain-language message instead of
falling back silently. When the cloud backend is in use, the privacy badge in
the pane says `Network: Cloud optional` and names the backend.

There is **no automatic fallback** from local to cloud. If local fails, you get
an error and a retry, not a quiet upload.

## 4. When network access happens

- **Model download**, once per model, on first use (Hugging Face).
- **Cloud speech**, only under the three conditions above (Gradium).
- **Nothing else.** The plugin opens no listening port, runs no background
  process, checks in with no server, and never polls a remote endpoint.

## 5. How to clear data

| What | How |
|---|---|
| The current session's captions and pending audio | **Clear session** in the pane (also **Cancel**) |
| Everything, including settings | `hermes plugins remove clearvoice`, then delete `<hermes home>/plugin-data/clearvoice/` |
| Saved phrases | *My phrases* → **×** on each, or delete `phrases.json` |
| Your Gradium key | Remove `CLEARVOICE_GRADIUM_API_KEY` from `.env`, or `hermes config` → Plugins → ClearVoice |

There is nothing else to clear. That is the point of the design.

## 6. Why there is no memory

A profile of how someone speaks, what they ask for, and when, is sensitive in a
way that ordinary app telemetry is not: it is a record of a person's impairment
and their private requests. ClearVoice therefore has no user profile, no
behavioural memory, no conversation history, and no "personalisation" feature.
Every session starts from nothing. The trade is real — ClearVoice cannot learn
your vocabulary or remember yesterday's sentences — and it is taken deliberately.

## 7. What ClearVoice will never do

- Listen continuously, or open the microphone without a deliberate press.
- Read your email, calendar, files, contacts, or messages.
- Send a message to anyone, on any platform, autonomously.
- Create an account, or require one.
- Store your audio, transcripts, or generated speech after the session.
- Speak an inferred sentence without showing it to you first.

## 8. Third parties in the data path

| Component | Role | Licence |
|---|---|---|
| `faster-whisper` + Whisper weights | local speech recognition | MIT |
| `ffmpeg` | local audio decoding (pipes only) | LGPL/GPL (your distribution's build) |
| `ptts` + Phonon 31m | local speech synthesis | MIT OR Apache-2.0 / Apache-2.0 |
| Gradium API | optional cloud speech, off by default | commercial, your own key |

None of them receives data from this plugin unless the condition for that row in
section 3 is met.

## 9. Honest limitations

- The on-device models are downloaded from Hugging Face on first use, which
  reveals to that service that *someone on your network fetched a model* — not
  what you said.
- Your operating system may log audio-device activity, and Hermes's own logs
  record that the plugin loaded. Neither contains speech content: ClearVoice
  never logs audio, transcripts, or generated sentences.
- If you enable cloud speech, Gradium's own retention policy applies to what they
  receive. That is why it is off, and why it is the one setting the pane
  advertises while it is on.

---

Last reviewed: 2026-11-05 · Version 0.1.0
